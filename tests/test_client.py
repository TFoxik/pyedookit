import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp
import pytest

from pyedookit import auth
from pyedookit.client import EdookitClient
from pyedookit.exceptions import AuthError, EdookitConnectionError, SessionExpired
from pyedookit.session import Session

from .fakes import FailingResponse, FakeClientSession, ok, redirect

SCHOOL = "zs-example"
TIMETABLE_URL = f"https://{SCHOOL}.edookit.net/timetable/"

SESSION = Session.from_cookies(
    SCHOOL, edookit={"PHPSESSID": "s", "uu.app.csrf": "csrf"}, plus4u={}
)


EXPIRED = '{"redirect":"https://zs-example.edookit.net/user/login?message=1","state":[]}'


def _expired() -> object:
    return ok(TIMETABLE_URL, body=EXPIRED, content_type="application/json")


def _renewed(cookie: str) -> Session:
    return Session.from_cookies(SCHOOL, edookit={"PHPSESSID": cookie}, plus4u={"uoid.ps": "p"})


@pytest.mark.asyncio
async def test_a_redirect_is_never_followed_and_counts_as_expired(monkeypatch):
    # A redirect must never be followed here: our Cookie header is set
    # manually, and following it would forward the school's session cookie
    # to whatever host the redirect points at (see transport.request).
    monkeypatch.setattr(auth, "refresh", AsyncMock(side_effect=AuthError("stop here")))
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, redirect("https://uuidentity.plus4u.net/oidc/auth"))]
    )

    with pytest.raises(AuthError):
        await EdookitClient(SESSION, http=fake).fetch_timetable_html()


@pytest.mark.asyncio
async def test_get_raises_session_expired_on_the_ajax_login_redirect(monkeypatch):
    monkeypatch.setattr(auth, "refresh", AsyncMock(side_effect=AuthError("stop here")))
    response = ok(TIMETABLE_URL, body=EXPIRED, content_type="application/json; charset=utf-8")
    client = EdookitClient(SESSION, http=FakeClientSession([("GET", TIMETABLE_URL, response)]))

    with pytest.raises(AuthError):
        await client.fetch_timetable_html()


@pytest.mark.asyncio
async def test_expired_session_is_renewed_reported_and_retried(monkeypatch):
    refresh = AsyncMock(return_value=_renewed("new"))
    monkeypatch.setattr(auth, "refresh", refresh)
    updates: list[Session] = []
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, _expired()), ("GET", TIMETABLE_URL, ok(TIMETABLE_URL, body="tt"))]
    )
    client = EdookitClient(SESSION, http=fake, on_session_update=updates.append)

    assert await client.fetch_timetable_html() == "tt"
    assert [s.cookies.get(f"{SCHOOL}.edookit.net", "PHPSESSID") for s in updates] == ["new"]
    assert client.session is updates[0]
    refresh.assert_awaited_once_with(SESSION, http=fake)


@pytest.mark.asyncio
async def test_still_expired_after_renewal_raises_without_looping(monkeypatch):
    refresh = AsyncMock(return_value=_renewed("new"))
    monkeypatch.setattr(auth, "refresh", refresh)
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, _expired()), ("GET", TIMETABLE_URL, _expired())]
    )
    client = EdookitClient(SESSION, http=fake)

    with pytest.raises(SessionExpired):
        await client.fetch_timetable_html()
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_plus4u_sign_in_raises_auth_error(monkeypatch):
    monkeypatch.setattr(auth, "refresh", AsyncMock(side_effect=AuthError("expired")))
    client = EdookitClient(SESSION, http=FakeClientSession([("GET", TIMETABLE_URL, _expired())]))

    with pytest.raises(AuthError):
        await client.fetch_timetable_html()


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_renewal(monkeypatch):
    gate = asyncio.Event()

    async def slow_refresh(session, *, http=None):
        await gate.wait()
        return _renewed("new")

    refresh = AsyncMock(side_effect=slow_refresh)
    monkeypatch.setattr(auth, "refresh", refresh)
    fake = FakeClientSession(
        [
            ("GET", TIMETABLE_URL, _expired()),
            ("GET", TIMETABLE_URL, _expired()),
            ("GET", TIMETABLE_URL, ok(TIMETABLE_URL, body="a")),
            ("GET", TIMETABLE_URL, ok(TIMETABLE_URL, body="b")),
        ]
    )
    client = EdookitClient(SESSION, http=fake)

    calls = asyncio.gather(client.fetch_timetable_html(), client.fetch_timetable_html())
    for _ in range(5):  # let both calls hit the expiry and queue on the lock
        await asyncio.sleep(0)
    gate.set()

    assert sorted(await calls) == ["a", "b"]
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_oidc_logout_ajax_redirect_triggers_renewal(monkeypatch):
    refresh = AsyncMock(return_value=_renewed("new"))
    monkeypatch.setattr(auth, "refresh", refresh)
    logout = ok(
        TIMETABLE_URL,
        body='{"redirect":"https://zs-example.edookit.net/oidc/logout?performCallback=1","state":[]}',
        content_type="application/json; charset=utf-8",
    )
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, logout), ("GET", TIMETABLE_URL, ok(TIMETABLE_URL, body="tt"))]
    )
    client = EdookitClient(SESSION, http=fake)

    assert await client.fetch_timetable_html() == "tt"
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_returns_a_json_body_without_a_redirect_as_is(monkeypatch):
    refresh = AsyncMock(return_value=_renewed("new"))
    monkeypatch.setattr(auth, "refresh", refresh)
    response = ok(TIMETABLE_URL, body='{"state":[]}', content_type="application/json")
    client = EdookitClient(SESSION, http=FakeClientSession([("GET", TIMETABLE_URL, response)]))

    assert await client.fetch_timetable_html() == '{"state":[]}'
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_returns_body_on_success():
    fake = FakeClientSession([("GET", TIMETABLE_URL, ok(TIMETABLE_URL, body="<html>tt</html>"))])
    client = EdookitClient(SESSION, http=fake)

    html = await client.fetch_timetable_html()

    assert html == "<html>tt</html>"


@pytest.mark.asyncio
async def test_get_raises_connection_error_on_timeout():
    fake = FakeClientSession([("GET", TIMETABLE_URL, FailingResponse(TimeoutError()))])
    client = EdookitClient(SESSION, http=fake)

    with pytest.raises(EdookitConnectionError):
        await client.fetch_timetable_html()


@pytest.mark.asyncio
async def test_get_raises_connection_error_on_client_error():
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, FailingResponse(aiohttp.ClientConnectionError("reset")))]
    )
    client = EdookitClient(SESSION, http=fake)

    with pytest.raises(EdookitConnectionError):
        await client.fetch_timetable_html()


EVENTS_URL = f"https://{SCHOOL}.edookit.net/timetable/upcoming"
PAYMENTS_URL = f"https://{SCHOOL}.edookit.net/payments/"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_get_events_parses_the_upcoming_page():
    body = (FIXTURES / "upcoming_events_structure.html").read_text()
    client = EdookitClient(
        SESSION, http=FakeClientSession([("GET", EVENTS_URL, ok(EVENTS_URL, body=body))])
    )

    events = await client.get_events()

    assert [e.id for e in events] == ["5001", "5002", "5003", "5004", "5005"]


@pytest.mark.asyncio
async def test_get_payments_parses_the_payments_page():
    body = (FIXTURES / "payments_structure.html").read_text()
    client = EdookitClient(
        SESSION, http=FakeClientSession([("GET", PAYMENTS_URL, ok(PAYMENTS_URL, body=body))])
    )

    payments = await client.get_payments()

    assert payments.remaining == Decimal(321)


@pytest.mark.asyncio
async def test_fetch_page_only_allows_capture_pages():
    url = f"https://{SCHOOL}.edookit.net/assignments/"
    client = EdookitClient(
        SESSION, http=FakeClientSession([("GET", url, ok(url, body="<p>x</p>"))])
    )

    assert await client.fetch_page("assignments") == "<p>x</p>"
    with pytest.raises(ValueError):
        await client.fetch_page("settings")


@pytest.mark.asyncio
async def test_cookies_rotated_by_the_portal_are_kept_and_sent_next_time():
    seen: list[dict] = []

    def first(headers):
        seen.append(headers)
        return ok(TIMETABLE_URL, raw_set_cookies=["PHPSESSID=rotated; path=/"])

    def second(headers):
        seen.append(headers)
        return ok(TIMETABLE_URL)

    session = Session.from_cookies(SCHOOL, edookit={"PHPSESSID": "s"}, plus4u={})
    fake = FakeClientSession([("GET", TIMETABLE_URL, first), ("GET", TIMETABLE_URL, second)])
    client = EdookitClient(session, http=fake)

    await client.fetch_timetable_html()
    await client.fetch_timetable_html()

    assert seen[1]["Cookie"] == "PHPSESSID=rotated"

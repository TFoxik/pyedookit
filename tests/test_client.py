from decimal import Decimal
from pathlib import Path

import aiohttp
import pytest

from pyedookit.client import EdookitClient
from pyedookit.exceptions import EdookitConnectionError, SessionExpired
from pyedookit.session import Session

from .fakes import FailingResponse, FakeClientSession, ok, redirect

SCHOOL = "zs-example"
TIMETABLE_URL = f"https://{SCHOOL}.edookit.net/timetable/"

SESSION = Session(
    school=SCHOOL,
    edookit_cookies={"PHPSESSID": "s", "uu.app.csrf": "csrf"},
    plus4u_cookies={},
    csrf_token="csrf",
)


@pytest.mark.asyncio
async def test_get_raises_session_expired_on_any_redirect_without_following_it():
    # A redirect must never be followed here: our Cookie header is set
    # manually, and following it would forward the school's session cookie
    # to whatever host the redirect points at (see client.py's _get).
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, redirect("https://uuidentity.plus4u.net/oidc/auth"))]
    )
    client = EdookitClient(SESSION, http=fake)

    with pytest.raises(SessionExpired):
        await client.fetch_timetable_html()


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

    assert payments.remaining == Decimal(400)


@pytest.mark.asyncio
async def test_fetch_page_only_allows_capture_pages():
    url = f"https://{SCHOOL}.edookit.net/assignments/"
    client = EdookitClient(
        SESSION, http=FakeClientSession([("GET", url, ok(url, body="<p>x</p>"))])
    )

    assert await client.fetch_page("assignments") == "<p>x</p>"
    with pytest.raises(ValueError):
        await client.fetch_page("settings")

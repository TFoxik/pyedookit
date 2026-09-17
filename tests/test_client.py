import pytest

from pyedookit.client import EdookitClient
from pyedookit.exceptions import SessionExpired
from pyedookit.session import Session

from .fakes import FakeClientSession, ok, redirect

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
    # to whatever host the redirect points at (see client.py's _request).
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, redirect("https://uuidentity.plus4u.net/oidc/auth"))]
    )
    client = EdookitClient(SESSION, http=fake)

    with pytest.raises(SessionExpired):
        await client.fetch_timetable_html()


@pytest.mark.asyncio
async def test_get_raises_session_expired_when_response_is_the_login_page():
    fake = FakeClientSession(
        [("GET", TIMETABLE_URL, ok(f"https://{SCHOOL}.edookit.net/user/login"))]
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

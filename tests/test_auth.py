import re

import pytest
from aioresponses import aioresponses
from multidict import CIMultiDict

from pyedookit import auth
from pyedookit.exceptions import AuthError
from pyedookit.session import Session

SCHOOL = "zs-example"
AUTH_URL_PREFIX = (
    "https://uuidentity.plus4u.net/uu-oidc-maing02/bb977a99f4cc4c37a2afce3fd599d0a7/oidc/auth"
)
PASSWORD_URL = (
    "https://uuidentity.plus4u.net/uu-oidc-maing02/"
    "bb977a99f4cc4c37a2afce3fd599d0a7/authPassword/authenticate"
)
CALLBACK_URL = f"https://{SCHOOL}.edookit.net/user/oidc-login-callback"
DASHBOARD_URL = f"https://{SCHOOL}.edookit.net/overview/updates"
LOGIN_PAGE_URL = "https://uuidentity.plus4u.net/uu-oidc-maing02/login?state=srv-state&clientId=cid-1"
CONTINUE_URL = "https://uuidentity.plus4u.net/uu-oidc-maing02/continue"


def _set_cookie_headers(cookies: dict[str, str]) -> CIMultiDict:
    headers: CIMultiDict = CIMultiDict()
    for key, value in cookies.items():
        headers.add("Set-Cookie", f"{key}={value}; Path=/")
    return headers


@pytest.mark.asyncio
async def test_login_success_extracts_edookit_and_plus4u_cookies():
    with aioresponses() as mocked:
        mocked.get(
            re.compile(re.escape(AUTH_URL_PREFIX) + r".*"),
            status=302,
            headers={"Location": LOGIN_PAGE_URL},
        )
        password_response_headers = _set_cookie_headers(
            {"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"}
        )
        password_response_headers["Location"] = CONTINUE_URL
        mocked.post(PASSWORD_URL, status=302, headers=password_response_headers)
        mocked.get(
            CONTINUE_URL,
            status=302,
            headers={"Location": f"{CALLBACK_URL}?code=abc123"},
        )
        mocked.get(
            f"{CALLBACK_URL}?code=abc123",
            status=302,
            headers={"Location": DASHBOARD_URL},
        )
        mocked.get(
            DASHBOARD_URL,
            status=200,
            headers=_set_cookie_headers(
                {
                    "PHPSESSID": "sess1",
                    "_nss": "n1",
                    "X-EdooCacheId": "c1",
                    "X-Auth-Id": "a1",
                    "uu.app.csrf": "csrf1",
                }
            ),
            body="<html>ok</html>",
        )

        session = await auth.login(SCHOOL, "user@example.com", "hunter2")

    assert session.school == SCHOOL
    assert session.edookit_cookies["PHPSESSID"] == "sess1"
    assert session.csrf_token == "csrf1"
    assert session.plus4u_cookies == {"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"}


@pytest.mark.asyncio
async def test_login_raises_auth_error_on_bad_credentials():
    with aioresponses() as mocked:
        mocked.get(
            re.compile(re.escape(AUTH_URL_PREFIX) + r".*"),
            status=302,
            headers={"Location": LOGIN_PAGE_URL},
        )
        mocked.post(PASSWORD_URL, status=401)

        with pytest.raises(AuthError):
            await auth.login(SCHOOL, "user@example.com", "wrong")


@pytest.mark.asyncio
async def test_refresh_success_reuses_plus4u_cookies_without_password():
    stale = Session(
        school=SCHOOL,
        edookit_cookies={"PHPSESSID": "old"},
        plus4u_cookies={"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"},
        csrf_token="old-csrf",
    )

    with aioresponses() as mocked:
        mocked.get(
            re.compile(re.escape(AUTH_URL_PREFIX) + r".*"),
            status=302,
            headers={"Location": f"{CALLBACK_URL}?code=fresh123"},
        )
        mocked.get(
            f"{CALLBACK_URL}?code=fresh123",
            status=302,
            headers={"Location": DASHBOARD_URL},
        )
        mocked.get(
            DASHBOARD_URL,
            status=200,
            headers=_set_cookie_headers(
                {
                    "PHPSESSID": "sess-new",
                    "_nss": "n2",
                    "X-EdooCacheId": "c2",
                    "X-Auth-Id": "a2",
                    "uu.app.csrf": "csrf2",
                }
            ),
            body="<html>ok</html>",
        )

        refreshed = await auth.refresh(stale)

    assert refreshed.edookit_cookies["PHPSESSID"] == "sess-new"
    assert refreshed.csrf_token == "csrf2"


@pytest.mark.asyncio
async def test_refresh_raises_auth_error_when_plus4u_cookie_expired():
    stale = Session(
        school=SCHOOL,
        edookit_cookies={"PHPSESSID": "old"},
        plus4u_cookies={"uoid.ps": "expired"},
        csrf_token="old-csrf",
    )

    with aioresponses() as mocked:
        mocked.get(
            re.compile(re.escape(AUTH_URL_PREFIX) + r".*"),
            status=302,
            headers={"Location": LOGIN_PAGE_URL},
        )

        with pytest.raises(AuthError):
            await auth.refresh(stale)

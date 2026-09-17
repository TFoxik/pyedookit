import pytest

from pyedookit import auth
from pyedookit.exceptions import AuthError
from pyedookit.session import Session

from .fakes import FakeClientSession, ok, redirect, rejected

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


def _install_fake_session(monkeypatch: pytest.MonkeyPatch, routes) -> FakeClientSession:
    fake = FakeClientSession(routes)
    monkeypatch.setattr(auth, "_new_http_session", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_login_success_extracts_edookit_and_plus4u_cookies(monkeypatch):
    _install_fake_session(
        monkeypatch,
        [
            ("GET", AUTH_URL_PREFIX, redirect(LOGIN_PAGE_URL)),
            (
                "POST",
                PASSWORD_URL,
                redirect(CONTINUE_URL, set_cookies={"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"}),
            ),
            ("GET", CONTINUE_URL, redirect(f"{CALLBACK_URL}?code=abc123")),
            ("GET", CALLBACK_URL, redirect(DASHBOARD_URL)),
            (
                "GET",
                DASHBOARD_URL,
                ok(
                    DASHBOARD_URL,
                    set_cookies={
                        "PHPSESSID": "sess1",
                        "_nss": "n1",
                        "X-EdooCacheId": "c1",
                        "X-Auth-Id": "a1",
                        "uu.app.csrf": "csrf1",
                    },
                ),
            ),
        ],
    )

    session = await auth.login(SCHOOL, "user@example.com", "hunter2")

    assert session.school == SCHOOL
    assert session.edookit_cookies["PHPSESSID"] == "sess1"
    assert session.csrf_token == "csrf1"
    assert session.plus4u_cookies == {"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"}


@pytest.mark.asyncio
async def test_login_raises_auth_error_on_bad_credentials(monkeypatch):
    _install_fake_session(
        monkeypatch,
        [
            ("GET", AUTH_URL_PREFIX, redirect(LOGIN_PAGE_URL)),
            ("POST", PASSWORD_URL, rejected(401)),
        ],
    )

    with pytest.raises(AuthError):
        await auth.login(SCHOOL, "user@example.com", "wrong")


@pytest.mark.asyncio
async def test_refresh_success_reuses_plus4u_cookies_without_password(monkeypatch):
    stale = Session(
        school=SCHOOL,
        edookit_cookies={"PHPSESSID": "old"},
        plus4u_cookies={"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"},
        csrf_token="old-csrf",
    )
    _install_fake_session(
        monkeypatch,
        [
            ("GET", AUTH_URL_PREFIX, redirect(f"{CALLBACK_URL}?code=fresh123")),
            ("GET", CALLBACK_URL, redirect(DASHBOARD_URL)),
            (
                "GET",
                DASHBOARD_URL,
                ok(
                    DASHBOARD_URL,
                    set_cookies={
                        "PHPSESSID": "sess-new",
                        "_nss": "n2",
                        "X-EdooCacheId": "c2",
                        "X-Auth-Id": "a2",
                        "uu.app.csrf": "csrf2",
                    },
                ),
            ),
        ],
    )

    refreshed = await auth.refresh(stale)

    assert refreshed.edookit_cookies["PHPSESSID"] == "sess-new"
    assert refreshed.csrf_token == "csrf2"


@pytest.mark.asyncio
async def test_refresh_raises_auth_error_when_plus4u_cookie_expired(monkeypatch):
    stale = Session(
        school=SCHOOL,
        edookit_cookies={"PHPSESSID": "old"},
        plus4u_cookies={"uoid.ps": "expired"},
        csrf_token="old-csrf",
    )
    _install_fake_session(
        monkeypatch,
        [
            ("GET", AUTH_URL_PREFIX, redirect(LOGIN_PAGE_URL)),
        ],
    )

    with pytest.raises(AuthError):
        await auth.refresh(stale)


@pytest.mark.asyncio
async def test_login_rejects_malformed_school_without_making_a_request(monkeypatch):
    _install_fake_session(monkeypatch, [])  # any request would raise AssertionError

    with pytest.raises(AuthError):
        await auth.login("evil.com/", "user@example.com", "hunter2")


def test_is_login_url():
    assert auth.is_login_url(f"https://{SCHOOL}.edookit.net/user/login")
    assert auth.is_login_url(f"https://{SCHOOL}.edookit.net/user/oidc?x=1")
    assert not auth.is_login_url(f"https://{SCHOOL}.edookit.net/overview/updates")

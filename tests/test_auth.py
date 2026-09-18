import pytest

from pyedookit import auth
from pyedookit.exceptions import AuthError
from pyedookit.session import Session

from .fakes import FakeClientSession, ok, redirect, rejected

SCHOOL = "zs-example"
LOGIN_URL = f"https://{SCHOOL}.edookit.net/user/login"
AUTH_URL_PREFIX = (
    "https://uuidentity.plus4u.net/uu-oidc-maing02/bb977a99f4cc4c37a2afce3fd599d0a7/oidc/auth"
)
PASSWORD_URL = (
    "https://uuidentity.plus4u.net/uu-oidc-maing02/"
    "bb977a99f4cc4c37a2afce3fd599d0a7/authPassword/authenticate"
)
CALLBACK_URL = f"https://{SCHOOL}.edookit.net/user/oidc-login-callback"
DASHBOARD_URL = f"https://{SCHOOL}.edookit.net/overview/updates"
SCHOOL_BASE_URL = f"https://{SCHOOL}.edookit.net"
LOGIN_PAGE_URL = "https://uuidentity.plus4u.net/uu-oidc-maing02/login?state=srv-state&clientId=cid-1"
CONTINUE_URL = "https://uuidentity.plus4u.net/uu-oidc-maing02/continue"

# The client_id is embedded per-school in this inline JS config block on the
# real portal's own /user/login page - see auth._CLIENT_ID_RE.
DISCOVERED_CLIENT_ID = "983960dcb7b84b34b9aecc5194381d56"
LOGIN_PAGE_HTML = f"""
<script type="text/javascript">
    window.UU5 = {{
        Environment: {{
            uu_app_oidc_providers_oidcg02_client_id: "{DISCOVERED_CLIENT_ID}"
        }}
    }};
</script>
"""


def _discovery_route() -> tuple[str, str, object]:
    return ("GET", LOGIN_URL, ok(LOGIN_URL, body=LOGIN_PAGE_HTML))


def _settle_route() -> tuple[str, str, object]:
    # The extra GET to the portal root that _finish_callback makes after the
    # OIDC callback resolves - confirmed against a real browser trace to be
    # what actually activates the full session (see auth._finish_callback).
    return ("GET", SCHOOL_BASE_URL, ok(SCHOOL_BASE_URL))


def _install_fake_session(monkeypatch: pytest.MonkeyPatch, routes) -> FakeClientSession:
    fake = FakeClientSession(routes)
    monkeypatch.setattr(auth, "_new_http_session", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_login_success_extracts_edookit_and_plus4u_cookies(monkeypatch):
    _install_fake_session(
        monkeypatch,
        [
            _discovery_route(),
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
            _settle_route(),
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
            _discovery_route(),
            ("GET", AUTH_URL_PREFIX, redirect(LOGIN_PAGE_URL)),
            ("POST", PASSWORD_URL, rejected(401)),
        ],
    )

    with pytest.raises(AuthError):
        await auth.login(SCHOOL, "user@example.com", "wrong")


@pytest.mark.asyncio
async def test_login_raises_auth_error_when_client_id_not_found(monkeypatch):
    _install_fake_session(
        monkeypatch,
        [("GET", LOGIN_URL, ok(LOGIN_URL, body="<html>no config here</html>"))],
    )

    with pytest.raises(AuthError):
        await auth.login(SCHOOL, "user@example.com", "hunter2")


@pytest.mark.asyncio
async def test_probe_client_id_returns_the_discovered_value(monkeypatch):
    _install_fake_session(monkeypatch, [_discovery_route()])

    client_id = await auth.probe_client_id(SCHOOL)

    assert client_id == DISCOVERED_CLIENT_ID


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
            _discovery_route(),
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
            _settle_route(),
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
            _discovery_route(),
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

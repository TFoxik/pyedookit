import aiohttp
import pytest

from pyedookit import auth, transport
from pyedookit.exceptions import AuthError, EdookitConnectionError
from pyedookit.session import PLUS4U_HOST, Session

from .fakes import FailingResponse, FakeClientSession, ok, redirect, rejected

SCHOOL = "zs-example"
EDOOKIT_HOST = f"{SCHOOL}.edookit.net"
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
DISCOVERED_CLIENT_ID = "0123456789abcdef0123456789abcdef"
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
    monkeypatch.setattr(transport, "_new_http_session", lambda: fake)
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
    assert session.cookies.get(EDOOKIT_HOST, "PHPSESSID") == "sess1"
    assert session.csrf_token == "csrf1"
    assert session.cookies.get(PLUS4U_HOST, "uoid.ps") == "p"
    assert session.cookies.get(PLUS4U_HOST, "uoid.s") == "s"
    assert session.cookies.get(PLUS4U_HOST, "uoid.bs") == "b"


@pytest.mark.asyncio
async def test_login_keeps_cookies_that_simplecookie_would_drop(monkeypatch):
    # Python's SimpleCookie silently discards a whole Set-Cookie header with
    # an attribute it doesn't know (e.g. Partitioned) or a quote/space in the
    # value - that lost the long-lived uoid.ps cookie on a real login, so
    # the ~19-day silent refresh never worked.
    _install_fake_session(
        monkeypatch,
        [
            _discovery_route(),
            ("GET", AUTH_URL_PREFIX, redirect(LOGIN_PAGE_URL)),
            (
                "POST",
                PASSWORD_URL,
                redirect(
                    CONTINUE_URL,
                    raw_set_cookies=[
                        "uoid.ps=persist1; Path=/; Secure; HttpOnly; SameSite=None; Partitioned",
                        'uoid.s="quoted value"; Path=/; Secure',
                        "uoid.bs=b; Path=/",
                    ],
                ),
            ),
            ("GET", CONTINUE_URL, redirect(f"{CALLBACK_URL}?code=abc123")),
            ("GET", CALLBACK_URL, redirect(DASHBOARD_URL)),
            ("GET", DASHBOARD_URL, ok(DASHBOARD_URL, set_cookies={"PHPSESSID": "sess1"})),
            _settle_route(),
        ],
    )

    session = await auth.login(SCHOOL, "user@example.com", "hunter2")

    assert session.cookies.get(PLUS4U_HOST, "uoid.ps") == "persist1"
    assert session.cookies.get(PLUS4U_HOST, "uoid.s") == '"quoted value"'
    assert session.cookies.get(PLUS4U_HOST, "uoid.bs") == "b"


@pytest.mark.asyncio
async def test_cookie_cleared_by_the_server_is_dropped(monkeypatch):
    _install_fake_session(
        monkeypatch,
        [
            _discovery_route(),
            ("GET", AUTH_URL_PREFIX, redirect(LOGIN_PAGE_URL, set_cookies={"uoid.old": "x"})),
            (
                "POST",
                PASSWORD_URL,
                redirect(
                    CONTINUE_URL,
                    raw_set_cookies=["uoid.old=; Max-Age=0; Path=/", "uoid.ps=p; Path=/"],
                ),
            ),
            ("GET", CONTINUE_URL, redirect(f"{CALLBACK_URL}?code=abc123")),
            ("GET", CALLBACK_URL, redirect(DASHBOARD_URL)),
            ("GET", DASHBOARD_URL, ok(DASHBOARD_URL, set_cookies={"PHPSESSID": "sess1"})),
            _settle_route(),
        ],
    )

    session = await auth.login(SCHOOL, "user@example.com", "hunter2")

    assert session.cookies.get(PLUS4U_HOST, "uoid.ps") == "p"
    assert session.cookies.get(PLUS4U_HOST, "uoid.old") is None


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
async def test_login_raises_connection_error_when_portal_is_unreachable(monkeypatch):
    _install_fake_session(
        monkeypatch,
        [("GET", LOGIN_URL, FailingResponse(aiohttp.ClientConnectionError("refused")))],
    )

    with pytest.raises(EdookitConnectionError):
        await auth.login(SCHOOL, "user@example.com", "hunter2")


@pytest.mark.asyncio
async def test_login_uses_an_injected_http_session_instead_of_opening_one(monkeypatch):
    def fail() -> None:
        raise AssertionError("login opened its own session despite http= being passed")

    monkeypatch.setattr(transport, "_new_http_session", fail)
    injected = FakeClientSession([("GET", LOGIN_URL, ok(LOGIN_URL, body="<html></html>"))])

    with pytest.raises(AuthError):
        await auth.login(SCHOOL, "user@example.com", "hunter2", http=injected)


@pytest.mark.asyncio
async def test_probe_client_id_returns_the_discovered_value(monkeypatch):
    _install_fake_session(monkeypatch, [_discovery_route()])

    client_id = await auth.probe_client_id(SCHOOL)

    assert client_id == DISCOVERED_CLIENT_ID


@pytest.mark.asyncio
async def test_refresh_success_reuses_plus4u_cookies_without_password(monkeypatch):
    stale = Session.from_cookies(
        SCHOOL,
        edookit={"PHPSESSID": "old", "uu.app.csrf": "old-csrf"},
        plus4u={"uoid.ps": "p", "uoid.s": "s", "uoid.bs": "b"},
    )
    _install_fake_session(
        monkeypatch,
        [
            _discovery_route(),
            (
                "GET",
                AUTH_URL_PREFIX,
                redirect(
                    f"{CALLBACK_URL}?code=fresh123",
                    set_cookies={"uoid.s": "s2", "uoid.bs": "b2"},
                ),
            ),
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

    assert refreshed.cookies.get(EDOOKIT_HOST, "PHPSESSID") == "sess-new"
    assert refreshed.csrf_token == "csrf2"
    assert refreshed.cookies.get(PLUS4U_HOST, "uoid.ps") == "p"
    assert refreshed.cookies.get(PLUS4U_HOST, "uoid.s") == "s2"
    assert refreshed.cookies.get(PLUS4U_HOST, "uoid.bs") == "b2"
    assert stale.cookies.get(PLUS4U_HOST, "uoid.s") == "s"
    assert stale.cookies.get(PLUS4U_HOST, "uoid.bs") == "b"
    assert stale.cookies.get(PLUS4U_HOST, "uoid.ps") == "p"
    assert stale.cookies.get(EDOOKIT_HOST, "PHPSESSID") == "old"
    assert stale.cookies.get(EDOOKIT_HOST, "uu.app.csrf") == "old-csrf"


@pytest.mark.asyncio
async def test_refresh_does_not_send_the_stale_edookit_session_to_the_login_page(monkeypatch):
    # Confirmed on a real portal: /user/login with an expired edookit session
    # cookie redirects to /oidc/logout instead of serving the page that holds
    # the Plus4U client_id, so refresh failed on its very first request.
    def login_page(headers: dict[str, str]):
        if "PHPSESSID" in headers.get("Cookie", ""):
            return redirect(f"https://{SCHOOL}.edookit.net/oidc/logout?performCallback=1")
        return ok(LOGIN_URL, body=LOGIN_PAGE_HTML, set_cookies={"PHPSESSID": "fresh"})

    stale = Session.from_cookies(
        SCHOOL,
        edookit={"PHPSESSID": "old", "uu.app.csrf": "old-csrf"},
        plus4u={"uoid.ps": "p"},
    )
    _install_fake_session(
        monkeypatch,
        [
            ("GET", LOGIN_URL, login_page),
            ("GET", AUTH_URL_PREFIX, redirect(f"{CALLBACK_URL}?code=fresh123")),
            ("GET", CALLBACK_URL, redirect(DASHBOARD_URL)),
            ("GET", DASHBOARD_URL, ok(DASHBOARD_URL, set_cookies={"uu.app.csrf": "csrf2"})),
            _settle_route(),
        ],
    )

    refreshed = await auth.refresh(stale)

    assert refreshed.cookies.get(EDOOKIT_HOST, "PHPSESSID") == "fresh"
    assert refreshed.cookies.get(EDOOKIT_HOST, "uu.app.csrf") == "csrf2"
    assert refreshed.csrf_token == "csrf2"


@pytest.mark.asyncio
async def test_refresh_raises_auth_error_when_plus4u_cookie_expired(monkeypatch):
    stale = Session.from_cookies(
        SCHOOL,
        edookit={"PHPSESSID": "old", "uu.app.csrf": "old-csrf"},
        plus4u={"uoid.ps": "expired"},
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

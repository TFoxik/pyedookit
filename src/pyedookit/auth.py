from __future__ import annotations

import json as _json
import re
import secrets

import aiohttp
from yarl import URL

from . import transport
from .exceptions import AuthError
from .session import PLUS4U_HOST, Session, school_base, school_host, validate_school
from .transport import CookieStore, Response

_PLUS4U_OIDC_BASE = (
    "https://uuidentity.plus4u.net/uu-oidc-maing02/bb977a99f4cc4c37a2afce3fd599d0a7"
)
_AUTH_URL = f"{_PLUS4U_OIDC_BASE}/oidc/auth"
_AUTH_PASSWORD_URL = f"{_PLUS4U_OIDC_BASE}/authPassword/authenticate"
_REALM_CODE = "uuIdentityPasswordAuthNRealm"

# Confirmed against a real portal: the OIDC client_id is per-school, not a
# single value shared across every Edookit install (third-party docs this
# was originally inferred from implied otherwise). Each school's /user/login
# page embeds it in a small inline JS config block, e.g.
#   uu_app_oidc_providers_oidcg02_client_id: "983960dcb7b84b34b9aecc5194381d56"
# so it has to be scraped fresh per school rather than hardcoded.
_CLIENT_ID_RE = re.compile(
    r"uu_app_oidc_providers_oidcg02_client_id\s*:\s*['\"]([^'\"]+)['\"]"
)

# Edookit sends the browser back to one of these paths when a session has
# expired or was never valid; shared with client.py so "did we get logged
# out" is checked the same way everywhere.
LOGIN_MARKERS = ("/user/login", "/user/oidc")


def is_login_url(url: str) -> bool:
    return any(marker in url for marker in LOGIN_MARKERS)


def _callback_url(school: str) -> str:
    return f"{school_base(school)}/user/oidc-login-callback"


def _auth_params(
    school: str, client_id: str, state: str, *, prompt_none: bool = False
) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _callback_url(school),
        "scope": "openid",
        "state": state,
    }
    if prompt_none:
        params["prompt"] = "none"
    return params


async def _discover_client_id(
    http: aiohttp.ClientSession, school: str, cookies: CookieStore
) -> str:
    """Scrape the school's own /user/login page for its Plus4U client_id.

    Its Set-Cookie response - PHPSESSID etc. - lands in `cookies` and so
    joins the rest of the login flow, rather than being discarded.
    """
    result = await transport.request(http, "GET", f"{school_base(school)}/user/login", cookies)
    match = _CLIENT_ID_RE.search(result.text)
    if not match:
        raise AuthError(f"could not find a Plus4U client_id on {school}'s login page")
    return match.group(1)


def _session_from_cookies(school: str, cookies: CookieStore) -> Session:
    if not cookies.get(school_host(school), "PHPSESSID"):
        raise AuthError("login flow completed but no edookit session cookie was set")
    return Session(school=school, cookies=cookies)


async def _finish_callback(
    http: aiohttp.ClientSession, callback_url: str, cookies: CookieStore, school: str
) -> Session:
    """Follow the final OIDC callback redirect chain and build a Session from it.

    Shared tail of login() and refresh(): both end with "GET the code=
    callback, make sure we didn't land back on the login page, then read the
    cookies that piled up along the way."

    Confirmed against a real browser trace (HAR): after the callback GET
    resolves (still 200 on /oidc/callback), the browser makes one more GET
    to the portal root, which is what actually settles the session server
    side - skipping it leaves the account looking like it has almost no
    modules enabled (only the dashboard and badges), even though login
    itself succeeded and the session cookies are valid.
    """
    result = await transport.request(http, "GET", callback_url, cookies, follow_redirects=True)
    if is_login_url(result.url):
        raise AuthError("edookit rejected the Plus4U authorization code")
    settle = await transport.request(
        http, "GET", school_base(school), cookies, follow_redirects=True
    )
    if is_login_url(settle.url):
        raise AuthError("session did not settle after the OIDC callback")
    return _session_from_cookies(school, cookies)


async def probe_client_id(school: str) -> str:
    """Discover a school's Plus4U client_id without logging in.

    Used by scripts/capture_fixtures.py to show what login()/refresh() will
    use for this school before spending the user's password.
    """
    validate_school(school)
    async with transport.http_session(None) as http:
        return await _discover_client_id(http, school, CookieStore())


async def _authorize(
    http: aiohttp.ClientSession, school: str, cookies: CookieStore, *, prompt_none: bool = False
) -> tuple[str, str, Response]:
    """Start the OIDC authorization: shared opening of login() and refresh()."""
    client_id = await _discover_client_id(http, school, cookies)
    state = secrets.token_urlsafe(16)
    params = _auth_params(school, client_id, state, prompt_none=prompt_none)
    return client_id, state, await transport.request(
        http, "GET", _AUTH_URL, cookies, params=params
    )


async def login(
    school: str,
    username: str,
    password: str,
    *,
    http: aiohttp.ClientSession | None = None,
) -> Session:
    """Run the Plus4U OIDC password login and return a usable Session.

    Raises AuthError if the credentials are rejected or the flow's shape has
    changed (e.g. Edookit or Plus4U altered a redirect), and
    EdookitConnectionError if either host can't be reached.

    A passed-in `http` session must not keep its own cookies (use
    `aiohttp.DummyCookieJar()`): cookies are tracked per host by hand here,
    and a real jar would also collect and resend them.
    """
    validate_school(school)
    cookies = CookieStore()
    async with transport.http_session(http) as http:
        client_id, state, step1 = await _authorize(http, school, cookies)
        if not step1.is_redirect or not step1.location:
            raise AuthError(f"expected a redirect from Plus4U auth endpoint, got {step1.status}")
        login_url = URL(step1.location)
        server_state = login_url.query.get("state", state)
        server_client_id = login_url.query.get("clientId", client_id)

        payload = {
            "clientId": server_client_id,
            "state": server_state,
            "rememberMe": True,
            "realmCode": _REALM_CODE,
            "username": username,
            "password": password,
        }
        step2 = await transport.request(http, "POST", _AUTH_PASSWORD_URL, cookies, json=payload)
        if step2.status in (400, 401):
            raise AuthError("Plus4U rejected the username or password")
        continue_url = step2.location
        if not continue_url and step2.text:
            try:
                body = _json.loads(step2.text)
            except ValueError:
                body = None
            if isinstance(body, dict):
                continue_url = body.get("redirectUrl")
        if not continue_url:
            raise AuthError("Plus4U password auth did not return a continuation URL")

        step3 = await transport.request(http, "GET", continue_url, cookies)
        if not step3.location or "code=" not in step3.location:
            raise AuthError("Plus4U did not return an authorization code")

        return await _finish_callback(http, step3.location, cookies, school)


async def refresh(session: Session, *, http: aiohttp.ClientSession | None = None) -> Session:
    """Obtain a fresh edookit session using the stored Plus4U cookies.

    No password is needed; this is what keeps a long-running Home Assistant
    integration logged in across the ~30-60 minute edookit session lifetime.
    Raises AuthError if the Plus4U cookies have themselves expired (roughly
    every 19 days), which means a full `login()` with the password is needed.
    `http` has the same cookie-jar requirement as in `login()`.
    """
    # Only the Plus4U cookies: the portal answers /user/login with a redirect
    # to /oidc/logout when it sees the expired edookit session, so the new
    # edookit session is built from scratch, exactly like in login().
    cookies = session.cookies.for_host(PLUS4U_HOST)
    async with transport.http_session(http) as http:
        _, _, step1 = await _authorize(http, session.school, cookies, prompt_none=True)
        if not step1.is_redirect or not step1.location or "code=" not in step1.location:
            raise AuthError("Plus4U session expired; full login required")

        return await _finish_callback(http, step1.location, cookies, session.school)

from __future__ import annotations

import json as _json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass

import aiohttp
from yarl import URL

from .exceptions import AuthError
from .session import Session

_PLUS4U_OIDC_BASE = (
    "https://uuidentity.plus4u.net/uu-oidc-maing02/bb977a99f4cc4c37a2afce3fd599d0a7"
)
_AUTH_URL = f"{_PLUS4U_OIDC_BASE}/oidc/auth"
_AUTH_PASSWORD_URL = f"{_PLUS4U_OIDC_BASE}/authPassword/authenticate"
_REALM_CODE = "uuIdentityPasswordAuthNRealm"

# Observed on one school's login redirect. Edookit apps may all share a single
# Plus4U OIDC client, but this hasn't been confirmed across schools yet -
# `probe_client_id()` / `scripts/capture_fixtures.py` check the value seen on
# a real portal against this one.
CLIENT_ID = "0fa24fa43e794de89003790253a93cb6"

_PLUS4U_HOST = "uuidentity.plus4u.net"
_MAX_REDIRECTS = 5

# A school subdomain becomes part of a URL (redirect_uri, portal base) with
# no other encoding, so reject anything that isn't a bare hostname label -
# otherwise a value like "evil.com/" would redirect the OIDC flow off-portal.
_SCHOOL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Edookit sends the browser back to one of these paths when a session has
# expired or was never valid; shared with client.py so "did we get logged
# out" is checked the same way everywhere.
LOGIN_MARKERS = ("/user/login", "/user/oidc")


def is_login_url(url: str) -> bool:
    return any(marker in url for marker in LOGIN_MARKERS)


# Cookies are tracked per host explicitly rather than via aiohttp's
# CookieJar: the login flow hops between the plus4u.net and edookit.net
# hosts, and a plain per-host dict is simpler to reason about (and to test)
# than relying on the jar's own domain-matching for a flow that only ever
# touches two hosts.
CookiesByHost = dict[str, dict[str, str]]


@dataclass(slots=True)
class _FetchResult:
    status: int
    url: str
    text: str
    location: str | None
    is_redirect: bool


def _validate_school(school: str) -> None:
    if not _SCHOOL_RE.match(school):
        raise AuthError(f"{school!r} is not a valid Edookit school subdomain")


def _school_host(school: str) -> str:
    return f"{school}.edookit.net"


def _school_base(school: str) -> str:
    return f"https://{_school_host(school)}"


def _callback_url(school: str) -> str:
    return f"{_school_base(school)}/user/oidc-login-callback"


def _cookie_header(cookies: Mapping[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _auth_params(school: str, state: str, *, prompt_none: bool = False) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": _callback_url(school),
        "scope": "openid",
        "state": state,
    }
    if prompt_none:
        params["prompt"] = "none"
    return params


async def _fetch(
    http: aiohttp.ClientSession,
    method: str,
    url: str,
    cookies_by_host: CookiesByHost,
    *,
    json: dict[str, object] | None = None,
    params: Mapping[str, str] | None = None,
    follow_redirects: bool = False,
) -> _FetchResult:
    """Make one request (optionally chasing redirects), updating cookies_by_host in place.

    Each hop sends only the cookies stored for that hop's own host, and any
    Set-Cookie in the response is recorded under that same host - this is
    what lets the flow move from plus4u.net to <school>.edookit.net without
    leaking cookies to the wrong domain.
    """
    current_url = url
    current_method = method
    current_json = json
    current_params = params

    for _ in range(_MAX_REDIRECTS + 1):
        host = URL(current_url).host or ""
        headers: dict[str, str] = {}
        host_cookies = cookies_by_host.get(host)
        if host_cookies:
            headers["Cookie"] = _cookie_header(host_cookies)

        async with http.request(
            current_method,
            current_url,
            params=current_params,
            json=current_json,
            headers=headers,
            allow_redirects=False,
        ) as resp:
            new_cookies = {key: morsel.value for key, morsel in resp.cookies.items()}
            if new_cookies:
                cookies_by_host.setdefault(host, {}).update(new_cookies)

            is_redirect = resp.status in REDIRECT_STATUSES
            location = resp.headers.get("Location")
            text = "" if is_redirect else await resp.text()
            result = _FetchResult(
                status=resp.status,
                url=str(resp.url),
                text=text,
                location=location,
                is_redirect=is_redirect,
            )

        if not (follow_redirects and is_redirect and location):
            return result

        current_url = str(URL(current_url).join(URL(location)))
        current_method = "GET"
        current_json = None
        current_params = None

    raise AuthError("too many redirects while following the Plus4U/edookit login flow")


def _new_http_session() -> aiohttp.ClientSession:
    # Cookies are tracked manually in `cookies_by_host`, not via aiohttp's own
    # jar, so redirect-following never needs a real one; tests replace this
    # factory with a fake session instead of mocking ClientSession internals.
    return aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())


def _session_from_cookies(school: str, cookies_by_host: CookiesByHost) -> Session:
    edookit_cookies = cookies_by_host.get(_school_host(school), {})
    plus4u_cookies = cookies_by_host.get(_PLUS4U_HOST, {})
    if not edookit_cookies.get("PHPSESSID"):
        raise AuthError("login flow completed but no edookit session cookie was set")
    return Session(
        school=school,
        edookit_cookies=edookit_cookies,
        plus4u_cookies=plus4u_cookies,
        csrf_token=edookit_cookies.get("uu.app.csrf", ""),
    )


async def _finish_callback(
    http: aiohttp.ClientSession,
    callback_url: str,
    cookies_by_host: CookiesByHost,
    school: str,
) -> Session:
    """Follow the final OIDC callback redirect chain and build a Session from it.

    Shared tail of login() and refresh(): both end with "GET the code=
    callback, make sure we didn't land back on the login page, then read the
    cookies that piled up along the way."
    """
    result = await _fetch(http, "GET", callback_url, cookies_by_host, follow_redirects=True)
    if is_login_url(result.url):
        raise AuthError("edookit rejected the Plus4U authorization code")
    return _session_from_cookies(school, cookies_by_host)


async def probe_client_id(school: str) -> str:
    """GET the Plus4U auth redirect without logging in, to observe its clientId.

    Used by scripts/capture_fixtures.py to check CLIENT_ID against a real
    school before spending the user's password on a full login.
    """
    _validate_school(school)
    cookies_by_host: CookiesByHost = {}
    async with _new_http_session() as http:
        state = secrets.token_urlsafe(16)
        step1 = await _fetch(
            http, "GET", _AUTH_URL, cookies_by_host, params=_auth_params(school, state)
        )
        if not step1.is_redirect or not step1.location:
            raise AuthError(f"expected a redirect from Plus4U auth endpoint, got {step1.status}")
        return URL(step1.location).query.get("clientId", CLIENT_ID)


async def login(school: str, username: str, password: str) -> Session:
    """Run the Plus4U OIDC password login and return a usable Session.

    Raises AuthError if the credentials are rejected or the flow's shape has
    changed (e.g. Edookit or Plus4U altered a redirect).
    """
    _validate_school(school)
    cookies_by_host: CookiesByHost = {}
    async with _new_http_session() as http:
        state = secrets.token_urlsafe(16)
        step1 = await _fetch(
            http, "GET", _AUTH_URL, cookies_by_host, params=_auth_params(school, state)
        )
        if not step1.is_redirect or not step1.location:
            raise AuthError(f"expected a redirect from Plus4U auth endpoint, got {step1.status}")
        login_url = URL(step1.location)
        server_state = login_url.query.get("state", state)
        client_id = login_url.query.get("clientId", CLIENT_ID)

        payload = {
            "clientId": client_id,
            "state": server_state,
            "rememberMe": True,
            "realmCode": _REALM_CODE,
            "username": username,
            "password": password,
        }
        step2 = await _fetch(http, "POST", _AUTH_PASSWORD_URL, cookies_by_host, json=payload)
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

        step3 = await _fetch(http, "GET", continue_url, cookies_by_host)
        if not step3.location or "code=" not in step3.location:
            raise AuthError("Plus4U did not return an authorization code")

        return await _finish_callback(http, step3.location, cookies_by_host, school)


async def refresh(session: Session) -> Session:
    """Obtain a fresh edookit session using the stored Plus4U cookies.

    No password is needed; this is what keeps a long-running Home Assistant
    integration logged in across the ~30-60 minute edookit session lifetime.
    Raises AuthError if the Plus4U cookies have themselves expired (roughly
    every 19 days), which means a full `login()` with the password is needed.
    """
    _validate_school(session.school)
    cookies_by_host: CookiesByHost = {
        _PLUS4U_HOST: dict(session.plus4u_cookies),
        _school_host(session.school): dict(session.edookit_cookies),
    }
    async with _new_http_session() as http:
        state = secrets.token_urlsafe(16)
        step1 = await _fetch(
            http,
            "GET",
            _AUTH_URL,
            cookies_by_host,
            params=_auth_params(session.school, state, prompt_none=True),
        )
        if not step1.is_redirect or not step1.location or "code=" not in step1.location:
            raise AuthError("Plus4U session expired; full login required")

        return await _finish_callback(http, step1.location, cookies_by_host, session.school)


def build_headers(session: Session) -> dict[str, str]:
    """Cookie/CSRF headers for a plain page request against the school's portal."""
    return {
        "Cookie": _cookie_header(session.edookit_cookies),
        "X-CSRF-Token": session.csrf_token,
        "X-Requested-With": "XMLHttpRequest",
    }

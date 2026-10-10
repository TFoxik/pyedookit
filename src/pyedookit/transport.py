from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import aiohttp
from yarl import URL

from .exceptions import AuthError, EdookitConnectionError

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_REDIRECTS = 5
# Every hop stays on these over https; anything else means a response was
# tampered with, and must not receive cookies or an authorization code.
_ALLOWED_HOST_SUFFIXES = (".plus4u.net", ".edookit.net")


@dataclass(frozen=True, slots=True)
class Cookie:
    value: str
    expires: datetime | None = None


class CookieStore:
    """Cookies per host, kept the way a browser keeps them.

    Set-Cookie is parsed by hand: aiohttp's SimpleCookie drops a whole header
    on an attribute it doesn't know (Plus4U's `Partitioned`) or on unquoted
    spaces in the value, which is how the long-lived `uoid.ps` was lost.
    Values are kept verbatim because that is what gets sent back.
    """

    def __init__(self, cookies: Mapping[str, Mapping[str, Cookie]] | None = None) -> None:
        self._hosts: dict[str, dict[str, Cookie]] = {
            host: dict(jar) for host, jar in (cookies or {}).items()
        }

    def get(self, host: str, name: str) -> str | None:
        cookie = self._live(host).get(name)
        return cookie.value if cookie else None

    def expires(self, host: str, name: str) -> datetime | None:
        cookie = self._live(host).get(name)
        return cookie.expires if cookie else None

    def header(self, host: str) -> str:
        return "; ".join(f"{name}={cookie.value}" for name, cookie in self._live(host).items())

    def update(self, host: str, set_cookie_headers: Iterable[str]) -> None:
        jar = self._hosts.setdefault(host, {})
        now = datetime.now(UTC)
        for header in set_cookie_headers:
            if (parsed := _parse_set_cookie(header, now)) is None:
                continue
            name, cookie = parsed
            if cookie.expires is not None and cookie.expires <= now:
                jar.pop(name, None)
            else:
                jar[name] = cookie

    def for_host(self, host: str) -> CookieStore:
        return CookieStore({host: self._hosts.get(host, {})})

    def to_dict(self) -> dict[str, dict[str, dict[str, str | None]]]:
        return {
            host: {
                name: {
                    "value": cookie.value,
                    "expires": cookie.expires.isoformat() if cookie.expires else None,
                }
                for name, cookie in jar.items()
            }
            for host, jar in self._hosts.items()
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Mapping[str, Mapping[str, str | None]]]) -> CookieStore:
        return cls(
            {
                host: {
                    name: Cookie(str(raw["value"]), _from_iso(raw.get("expires")))
                    for name, raw in jar.items()
                }
                for host, jar in data.items()
            }
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CookieStore) and self._hosts == other._hosts

    def _live(self, host: str) -> dict[str, Cookie]:
        now = datetime.now(UTC)
        return {
            name: cookie
            for name, cookie in self._hosts.get(host, {}).items()
            if cookie.expires is None or cookie.expires > now
        }


def _from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_set_cookie(header: str, now: datetime) -> tuple[str, Cookie] | None:
    pair, _, attributes = header.partition(";")
    name, sep, value = pair.partition("=")
    name = name.strip()
    if not sep or not name:
        return None
    max_age: int | None = None
    expires: datetime | None = None
    for attribute in attributes.split(";"):
        key, _, raw = attribute.partition("=")
        key, raw = key.strip().lower(), raw.strip()
        if key == "max-age":
            try:
                max_age = int(raw)
            except ValueError:
                continue
        elif key == "expires":
            try:
                expires = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                continue
    if max_age is not None:
        # RFC 6265 5.3: Max-Age takes precedence over Expires.
        try:
            expires = now + timedelta(seconds=max_age)
        except OverflowError:
            expires = datetime.max.replace(tzinfo=UTC) if max_age > 0 else now
    elif expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return name, Cookie(value.strip(), expires)


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    url: str
    text: str
    location: str | None
    content_type: str

    @property
    def is_redirect(self) -> bool:
        return self.status in REDIRECT_STATUSES


def check_hop(url: URL) -> None:
    host = url.host or ""
    if url.scheme != "https" or not host.endswith(_ALLOWED_HOST_SUFFIXES):
        raise AuthError(f"request tried to leave Plus4U/Edookit (to {url.scheme}://{host})")


async def request(
    http: aiohttp.ClientSession,
    method: str,
    url: str,
    cookies: CookieStore,
    *,
    headers: Mapping[str, str] | None = None,
    json: dict[str, object] | None = None,
    params: Mapping[str, str | int] | None = None,
    follow_redirects: bool = False,
) -> Response:
    """One request (optionally chasing redirects), keeping `cookies` up to date.

    Redirects are never left to aiohttp: older versions forward a manually
    set Cookie header to a redirect target on another host. Each hop sends
    only its own host's cookies, and `headers` only go to the first hop.
    """
    current_url, current_method = url, method
    current_json, current_params, extra_headers = json, params, headers
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = URL(current_url)
        check_hop(parsed)
        host = parsed.host or ""
        request_headers = dict(extra_headers or {})
        if cookie_header := cookies.header(host):
            request_headers["Cookie"] = cookie_header
        try:
            async with http.request(
                current_method,
                current_url,
                params=current_params,
                json=current_json,
                headers=request_headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                cookies.update(host, resp.headers.getall("Set-Cookie", []))
                response = Response(
                    status=resp.status,
                    url=str(resp.url),
                    text="" if resp.status in REDIRECT_STATUSES else await resp.text(),
                    location=resp.headers.get("Location"),
                    content_type=resp.headers.get("Content-Type", ""),
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EdookitConnectionError(f"request to {host} failed: {err}") from err

        if not (follow_redirects and response.is_redirect and response.location):
            return response
        current_url = str(parsed.join(URL(response.location)))
        current_method, current_json, current_params, extra_headers = "GET", None, None, None

    raise AuthError("too many redirects while following the Plus4U/edookit login flow")


def _new_http_session() -> aiohttp.ClientSession:
    # Cookies live in CookieStore, never in aiohttp's jar; tests replace this
    # factory with a fake session instead of mocking ClientSession internals.
    return aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())


@asynccontextmanager
async def http_session(
    http: aiohttp.ClientSession | None,
) -> AsyncIterator[aiohttp.ClientSession]:
    if http is not None:
        yield http
        return
    async with _new_http_session() as own:
        yield own

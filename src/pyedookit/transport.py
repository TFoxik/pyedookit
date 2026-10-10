from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime


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

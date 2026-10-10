"""A minimal aiohttp.ClientSession stand-in for testing auth.py.

aioresponses (the usual mocking choice) monkeypatches ClientSession
internals that have changed across aiohttp releases, which would force
pinning aiohttp to an old version just for tests - unacceptable for a
library meant to run inside Home Assistant, which tracks recent aiohttp.
This fake only implements the handful of members auth.py actually uses
(`.request()` as an async context manager exposing `.status`, `.headers`,
`.url`, `.text()`), so it has nothing to break when aiohttp changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from multidict import CIMultiDict


@dataclass
class FakeResponse:
    status: int
    headers: CIMultiDict = field(default_factory=CIMultiDict)
    body: str = ""
    url: str = ""

    async def text(self) -> str:
        return self.body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _response(
    status: int,
    url: str,
    set_cookies: dict[str, str] | None = None,
    body: str = "",
    raw_set_cookies: list[str] | None = None,
    **headers: str,
) -> FakeResponse:
    all_headers: CIMultiDict[str] = CIMultiDict(headers)
    for key, value in (set_cookies or {}).items():
        all_headers.add("Set-Cookie", f"{key}={value}; Path=/")
    for raw in raw_set_cookies or []:
        all_headers.add("Set-Cookie", raw)
    return FakeResponse(status=status, headers=all_headers, body=body, url=url)


def redirect(
    location: str,
    set_cookies: dict[str, str] | None = None,
    raw_set_cookies: list[str] | None = None,
) -> FakeResponse:
    return _response(302, location, set_cookies, raw_set_cookies=raw_set_cookies, Location=location)


def ok(
    url: str,
    set_cookies: dict[str, str] | None = None,
    body: str = "<html>ok</html>",
    raw_set_cookies: list[str] | None = None,
    content_type: str = "text/html; charset=utf-8",
) -> FakeResponse:
    return _response(
        200,
        url,
        set_cookies,
        body=body,
        raw_set_cookies=raw_set_cookies,
        **{"Content-Type": content_type},
    )


def rejected(status: int = 401) -> FakeResponse:
    return FakeResponse(status=status)


class FakeClientSession:
    """Routes (method, url-prefix) pairs to canned FakeResponses, in order.

    Each route is consumed once so a test can script a sequence of requests
    to the same URL returning different responses, matching how the real
    login/refresh flows each hit some endpoints exactly once.
    """

    def __init__(self, routes: list[tuple[str, str, FakeResponse]]) -> None:
        self._routes = list(routes)

    async def __aenter__(self) -> FakeClientSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        for index, (route_method, url_prefix, response) in enumerate(self._routes):
            if route_method.upper() == method.upper() and str(url).startswith(url_prefix):
                del self._routes[index]
                # A route may be a callable taking the request headers, for
                # endpoints whose answer depends on the cookies sent.
                return response(kwargs.get("headers") or {}) if callable(response) else response
        raise AssertionError(f"FakeClientSession: no route for {method} {url}")

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        return self.request("GET", url, **kwargs)


class FailingResponse:
    """Raises on entry, the way aiohttp does when a host can't be reached."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def __aenter__(self) -> FailingResponse:
        raise self._error

    async def __aexit__(self, *exc: object) -> bool:
        return False

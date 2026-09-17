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

from collections.abc import Callable
from dataclasses import dataclass, field

from multidict import CIMultiDict
from yarl import URL


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


def redirect(location: str, set_cookies: dict[str, str] | None = None) -> FakeResponse:
    headers = CIMultiDict({"Location": location})
    for key, value in (set_cookies or {}).items():
        headers.add("Set-Cookie", f"{key}={value}; Path=/")
    return FakeResponse(status=302, headers=headers, url=location)


def ok(
    url: str, set_cookies: dict[str, str] | None = None, body: str = "<html>ok</html>"
) -> FakeResponse:
    headers = CIMultiDict()
    for key, value in (set_cookies or {}).items():
        headers.add("Set-Cookie", f"{key}={value}; Path=/")
    return FakeResponse(status=200, headers=headers, body=body, url=url)


def rejected(status: int = 401) -> FakeResponse:
    return FakeResponse(status=status)


Matcher = Callable[[str], bool]


def prefix(url: str) -> Matcher:
    return lambda actual: actual.startswith(url)


class FakeClientSession:
    """Routes (method, url-matcher) pairs to canned FakeResponses, in order.

    Each route is consumed once so a test can script a sequence of requests
    to the same URL returning different responses, matching how the real
    login/refresh flows each hit some endpoints exactly once.
    """

    def __init__(self, routes: list[tuple[str, Matcher, FakeResponse]]) -> None:
        self._routes = list(routes)
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> FakeClientSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        full_url = str(URL(url).with_query(kwargs.get("params") or {}))
        self.calls.append((method, full_url))
        for index, (route_method, matcher, response) in enumerate(self._routes):
            if route_method.upper() == method.upper() and matcher(str(url)):
                del self._routes[index]
                return response
        raise AssertionError(f"FakeClientSession: no route for {method} {url}")

from __future__ import annotations

import aiohttp

from . import auth
from .exceptions import EdookitConnectionError, SessionExpired
from .models import Lesson, Term
from .parsers.timetable import parse_terms, parse_timetable
from .session import Session

_TIMETABLE_PATH = "/timetable/"


class EdookitClient:
    """Fetches parsed data from one school's Edookit parent portal.

    Holds a `Session` that the caller is responsible for persisting and
    refreshing (see `pyedookit.auth.refresh`); this class only detects when
    the current session has gone stale and raises `SessionExpired` so the
    caller can refresh and retry.

    Pass `http` to reuse an existing `aiohttp.ClientSession` across requests
    instead of opening a new connection per call; otherwise one is created
    and closed per request. Cookies are sent by hand, so give it a
    `aiohttp.DummyCookieJar()` rather than a shared session whose jar would
    also collect the portal's cookies.
    """

    def __init__(self, session: Session, http: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._http = http

    @property
    def session(self) -> Session:
        return self._session

    async def get_terms(self) -> list[Term]:
        html = await self.fetch_timetable_html()
        return parse_terms(html)

    async def get_timetable(self, week_offset: int = 0) -> list[Lesson]:
        html = await self.fetch_timetable_html(week_offset)
        return parse_timetable(html)

    async def fetch_timetable_html(self, week_offset: int = 0) -> str:
        """Raw `/timetable/` HTML for one week - also used by
        scripts/capture_fixtures.py, so the request shape lives in one place."""
        return await self._get(_TIMETABLE_PATH, params={"familyTimetable-value": week_offset})

    async def _get(self, path: str, params: dict[str, int] | None = None) -> str:
        url = f"{self._session.base_url}{path}"
        headers = auth.build_headers(self._session)
        if self._http is not None:
            return await self._request(self._http, url, params, headers)
        async with aiohttp.ClientSession() as http:
            return await self._request(http, url, params, headers)

    async def _request(
        self,
        http: aiohttp.ClientSession,
        url: str,
        params: dict[str, int] | None,
        headers: dict[str, str],
    ) -> str:
        # allow_redirects=False: our Cookie/CSRF headers are set manually, and
        # older aiohttp forwards a manually-set Cookie header to a redirect's
        # target even when that target is a different host - so an expired
        # session's redirect to Plus4U must never be followed with them
        # attached. Any redirect at all means the session isn't good anymore.
        try:
            async with http.get(
                url,
                params=params,
                headers=headers,
                allow_redirects=False,
                timeout=auth.REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in auth.REDIRECT_STATUSES or auth.is_login_url(str(resp.url)):
                    raise SessionExpired("edookit session has expired")
                return await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EdookitConnectionError(f"request to {url} failed: {err}") from err

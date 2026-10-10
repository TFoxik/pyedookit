from __future__ import annotations

import asyncio

import aiohttp

from . import auth
from .exceptions import EdookitConnectionError, SessionExpired
from .models import Lesson, Payments, SchoolEvent, Term
from .parsers.events import parse_events
from .parsers.payments import parse_payments
from .parsers.timetable import parse_terms, parse_timetable
from .session import Session

_TIMETABLE_PATH = "/timetable/"
_EVENTS_PATH = "/timetable/upcoming"
_PAYMENTS_PATH = "/payments/"

CAPTURE_PAGES: dict[str, str] = {
    "assignments": "/assignments/",
    "exams": "/exams/",
    "inbox": "/overview/updates",
    "consents": "/consents/",
}


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

    Pages are parsed in a worker thread so a large timetable doesn't stall
    the caller's event loop.
    """

    def __init__(self, session: Session, http: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._http = http

    @property
    def session(self) -> Session:
        return self._session

    async def get_terms(self) -> list[Term]:
        return await asyncio.to_thread(parse_terms, await self.fetch_timetable_html())

    async def get_timetable(self, week_offset: int = 0) -> list[Lesson]:
        html = await self.fetch_timetable_html(week_offset)
        return await asyncio.to_thread(parse_timetable, html)

    async def fetch_timetable_html(self, week_offset: int = 0) -> str:
        """Raw `/timetable/` HTML for one week - also used by
        scripts/capture_fixtures.py, so the request shape lives in one place."""
        return await self._get(_TIMETABLE_PATH, params={"familyTimetable-value": week_offset})

    async def get_events(self) -> list[SchoolEvent]:
        return await asyncio.to_thread(parse_events, await self._get(_EVENTS_PATH))

    async def get_payments(self) -> Payments:
        return await asyncio.to_thread(parse_payments, await self._get(_PAYMENTS_PATH))

    async def fetch_page(self, name: str) -> str:
        """Raw HTML of one of `CAPTURE_PAGES`, for pages without a parser yet."""
        try:
            path = CAPTURE_PAGES[name]
        except KeyError:
            raise ValueError(f"{name!r} is not one of {sorted(CAPTURE_PAGES)}") from None
        return await self._get(path)

    async def _get(self, path: str, params: dict[str, int] | None = None) -> str:
        url = f"{self._session.base_url}{path}"
        # allow_redirects=False: our Cookie/CSRF headers are set manually, and
        # older aiohttp forwards a manually-set Cookie header to a redirect's
        # target even when that target is a different host - so an expired
        # session's redirect to Plus4U must never be followed with them
        # attached. Any redirect at all means the session isn't good anymore.
        try:
            async with (
                auth.http_session(self._http) as http,
                http.get(
                    url,
                    params=params,
                    headers=auth.build_headers(self._session),
                    allow_redirects=False,
                    timeout=auth.REQUEST_TIMEOUT,
                ) as resp,
            ):
                if resp.status in auth.REDIRECT_STATUSES:
                    raise SessionExpired("edookit session has expired")
                return await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EdookitConnectionError(f"request to {url} failed: {err}") from err

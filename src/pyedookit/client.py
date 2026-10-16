from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

import aiohttp

from . import auth, transport
from .exceptions import ParseError, SessionExpired
from .models import Lesson, Payments, SchoolEvent, Term, TimetableWeek
from .parsers.events import parse_events
from .parsers.payments import parse_payments
from .parsers.timetable import parse_periods, parse_terms, parse_timetable
from .session import Session

_LOGGER = logging.getLogger(__name__)

_TIMETABLE_PATH = "/timetable/"
_EVENTS_PATH = "/timetable/upcoming"
_PAYMENTS_PATH = "/payments/"

CAPTURE_PAGES: dict[str, str] = {
    "assignments": "/assignments/",
    "exams": "/exams/",
    "inbox": "/overview/updates",
    "consents": "/consents/",
}


def _parse_week(html: str) -> TimetableWeek:
    periods = parse_periods(html)
    try:
        lessons = parse_timetable(html)
    except ParseError:
        # A holiday week renders the bell-schedule header but no lessons;
        # a page with neither is not a timetable at all.
        if not periods:
            raise
        lessons = []
    return TimetableWeek(lessons, periods)


class EdookitClient:
    """Fetches parsed data from one school's Edookit parent portal.

    Renews an expired edookit session by itself from the Plus4U sign-in and
    retries once; `on_session_update` receives each renewed `Session` so the
    caller can persist it. `AuthError` means the Plus4U sign-in expired too
    and a full `login()` is needed.

    Pass `http` to reuse an existing `aiohttp.ClientSession` across requests
    instead of opening a new connection per call; otherwise one is created
    and closed per request. Cookies are sent by hand, so give it a
    `aiohttp.DummyCookieJar()` rather than a shared session whose jar would
    also collect the portal's cookies.

    Pages are parsed in a worker thread so a large timetable doesn't stall
    the caller's event loop.
    """

    def __init__(
        self,
        session: Session,
        http: aiohttp.ClientSession | None = None,
        *,
        on_session_update: Callable[[Session], None] | None = None,
    ) -> None:
        self._session = session
        self._http = http
        self._on_session_update = on_session_update
        self._renew_lock = asyncio.Lock()

    @property
    def session(self) -> Session:
        return self._session

    async def get_terms(self) -> list[Term]:
        return await asyncio.to_thread(parse_terms, await self.fetch_timetable_html())

    async def get_timetable(self, week_offset: int = 0) -> list[Lesson]:
        html = await self.fetch_timetable_html(week_offset)
        return await asyncio.to_thread(parse_timetable, html)

    async def get_timetable_week(self, week_offset: int = 0) -> TimetableWeek:
        """Lessons and bell schedule of one week, parsed from a single fetch."""
        html = await self.fetch_timetable_html(week_offset)
        return await asyncio.to_thread(_parse_week, html)

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
        session = self._session
        try:
            return await self._fetch(session, path, params)
        except SessionExpired:
            _LOGGER.debug("Edookit session expired, renewing it")
            await self._renew(session)
        return await self._fetch(self._session, path, params)

    async def _renew(self, stale: Session) -> None:
        async with self._renew_lock:
            if self._session is not stale:
                return
            self._session = await auth.refresh(stale, http=self._http)
            if self._on_session_update is not None:
                self._on_session_update(self._session)

    async def _fetch(self, session: Session, path: str, params: dict[str, int] | None) -> str:
        async with transport.http_session(self._http) as http:
            response = await transport.request(
                http,
                "GET",
                f"{session.base_url}{path}",
                session.cookies,
                headers={"X-CSRF-Token": session.csrf_token, "X-Requested-With": "XMLHttpRequest"},
                params=params,
            )
        if response.is_redirect or _is_ajax_redirect(response.content_type, response.text):
            raise SessionExpired("edookit session has expired")
        return response.text


def _is_ajax_redirect(content_type: str, body: str) -> bool:
    """Whether the portal answered with an AJAX-style redirect.

    Requests carry X-Requested-With, so an expired session gets a 200 with a
    JSON {"redirect": url} rather than an HTTP redirect. Both shapes seen on a
    real portal are expired sessions: /user/login?message=1 and
    /oidc/logout?performCallback=.... A redirect answer never carries the
    page, so the target URL is deliberately not inspected.
    """
    if not content_type.startswith("application/json"):
        return False
    try:
        data = json.loads(body)
    except ValueError:
        return False
    return isinstance(data, dict) and isinstance(data.get("redirect"), str)

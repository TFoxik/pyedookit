from __future__ import annotations

import asyncio
import json

import aiohttp

from . import auth, transport
from .exceptions import SessionExpired
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
        session = self._session
        async with transport.http_session(self._http) as http:
            response = await transport.request(
                http,
                "GET",
                f"{session.base_url}{path}",
                session.cookies,
                headers={"X-CSRF-Token": session.csrf_token, "X-Requested-With": "XMLHttpRequest"},
                params=params,
            )
        if response.is_redirect or _redirects_to_login(response.content_type, response.text):
            raise SessionExpired("edookit session has expired")
        return response.text


def _redirects_to_login(content_type: str, body: str) -> bool:
    """Whether the portal answered with its AJAX-style login redirect.

    Requests carry X-Requested-With, so an expired session gets a 200 with
    {"redirect": "https://<school>.edookit.net/user/login?message=1"} rather
    than an HTTP redirect (confirmed against a real portal).
    """
    if not content_type.startswith("application/json"):
        return False
    try:
        data = json.loads(body)
    except ValueError:
        return False
    redirect = data.get("redirect") if isinstance(data, dict) else None
    return isinstance(redirect, str) and auth.is_login_url(redirect)

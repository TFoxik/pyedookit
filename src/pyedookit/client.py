from __future__ import annotations

from datetime import date, timedelta

import aiohttp

from . import auth
from .exceptions import SessionExpired
from .models import Lesson, Term
from .parsers.timetable import parse_terms, parse_timetable
from .session import Session

_TIMETABLE_PATH = "/timetable/"
_LOGIN_MARKERS = ("/user/login", "/user/oidc")


class EdookitClient:
    """Fetches parsed data from one school's Edookit parent portal.

    Holds a `Session` that the caller is responsible for persisting and
    refreshing (see `pyedookit.auth.refresh`); this class only detects when
    the current session has gone stale and raises `SessionExpired` so the
    caller can refresh and retry.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    async def get_terms(self) -> list[Term]:
        html = await self._get(_TIMETABLE_PATH)
        return parse_terms(html)

    async def get_timetable(self, week_offset: int = 0) -> list[Lesson]:
        html = await self._get(_TIMETABLE_PATH, params={"familyTimetable-value": week_offset})
        return parse_timetable(html, week_start=_week_start(week_offset))

    async def _get(self, path: str, params: dict[str, object] | None = None) -> str:
        base = f"https://{self._session.school}.edookit.net"
        headers = auth.build_headers(self._session)
        async with aiohttp.ClientSession() as http:
            async with http.get(
                f"{base}{path}", params=params, headers=headers, allow_redirects=True
            ) as resp:
                final_url = str(resp.url)
                if any(marker in final_url for marker in _LOGIN_MARKERS):
                    raise SessionExpired("edookit session has expired")
                return await resp.text()


def _week_start(week_offset: int) -> date:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(weeks=week_offset)

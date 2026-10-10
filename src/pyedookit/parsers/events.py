from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import PORTAL_TZ, SchoolEvent
from .dates import TIME_RE, find_days, portal_today

_EVENT_ID_RE = re.compile(r"event=(\d+)")

_LOGGER = logging.getLogger(__name__)


def parse_events(html: str, today: date | None = None) -> list[SchoolEvent]:
    """Parse `/timetable/upcoming` ("Mé budoucí události").

    Confirmed against a real capture: one `ul.table_row` per event inside
    `div.events_table`, after a `gridLabel` header row that shares the class.
    Only a timed event on a single day, or an all-day event over one or more
    days, has been seen; anything else is skipped with a warning.
    """
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one("section.content") is None:
        raise ParseError("upcoming events page has no content section")
    if today is None:
        today = portal_today()

    events: list[SchoolEvent] = []
    for row in soup.select("div.events_table ul.table_row"):
        if "gridLabel" in (row.get("class") or []):
            continue
        event = _parse_row(row, today)
        if event is None:
            _LOGGER.warning("skipping unparseable event row %s", _event_id(row) or "?")
        else:
            events.append(event)
    return events


def _event_id(row: Tag) -> str | None:
    link = row.select_one("li.c2 a[href]")
    match = _EVENT_ID_RE.search(str(link.get("href"))) if link else None
    return match.group(1) if match else None


def _parse_row(row: Tag, today: date) -> SchoolEvent | None:
    event_id = _event_id(row)
    when = row.select_one("li.c1 b")
    title = row.select_one("li.c2 div.bold")
    if event_id is None or when is None or title is None:
        return None

    text = " ".join(when.get_text(" ", strip=True).split())
    days = find_days(text, today)
    times = [time(int(h), int(m)) for h, m in TIME_RE.findall(text)]
    if not days:
        return None

    start: datetime | date
    end: datetime | date
    if times:
        if len(days) != 1 or len(times) != 2:
            return None
        start = datetime.combine(days[0], times[0], tzinfo=PORTAL_TZ)
        end = datetime.combine(days[0], times[1], tzinfo=PORTAL_TZ)
    else:
        start, end = days[0], days[-1]

    description = " ".join(
        text for p in row.select("li.c2 > p") if (text := p.get_text(" ", strip=True))
    )
    creator = row.select_one("li.c3 div.smaller p b")
    return SchoolEvent(
        id=event_id,
        title=title.get_text(" ", strip=True),
        start=start,
        end=end,
        description=description or None,
        created_by=creator.get_text(strip=True) if creator else None,
    )

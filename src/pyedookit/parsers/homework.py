from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import PORTAL_TZ, Homework
from .dates import portal_today, resolve_day
from .rows import at, row_course, row_course_id, row_created, row_id, row_text
from .text import tag_text as _text

_PROGRESS_RE = re.compile(r"(\d+)\s*%")
_END_OF_DAY = time(23, 59)
_NO_DUE = datetime.max.replace(tzinfo=PORTAL_TZ)

_LOGGER = logging.getLogger(__name__)


def parse_homework(html: str, today: date | None = None) -> list[Homework]:
    """Homework from Úkoly (`/assignments/`): the sections for today, upcoming
    and recent, merged, soonest deadline first, undated last."""
    soup = BeautifulSoup(html, "lxml")
    # Not the filter list: the portal leaves it out when nothing is due today or upcoming.
    if soup.select_one("h2.heading") is None:
        raise ParseError("assignments page has no section headings")
    if today is None:
        today = portal_today()
    rows = soup.select("ul.table_row:not(.gridLabel)")
    items: dict[int, Homework] = {}
    for row in rows:
        item = _parse_row(row, today)
        if item is None:
            _LOGGER.warning("skipping homework row without an assignment id")
        else:
            items.setdefault(item.id, item)
    if rows and not items:
        raise ParseError("assignments page has homework rows but none has an assignment id")
    return sorted(items.values(), key=lambda h: (h.due or _NO_DUE, h.id))


def _parse_row(row: Tag, today: date) -> Homework | None:
    item_id = row_id(row)
    if item_id is None:
        return None
    classes = list(row.get("class") or [])
    created = row_created(row, today)
    progress = _progress(row)
    subject, course_code = row_course(row)
    return Homework(
        id=item_id,
        title=_text(row.select_one("li.c2 div.bold a")),
        text=row_text(row),
        done=progress >= 100 if progress is not None else "incomplete" not in classes,
        due=_due(row, created.date() if created else None, today),
        progress=progress,
        teacher=_text(row.select_one("li.c4 b")) or None,
        created=created,
        course_id=row_course_id(row),
        subject=subject,
        course_code=course_code,
    )


def _due(row: Tag, created: date | None, today: date) -> datetime | None:
    text = _text(row.select_one("li.c1 p > b"))
    day = resolve_day(text, today, not_before=created)
    if day is None:
        _LOGGER.debug("homework deadline not found in %r", text)
        return None
    return at(day, text, _END_OF_DAY)


def _progress(row: Tag) -> int | None:
    match = _PROGRESS_RE.search(_text(row.select_one("li.c3")))
    return int(match.group(1)) if match else None

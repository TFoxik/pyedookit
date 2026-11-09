from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, NavigableString

from ..exceptions import ParseError
from ..models import PORTAL_TZ, Homework
from .dates import TIME_RE, find_days, portal_today
from .text import tag_text as _text

_ASSIGNMENT_ID_RE = re.compile(r"assignment=(\d+)")
_COURSE_CLASS_RE = re.compile(r"course(\d+)")
_PROGRESS_RE = re.compile(r"(\d+)\s*%")
_YEARLESS_DATE_RE = re.compile(r"\d{1,2}\.\s*\d{1,2}\.(?!\s*\d{4})")
_LINE_BREAK = "\ue000"
_END_OF_DAY = time(23, 59)
_NO_DUE = datetime.max.replace(tzinfo=PORTAL_TZ)

_LOGGER = logging.getLogger(__name__)


def parse_homework(html: str, today: date | None = None) -> list[Homework]:
    """Homework from Úkoly (`/assignments/`): the sections for today, upcoming
    and recent, merged, soonest deadline first, undated last."""
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one("#filterIncomplete") is None or soup.select_one("h2.heading") is None:
        raise ParseError("assignments page has neither the filter nor the section headings")
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
    id_match = _ASSIGNMENT_ID_RE.search(str(row.get("onclick", "")))
    if id_match is None:
        link = row.select_one('li.c2 div.bold a[href*="assignment="]')
        id_match = _ASSIGNMENT_ID_RE.search(str(link.get("href", ""))) if link else None
    if id_match is None:
        return None
    classes = list(row.get("class") or [])
    created = _created(row, today)
    progress = _progress(row)
    course_match = next((m for c in classes if (m := _COURSE_CLASS_RE.fullmatch(c))), None)
    subject, course_code = _course(row)
    return Homework(
        id=int(id_match.group(1)),
        title=_text(row.select_one("li.c2 div.bold a")),
        text=_homework_text(row),
        done=progress >= 100 if progress is not None else "incomplete" not in classes,
        due=_due(row, created.date() if created else None, today),
        progress=progress,
        teacher=_text(row.select_one("li.c4 b")) or None,
        created=created,
        course_id=int(course_match.group(1)) if course_match else None,
        subject=subject,
        course_code=course_code,
    )


def _at(day: date, text: str, default: time) -> datetime:
    match = TIME_RE.search(text)
    try:
        at = time(int(match.group(1)), int(match.group(2))) if match else default
    except ValueError:
        at = default
    return datetime.combine(day, at, tzinfo=PORTAL_TZ)


def _created(row: Tag, today: date) -> datetime | None:
    cells = row.select("li.c4 p")
    text = _text(cells[-1]) if cells else ""
    days = find_days(text, today)
    if not days:
        _LOGGER.debug("homework created date not found in %r", text)
        return None
    return _at(days[0], text, time(0, 0))


def _due(row: Tag, created: date | None, today: date) -> datetime | None:
    text = _text(row.select_one("li.c1 p > b"))
    if _YEARLESS_DATE_RE.search(text):
        day = _yearless_date(text, created, today)
    else:
        day = next(iter(find_days(text, today)), None)
    if day is None:
        _LOGGER.debug("homework deadline not found in %r", text)
        return None
    return _at(day, text, _END_OF_DAY)


def _yearless_date(text: str, created: date | None, today: date) -> date | None:
    first = next(iter(find_days(text, created or today)), None)
    if first is None:
        return None
    if created is not None:
        return first if first >= created else _in_year(first, first.year + 1)
    years = (today.year - 1, today.year, today.year + 1)
    options = [day for year in years if (day := _in_year(first, year)) is not None]
    return min(options, key=lambda day: abs(day - today))


def _in_year(day: date, year: int) -> date | None:
    try:
        return day.replace(year=year)
    except ValueError:
        return None


def _progress(row: Tag) -> int | None:
    match = _PROGRESS_RE.search(_text(row.select_one("li.c3")))
    return int(match.group(1)) if match else None


def _course(row: Tag) -> tuple[str | None, str | None]:
    for paragraph in row.select("li.c1 p"):
        if paragraph.find("b") is not None:
            continue
        code = paragraph.select_one("span.link_info")
        code_text = _text(code) or None
        if code is not None:
            code.extract()
        return _text(paragraph) or None, code_text
    return None, None


def _homework_text(row: Tag) -> str:
    cell = row.select_one("li.c2")
    if cell is None:
        return ""
    title_link = cell.select_one("div.bold a")
    lines: list[str] = []
    for child in cell.children:
        if isinstance(child, Tag):
            if child.name == "h3" or _holds(child, title_link):
                continue
            for br in child.find_all("br"):
                br.replace_with(NavigableString(_LINE_BREAK))
            raw = child.get_text()
        elif isinstance(child, Comment):
            continue
        else:
            raw = str(child)
        text = "\n".join(part.strip() for part in " ".join(raw.split()).split(_LINE_BREAK))
        if text := text.strip("\n"):
            lines.append(text)
    return "\n".join(lines)


def _holds(tag: Tag, link: Tag | None) -> bool:
    return link is not None and (tag is link or any(d is link for d in tag.descendants))

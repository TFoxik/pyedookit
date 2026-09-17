from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import Lesson, Term

# Matches the day header text e.g. "Pondělí 15. 9. 2026" -> groups (day, month, year)
_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
_TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")

_TERM_ID_RE = re.compile(r"termSelector-new=(\d+)")


def parse_timetable(html: str, week_start: date | None = None) -> list[Lesson]:
    """Parse a rendered `/timetable/` (or AJAX week-fragment) page into lessons.

    Edookit's timetable is a table with one column per weekday and lessons as
    `.lesson-entry`/`.lessonRow` blocks; the day it belongs to comes from the
    surrounding day-column header, not from each entry, so this walks the
    table structure rather than each lesson block in isolation.
    """
    soup = BeautifulSoup(html, "lxml")
    lessons: list[Lesson] = []

    day_columns = soup.select("[data-day], .timetable-day, .day-column")
    if not day_columns:
        raise ParseError("no day columns found in timetable page")

    for column in day_columns:
        day_date = _extract_day_date(column, week_start)
        for entry in column.select(".lesson-entry, .lessonRow"):
            lesson = _parse_entry(entry, day_date)
            if lesson is not None:
                lessons.append(lesson)

    return lessons


def parse_terms(html: str) -> list[Term]:
    soup = BeautifulSoup(html, "lxml")
    terms: list[Term] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="termSelector-new"]'):
        href = str(link.get("href") or "")
        match = _TERM_ID_RE.search(href)
        if not match:
            continue
        term_id = match.group(1)
        if term_id in seen:
            continue
        seen.add(term_id)
        terms.append(Term(id=term_id, name=link.get_text(strip=True)))
    return terms


def _extract_day_date(column: Tag, week_start: date | None) -> date | None:
    header = column.select_one(".day-header, .date, h3, h4")
    text = header.get_text(" ", strip=True) if header else column.get_text(" ", strip=True)
    match = _DATE_RE.search(text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        return date(year, month, day)
    if week_start is not None:
        # Fall back to the day-column's position within the week when the
        # header omits the full date (some renderings only show a weekday name).
        index = column.get("data-day")
        if isinstance(index, str) and index.isdigit():
            return week_start + timedelta(days=int(index))
    return None


def _text(tag: Tag, selector: str) -> str | None:
    el = tag.select_one(selector)
    return el.get_text(strip=True) if el else None


def _parse_entry(entry: Tag, day_date: date | None) -> Lesson | None:
    text = entry.get_text(" ", strip=True)
    time_match = _TIME_RANGE_RE.search(text)
    if not time_match or day_date is None:
        return None
    sh, sm, eh, em = (int(g) for g in time_match.groups())

    subject = _text(entry, ".subject, .lesson-subject, .name") or text

    classes = [c.lower() for c in entry.get_attribute_list("class")]
    is_cancelled = any("cancel" in c or "zrus" in c for c in classes)
    is_changed = any("change" in c or "zmen" in c or "subst" in c for c in classes)

    return Lesson(
        start=datetime.combine(day_date, time(sh, sm)),
        end=datetime.combine(day_date, time(eh, em)),
        subject=subject,
        teacher=_text(entry, ".teacher, .lesson-teacher"),
        room=_text(entry, ".room, .lesson-room"),
        group=_text(entry, ".group, .lesson-group"),
        is_changed=is_changed,
        is_cancelled=is_cancelled,
    )

from __future__ import annotations

import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import Lesson, Term

_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
_TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
_TERM_ID_RE = re.compile(r"termSelector-new=(\d+)")
_NOTE_PREFIX = "Učivo:"


def parse_timetable(html: str) -> list[Lesson]:
    """Parse the hidden `.lesson-info` detail blocks on a rendered `/timetable/` page.

    Confirmed against a real portal capture: the *visible* week grid is an
    absolutely-positioned canvas of `<a class="... lesson ...">` tiles with
    no semantic day/time markup at all (position is encoded as inline CSS
    percentages). Each lesson also gets a hidden
    `<div class="lesson-info" id="lesson-info-{id}">` block, though, with a
    fixed field order and a full date+time already inside it - parsing those
    is far more reliable than reading positions off the canvas, and doesn't
    need a day-column or week_start argument at all since each block already
    carries its own date.

    Cancelled/substituted lessons could not be confirmed: the captured week
    had none, so `is_changed`/`is_cancelled` are always False for now. Fix
    once a real capture has one - see the parser test file for the exact gap.
    """
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select("div.lesson-info")
    if not blocks:
        raise ParseError("no lesson-info blocks found on timetable page")

    lessons = [_parse_lesson_info(block) for block in blocks]
    return [lesson for lesson in lessons if lesson is not None]


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


def _parse_lesson_info(block: Tag) -> Lesson | None:
    fields = block.find_all("div", recursive=False)
    datetime_div = next((f for f in fields if f.select_one(".date_time")), None)
    if datetime_div is None:
        return None

    text = datetime_div.get_text(" ", strip=True)
    date_match = _DATE_RE.search(text)
    time_match = _TIME_RANGE_RE.search(text)
    if not date_match or not time_match:
        return None
    day, month, year = (int(g) for g in date_match.groups())
    sh, sm, eh, em = (int(g) for g in time_match.groups())
    lesson_date = date(year, month, day)

    # Field order after the date/time div is fixed on every lesson observed:
    # "{code} - {group}", full subject name, teacher(s), room, curriculum
    # notes (last one is sometimes absent).
    rest = [f for f in fields if f is not datetime_div]
    code_group = rest[0].get_text(strip=True) if len(rest) > 0 else ""
    subject = rest[1].get_text(strip=True) if len(rest) > 1 else code_group
    teacher = rest[2].get_text(strip=True) if len(rest) > 2 else None
    room = rest[3].get_text(strip=True) if len(rest) > 3 else None

    note = None
    if len(rest) > 4:
        note_text = rest[4].get_text(" ", strip=True)
        if note_text.startswith(_NOTE_PREFIX):
            note = note_text[len(_NOTE_PREFIX) :].strip() or None

    _, _, group = code_group.partition(" - ")

    return Lesson(
        start=datetime.combine(lesson_date, time(sh, sm)),
        end=datetime.combine(lesson_date, time(eh, em)),
        subject=subject or code_group,
        teacher=teacher or None,
        room=room or None,
        group=group or None,
        note=note,
    )

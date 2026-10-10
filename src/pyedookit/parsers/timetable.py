from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import PORTAL_TZ, Lesson, Term
from .dates import find_days, portal_today

_TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
_TERM_ID_RE = re.compile(r"termSelector-new=(\d+)")
_NOTE_PREFIX = "Učivo:"

_LOGGER = logging.getLogger(__name__)


def parse_timetable(html: str, today: date | None = None) -> list[Lesson]:
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

    Yesterday's and today's lessons carry "Včera"/"Dnes" instead of a date;
    those resolve against `today`, which defaults to the current date in
    `PORTAL_TZ`.

    Cancelled/substituted lessons could not be confirmed: the captured week
    had none, so `is_changed`/`is_cancelled` are always False for now. Fix
    once a real capture has one - see the parser test file for the exact gap.
    """
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select("div.lesson-info")
    if not blocks:
        raise ParseError("no lesson-info blocks found on timetable page")

    if today is None:
        today = portal_today()
    lessons = []
    for block in blocks:
        lesson = _parse_lesson_info(block, today)
        if lesson is None:
            _LOGGER.warning("skipping unparseable lesson block %s", block.get("id"))
        else:
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


def _parse_lesson_info(block: Tag, today: date) -> Lesson | None:
    fields = block.find_all("div", recursive=False)
    datetime_div = next((f for f in fields if f.select_one(".date_time")), None)
    if datetime_div is None:
        return None

    text = datetime_div.get_text(" ", strip=True)
    days = find_days(text, today)
    lesson_date = days[0] if days else None
    time_match = _TIME_RANGE_RE.search(text)
    if lesson_date is None or not time_match:
        return None
    sh, sm, eh, em = (int(g) for g in time_match.groups())

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
        start=datetime.combine(lesson_date, time(sh, sm), tzinfo=PORTAL_TZ),
        end=datetime.combine(lesson_date, time(eh, em), tzinfo=PORTAL_TZ),
        subject=subject or code_group,
        teacher=teacher or None,
        room=room or None,
        group=group or None,
        note=note,
    )

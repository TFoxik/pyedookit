from __future__ import annotations

import logging
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import PORTAL_TZ, Exam
from .dates import TIME_RE, portal_today, resolve_day
from .rows import row_course, row_course_id, row_created, row_id, row_text
from .text import tag_text as _text

_LOGGER = logging.getLogger(__name__)


def parse_exams(html: str, today: date | None = None) -> list[Exam]:
    """Exams from Písemky, zkoušení (`/exams/`): the upcoming, today's and
    recent grids merged, soonest first. Older ones are only in the archive."""
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("section.content")
    if content is None or content.select_one("div.boxes1") is None:
        raise ParseError("exams page has no exam grids")
    if today is None:
        today = portal_today()
    rows = content.select("ul.table_row:not(.gridLabel)")
    exams: dict[int, Exam] = {}
    for row in rows:
        exam = _parse_row(row, today)
        if exam is not None:
            exams.setdefault(exam.id, exam)
    if rows and not exams:
        raise ParseError("exams page has rows but none could be read")
    return sorted(exams.values(), key=lambda e: (e.start, e.id))


def _parse_row(row: Tag, today: date) -> Exam | None:
    exam_id = row_id(row)
    if exam_id is None:
        _LOGGER.warning("skipping exam row without an assignment id")
        return None
    announced = row_created(row, today)
    when = _text(row.select_one("li.c1 p > b"))
    times = [time(int(h), int(m)) for h, m in TIME_RE.findall(when)[:2]]
    day = resolve_day(when, today, near=announced.date() if announced else None)
    if day is None or len(times) != 2:
        _LOGGER.warning("skipping exam %s without a readable date and time: %r", exam_id, when)
        return None

    paragraphs = row.select("li.c1 > p")
    kind = _text(paragraphs[2]) if len(paragraphs) > 2 else ""
    subject, course_code = row_course(row)
    return Exam(
        id=exam_id,
        title=_text(row.select_one("li.c2 div.bold a")),
        start=datetime.combine(day, times[0], tzinfo=PORTAL_TZ),
        end=datetime.combine(day, times[1], tzinfo=PORTAL_TZ),
        subject=subject,
        course_code=course_code,
        course_id=row_course_id(row),
        kind=kind or None,
        teacher=_text(row.select_one("li.c4 b")) or None,
        announced=announced,
        description=row_text(row) or None,
    )

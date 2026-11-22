"""Cells shared by the portal's `ul.table_row` grids (homework, exams): the
course in `li.c1`, the text in `li.c2`, who created a row and when in `li.c4`."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from bs4 import Tag
from bs4.element import Comment, NavigableString

from ..models import PORTAL_TZ
from .dates import TIME_RE, find_days
from .text import tag_text as _text

_LINE_BREAK = "\ue000"
_ASSIGNMENT_ID_RE = re.compile(r"assignment=(\d+)")
_COURSE_CLASS_RE = re.compile(r"course(\d+)")

_LOGGER = logging.getLogger(__name__)


def row_id(row: Tag) -> int | None:
    match = _ASSIGNMENT_ID_RE.search(str(row.get("onclick", "")))
    if match is None:
        link = row.select_one('li.c2 div.bold a[href*="assignment="]')
        match = _ASSIGNMENT_ID_RE.search(str(link.get("href", ""))) if link else None
    return int(match.group(1)) if match else None


def row_course_id(row: Tag) -> int | None:
    match = next((m for c in row.get("class") or [] if (m := _COURSE_CLASS_RE.fullmatch(c))), None)
    return int(match.group(1)) if match else None


def at(day: date, text: str, default: time) -> datetime:
    match = TIME_RE.search(text)
    try:
        at = time(int(match.group(1)), int(match.group(2))) if match else default
    except ValueError:
        at = default
    return datetime.combine(day, at, tzinfo=PORTAL_TZ)


def row_created(row: Tag, today: date) -> datetime | None:
    cells = row.select("li.c4 p")
    text = _text(cells[-1]) if cells else ""
    days = find_days(text, today)
    if not days:
        _LOGGER.debug("created date not found in %r", text)
        return None
    return at(days[0], text, time(0, 0))


def row_course(row: Tag) -> tuple[str | None, str | None]:
    for paragraph in row.select("li.c1 p"):
        if paragraph.find("b") is not None:
            continue
        code = paragraph.select_one("span.link_info")
        code_text = _text(code) or None
        if code is not None:
            code.extract()
        return _text(paragraph) or None, code_text
    return None, None


def row_text(row: Tag) -> str:
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

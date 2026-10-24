from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import Grade, Subject
from .dates import find_days, portal_today
from .text import tag_text as _text

_EVALUATION_ID_RE = re.compile(r"evaluationId=(\d+)")
_COURSE_ID_RE = re.compile(r"courseId=(\d+)")
_WEIGHT_RE = re.compile(r"Váha:\s*(\d+(?:[.,]\d+)?)")
_TERM_RE = re.compile(r"(\d)\.\s*(?:pololetí|čtvrtletí)\s+(\d{2})/(\d{2})")
_CODE_AND_NAME_RE = re.compile(r"^(?P<code>.+?)\s*\((?P<name>.+)\)$")
_ATTENDANCE_RE = re.compile(r"^(?P<term>.+?):\s*(?P<percent>[\d,.]+)\s*%$")
_COURSE_HREF = '[href^="/courses/detail?courseId="]'

_LOGGER = logging.getLogger(__name__)


def parse_grade_listing(html: str, today: date | None = None) -> tuple[str | None, list[Grade]]:
    """The current term's grades from Výpis hodnocení (`/evaluation/listing`).

    Each term is an `h3.termHeading` followed by its `#shownSelector<N>`
    grid. The current term is the latest by its heading, not by position:
    only one term has been seen, so the page order of several is unknown.
    """
    soup = BeautifulSoup(html, "lxml")
    headings = soup.select("h3.termHeading")
    if not headings:
        if soup.select_one("#filterAll") is None:
            raise ParseError("evaluation listing has neither terms nor the subject filter")
        return None, []

    # max() keeps the first of equal keys, so reversed() lets the later heading win a tie.
    heading = max(reversed(headings), key=lambda tag: _term_key(_text(tag)))
    grid = _term_grid(heading)
    rows = grid.select("ul.table_row[onclick]") if grid is not None else []
    if today is None:
        today = portal_today()
    grades: list[Grade] = []
    for row in rows:
        grade = _parse_row(row, today)
        if grade is None:
            _LOGGER.warning("skipping unparseable grade row")
        else:
            grades.append(grade)
    if rows and not grades:
        raise ParseError("no grade row in the evaluation listing could be read")
    grades.sort(key=lambda g: (g.entered, g.id), reverse=True)
    return _text(heading), grades


def parse_subjects(html: str, term: str | None) -> list[Subject]:
    """Subjects from Hodnocení po předmětech (`/evaluation/`), in page order,
    with the attendance of `term`. Its marks are not read: the listing has
    the same grades with ids."""
    soup = BeautifulSoup(html, "lxml")
    links = soup.select(f"a.main-highlight{_COURSE_HREF}")
    if not links:
        raise ParseError("evaluation page has no subjects")
    subjects: list[Subject] = []
    for link in links:
        subject = _parse_subject(link, term)
        if subject is None:
            _LOGGER.warning("skipping unparseable subject row")
        else:
            subjects.append(subject)
    return subjects


def _term_grid(heading: Tag) -> Tag | None:
    """The heading's own grid; a term without one (none seen yet) is empty
    rather than borrowing the next term's grid."""
    for element in heading.find_all_next(True):
        if element.name == "h3" and "termHeading" in (element.get("class") or []):
            return None
        if str(element.get("id", "")).startswith("shownSelector"):
            return element
    return None


def _mark(row: Tag) -> tuple[str, float | None]:
    tag = row.select_one("li.c2 span.evaluation > span")
    if tag is not None:
        weight = _WEIGHT_RE.search(str(tag.get("title", "")))
        return _text(tag), _number(weight.group(1)) if weight else None
    # Unknown mark markup (a verbal evaluation, say) is kept as its text.
    cell = row.select_one("li.c2")
    label = _text(cell.select_one("h3")) if cell else ""
    return _text(cell).removeprefix(label).strip(), None


def _term_key(heading: str) -> tuple[int, int]:
    match = _TERM_RE.search(heading)
    return (int(match.group(2)), int(match.group(1))) if match else (-1, -1)


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _parse_row(row: Tag, today: date) -> Grade | None:
    id_match = _EVALUATION_ID_RE.search(str(row.get("onclick", "")))
    mark, weight = _mark(row)
    created = row.select("li.c3 .smaller p")
    days = find_days(_text(created[-1]), today) if created else []
    if id_match is None or not mark or not days:
        return None
    parts = row.select("li.c1 div.bold strong p")
    course = row.select_one(f"li.c1 a{_COURSE_HREF}")
    course_match = _COURSE_ID_RE.search(str(course["href"])) if course else None
    return Grade(
        id=int(id_match.group(1)),
        mark=mark,
        weight=weight,
        category=_text(parts[0]) if parts else "",
        topic=_text(parts[1]) if len(parts) > 1 else "",
        teacher=_text(row.select_one("li.c3 .smaller b")),
        entered=days[0],
        course_id=int(course_match.group(1)) if course_match else None,
        subject=_text(course) or None,
        course_code=_text(row.select_one("li.c1 span.link_info")) or None,
    )


def _parse_subject(link: Tag, term: str | None) -> Subject | None:
    course_match = _COURSE_ID_RE.search(str(link.get("href", "")))
    cell = link.find_parent("li")
    if course_match is None or not isinstance(cell, Tag):
        return None
    label = _text(link)
    code_tag = link.find_next_sibling("span", class_="link_info")
    if isinstance(code_tag, Tag):
        name, code = label, _text(code_tag)
    elif match := _CODE_AND_NAME_RE.match(label):
        name, code = match.group("name"), match.group("code")
    else:
        name, code = label, ""
    attendance = None
    for small in cell.select("li small"):
        match = _ATTENDANCE_RE.match(_text(small))
        if match and match.group("term") == term:
            attendance = _number(match.group("percent"))
    return Subject(
        course_id=int(course_match.group(1)),
        name=name,
        code=code,
        teacher=_text(cell.select_one("p > small")),
        attendance_percent=attendance,
    )

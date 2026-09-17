from datetime import date, time
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.parsers.timetable import parse_timetable

FIXTURE = (Path(__file__).parent / "fixtures" / "timetable_synthetic.html").read_text()


def test_parses_lessons_grouped_by_day():
    lessons = parse_timetable(FIXTURE)
    assert len(lessons) == 3

    monday = [ls for ls in lessons if ls.start.date() == date(2026, 9, 14)]
    assert len(monday) == 2
    assert monday[0].subject == "Matematika"
    assert monday[0].start.time() == time(8, 0)
    assert monday[0].end.time() == time(8, 45)
    assert monday[0].teacher == "Nováková"
    assert monday[0].room == "12"
    assert not monday[0].is_cancelled
    assert not monday[0].is_changed


def test_detects_cancelled_lesson():
    lessons = parse_timetable(FIXTURE)
    cancelled = next(ls for ls in lessons if ls.subject == "Tělesná výchova")
    assert cancelled.is_cancelled
    assert not cancelled.is_changed


def test_detects_changed_lesson():
    lessons = parse_timetable(FIXTURE)
    changed = next(ls for ls in lessons if "suplování" in ls.subject)
    assert changed.is_changed
    assert not changed.is_cancelled


def test_second_day_uses_its_own_date():
    lessons = parse_timetable(FIXTURE)
    tuesday = next(ls for ls in lessons if ls.subject.startswith("Český"))
    assert tuesday.start.date() == date(2026, 9, 15)


def test_raises_parse_error_on_unrecognised_page():
    with pytest.raises(ParseError):
        parse_timetable("<html><body>Přihlašovací stránka</body></html>")

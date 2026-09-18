from datetime import date, datetime, time
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.parsers.timetable import parse_terms, parse_timetable

FIXTURE = (Path(__file__).parent / "fixtures" / "timetable_real_structure.html").read_text()


def test_parses_each_lesson_info_block_with_its_own_date():
    lessons = parse_timetable(FIXTURE)
    assert len(lessons) == 2

    monday = lessons[0]
    assert monday.start == datetime(2026, 9, 14, 8, 0)
    assert monday.end == datetime(2026, 9, 14, 8, 45)
    assert monday.subject == "Matematika"
    assert monday.teacher == "Novák J."
    assert monday.room == "1.A"
    assert monday.group == "I.A"
    assert monday.note == "Sčítání do dvaceti"


def test_handles_a_lesson_with_no_curriculum_note():
    lessons = parse_timetable(FIXTURE)
    tuesday = lessons[1]
    assert tuesday.start.date() == date(2026, 9, 15)
    assert tuesday.start.time() == time(9, 0)
    assert tuesday.subject == "Tělesná výchova"
    assert tuesday.room == "TV 1"
    assert tuesday.note is None


def test_raises_parse_error_when_no_lesson_info_blocks_found():
    with pytest.raises(ParseError):
        parse_timetable("<html><body>no lessons here</body></html>")


def test_parse_terms_reads_term_selector_links():
    terms = parse_terms(FIXTURE)
    assert {t.id: t.name for t in terms} == {"61": "2026/2027", "58": "2025/2026"}

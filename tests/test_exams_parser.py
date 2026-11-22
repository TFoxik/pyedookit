"""`parse_exams` against `exams_structure.html`.

A row's c1 cell has two labels: the exam type as its third paragraph
("Malá písemka", "Diktát") and a broader category as loose text after it
("Písemná práce"). `kind` is the exam type; the category isn't kept.
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.models import PORTAL_TZ as P
from pyedookit.models import Exam
from pyedookit.parsers.exams import parse_exams

PAGE = (Path(__file__).parent / "fixtures" / "exams_structure.html").read_text()
TODAY = date(2026, 11, 22)
_EMPTY_GRID = '<div class="boxes1"><p><em>Žádné písemky, zkoušení</em></p><br><br></div>'
_GRID = re.compile(r'<div class="boxes1">.*?<div class="cleaner"></div></div>', re.DOTALL)


def _by_id(exams: list[Exam], exam_id: int) -> Exam:
    return next(e for e in exams if e.id == exam_id)


def test_parses_upcoming_exam_fields():
    exam = _by_id(parse_exams(PAGE, TODAY), 9104)
    assert exam == Exam(
        id=9104,
        title="Zlomky",
        start=datetime(2026, 11, 25, 8, 0, tzinfo=P),
        end=datetime(2026, 11, 25, 8, 45, tzinfo=P),
        subject="Matematika",
        course_code="M T - 1.A",
        course_id=9204,
        kind="Malá písemka",
        teacher="Jana Nováková",
        announced=datetime(2026, 11, 17, 10, 32, tzinfo=P),
        description="Sčítání a odčítání zlomků",
    )
    assert (exam.short, exam.code, exam.group) == ("M", "M T", "1.A")


def test_exam_without_description_has_none():
    assert _by_id(parse_exams(PAGE, TODAY), 9102).description is None


def test_exams_are_sorted_soonest_first_and_each_id_once():
    assert [e.id for e in parse_exams(PAGE, TODAY)] == [9101, 9102, 9103, 9104]


def test_yearless_exam_date_rolls_into_next_year():
    row = PAGE.replace("25.&thinsp;11., od", "8.&thinsp;1., od").replace(
        "Po 17.&thinsp;11.&thinsp;2026", "Pá 18.&thinsp;12.&thinsp;2026"
    )
    exam = _by_id(parse_exams(row, date(2026, 12, 20)), 9104)
    assert exam.start == datetime(2027, 1, 8, 8, 0, tzinfo=P)


def test_row_without_readable_date_is_skipped(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        exams = parse_exams(PAGE, TODAY)
    assert 9105 not in [e.id for e in exams]
    assert "9105" in caplog.text


def test_empty_grids_return_empty_list():
    assert parse_exams(_GRID.sub(_EMPTY_GRID, PAGE), TODAY) == []


def test_page_without_exam_grids_raises_parse_error():
    with pytest.raises(ParseError):
        parse_exams("<html><body></body></html>", TODAY)


def test_rows_present_but_none_readable_raises_parse_error():
    unreadable = re.sub(r'<span class="date_time">[^<]*</span>', "", PAGE)
    with pytest.raises(ParseError):
        parse_exams(unreadable, TODAY)


def test_exam_entered_after_it_took_place_keeps_its_year():
    late = PAGE.replace(
        "Pá 14.&thinsp;11.&thinsp;2026, <span", "Po 24.&thinsp;11.&thinsp;2026, <span"
    )
    exam = _by_id(parse_exams(late, date(2026, 11, 24)), 9103)
    assert exam.start == datetime(2026, 11, 22, 10, 0, tzinfo=P)

import dataclasses
from datetime import date

import pytest

from pyedookit import Grade, Grades, Subject


def _grade(grade_id: int, mark: str = "1", weight: float | None = 1.0) -> Grade:
    return Grade(
        id=grade_id,
        mark=mark,
        weight=weight,
        category="Obecné hodnocení",
        topic="Test",
        teacher="Učitelka A",
        entered=date(2026, 10, 21),
        course_id=501,
        subject="Anglický jazyk",
        course_code="Aj 2 - I.B",
    )


def test_value_is_numeric_only_for_marks_1_to_5():
    assert [_grade(1, mark=m).value for m in ("1", "5", "A", "1-", "6")] == [1, 5, None, None, None]


def test_weighted_average():
    grades = Grades("1. pololetí 26/27", [_grade(1, "1", 1.0), _grade(2, "3", 2.0)], [])
    assert grades.average(501) == pytest.approx(7 / 3)


def test_missing_weight_counts_as_one():
    grades = Grades("t", [_grade(1, "1", None), _grade(2, "2", None)], [])
    assert grades.average(501) == 1.5


def test_average_skips_non_numeric_marks():
    grades = Grades("t", [_grade(1, "A", 5.0), _grade(2, "2", 1.0)], [])
    assert grades.average(501) == 2.0


def test_average_of_subject_without_numeric_marks_is_none():
    assert Grades("t", [_grade(1, "A", 1.0)], []).average(501) is None
    assert Grades("t", [], []).average(501) is None


def test_for_subject_keeps_newest_first_and_filters_by_course():
    other = dataclasses.replace(_grade(3, "1", 1.0), course_id=502)
    grades = Grades("t", [_grade(2, "1", 1.0), other, _grade(1, "2", 1.0)], [])
    assert [g.id for g in grades.for_subject(501)] == [2, 1]


def test_short_is_the_first_word_of_the_course_code():
    assert _grade(1).short == "Aj"
    assert Subject(503, "Matematika", "M - I.B", "Učitelka A", None).short == "M"


def test_short_falls_back_to_the_name():
    no_code = dataclasses.replace(_grade(1), course_code=None)
    assert no_code.short == "Anglický jazyk"
    assert dataclasses.replace(no_code, subject=None).short is None
    assert Subject(503, "Matematika", "", "Učitelka A", None).short == "Matematika"

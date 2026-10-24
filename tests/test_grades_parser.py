import re
from datetime import date
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.parsers.grades import parse_grade_listing, parse_subjects

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "evaluation_listing_structure.html").read_text()
SUBJECTS = (FIXTURES / "evaluation_subjects_structure.html").read_text()
TERM = "1. pololetí 26/27"

SECOND_SECTION = """
            <h3 class="termHeading">2. pololetí 26/27</h3>
            <p id="noSuchSelector2" style="display:none"><em>Žádná hodnocení</em></p>
            <div id="shownSelector2" class="evaluation_table spacy-grid cssHack-no-bg">
                <div class="cssHack-box">
                <ul class="anyCourse course501 table_row"
                    onclick="window.location.href = '/evaluation/detail?evaluationId=9200'">
                    <li class="c1">
                        <p><a href="/courses/detail?courseId=501">Anglický jazyk</a>
                        <span class="link_info">Aj 2 - I.B</span></p>
                        <div class="bold"><a href="/evaluation/detail?evaluationId=9200"><strong>
                            <p>Obecné hodnocení</p><p>Unit 5</p></strong></a></div>
                    </li>
                    <li class="c2"><p><span class="evaluation">
                        <span title="Váha: 1">2</span></span></p></li>
                    <li class="c3"><div class="smaller"><p><b>Učitelka A</b></p>
                        <p>Út 9.&thinsp;2.&thinsp;2027</p></div></li>
                </ul>
                </div>
            </div>
"""


def _with_second_section_first(html: str) -> str:
    heading = '<h3 class="termHeading">'
    return html.replace(heading, SECOND_SECTION + heading, 1)


def _without_rows(html: str) -> str:
    row = r'<div class="cssHack-box">\s*<ul class="anyCourse.*?</ul>\s*</div>'
    return re.sub(row, "", html, flags=re.S)


def test_listing_term_and_order():
    term, grades = parse_grade_listing(LISTING)
    assert term == TERM
    assert [g.id for g in grades] == [9102, 9101, 9100, 9099]


def test_listing_grade_fields():
    g = parse_grade_listing(LISTING)[1][0]
    assert (g.course_id, g.subject, g.course_code) == (501, "Anglický jazyk", "Aj 2 - I.B")
    assert (g.category, g.topic, g.mark, g.weight) == ("Obecné hodnocení", "Test Unit 1", "1", 1.0)
    assert (g.teacher, g.entered) == ("Učitelka A", date(2026, 10, 21))


def test_decimal_comma_weight():
    g = parse_grade_listing(LISTING)[1][1]
    assert (g.id, g.weight) == (9101, 0.5)


def test_grade_without_weight_or_course():
    g = parse_grade_listing(LISTING)[1][3]
    assert (g.id, g.mark, g.weight, g.value, g.course_id, g.subject) == (
        9099,
        "A",
        None,
        None,
        None,
        None,
    )
    assert (g.category, g.topic) == ("Ostatní", "Výlet")


def test_second_half_year_wins_wherever_it_is():
    term, grades = parse_grade_listing(_with_second_section_first(LISTING))
    assert term == "2. pololetí 26/27"
    assert [g.id for g in grades] == [9200]
    assert grades[0].entered == date(2027, 2, 9)


def test_listing_without_grades_is_empty():
    assert parse_grade_listing(_without_rows(LISTING)) == (TERM, [])


def test_subjects_both_name_forms_and_attendance():
    subjects = parse_subjects(SUBJECTS, TERM)
    assert [(s.course_id, s.name, s.code) for s in subjects] == [
        (501, "Anglický jazyk", "Aj 2 - I.B"),
        (502, "Hudební výchova", "Hv - I.B"),
        (503, "Matematika", "M - I.B"),
    ]
    assert [s.attendance_percent for s in subjects] == [100.0, 90.0, 91.5]
    assert subjects[0].teacher == "Učitelka A, Mgr."


def test_attendance_of_another_term_is_none():
    assert parse_subjects(SUBJECTS, "2. pololetí 26/27")[0].attendance_percent is None


@pytest.mark.parametrize("parse", [parse_grade_listing, lambda html: parse_subjects(html, None)])
def test_page_without_anchor_is_a_parse_error(parse):
    with pytest.raises(ParseError):
        parse("<html><body><a href='/user/logout'>x</a></body></html>")


def test_unknown_mark_markup_is_kept_as_text():
    html = LISTING.replace(
        '<span class="evaluation"><span title="Váha: 1">1</span></span>',
        '<em class="slovni">Výborně</em>',
        1,
    )

    g = parse_grade_listing(html)[1][0]
    assert (g.id, g.mark, g.value, g.weight) == (9102, "Výborně", None, None)


def test_rows_that_all_fail_to_parse_are_a_parse_error():
    html = re.sub(r'<div class="smaller">.*?</div>', "", LISTING, flags=re.S)

    with pytest.raises(ParseError):
        parse_grade_listing(html)


def test_term_heading_without_its_own_grid_is_empty():
    heading = '<h3 class="termHeading">'
    empty_second = (
        '<h3 class="termHeading">2. pololetí 26/27</h3>'
        '<p id="noSuchSelector2" style="display:none"><em>Žádná hodnocení</em></p>'
    )

    assert parse_grade_listing(LISTING.replace(heading, empty_second + heading, 1)) == (
        "2. pololetí 26/27",
        [],
    )


def test_malformed_weight_is_no_weight():
    html = LISTING.replace('title="Váha: 1">1<', 'title="Váha: .">1<', 1)

    assert parse_grade_listing(html)[1][0].weight is None

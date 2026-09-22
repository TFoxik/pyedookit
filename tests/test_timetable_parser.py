from datetime import date, datetime, time
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.models import PORTAL_TZ
from pyedookit.parsers.timetable import parse_terms, parse_timetable

FIXTURE = (Path(__file__).parent / "fixtures" / "timetable_real_structure.html").read_text()


def test_parses_each_lesson_info_block_with_its_own_date():
    lessons = parse_timetable(FIXTURE)
    assert len(lessons) == 2

    monday = lessons[0]
    assert monday.start == datetime(2026, 9, 14, 8, 0, tzinfo=PORTAL_TZ)
    assert monday.end == datetime(2026, 9, 14, 8, 45, tzinfo=PORTAL_TZ)
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


def _block(lesson_id: int, when: str, subject: str) -> str:
    # Same shape as the fixture; the portal writes "Včera"/"Dnes" instead of
    # a date for yesterday's and today's lessons (confirmed 2026-09-22).
    return f"""
<div class="lesson-info" style="display:none" id="lesson-info-{lesson_id}">
    <h3 class="attendance-heading">Informace o hodině</h3>
    <div>
        {when}, <span class="date_time">8:00</span>&ndash;<span class="date_time">8:45</span>
    </div>
    <div>Čj - I.A</div>
    <div>{subject}</div>
    <div>Novák J.</div>
    <div>1.A</div>
</div>"""


def test_resolves_relative_day_names_against_today():
    html = "".join(
        [
            _block(1, "Včera ", "Včerejší"),
            _block(2, "Dnes ", "Dnešní"),
            _block(3, "Zítra ", "Zítřejší"),
            _block(4, "Čt 24.&thinsp;9.&thinsp;2026", "Čtvrteční"),
        ]
    )

    lessons = parse_timetable(html, today=date(2026, 9, 22))

    assert [(ls.subject, ls.start) for ls in lessons] == [
        ("Včerejší", datetime(2026, 9, 21, 8, 0, tzinfo=PORTAL_TZ)),
        ("Dnešní", datetime(2026, 9, 22, 8, 0, tzinfo=PORTAL_TZ)),
        ("Zítřejší", datetime(2026, 9, 23, 8, 0, tzinfo=PORTAL_TZ)),
        ("Čtvrteční", datetime(2026, 9, 24, 8, 0, tzinfo=PORTAL_TZ)),
    ]


def test_warns_about_a_lesson_whose_date_cannot_be_read(caplog):
    html = _block(1, "Předevčírem ", "Záhadná") + _block(2, "Dnes ", "Dnešní")

    lessons = parse_timetable(html, today=date(2026, 9, 22))

    assert [ls.subject for ls in lessons] == ["Dnešní"]
    assert "lesson-info-1" in caplog.text

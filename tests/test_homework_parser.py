import re
from datetime import date, datetime
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.models import PORTAL_TZ as P
from pyedookit.models import Homework
from pyedookit.parsers.homework import parse_homework

PAGE = (Path(__file__).parent / "fixtures" / "assignments_structure.html").read_text()
TODAY = date(2026, 11, 6)
_NO_ITEMS = "<p><em>Žádné úkoly</em></p>"
_ROW_BOX = re.compile(r'<div class="cssHack-box">.*?</ul>\s*</div>', re.DOTALL)


def _by_id(items: list[Homework], item_id: int) -> Homework:
    return next(h for h in items if h.id == item_id)


def _with_144001_also_in_today(page: str) -> str:
    box = next(m.group(0) for m in _ROW_BOX.finditer(page) if "assignment=144001" in m.group(0))
    return page.replace(_NO_ITEMS, box, 1)


def _without_rows(page: str) -> str:
    page = _ROW_BOX.sub("", page)
    return page.replace('<div class="boxes1">', f'<div class="boxes1">{_NO_ITEMS}')


def test_items_from_every_section_ordered_by_deadline():
    assert [h.id for h in parse_homework(PAGE, TODAY)] == [144002, 144001, 144004, 144003]


def test_item_fields():
    h = _by_id(parse_homework(PAGE, TODAY), 144001)
    assert (h.course_id, h.subject, h.course_code, h.short) == (
        9101,
        "Anglický jazyk",
        "Aj 2 - I.B",
        "Aj",
    )
    assert h.title == "Aj 2 - I.B (Anglický jazyk) - Domácí úkol"
    assert h.text == "Uč. str. 20 - přečíst."
    assert h.due == datetime(2026, 11, 10, 9, 30, tzinfo=P)
    assert (h.progress, h.done, h.teacher) == (0, False, "Učitelka A")
    assert h.created == datetime(2026, 11, 3, 15, 41, tzinfo=P)


def test_line_breaks_in_text():
    assert _by_id(parse_homework(PAGE, TODAY), 144002).text == "Pracovní list\nstr. 5"


def test_link_in_the_text_is_kept_as_text():
    page = PAGE.replace("Slovíčka lekce 3", 'Viz <a href="/x">odkaz</a> a poznámky')
    assert _by_id(parse_homework(page, TODAY), 144003).text == "Viz odkaz a poznámky"


def test_full_progress_is_done_and_deadline_without_time_is_end_of_day():
    h = _by_id(parse_homework(PAGE, TODAY), 144003)
    assert (h.progress, h.done) == (100, True)
    assert h.due == datetime(2026, 11, 13, 23, 59, tzinfo=P)


def test_item_without_course_and_relative_created_date():
    h = _by_id(parse_homework(PAGE, TODAY), 144004)
    assert (h.course_id, h.subject, h.course_code, h.short) == (None, None, None, None)
    assert h.created == datetime(2026, 11, 5, 10, 0, tzinfo=P)


def _without_created(page: str) -> str:
    return page.replace("Út 3.&thinsp;11.&thinsp;2026, ", "").replace(
        '<span class="date_time">15:41</span>', "neznámo"
    )


@pytest.mark.parametrize(
    ("with_created", "deadline", "today", "expected"),
    [
        (True, "5.&thinsp;1.", date(2026, 12, 15), datetime(2027, 1, 5, 9, 30, tzinfo=P)),
        (False, "5.&thinsp;11.", date(2026, 11, 9), datetime(2026, 11, 5, 9, 30, tzinfo=P)),
        (False, "5.&thinsp;1.", date(2026, 12, 15), datetime(2027, 1, 5, 9, 30, tzinfo=P)),
    ],
    ids=["year_rolls_after_new_year", "overdue_stays_in_year", "nearest_year_to_today"],
)
def test_yearless_deadline_resolves_to_the_year_nearest_to_today(
    with_created, deadline, today, expected
):
    page = PAGE if with_created else _without_created(PAGE)
    if with_created:
        page = page.replace("Út 3.&thinsp;11.&thinsp;2026", "Po 14.&thinsp;12.&thinsp;2026")
    page = page.replace("do 10.&thinsp;11.", f"do {deadline}")
    h = _by_id(parse_homework(page, today), 144001)
    assert h.created is None or with_created
    assert h.due == expected


def test_unparseable_deadline_keeps_the_item():
    page = PAGE.replace("do 10.&thinsp;11., <span>9:30</span>", "do pondělí")
    h = _by_id(parse_homework(page, TODAY), 144001)
    assert h.due is None and h.text == "Uč. str. 20 - přečíst."


@pytest.mark.parametrize(
    ("page_edit", "item_id", "done"),
    [
        (("0&nbsp;%", "?", 1), 144001, False),
        (("100&nbsp;%", "?", -1), 144003, True),
    ],
    ids=["incomplete_row", "complete_row"],
)
def test_unreadable_progress_falls_back_to_the_row_class(page_edit, item_id, done):
    old, new, count = page_edit
    page = PAGE.replace(old, new, count)
    h = _by_id(parse_homework(page, TODAY), item_id)
    assert (h.progress, h.done) == (None, done)


def test_row_without_assignment_id_is_skipped(caplog):
    page = PAGE.replace("assignment=144004", "x=1")
    assert 144004 not in [h.id for h in parse_homework(page, TODAY)]
    assert "skipping homework row without an assignment id" in caplog.text


def test_id_is_taken_from_the_title_link_when_onclick_lacks_it():
    page = PAGE.replace("detail?assignment=144004'\"", "detail'\"")
    assert "assignment=144004" in page
    assert _by_id(parse_homework(page, TODAY), 144004).title == "Domácí úkol"


def test_page_whose_rows_are_all_unreadable_is_a_parse_error():
    page = PAGE.replace("assignment=", "x=")
    with pytest.raises(ParseError):
        parse_homework(page, TODAY)


def test_duplicate_item_in_two_sections_is_listed_once():
    items = parse_homework(_with_144001_also_in_today(PAGE), TODAY)
    assert [h.id for h in items].count(144001) == 1


def test_empty_page_is_an_empty_list():
    assert parse_homework(_without_rows(PAGE), TODAY) == []


def test_page_without_anchors_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_homework("<html><body><a href='/user/logout'>x</a></body></html>", TODAY)


def test_relative_deadline_words_resolve_against_today_not_the_created_date():
    today_page = PAGE.replace("do 10.&thinsp;11., <span>9:30</span>", "do Dnes, <span>10:00</span>")
    tomorrow_page = PAGE.replace("do 10.&thinsp;11., <span>9:30</span>", "do Zítra")
    assert _by_id(parse_homework(today_page, TODAY), 144001).due == datetime(
        2026, 11, 6, 10, 0, tzinfo=P
    )
    assert _by_id(parse_homework(tomorrow_page, TODAY), 144001).due == datetime(
        2026, 11, 7, 23, 59, tzinfo=P
    )


def test_item_without_deadline_is_listed_last():
    page = PAGE.replace("do 2.&thinsp;11., <span>8:00</span>", "do pondělí")
    items = parse_homework(page, TODAY)
    assert [h.id for h in items] == [144001, 144004, 144003, 144002]
    assert items[-1].due is None


def test_text_in_a_block_nested_in_a_paragraph_is_kept():
    page = PAGE.replace("<p>Uč. str. 20 - přečíst.</p>", "<p>Úvod<div>Druhá část</div></p>")
    assert _by_id(parse_homework(page, TODAY), 144001).text == "Úvod\nDruhá část"


@pytest.mark.parametrize(
    ("course_code", "code", "group"),
    [("Aj 2 - I.B", "Aj 2", "I.B"), (None, None, None), ("Čj", "Čj", None)],
)
def test_code_and_group_come_from_the_course_code(course_code, code, group):
    h = Homework(id=1, title="t", text="", done=False, course_code=course_code)
    assert (h.code, h.group) == (code, group)

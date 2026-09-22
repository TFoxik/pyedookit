from datetime import date, datetime
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.models import PORTAL_TZ
from pyedookit.parsers.events import parse_events

FIXTURE = (Path(__file__).parent / "fixtures" / "upcoming_events_structure.html").read_text()
TODAY = date(2026, 9, 22)


def _row(event_id: int, when: str, title: str = "Akce") -> str:
    return f"""
<ul class="table_row">
  <li class="c1"><p><b>{when}</b></p></li>
  <li class="c2"><div class="bold">
    <a href="/timetable/detail?event={event_id}"><span>{title}</span></a>
  </div></li>
</ul>"""


def _page(rows: str) -> str:
    return f'<section class="content"><div class="events_table">{rows}</div></section>'


def test_skips_the_header_row_and_keeps_page_order():
    events = parse_events(FIXTURE, today=TODAY)
    assert [e.id for e in events] == ["5001", "5002", "5003", "5004", "5005"]


def test_timed_event():
    event = parse_events(FIXTURE, today=TODAY)[0]
    assert event.title == "ŠD Pasování na čtenáře"
    assert event.start == datetime(2026, 9, 23, 13, 30, tzinfo=PORTAL_TZ)
    assert event.end == datetime(2026, 9, 23, 15, 30, tzinfo=PORTAL_TZ)
    assert not event.all_day
    assert event.description is None
    assert event.created_by == "Učitelka B"


def test_description_is_read():
    event = parse_events(FIXTURE, today=TODAY)[1]
    assert event.description == 'Představení "Kocour v botách" v KD'


def test_all_day_single_day_uses_todays_year():
    event = parse_events(FIXTURE, today=TODAY)[2]
    assert event.all_day
    assert (event.start, event.end) == (date(2026, 9, 28), date(2026, 9, 28))


def test_multi_day_range_crossing_the_year():
    event = parse_events(FIXTURE, today=TODAY)[3]
    assert (event.start, event.end) == (date(2026, 12, 23), date(2027, 1, 3))


def test_explicit_year():
    event = parse_events(FIXTURE, today=TODAY)[4]
    assert (event.start, event.end) == (date(2027, 1, 29), date(2027, 1, 29))


def test_skips_and_warns_about_unexpected_date_shapes(caplog):
    html = _page(
        _row(1, "23. 9., od 13:30")
        + _row(2, "od 23. 9. 13:30 do 24. 9. 10:00")
        + _row(3, "brzy")
        + _row(4, "28. 9.", "Platná akce")
    )

    events = parse_events(html, today=TODAY)

    assert [e.title for e in events] == ["Platná akce"]
    for event_id in ("1", "2", "3"):
        assert f"event row {event_id}" in caplog.text


def test_page_without_events_table_has_no_events():
    html = '<section class="content"><p>Žádné události</p></section>'
    assert parse_events(html, today=TODAY) == []


def test_non_portal_page_raises():
    with pytest.raises(ParseError):
        parse_events("<html><body>login</body></html>", today=TODAY)

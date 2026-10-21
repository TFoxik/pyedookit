import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.models import PORTAL_TZ
from pyedookit.parsers.inbox import parse_inbox

FIXTURE = (Path(__file__).parent / "fixtures" / "inbox_structure.html").read_text()
TODAY = date(2026, 10, 21)


def test_lists_only_real_messages_in_page_order():
    assert [m.id for m in parse_inbox(FIXTURE, today=TODAY)] == [9003, 9002, 9001]


def test_unread_message_fields():
    message = parse_inbox(FIXTURE, today=TODAY)[0]
    assert (message.subject, message.sender, message.unread) == (
        "Třídní schůzky",
        "Učitelka A",
        True,
    )
    assert message.preview == "Vážení rodiče, zveme vás…"
    assert message.sent == datetime(2026, 10, 21, 8, 12, tzinfo=PORTAL_TZ)


def test_yesterday_form_uses_the_title_date():
    message = parse_inbox(FIXTURE, today=TODAY)[1]
    assert message.sent == datetime(2026, 10, 20, 17, 5, tzinfo=PORTAL_TZ)


def test_time_only_means_today():
    message = parse_inbox(FIXTURE, today=TODAY)[2]
    assert message.sent == datetime(2026, 10, 21, 7, 30, tzinfo=PORTAL_TZ)


def test_read_messages_are_not_unread():
    assert [m.unread for m in parse_inbox(FIXTURE, today=TODAY)] == [True, False, False]


def test_page_without_inbox_grid_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_inbox("<html><body><p>x</p></body></html>", today=TODAY)


def test_empty_inbox_is_an_empty_list():
    assert parse_inbox('<div id="inbox-grid"></div>', today=TODAY) == []


def test_message_without_a_time_is_skipped_with_a_warning(caplog):
    html = FIXTURE.replace('21. 10. 2026, <span class="date_time">8:12</span>', "")

    with caplog.at_level(logging.WARNING):
        messages = parse_inbox(html, today=TODAY)

    assert [m.id for m in messages] == [9002, 9001]
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "9003" in caplog.records[0].getMessage()

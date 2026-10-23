from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import PORTAL_TZ, MessageSummary
from .dates import TIME_RE, find_days, portal_today

_MESSAGE_LINK_RE = re.compile(r"^/messages/detail\?message=(\d+)$")
# `initial` items are the first-run guide's samples ("Vzorová zpráva"), which
# stay in the page hidden; `archive-notification` items are hidden
# undo-archive templates.
_SKIPPED_CLASSES = {"initial", "archive-notification"}

_LOGGER = logging.getLogger(__name__)


def parse_inbox(html: str, today: date | None = None) -> list[MessageSummary]:
    """Parse the messages in Schránka (`/overview/updates`), in page order.

    Confirmed against a real capture: the feed mixes messages, events,
    evaluations and guidance items in `#inbox-grid`; only `div.item.message`
    is read; an unread one carries the `unread` class (confirmed on a real
    message, 2026-10-23).
    """
    soup = BeautifulSoup(html, "lxml")
    grid = soup.select_one("#inbox-grid")
    if grid is None:
        raise ParseError("inbox page has no inbox grid")
    if today is None:
        today = portal_today()

    messages: list[MessageSummary] = []
    for item in grid.select("div.item.message"):
        classes = set(item.get("class") or [])
        if classes & _SKIPPED_CLASSES:
            continue
        message_id = _message_id(item)
        if message_id is None:
            continue
        message = _parse_item(item, message_id, "unread" in classes, today)
        if message is None:
            _LOGGER.warning("skipping unparseable inbox message %s", message_id)
        else:
            messages.append(message)
    return messages


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _message_id(item: Tag) -> int | None:
    link = item.select_one(".object-name a[href]")
    match = _MESSAGE_LINK_RE.match(str(link["href"])) if link else None
    return int(match.group(1)) if match else None


def _sent(when: Tag | None, today: date) -> datetime | None:
    text = _text(when)
    times = TIME_RE.findall(text)
    if when is None or not times:
        return None
    days = find_days(text, today)
    yesterday = when.select_one(".date-yesterday[title]")
    if not days and yesterday is not None:
        days = find_days(str(yesterday["title"]), today)
    hour, minute = times[-1]
    return datetime.combine(days[0] if days else today, time(int(hour), int(minute)), PORTAL_TZ)


def _parse_item(item: Tag, message_id: int, unread: bool, today: date) -> MessageSummary | None:
    sent = _sent(item.select_one(".time"), today)
    if sent is None:
        return None
    return MessageSummary(
        id=message_id,
        subject=_text(item.select_one(".object-name a")),
        sender=_text(item.select_one(".creator")),
        sent=sent,
        preview=_text(item.select_one(".description")),
        unread=unread,
    )

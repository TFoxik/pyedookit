from __future__ import annotations

import re
from datetime import datetime, time

from bs4 import BeautifulSoup, Comment, Tag
from bs4.element import NavigableString

from ..exceptions import ParseError
from ..models import PORTAL_TZ, BodyNode, Message
from .dates import TIME_RE, find_days, portal_today

# The body is HTML written by school staff on a third-party site and ends up
# in the Home Assistant frontend, so only this allowlist survives; everything
# else is unwrapped to its text, or dropped with its content when the content
# itself is code or media.
_ALLOWED = {"p", "br", "strong", "em", "u", "ul", "ol", "li", "a"}
_RENAMED = {"b": "strong", "i": "em"}
_DROPPED = {
    "script", "style", "iframe", "object", "embed", "img", "svg", "math", "template",
    "noscript", "form", "input", "button", "textarea", "select", "video", "audio", "canvas",
}  # fmt: skip
_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)
_BLOCKS = {"p", "li", "div"}


def parse_message(html: str, message_id: int, base_url: str) -> Message:
    """Parse a message detail page (`/messages/detail?message=<id>`).

    Confirmed against real captures: a `.messages_detail_table` of `.ft_row`
    rows, each a `.ft_c1` label and a `.ft_c2` value; the body is Quill HTML
    in `div.rich_content`.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one(".messages_detail_table")
    if table is None:
        raise ParseError("message page has no detail table")
    rows = _rows(table)
    body = rows.get("Text zprávy:")
    sent = _sent(rows.get("Odeslané:"))
    if body is None or sent is None:
        raise ParseError(f"message {message_id} has no body or sent time")
    return Message(
        id=message_id,
        subject=_text(rows.get("Předmět:")),
        sender=_text(rows.get("Odesílatel:")),
        recipients=_text(rows.get("Příjemce:") or rows.get("Příjemci:")),
        sent=sent,
        body=sanitize_body(body, base_url),
        body_text="\n".join(_lines(body)),
    )


def sanitize_body(element: Tag, base_url: str) -> list[BodyNode]:
    nodes: list[BodyNode] = []
    for child in element.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            if text := str(child):
                nodes.append({"text": text if text.strip() else " "})
            continue
        if not isinstance(child, Tag) or child.name in _DROPPED:
            continue
        name = _RENAMED.get(child.name, child.name)
        children = sanitize_body(child, base_url)
        if name == "a":
            href = _safe_href(child.get("href"), base_url)
            if href is None:
                nodes.extend(children)
            else:
                nodes.append({"tag": "a", "href": href, "children": children})
        elif name in _ALLOWED:
            nodes.append({"tag": name, "children": children})
        else:
            nodes.extend(children)
    return nodes


def _safe_href(value: object, base_url: str) -> str | None:
    if not isinstance(value, str):
        return None
    href = value.strip()
    if _HTTP_RE.match(href):
        return href
    if href.startswith("/") and not href.startswith("//"):
        return f"{base_url}{href}"
    return None


def _rows(table: Tag) -> dict[str, Tag]:
    rows: dict[str, Tag] = {}
    # Direct children only: the body is staff-written HTML and may contain
    # its own `.ft_row` elements posing as the sender or the sent time.
    for row in table.select(":scope > .ft_row"):
        label = row.select_one(":scope > .ft_c1")
        value = row.select_one(":scope > .ft_c2")
        if label is not None and value is not None:
            rows.setdefault(label.get_text(strip=True), value)
    return rows


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _sent(value: Tag | None) -> datetime | None:
    text = _text(value)
    days = find_days(text, portal_today())
    times = TIME_RE.findall(text)
    if not days or not times:
        return None
    hour, minute = times[-1]
    return datetime.combine(days[0], time(int(hour), int(minute)), PORTAL_TZ)


def _lines(element: Tag) -> list[str]:
    """Plain text of a body, one line per paragraph or list item."""
    lines: list[str] = []
    inline: list[str] = []

    def flush() -> None:
        if line := " ".join("".join(inline).split()):
            lines.append(line)
        inline.clear()

    def walk(tag: Tag) -> None:
        for child in tag.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                inline.append(str(child))
            elif isinstance(child, Tag) and child.name not in _DROPPED:
                if child.name == "br":
                    flush()
                elif child.name in _BLOCKS:
                    flush()
                    walk(child)
                    flush()
                else:
                    walk(child)

    walk(element)
    flush()
    return lines

import json
from datetime import datetime
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag

from pyedookit.exceptions import ParseError
from pyedookit.models import PORTAL_TZ
from pyedookit.parsers.message import parse_message, sanitize_body

FIXTURE = (Path(__file__).parent / "fixtures" / "message_structure.html").read_text()
BASE = "https://zs-example.edookit.net"


def _body(html: str) -> Tag:
    body = BeautifulSoup(f"<div>{html}</div>", "lxml").div
    assert body is not None
    return body


def _flatten(nodes: list) -> list:
    out = []
    for node in nodes:
        out.append(node)
        out.extend(_flatten(node.get("children", [])))
    return out


def test_header_fields():
    message = parse_message(FIXTURE, 9003, BASE)
    assert (message.id, message.subject, message.sender, message.recipients) == (
        9003,
        "Třídní schůzky",
        "Učitelka A",
        "Rodič B",
    )
    assert message.sent == datetime(2026, 10, 21, 8, 12, tzinfo=PORTAL_TZ)


def test_recipients_label_plural_is_read():
    html = FIXTURE.replace("Příjemce:", "Příjemci:").replace("Rodič B", "Rodič B, Rodič C")
    assert parse_message(html, 9003, BASE).recipients == "Rodič B, Rodič C"


def test_body_keeps_allowed_formatting():
    body = parse_message(FIXTURE, 9003, BASE).body
    assert body[0] == {"tag": "p", "children": [{"text": "Vážení rodiče,"}]}
    assert {"tag": "strong", "children": [{"text": "4. 11. od 17:00"}]} in body[1]["children"]
    tags = {node.get("tag") for node in _flatten(body)}
    assert {"p", "br", "strong", "em", "u", "ul", "li", "a"} <= tags


def test_span_is_unwrapped_to_its_text():
    body = parse_message(FIXTURE, 9003, BASE).body
    assert "span" not in {node.get("tag") for node in _flatten(body)}
    assert {"text": "včasný příchod"} in body[2]["children"]


def test_absolute_link_is_kept():
    body = parse_message(FIXTURE, 9003, BASE).body
    assert {
        "tag": "a",
        "href": "https://example.org/x",
        "children": [{"text": "odkaz"}],
    } in _flatten(body)


def test_relative_link_is_made_absolute():
    body = parse_message(FIXTURE, 9003, BASE).body
    assert {
        "tag": "a",
        "href": f"{BASE}/messages/detail?message=1",
        "children": [{"text": "portál"}],
    } in _flatten(body)


def test_body_text_is_plain_text_with_paragraph_breaks():
    text = parse_message(FIXTURE, 9003, BASE).body_text
    assert text.startswith("Vážení rodiče,\nzveme vás na schůzky")
    assert text.endswith("S pozdravem")
    assert "<" not in text


def test_page_without_detail_table_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_message("<html><body><p>x</p></body></html>", 9003, BASE)


@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script>ok",
        "<style>p{}</style>ok",
        "<iframe src=//x></iframe>ok",
        "<img src=x onerror=alert(1)>ok",
        "<svg onload=alert(1)><circle/></svg>ok",
        "<object data=x></object>ok",
    ],
)
def test_dangerous_elements_are_removed_with_their_content(html):
    assert sanitize_body(_body(html), BASE) == [{"text": "ok"}]


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " javascript:alert(1)",
        "data:text/html,<script>",
        "vbscript:x",
        "//evil.example/x",
    ],
)
def test_unsafe_link_loses_its_href_and_becomes_text(href):
    html = f'<a href="{href.replace("<", "&lt;")}">x</a>'
    assert sanitize_body(_body(html), BASE) == [{"text": "x"}]


def test_event_handler_attributes_never_survive():
    out = json.dumps(sanitize_body(_body('<p onclick="x" style="y" class="z">t</p>'), BASE))
    assert "onclick" not in out
    assert "style" not in out
    assert "class" not in out


def test_b_and_i_are_normalised():
    assert sanitize_body(_body("<b>x</b><i>y</i>"), BASE) == [
        {"tag": "strong", "children": [{"text": "x"}]},
        {"tag": "em", "children": [{"text": "y"}]},
    ]


def test_unknown_element_is_unwrapped():
    assert sanitize_body(_body("<section><p>t</p></section>"), BASE) == [
        {"tag": "p", "children": [{"text": "t"}]}
    ]


def test_space_between_inline_elements_is_kept():
    nodes = sanitize_body(_body("<strong>a</strong> <em>b</em>"), BASE)
    assert nodes[1] == {"text": " "}


def test_comments_are_dropped():
    assert sanitize_body(_body("<!-- secret -->ok"), BASE) == [{"text": "ok"}]


def test_rows_inside_the_body_cannot_spoof_the_header():
    spoof = (
        '<div class="ft_row"><span class="ft_c1">Odesílatel:</span>'
        '<span class="ft_c2">Ředitel</span></div>'
    )
    html = FIXTURE.replace("<p>S pozdravem</p>", f"{spoof}<p>S pozdravem</p>")

    message = parse_message(html, 9003, BASE)

    assert message.sender == "Učitelka A"

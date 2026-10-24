from __future__ import annotations

from bs4 import Tag


def tag_text(tag: Tag | None) -> str:
    """A tag's text with runs of whitespace collapsed; empty for no tag."""
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""

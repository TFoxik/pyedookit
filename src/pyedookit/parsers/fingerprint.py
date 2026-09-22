from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup

_NUMBER_RE = re.compile(r"\d+")


def content_fingerprint(html: str) -> str | None:
    """Hash of a page's visible content, stable across counters and timestamps.

    Used to notice when a page that has only ever been empty gets real items.
    It can't rely on empty-state text disappearing, because some pages keep
    their hidden "no data" block in the HTML even when items exist. Returns
    None for error and maintenance pages, which lack the portal's content
    section and must not count as a change.
    """
    root = BeautifulSoup(html, "lxml").select_one("section.content")
    if root is None:
        return None
    for tag in root.select("script, style"):
        tag.decompose()
    text = " ".join(root.get_text(" ", strip=True).split())
    return hashlib.sha256(_NUMBER_RE.sub("#", text).encode()).hexdigest()

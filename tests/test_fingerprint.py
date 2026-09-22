from pyedookit.parsers.fingerprint import content_fingerprint

EMPTY = """<html><body><nav>menu 3</nav><section class="content">
<h1>Domácí úkoly</h1><p>Úkoly na dnešek</p><p>Žádné úkoly</p>
<script>var t = 1727000000;</script></section></body></html>"""


def test_same_page_same_fingerprint():
    assert content_fingerprint(EMPTY) == content_fingerprint(EMPTY)


def test_numbers_and_whitespace_do_not_matter():
    changed = EMPTY.replace("1727000000", "1727999999").replace("Úkoly na", "Úkoly   na")
    assert content_fingerprint(changed) == content_fingerprint(EMPTY)


def test_outside_content_section_does_not_matter():
    assert content_fingerprint(EMPTY.replace("menu", "nabídka")) == content_fingerprint(EMPTY)


def test_new_item_changes_fingerprint():
    with_item = EMPTY.replace("<p>Žádné úkoly</p>", "<p>Žádné úkoly</p><div>Čtení str. 12</div>")
    assert content_fingerprint(with_item) != content_fingerprint(EMPTY)


def test_error_pages_have_no_fingerprint():
    assert content_fingerprint("<html><body><h1>503 Service Unavailable</h1></body></html>") is None

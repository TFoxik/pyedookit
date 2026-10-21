#!/usr/bin/env python3
"""Log in to a real Edookit portal and save timetable and inbox HTML for inspection.

Run this yourself so credentials never enter the assistant's session:

    ! python scripts/capture_fixtures.py <school-subdomain> [--messages]

It first discovers this school's Plus4U client_id (scraped from its own
/user/login page - it's per-school, not shared) without needing a password,
then prompts for username/password interactively (not via argv, so they
don't end up in shell history), logs in, and saves:

  captures/timetable_current_week.html
  captures/timetable_next_week.html
  captures/inbox.html
  captures/message_<id>.html  (every message in the inbox; only with --messages)

Fetching a message page is expected to mark that message read on the portal,
so --messages reads every unread message: leave it off while waiting for an
unread one.

`captures/` is gitignored. These files come from an authenticated session
and can contain more than student/teacher names - a CSRF token, session
identifiers, or the parent's e-mail may be echoed into the page. Read the
printed warning before turning any of this into a committed test fixture.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pyedookit import auth  # noqa: E402
from pyedookit.client import EdookitClient  # noqa: E402

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"


def save(filename: str, html: str) -> None:
    path = CAPTURES_DIR / filename
    path.touch(mode=0o600)
    path.write_text(html, encoding="utf-8")
    print(f"Saved {filename}")


async def main() -> None:
    args = sys.argv[1:]
    with_messages = "--messages" in args
    if with_messages:
        args.remove("--messages")
    if len(args) != 1:
        print("usage: capture_fixtures.py <school-subdomain> [--messages]", file=sys.stderr)
        raise SystemExit(2)
    school = args[0]

    client_id = await auth.probe_client_id(school)
    print(f"Discovered Plus4U client_id for {school}: {client_id!r}")

    username = input("Plus4U username/email: ")
    password = getpass.getpass("Plus4U password: ")

    print(f"Logging in to https://{school}.edookit.net ...")
    session = await auth.login(school, username, password)
    print("Login succeeded.")

    client = EdookitClient(session)
    CAPTURES_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    weeks = ((0, "timetable_current_week.html"), (1, "timetable_next_week.html"))
    for week_offset, filename in weeks:
        save(filename, await client.fetch_timetable_html(week_offset))

    # Raw HTML for building parsers; dev-only script, so the private fetch is fine.
    save("inbox.html", await client._get("/overview/updates", ajax=False))
    messages = await client.get_inbox() if with_messages else []
    print(f"Saving {len(messages)} messages" if with_messages else "Messages skipped")
    for message in messages:
        path = f"/messages/detail?message={message.id}"
        save(f"message_{message.id}.html", await client._get(path, ajax=False))

    print()
    print(f"Files were saved to {CAPTURES_DIR}/ (gitignored) rather than tests/fixtures/,")
    print("because an authenticated page can contain more than names. Before turning any")
    print("of this into a committed test fixture:")
    print("  1. Replace real student/teacher/parent names with placeholders.")
    print("  2. Scrub any CSRF token, session id, or e-mail address you find in the HTML.")
    print("  3. Confirm the markup matches the selectors in src/pyedookit/parsers/, and")
    print("     adjust them if the real markup differs (view page source in a browser to")
    print("     compare class names).")
    print("  4. Only then copy the relevant snippet into tests/fixtures/ and `git add` it.")


if __name__ == "__main__":
    asyncio.run(main())

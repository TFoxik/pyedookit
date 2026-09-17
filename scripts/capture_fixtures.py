#!/usr/bin/env python3
"""Log in to a real Edookit portal and save timetable HTML for inspection.

Run this yourself so credentials never enter the assistant's session:

    ! python scripts/capture_fixtures.py <school-subdomain>

It first checks the observed Plus4U `clientId` against `auth.CLIENT_ID`
without needing a password, then prompts for username/password
interactively (not via argv, so they don't end up in shell history), logs
in, and saves:

  captures/timetable_current_week.html
  captures/timetable_next_week.html

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


async def main() -> None:
    if len(sys.argv) != 2:
        print("usage: capture_fixtures.py <school-subdomain>", file=sys.stderr)
        raise SystemExit(2)
    school = sys.argv[1]

    observed_client_id = await auth.probe_client_id(school)
    if observed_client_id == auth.CLIENT_ID:
        print(f"Plus4U clientId confirmed: {observed_client_id!r}")
    else:
        print(
            f"NOTE: observed Plus4U clientId {observed_client_id!r} differs from "
            f"the hardcoded CLIENT_ID {auth.CLIENT_ID!r} in src/pyedookit/auth.py - "
            "update it before relying on this school's login working elsewhere."
        )

    username = input("Plus4U username/email: ")
    password = getpass.getpass("Plus4U password: ")

    print(f"Logging in to https://{school}.edookit.net ...")
    session = await auth.login(school, username, password)
    print("Login succeeded.")

    client = EdookitClient(session)
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    weeks = ((0, "timetable_current_week.html"), (1, "timetable_next_week.html"))
    for week_offset, filename in weeks:
        html = await client.fetch_timetable_html(week_offset)
        (CAPTURES_DIR / filename).write_text(html)
        print(f"Saved {filename}")

    print()
    print(f"Files were saved to {CAPTURES_DIR}/ (gitignored) rather than tests/fixtures/,")
    print("because an authenticated page can contain more than names. Before turning any")
    print("of this into a committed test fixture:")
    print("  1. Replace real student/teacher/parent names with placeholders.")
    print("  2. Scrub any CSRF token, session id, or e-mail address you find in the HTML.")
    print("  3. Confirm the day-column and lesson-entry markup matches the selectors in")
    print("     src/pyedookit/parsers/timetable.py, and adjust them if the real markup")
    print("     differs (view page source in a browser to compare class names).")
    print("  4. Only then copy the relevant snippet into tests/fixtures/ and `git add` it.")


if __name__ == "__main__":
    asyncio.run(main())

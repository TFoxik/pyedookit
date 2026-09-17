#!/usr/bin/env python3
"""Log in to a real Edookit portal and save anonymised timetable HTML fixtures.

Run this yourself so credentials never enter the assistant's session:

    ! python scripts/capture_fixtures.py <school-subdomain>

It prompts for username/password interactively (not via argv, so they don't
end up in shell history), logs in, and saves:

  tests/fixtures/timetable_current_week.html
  tests/fixtures/timetable_next_week.html
  tests/fixtures/terms.html

It also prints the `clientId` seen on the Plus4U login redirect, which
should be compared against `_CLIENT_ID` in `src/pyedookit/auth.py` -
that value was inferred from third-party documentation, not observed here.

Names in the saved HTML are NOT scrubbed automatically - open each file and
replace real names before committing, or keep them out of git entirely.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import aiohttp  # noqa: E402

from pyedookit import auth  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


async def main() -> None:
    if len(sys.argv) != 2:
        print("usage: capture_fixtures.py <school-subdomain>", file=sys.stderr)
        raise SystemExit(2)
    school = sys.argv[1]

    username = input("Plus4U username/email: ")
    password = getpass.getpass("Plus4U password: ")

    print(f"Logging in to https://{school}.edookit.net ...")
    session = await auth.login(school, username, password)
    print("Login succeeded.")

    base = f"https://{school}.edookit.net"
    headers = auth.build_headers(session)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession() as http:
        async with http.get(f"{base}/timetable/", headers=headers) as resp:
            html = await resp.text()
            (FIXTURES_DIR / "terms.html").write_text(html)
            (FIXTURES_DIR / "timetable_current_week.html").write_text(html)
            print(f"Saved terms.html and timetable_current_week.html (status {resp.status})")

        async with http.get(
            f"{base}/timetable/",
            params={"familyTimetable-value": 1},
            headers=headers,
        ) as resp:
            html = await resp.text()
            (FIXTURES_DIR / "timetable_next_week.html").write_text(html)
            print(f"Saved timetable_next_week.html (status {resp.status})")

    print()
    print("IMPORTANT: open the saved files and:")
    print("  1. Replace any real student/teacher names with placeholders.")
    print("  2. Confirm the day-column and lesson-entry markup matches the")
    print("     selectors in src/pyedookit/parsers/timetable.py, and adjust")
    print("     them if the real markup differs (view page source in a browser")
    print("     to compare class names).")
    print("  3. Only then `git add tests/fixtures` and commit.")


if __name__ == "__main__":
    asyncio.run(main())

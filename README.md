# pyedookit

Unofficial async Python client for the Edookit parent portal
(`https://<school>.edookit.net`), used by Czech schools. Built for the
`ha-edookit` Home Assistant integration but usable standalone.

Edookit's official REST API exists but is only enabled per-school by an
administrator, so this library works the way a parent actually does: it logs
in through Plus4U (OIDC) and scrapes the portal's server-rendered pages.
There is no vendor support for this - selectors may break when Edookit
changes its markup.

## Status

v0.3.0 - timetable, upcoming school events and payments. Verified end-to-end against a real portal
(login, session-settling after the OIDC callback, and the timetable parser
all confirmed working on real data).

**Only `week_offset=0` (the current week) is confirmed working.** The
portal accepts `week_offset=1` ("next week") without error, but returns the
same week's data back rather than actually advancing - the real
week-navigation parameter hasn't been identified yet. Since a school's
weekly timetable is typically the same all year, current-week-only is
usually enough in practice. See `scripts/capture_fixtures.py` for how to
capture and inspect real portal HTML if you want to chase this further (a
browser HAR trace of clicking the forward-week arrow is what's needed).

Cancelled/substituted lessons are also unverified: no real capture has had
one yet, so `Lesson.is_changed`/`is_cancelled` are always `False` for now.

## Install

```bash
pip install pyedookit
```

## Usage

```python
import asyncio
from pyedookit import login, EdookitClient

async def main():
    session = await login("zs-example", "parent@example.com", "hunter2")
    client = EdookitClient(session)
    for lesson in await client.get_timetable(week_offset=0):
        print(lesson.start, lesson.subject, lesson.room)

asyncio.run(main())
```

`client.get_events()` returns upcoming school events (`SchoolEvent`, all-day
events have `date` start/end with an inclusive end), and `client.get_payments()`
returns the family's payment totals and requests (`Payments`, amounts as
`Decimal`). Only paid requests have been seen on a real portal so far; a request
without the "accepted" marker is reported as unpaid.

`client.fetch_page(name)` returns the raw HTML of a page that has no parser yet
(`CAPTURE_PAGES`: assignments, exams, inbox, consents), and
`content_fingerprint(html)` tells you when such a page's content changed.

Persist `session.to_json()` / `Session.from_json()` between runs instead of
storing the password; use `pyedookit.refresh(session)` to renew the
short-lived edookit session from the long-lived Plus4U cookie, and fall back
to `login()` only when `refresh()` raises `AuthError`.

Lesson times are timezone-aware (`pyedookit.PORTAL_TZ`, Europe/Prague).

Errors all derive from `EdookitError`:

| Exception | Meaning | What to do |
|---|---|---|
| `SessionExpired` | short-lived edookit session aged out | `refresh()` and retry |
| `AuthError` | bad credentials, or the Plus4U cookie expired | full `login()` |
| `EdookitConnectionError` | network error or 30 s timeout | retry later |
| `ParseError` | portal markup changed | parser needs updating |

`login()`, `refresh()` and `EdookitClient` all accept an optional
`http: aiohttp.ClientSession` to reuse. Cookies are handled by hand, so
create that session with `cookie_jar=aiohttp.DummyCookieJar()`; a session
with a real cookie jar would also store and resend the portal's cookies.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy src
```

## Releasing

Bump `version` in `pyproject.toml`, then push a `vX.Y.Z` tag. The
`Publish to PyPI` workflow tests, builds and uploads using PyPI trusted
publishing, which has to be configured once on pypi.org for this repository
and the `pypi` environment.

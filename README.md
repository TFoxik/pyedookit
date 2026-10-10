# pyedookit

[![PyPI](https://img.shields.io/pypi/v/pyedookit)](https://pypi.org/project/pyedookit/)
[![CI](https://github.com/TFoxik/pyedookit/actions/workflows/ci.yml/badge.svg)](https://github.com/TFoxik/pyedookit/actions/workflows/ci.yml)

Unofficial async Python client for the [Edookit](https://edookit.com) parent
portal (`https://<school>.edookit.net`) used by Czech schools. It powers the
[ha-edookit](https://github.com/TFoxik/ha-edookit) Home Assistant integration
and works standalone.

Edookit's REST API only works if a school administrator enables it, so this
library signs in like a parent does (Plus4U OIDC, no browser) and reads the
portal's pages. Edookit doesn't support it, and a change to the portal's
markup can break a parser until it's updated.

## Install

```bash
pip install pyedookit
```

Requires Python 3.12+.

## Usage

```python
import asyncio
from pyedookit import EdookitClient, login

async def main():
    session = await login("zs-example", "parent@example.com", "hunter2")
    client = EdookitClient(session)
    for lesson in await client.get_timetable():
        print(lesson.start, lesson.subject, lesson.room)

asyncio.run(main())
```

| Call | Returns |
|---|---|
| `get_timetable()` | this week's `Lesson`s, times in `PORTAL_TZ` (Europe/Prague) |
| `get_events()` | upcoming `SchoolEvent`s; all-day events have `date` start/end, end inclusive |
| `get_payments()` | `Payments` totals and requests, amounts as `Decimal` |
| `fetch_page(name)` | raw HTML of a page without a parser yet (`CAPTURE_PAGES`) |

`content_fingerprint(html)` tells you when such a page's content changed.

### Sessions

The password is only used by `login()`. Store `session.to_json()` instead,
and treat it like a password: it holds the Plus4U cookie, which signs in
for about 19 days. Load it with `Session.from_json()`.

The edookit session itself lasts 30-60 minutes. When it runs out, call
`refresh(session)` to get a new one from the Plus4U cookie. When `refresh()`
raises `AuthError`, the Plus4U cookie has expired too and you need `login()`
again.

| Exception | Meaning | What to do |
|---|---|---|
| `SessionExpired` | the edookit session ran out | `refresh()` and retry |
| `AuthError` | bad credentials, or the Plus4U cookie expired | `login()` |
| `EdookitConnectionError` | network error or 30 s timeout | retry later |
| `ParseError` | the portal's markup changed | the parser needs updating |

All of them derive from `EdookitError`. `login()`, `refresh()` and
`EdookitClient` accept an `http: aiohttp.ClientSession` to reuse. Create it
with `cookie_jar=aiohttp.DummyCookieJar()`: cookies are handled per host by
hand, and a real jar would resend them.

## Limitations

- **Current week only.** The portal ignores `week_offset=1`, and the real
  week-navigation parameter hasn't been found yet. A browser HAR trace of
  clicking the next-week arrow would solve it; `scripts/capture_fixtures.py`
  captures portal HTML.
- **Cancelled and changed lessons are unverified.** No real capture has had
  one yet, so `Lesson.is_changed` and `is_cancelled` are always `False`.
- **Unpaid payment requests are unverified.** Only paid ones have been seen.
  A request without the "accepted" marker is reported as unpaid.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy src
```

To release, bump `version` in `pyproject.toml` and push a `vX.Y.Z` tag. The
publish workflow checks that the tag matches the version, then tests, builds
and uploads to PyPI with trusted publishing.

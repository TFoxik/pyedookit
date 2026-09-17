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

v0.1.0 - timetable only (current/next week, term list). See
`scripts/capture_fixtures.py` for how to capture real portal HTML and correct
the parser's selectors against it; the current selectors are inferred from
third-party documentation and a synthetic fixture, not yet verified against a
live portal.

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

Persist `session.to_json()` / `Session.from_json()` between runs instead of
storing the password; use `pyedookit.refresh(session)` to renew the
short-lived edookit session from the long-lived Plus4U cookie, and fall back
to `login()` only when `refresh()` raises `AuthError`.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy src
```

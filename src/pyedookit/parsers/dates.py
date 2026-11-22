from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ..models import PORTAL_TZ

# The portal writes the year only when it isn't the current one, and uses a
# word instead of a date for recent days ("Dnes , 8:00 – 8:45"; Včera/Dnes
# confirmed, Zítra assumed).
_RELATIVE_DAYS = {"včera": -1, "dnes": 0, "zítra": 1}
_DAY_RE = re.compile(
    r"(?P<relative>včera|dnes|zítra)\b"
    r"|(?P<day>\d{1,2})\.\s*(?P<month>\d{1,2})\.(?:\s*(?P<year>\d{4}))?",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_YEARLESS_DATE_RE = re.compile(r"\d{1,2}\.\s*\d{1,2}\.(?!\s*\d{4})")


def portal_today() -> date:
    return datetime.now(PORTAL_TZ).date()


def find_days(text: str, today: date) -> list[date]:
    days: list[date] = []
    for match in _DAY_RE.finditer(text):
        if relative := match.group("relative"):
            days.append(today + timedelta(days=_RELATIVE_DAYS[relative.lower()]))
            continue
        year = int(match.group("year")) if match.group("year") else today.year
        try:
            days.append(date(year, int(match.group("month")), int(match.group("day"))))
        except ValueError:
            continue
    return days


def resolve_day(
    text: str, today: date, *, not_before: date | None = None, near: date | None = None
) -> date | None:
    """The first day in `text`. A day written without a year falls on or after
    `not_before` when given (homework is never due before it was set), else in
    the year nearest `near` (an exam can be entered after it took place),
    else nearest `today`."""
    if not _YEARLESS_DATE_RE.search(text):
        return next(iter(find_days(text, today)), None)
    first = next(iter(find_days(text, not_before or near or today)), None)
    if first is None:
        return None
    if not_before is not None:
        return first if first >= not_before else _in_year(first, first.year + 1)
    anchor = near or today
    years = (anchor.year - 1, anchor.year, anchor.year + 1)
    options = [day for year in years if (day := _in_year(first, year)) is not None]
    return min(options, key=lambda day: abs(day - anchor))


def _in_year(day: date, year: int) -> date | None:
    try:
        return day.replace(year=year)
    except ValueError:
        return None

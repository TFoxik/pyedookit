from __future__ import annotations

import re
from datetime import date, timedelta

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

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

# The portal renders wall-clock times with no zone; every Edookit school is
# Czech, so parsed times are pinned to Prague rather than left naive.
PORTAL_TZ = ZoneInfo("Europe/Prague")


@dataclass(frozen=True, slots=True)
class Lesson:
    start: datetime
    end: datetime
    subject: str
    teacher: str | None = None
    room: str | None = None
    group: str | None = None
    is_changed: bool = False
    is_cancelled: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Term:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Student:
    id: str
    name: str

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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


@dataclass(slots=True)
class Timetable:
    week_offset: int
    lessons: list[Lesson] = field(default_factory=list)

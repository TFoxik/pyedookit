from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
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
    code: str | None = None


@dataclass(frozen=True, slots=True)
class Period:
    number: int
    start: time
    end: time


@dataclass(slots=True)
class TimetableWeek:
    lessons: list[Lesson]
    periods: list[Period]


@dataclass(frozen=True, slots=True)
class Term:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class SchoolEvent:
    id: str
    title: str
    start: datetime | date
    end: datetime | date
    description: str | None = None
    created_by: str | None = None

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)


@dataclass(frozen=True, slots=True)
class MessageSummary:
    id: int
    subject: str
    sender: str
    sent: datetime
    preview: str
    unread: bool


# A sanitised message body, ready to serialise as JSON: `{"text": str}`, or
# `{"tag": str, "children": [...]}` with tag one of p, br, strong, em, u, ul,
# ol, li, a; an `a` also has `"href"`, always http(s).
type BodyNode = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    subject: str
    sender: str
    recipients: str
    sent: datetime
    body: list[BodyNode]
    body_text: str


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    title: str
    amount: Decimal
    currency: str
    is_paid: bool


@dataclass(frozen=True, slots=True)
class Payments:
    paid: Decimal
    remaining: Decimal
    overpaid: Decimal
    currency: str
    requests: list[PaymentRequest]

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from .exceptions import AuthError

# A school subdomain becomes part of every portal URL with no other encoding,
# so reject anything that isn't a bare hostname label - otherwise a value
# like "evil.com/" or "evil.com#" would send the session's cookies off-portal.
_SCHOOL_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def validate_school(school: str) -> None:
    if not _SCHOOL_RE.fullmatch(school):
        raise AuthError(f"{school!r} is not a valid Edookit school subdomain")


def school_base(school: str) -> str:
    return f"https://{school}.edookit.net"


@dataclass(slots=True)
class Session:
    """Everything needed to talk to a school's portal without the password.

    `edookit_cookies` is short-lived (expires in roughly 30-60 minutes).
    `plus4u_cookies` is long-lived (roughly 19 days) and is what `refresh()`
    uses to obtain a fresh edookit session silently. The password itself is
    never stored here.
    """

    school: str
    edookit_cookies: dict[str, str] = field(repr=False)
    plus4u_cookies: dict[str, str] = field(repr=False)
    csrf_token: str = field(repr=False)
    edookit_expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )

    def __post_init__(self) -> None:
        validate_school(self.school)

    @property
    def base_url(self) -> str:
        return school_base(self.school)

    @property
    def is_edookit_expired(self) -> bool:
        """True once the session is expected to have aged out.

        A conservative estimate (login/refresh don't know the portal's real
        TTL), meant for a caller to refresh proactively before it bothers
        making a request that's likely to just be redirected to the login
        page - not a substitute for handling `SessionExpired` reactively too.
        """
        return datetime.now(UTC) >= self.edookit_expires_at

    def to_json(self) -> str:
        data = asdict(self)
        data["edookit_expires_at"] = self.edookit_expires_at.isoformat()
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> Session:
        data = json.loads(raw)
        data["edookit_expires_at"] = datetime.fromisoformat(data["edookit_expires_at"])
        return cls(**data)

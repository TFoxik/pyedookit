from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class Session:
    """Everything needed to talk to a school's portal without the password.

    `edookit_cookies` is short-lived (expires in roughly 30-60 minutes).
    `plus4u_cookies` is long-lived (roughly 19 days) and is what `refresh()`
    uses to obtain a fresh edookit session silently. The password itself is
    never stored here.
    """

    school: str
    edookit_cookies: dict[str, str]
    plus4u_cookies: dict[str, str]
    csrf_token: str
    edookit_expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )

    @property
    def base_url(self) -> str:
        return f"https://{self.school}.edookit.net"

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

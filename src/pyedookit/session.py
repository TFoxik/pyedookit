from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from .exceptions import AuthError
from .transport import Cookie, CookieStore

PLUS4U_HOST = "uuidentity.plus4u.net"

# A school subdomain becomes part of every portal URL with no other encoding,
# so reject anything that isn't a bare hostname label - otherwise a value
# like "evil.com/" or "evil.com#" would send the session's cookies off-portal.
_SCHOOL_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def validate_school(school: str) -> None:
    if not _SCHOOL_RE.fullmatch(school):
        raise AuthError(f"{school!r} is not a valid Edookit school subdomain")


def school_host(school: str) -> str:
    return f"{school}.edookit.net"


def school_base(school: str) -> str:
    return f"https://{school_host(school)}"


@dataclass(slots=True)
class Session:
    """Everything needed to talk to a school's portal without the password.

    `cookies` holds the short-lived edookit session (30-60 minutes) and the
    long-lived Plus4U sign-in that `refresh()` renews it from. Treat the
    serialised form like a password.
    """

    school: str
    cookies: CookieStore = field(repr=False)

    def __post_init__(self) -> None:
        validate_school(self.school)

    @classmethod
    def from_cookies(
        cls, school: str, edookit: Mapping[str, str], plus4u: Mapping[str, str]
    ) -> Session:
        return cls(
            school,
            CookieStore(
                {
                    school_host(school): {n: Cookie(v) for n, v in edookit.items()},
                    PLUS4U_HOST: {n: Cookie(v) for n, v in plus4u.items()},
                }
            ),
        )

    @property
    def host(self) -> str:
        return school_host(self.school)

    @property
    def base_url(self) -> str:
        return school_base(self.school)

    @property
    def csrf_token(self) -> str:
        return self.cookies.get(self.host, "uu.app.csrf") or ""

    @property
    def plus4u_expires_at(self) -> datetime | None:
        return self.cookies.expires(PLUS4U_HOST, "uoid.ps")

    def to_json(self) -> str:
        return json.dumps({"school": self.school, "cookies": self.cookies.to_dict()})

    @classmethod
    def from_json(cls, raw: str) -> Session:
        data = json.loads(raw)
        if "cookies" in data:
            return cls(data["school"], CookieStore.from_dict(data["cookies"]))
        # Written by pyedookit <= 0.3.x: two plain dicts and no cookie expiry.
        return cls.from_cookies(data["school"], data["edookit_cookies"], data["plus4u_cookies"])

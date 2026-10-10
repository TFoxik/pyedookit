import json
from datetime import UTC, datetime

import pytest

from pyedookit.exceptions import AuthError
from pyedookit.session import PLUS4U_HOST, Session
from pyedookit.transport import CookieStore

EDOOKIT_HOST = "zs-example.edookit.net"


def _session(school: str) -> Session:
    return Session.from_cookies(
        school,
        edookit={"PHPSESSID": "secret-sid", "uu.app.csrf": "secret-csrf"},
        plus4u={"uoid.ps": "secret-ps"},
    )


@pytest.mark.parametrize("school", ["evil.com#", "evil.com/", "zs-example\n", "-zs", ""])
def test_session_rejects_a_school_that_is_not_a_bare_subdomain(school):
    with pytest.raises(AuthError):
        _session(school)


def test_from_json_rejects_a_tampered_school():
    raw = _session("zs-example").to_json().replace('"zs-example"', '"evil.com#"')
    with pytest.raises(AuthError):
        Session.from_json(raw)


def test_repr_hides_cookies_and_csrf_token():
    text = repr(_session("zs-example"))
    assert "zs-example" in text
    assert "secret" not in text


def test_csrf_token_follows_the_cookie():
    session = _session("zs-example")
    session.cookies.update(EDOOKIT_HOST, ["uu.app.csrf=rotated"])

    assert session.csrf_token == "rotated"


def test_plus4u_expiry_comes_from_the_cookie():
    session = Session("zs-example", CookieStore())
    assert session.plus4u_expires_at is None

    session.cookies.update(PLUS4U_HOST, ["uoid.ps=p; Expires=Wed, 21 Oct 2099 07:28:00 GMT"])
    assert session.plus4u_expires_at == datetime(2099, 10, 21, 7, 28, tzinfo=UTC)


def test_json_round_trip():
    session = _session("zs-example")
    assert Session.from_json(session.to_json()) == session


def test_loads_a_session_stored_by_pyedookit_0_3():
    legacy = json.dumps(
        {
            "school": "zs-example",
            "edookit_cookies": {"PHPSESSID": "s", "uu.app.csrf": "c"},
            "plus4u_cookies": {"uoid.ps": "p"},
            "csrf_token": "c",
            "edookit_expires_at": "2026-10-10T14:07:34.393462+00:00",
        }
    )

    session = Session.from_json(legacy)

    assert session.cookies.get(EDOOKIT_HOST, "PHPSESSID") == "s"
    assert session.cookies.get(PLUS4U_HOST, "uoid.ps") == "p"
    assert session.csrf_token == "c"

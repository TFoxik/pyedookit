import pytest
from yarl import URL

from pyedookit import auth
from pyedookit.exceptions import AuthError
from pyedookit.session import Session


def _session(school: str) -> Session:
    return Session(
        school=school,
        edookit_cookies={"PHPSESSID": "secret-sid"},
        plus4u_cookies={"uoid.ps": "secret-ps"},
        csrf_token="secret-csrf",
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


@pytest.mark.parametrize(
    "url",
    [
        "http://zs-example.edookit.net/user/oidc-login-callback?code=x",
        "https://evil.com/?code=x",
        "https://edookit.net.evil.com/",
    ],
)
def test_login_flow_refuses_to_leave_plus4u_and_edookit(url):
    with pytest.raises(AuthError):
        auth._check_hop(URL(url))


@pytest.mark.parametrize(
    "url",
    ["https://uuidentity.plus4u.net/oidc/auth", "https://zs-example.edookit.net/"],
)
def test_login_flow_allows_plus4u_and_edookit_over_https(url):
    auth._check_hop(URL(url))

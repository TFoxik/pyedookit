from datetime import UTC, datetime, timedelta, timezone

import pytest
from yarl import URL

from pyedookit import transport
from pyedookit.exceptions import AuthError, EdookitConnectionError
from pyedookit.transport import Cookie, CookieStore

from .fakes import FailingResponse, FakeClientSession, ok, redirect

HOST = "zs-example.edookit.net"
PAGE = f"https://{HOST}/timetable/"


def test_records_cookie_values_verbatim():
    store = CookieStore()
    store.update(HOST, ['uoid.ps="a b"; Path=/; Secure; Partitioned', "PHPSESSID=s1; path=/"])

    assert store.get(HOST, "uoid.ps") == '"a b"'
    assert store.header(HOST) == 'uoid.ps="a b"; PHPSESSID=s1'


def test_cookies_are_scoped_to_their_host():
    store = CookieStore()
    store.update(HOST, ["PHPSESSID=s1"])

    assert store.header("uuidentity.plus4u.net") == ""
    assert store.get("uuidentity.plus4u.net", "PHPSESSID") is None


def test_max_age_zero_deletes():
    store = CookieStore({HOST: {"PHPSESSID": Cookie("s1")}})
    store.update(HOST, ["PHPSESSID=; Max-Age=0"])

    assert store.get(HOST, "PHPSESSID") is None


def test_expires_in_the_past_deletes():
    store = CookieStore({HOST: {"PHPSESSID": Cookie("s1")}})
    store.update(HOST, ["PHPSESSID=deleted; expires=Thu, 01 Jan 1970 00:00:01 GMT"])

    assert store.get(HOST, "PHPSESSID") is None


def test_future_expiry_is_kept_and_reported():
    store = CookieStore()
    store.update(HOST, ["uoid.ps=p; Max-Age=1641600"])

    expires = store.expires(HOST, "uoid.ps")
    assert expires is not None
    assert timedelta(days=18) < expires - datetime.now(UTC) < timedelta(days=20)


def test_max_age_wins_over_expires():
    store = CookieStore()
    store.update(HOST, ["a=1; Expires=Thu, 01 Jan 1970 00:00:01 GMT; Max-Age=60"])

    assert store.get(HOST, "a") == "1"


def test_malformed_attributes_are_ignored():
    store = CookieStore()
    store.update(HOST, ["a=1; Expires=not a date; Max-Age=soon", "=nameless", "garbage"])

    assert store.get(HOST, "a") == "1"
    assert store.expires(HOST, "a") is None
    assert store.header(HOST) == "a=1"


def test_a_cookie_that_expired_meanwhile_is_not_sent():
    past = datetime.now(UTC) - timedelta(seconds=1)
    store = CookieStore({HOST: {"old": Cookie("x", past), "live": Cookie("y")}})

    assert store.header(HOST) == "live=y"


def test_round_trips_through_dict():
    store = CookieStore()
    store.update(HOST, ["a=1", "b=2; Max-Age=600"])

    assert CookieStore.from_dict(store.to_dict()) == store


def test_for_host_is_an_independent_copy():
    store = CookieStore()
    store.update("uuidentity.plus4u.net", ["uoid.ps=p"])
    store.update(HOST, ["PHPSESSID=s"])

    copy = store.for_host("uuidentity.plus4u.net")
    copy.update("uuidentity.plus4u.net", ["uoid.ps=changed"])

    assert copy.header(HOST) == ""
    assert store.get("uuidentity.plus4u.net", "uoid.ps") == "p"


def test_absurd_max_age_does_not_crash():
    store = CookieStore()
    store.update(HOST, ["a=1; Max-Age=99999999999999", "b=2; Max-Age=-99999999999999"])

    assert store.get(HOST, "a") == "1"
    assert store.get(HOST, "b") is None
    expires = store.expires(HOST, "a")
    assert expires is not None
    expires.astimezone(timezone(timedelta(hours=14)))
    expires + timedelta(days=1)
    assert CookieStore.from_dict(store.to_dict()) == store


async def test_request_sends_host_cookies_and_records_new_ones():
    seen: list[dict] = []

    def answer(headers):
        seen.append(headers)
        return ok(PAGE, raw_set_cookies=["PHPSESSID=rotated; path=/"])

    store = CookieStore({HOST: {"PHPSESSID": Cookie("s1")}})
    http = FakeClientSession([("GET", PAGE, answer)])

    response = await transport.request(http, "GET", PAGE, store, headers={"X-Test": "1"})

    assert response.status == 200
    assert response.content_type.startswith("text/html")
    assert seen[0]["Cookie"] == "PHPSESSID=s1"
    assert seen[0]["X-Test"] == "1"
    assert store.get(HOST, "PHPSESSID") == "rotated"


async def test_redirects_are_followed_only_when_asked():
    target = f"https://{HOST}/overview/"
    http = FakeClientSession([("GET", PAGE, redirect(target)), ("GET", target, ok(target))])

    first = await transport.request(http, "GET", PAGE, CookieStore())
    assert first.is_redirect and first.location == target

    http = FakeClientSession([("GET", PAGE, redirect(target)), ("GET", target, ok(target))])
    followed = await transport.request(
        http, "GET", PAGE, CookieStore(), follow_redirects=True
    )
    assert followed.url == target


async def test_extra_headers_are_not_forwarded_to_redirect_targets():
    target = "https://uuidentity.plus4u.net/oidc/auth"
    seen: list[dict] = []

    def answer(headers):
        seen.append(headers)
        return ok(target)

    http = FakeClientSession([("GET", PAGE, redirect(target)), ("GET", target, answer)])
    await transport.request(
        http, "GET", PAGE, CookieStore(), headers={"X-CSRF-Token": "t"}, follow_redirects=True
    )

    assert "X-CSRF-Token" not in seen[0]


async def test_network_errors_become_connection_errors():
    http = FakeClientSession([("GET", PAGE, FailingResponse(TimeoutError()))])

    with pytest.raises(EdookitConnectionError):
        await transport.request(http, "GET", PAGE, CookieStore())


@pytest.mark.parametrize(
    "url",
    [
        "http://zs-example.edookit.net/user/oidc-login-callback?code=x",
        "https://evil.com/?code=x",
        "https://edookit.net.evil.com/",
    ],
)
def test_check_hop_refuses_to_leave_plus4u_and_edookit(url):
    with pytest.raises(AuthError):
        transport.check_hop(URL(url))


@pytest.mark.parametrize(
    "url",
    ["https://uuidentity.plus4u.net/oidc/auth", "https://zs-example.edookit.net/"],
)
def test_check_hop_allows_plus4u_and_edookit_over_https(url):
    transport.check_hop(URL(url))

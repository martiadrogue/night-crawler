import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from night_crawler import oidc_client


def _token(**claims) -> str:
    """An unsigned JWT; the UI only reads claims, the API verifies."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"e30.{payload.decode()}.sig"


@pytest.fixture
def respond(monkeypatch):
    """Route Keycloak calls through a handler; returns the requests seen."""
    seen: list[httpx.Request] = []

    def install(handler):
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(oidc_client, "TRANSPORT", httpx.MockTransport(recording))
        return seen

    return install


def test_the_login_url_carries_state_and_a_pkce_challenge():
    request = oidc_client.create_login_request()

    url = urlsplit(request.url)
    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(request.code_verifier.encode()).digest()
    ).rstrip(b"=")
    assert f"{oidc_client.OIDC_BROWSER_URL}/protocol/openid-connect/auth" == (
        f"{url.scheme}://{url.netloc}{url.path}"
    )
    assert {
        "client_id": oidc_client.OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email",
        "redirect_uri": oidc_client.REDIRECT_URI,
        "state": request.state,
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
    } == query


def test_each_login_gets_its_own_state_and_verifier():
    first, second = (
        oidc_client.create_login_request(),
        oidc_client.create_login_request(),
    )

    assert first.state != second.state
    assert first.code_verifier != second.code_verifier
    assert 43 <= len(first.code_verifier) <= 128


def test_registration_asks_keycloak_for_its_sign_up_page():
    request = oidc_client.create_login_request(is_registration=True)

    assert ["create"] == parse_qs(urlsplit(request.url).query)["prompt"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"state": "s1", "code": "c1"}, ("c1", "")),
        ({"state": "other", "code": "c1"}, ("", "expired")),
        ({"code": "c1"}, ("", "expired")),
        ({"state": "s1"}, ("", "no authorization code")),
        (
            {"state": "s1", "error": "access_denied", "error_description": "No."},
            ("", "No."),
        ),
    ],
    ids=["ok", "wrong-state", "no-state", "no-code", "keycloak-error"],
)
def test_check_callback(params, expected):
    code, error = oidc_client.check_callback(params, "s1")

    assert expected[0] == code
    assert expected[1] in error


def test_a_callback_without_a_login_in_progress_is_refused():
    _, error = oidc_client.check_callback({"state": "", "code": "c1"}, "")

    assert "expired" in error


@pytest.mark.anyio
async def test_exchange_code_sends_the_secret_and_the_verifier(respond):
    seen = respond(
        lambda request: httpx.Response(
            200,
            json={"access_token": "a1", "refresh_token": "r1", "id_token": "i1"},
        )
    )

    tokens = await oidc_client.exchange_code("c1", "v1")

    form = parse_qs(seen[0].content.decode())
    assert oidc_client.SessionTokens("a1", "r1", "i1") == tokens
    assert f"{oidc_client.OIDC_INTERNAL_URL}/protocol/openid-connect/token" == str(
        seen[0].url
    )
    assert {
        "grant_type": ["authorization_code"],
        "code": ["c1"],
        "code_verifier": ["v1"],
        "redirect_uri": [oidc_client.REDIRECT_URI],
        "client_id": [oidc_client.OIDC_CLIENT_ID],
        "client_secret": [oidc_client.OIDC_CLIENT_SECRET],
    } == form


@pytest.mark.anyio
async def test_refresh_session_rotates_the_refresh_token(respond):
    seen = respond(
        lambda request: httpx.Response(
            200, json={"access_token": "a2", "refresh_token": "r2"}
        )
    )

    tokens = await oidc_client.refresh_session("r1")

    form = parse_qs(seen[0].content.decode())
    assert oidc_client.SessionTokens("a2", "r2", "") == tokens
    assert (["refresh_token"], ["r1"]) == (form["grant_type"], form["refresh_token"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (
            lambda request: httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Code not valid"},
            ),
            "Code not valid",
        ),
        (lambda request: httpx.Response(502, text="bad gateway"), "502"),
    ],
    ids=["refused", "server-error"],
)
async def test_a_refused_token_request_is_an_oidc_error(respond, handler, message):
    respond(handler)

    with pytest.raises(oidc_client.OidcError) as exc_info:
        await oidc_client.refresh_session("r1")

    assert message in exc_info.value.message


@pytest.mark.anyio
async def test_an_unreachable_keycloak_is_an_oidc_error(respond):
    def unreachable(request):
        raise httpx.ConnectError("refused")

    respond(unreachable)

    with pytest.raises(oidc_client.OidcError):
        await oidc_client.exchange_code("c1", "v1")


def test_the_logout_url_ends_the_keycloak_session():
    url = urlsplit(oidc_client.build_logout_url("i1"))

    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    assert url.path.endswith("/protocol/openid-connect/logout")
    assert {
        "client_id": oidc_client.OIDC_CLIENT_ID,
        "post_logout_redirect_uri": oidc_client.POST_LOGOUT_REDIRECT_URI,
        "id_token_hint": "i1",
    } == query


def test_the_logout_url_works_without_an_id_token():
    query = parse_qs(urlsplit(oidc_client.build_logout_url("")).query)

    assert "id_token_hint" not in query


@pytest.mark.parametrize(
    ("roles", "role"),
    [
        (["offline_access", "user", "admin"], "admin"),
        (["user", "viewer"], "user"),
        (["viewer"], "viewer"),
        (["offline_access"], ""),
    ],
)
def test_read_session_user_shows_the_highest_role(roles, role):
    token = _token(email="ana@example.com", exp=100, realm_access={"roles": roles})

    user = oidc_client.read_session_user(token)

    assert oidc_client.SessionUser("ana@example.com", role) == user


def test_an_unreadable_token_has_no_user():
    assert oidc_client.SessionUser("", "") == oidc_client.read_session_user("x")


@pytest.mark.parametrize(
    ("token", "now", "is_expiring"),
    [
        (_token(exp=1000), 900, False),
        (_token(exp=1000), 975, True),
        (_token(exp=1000), 1001, True),
        ("not-a-jwt", 0, True),
    ],
    ids=["fresh", "within-margin", "expired", "unreadable"],
)
def test_is_expiring(token, now, is_expiring):
    assert is_expiring is oidc_client.is_expiring(token, now)

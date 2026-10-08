"""Server-side client for Keycloak's OpenID Connect endpoints.

The UI logs in with the Authorization Code flow and PKCE as
`night-crawler-ui`, a confidential client: the browser only visits
Keycloak's login, registration, and logout pages; the code is exchanged
and tokens are refreshed here, on the Reflex backend, which holds the
client secret.
"""

import base64
import binascii
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

OIDC_BROWSER_URL = os.environ.get(
    "OIDC_BROWSER_URL", "http://localhost:8180/realms/night-crawler"
)
"""The realm as the browser reaches it, for the login and logout pages."""
OIDC_INTERNAL_URL = os.environ.get(
    "OIDC_INTERNAL_URL", "http://keycloak:8080/realms/night-crawler"
)
"""The realm as this container reaches it, for the token endpoint."""
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "night-crawler-ui")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:3000")
REDIRECT_URI = f"{APP_URL}/auth/callback"
POST_LOGOUT_REDIRECT_URI = f"{APP_URL}/login"

TIMEOUT_SECONDS = 15.0
EXPIRY_MARGIN_SECONDS = 30
"""Refresh an access token this long before it expires."""
ROLES_BY_PRECEDENCE = ("admin", "user", "viewer")
TRANSPORT: httpx.AsyncBaseTransport | None = None
"""Replaced in tests with `httpx.MockTransport`; `None` uses the network."""

EXPIRED_LOGIN_MESSAGE = (
    "This login expired or was started in another tab. Log in again."
)


class OidcError(Exception):
    """Keycloak refused a token request, or could not be reached."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class LoginRequest:
    """Where to send the browser, and what the callback must match."""

    url: str
    state: str
    code_verifier: str


@dataclass(frozen=True)
class SessionTokens:
    """What a token response holds; `id_token` is "" when absent."""

    access_token: str
    refresh_token: str
    id_token: str


@dataclass(frozen=True)
class SessionUser:
    """Who an access token is for, to show in the UI only."""

    email: str
    role: str


def create_login_request(is_registration: bool = False) -> LoginRequest:
    """Return Keycloak's login (or sign-up) URL with a new state and PKCE pair."""
    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=")
    query = {
        "client_id": OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
    }
    if is_registration:
        query["prompt"] = "create"
    url = f"{OIDC_BROWSER_URL}/protocol/openid-connect/auth?{urlencode(query)}"
    return LoginRequest(url=url, state=state, code_verifier=code_verifier)


def check_callback(params: dict, expected_state: str) -> tuple[str, str]:
    """Return the callback's code, or an error to show instead.

    The `state` must be the one this tab's login started with, so a
    callback forged by another site, or replayed, is refused.
    """
    error = _callback_error(params, expected_state)
    return ("", error) if error else (params["code"], "")


def _callback_error(params: dict, expected_state: str) -> str:
    """Return why the callback can't be used, or "" if it can."""
    if "error" in params:
        return params.get("error_description", params["error"])
    if not expected_state or expected_state != params.get("state"):
        return EXPIRED_LOGIN_MESSAGE
    if not params.get("code"):
        return "Keycloak sent no authorization code. Log in again."
    return ""


async def exchange_code(code: str, code_verifier: str) -> SessionTokens:
    """Trade the callback's code for the session's tokens."""
    return await _request_tokens(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": REDIRECT_URI,
        }
    )


async def refresh_session(refresh_token: str) -> SessionTokens:
    """Return new tokens; Keycloak also rotates the refresh token."""
    return await _request_tokens(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


async def _request_tokens(form: dict) -> SessionTokens:
    """Post to the token endpoint as the confidential client."""
    form = {**form, "client_id": OIDC_CLIENT_ID, "client_secret": OIDC_CLIENT_SECRET}
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, transport=TRANSPORT
        ) as client:
            response = await client.post(
                f"{OIDC_INTERNAL_URL}/protocol/openid-connect/token", data=form
            )
    except httpx.HTTPError as exc:
        raise OidcError("Keycloak is unreachable. Try again.") from exc
    if 200 != response.status_code:
        raise OidcError(_error_message(response))
    body = response.json()
    return SessionTokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", ""),
        id_token=body.get("id_token", ""),
    )


def _error_message(response: httpx.Response) -> str:
    """Return Keycloak's `error_description`, else the status."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and body.get("error_description"):
        return str(body["error_description"])
    return f"Keycloak answered {response.status_code}."


def build_logout_url(id_token: str) -> str:
    """Return Keycloak's end-session URL, back to /login afterwards.

    Without an `id_token_hint` (a new tab never had one) Keycloak asks
    the user to confirm the logout.
    """
    query = {
        "client_id": OIDC_CLIENT_ID,
        "post_logout_redirect_uri": POST_LOGOUT_REDIRECT_URI,
    }
    if id_token:
        query["id_token_hint"] = id_token
    return f"{OIDC_BROWSER_URL}/protocol/openid-connect/logout?{urlencode(query)}"


def read_session_user(access_token: str) -> SessionUser:
    """Return the email and highest role the token names.

    Read without checking the signature: it only decides what the UI
    shows (e.g. the Users link). The API verifies every token itself.
    """
    claims = _read_claims(access_token)
    roles = set((claims.get("realm_access") or {}).get("roles", []))
    role = next((name for name in ROLES_BY_PRECEDENCE if name in roles), "")
    return SessionUser(email=claims.get("email", ""), role=role)


def is_expiring(access_token: str, now: float) -> bool:
    """Tell whether the token expires within the margin (or is unreadable)."""
    expires_at = _read_claims(access_token).get("exp")
    if not isinstance(expires_at, int | float):
        return True
    return now >= expires_at - EXPIRY_MARGIN_SECONDS


def _read_claims(token: str) -> dict:
    """Return a JWT's payload, or {} if it isn't one."""
    parts = token.split(".")
    if 3 != len(parts):
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}

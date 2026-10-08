import time

import reflex as rx

from night_crawler import oidc_client

_SESSION_SECONDS = 60 * 60 * 10
"""Cookie lifetime: Keycloak's default SSO session maximum, 10 hours."""


class AuthState(rx.State):
    """The Keycloak session.

    The access token, email, and role are cookies, so a new tab is
    logged in too; their names start with `nc_` because cookies don't
    separate by port, and the Importer UI on localhost:3100 has its
    own. The refresh and id tokens, and a login's state and PKCE
    verifier, are backend-only vars (leading `_`): never sent to the
    browser, kept per tab.
    """

    token: str = rx.Cookie("", name="nc_access_token", max_age=_SESSION_SECONDS)
    email: str = rx.Cookie("", name="nc_email", max_age=_SESSION_SECONDS)
    role: str = rx.Cookie("", name="nc_role", max_age=_SESSION_SECONDS)
    error: str = ""

    _refresh_token: str = ""
    _id_token: str = ""
    _login_state: str = ""
    _code_verifier: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.token)

    @rx.event
    def start_login(self):
        return self._redirect_to_keycloak(is_registration=False)

    @rx.event
    def start_register(self):
        return self._redirect_to_keycloak(is_registration=True)

    def _redirect_to_keycloak(self, is_registration: bool):
        """Send the browser to Keycloak, remembering what to check on return."""
        request = oidc_client.create_login_request(is_registration)
        self._login_state = request.state
        self._code_verifier = request.code_verifier
        self.error = ""
        return rx.redirect(request.url)

    @rx.event
    async def finish_login(self):
        """On /auth/callback: check the state, then trade the code for tokens."""
        expected_state, self._login_state = self._login_state, ""
        code, self.error = oidc_client.check_callback(
            dict(self.router.url.query_parameters), expected_state
        )
        if self.error:
            return None
        try:
            tokens = await oidc_client.exchange_code(code, self._code_verifier)
        except oidc_client.OidcError as exc:
            self.error = exc.message
            return None
        self._keep_session(tokens)
        return rx.redirect("/crawlers")

    async def refresh_if_expiring(self) -> None:
        """Refresh a token about to expire; log out if that is refused.

        A tab that never logged in itself (a new tab, after a restart)
        has the cookie's access token but no refresh token, so it is
        logged out once that token expires; logging in again is one
        click, since Keycloak's own session is still open.
        """
        if not self.token or not oidc_client.is_expiring(self.token, time.time()):
            return
        if not self._refresh_token:
            self._clear_session()
            return
        try:
            tokens = await oidc_client.refresh_session(self._refresh_token)
        except oidc_client.OidcError:
            self._clear_session()
            return
        self._keep_session(tokens)

    def _keep_session(self, tokens: oidc_client.SessionTokens) -> None:
        user = oidc_client.read_session_user(tokens.access_token)
        self.token = tokens.access_token
        self.email = user.email
        self.role = user.role
        self._refresh_token = tokens.refresh_token
        self._id_token = tokens.id_token or self._id_token

    def _clear_session(self) -> None:
        self.token = ""
        self.email = ""
        self.role = ""
        self._refresh_token = ""
        self._id_token = ""

    @rx.event
    def logout(self):
        """Forget the session here and end Keycloak's, then go to /login."""
        logout_url = oidc_client.build_logout_url(self._id_token)
        self._clear_session()
        return rx.redirect(logout_url)

    @rx.event
    def redirect_from_index(self):
        return rx.redirect("/crawlers" if self.is_authenticated else "/login")


async def get_session(state: rx.State) -> AuthState:
    """Return `AuthState`, its access token refreshed if about to expire.

    Every handler that calls the API gets the token through this, so a
    5-minute access token never reaches the API expired. A refused
    refresh logs the user out: `token` is then empty, and the page's
    `on_load` sends them to /login.
    """
    auth = await state.get_state(AuthState)
    await auth.refresh_if_expiring()
    return auth

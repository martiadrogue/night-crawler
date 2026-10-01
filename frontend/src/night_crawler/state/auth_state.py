import reflex as rx

from night_crawler import api_client

_WEEK_SECONDS = 60 * 60 * 24 * 7


class AuthState(rx.State):
    """The logged-in session, kept in cookies for a week."""

    token: str = rx.Cookie("", name="night_crawler_token", max_age=_WEEK_SECONDS)
    email: str = rx.Cookie("", name="night_crawler_email", max_age=_WEEK_SECONDS)
    role: str = rx.Cookie("", name="night_crawler_role", max_age=_WEEK_SECONDS)
    error: str = ""
    is_loading: bool = False

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.token)

    @rx.event
    async def handle_login(self, form_data: dict):
        async for event in self._authenticate(api_client.login, form_data):
            yield event

    @rx.event
    async def handle_register(self, form_data: dict):
        async for event in self._authenticate(api_client.register, form_data):
            yield event

    async def _authenticate(self, call, form_data: dict):
        """Log in or register, keep the token, and go to the crawlers."""
        self.error = ""
        self.is_loading = True
        yield
        try:
            result = await call(form_data["email"], form_data["password"])
        except api_client.ApiError as exc:
            self.error = exc.message
            self.is_loading = False
            return
        self.token = result["access_token"]
        self.email = form_data["email"]
        self.role = result["role"]
        self.is_loading = False
        yield rx.redirect("/crawlers")

    @rx.event
    def logout(self):
        self.token = ""
        self.email = ""
        self.role = ""
        return rx.redirect("/login")

    @rx.event
    def redirect_from_index(self):
        return rx.redirect("/crawlers" if self.is_authenticated else "/login")

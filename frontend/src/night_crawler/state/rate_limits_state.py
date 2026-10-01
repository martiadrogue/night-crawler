import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState


class RateLimitsState(rx.State):
    """The reusable rate-limit rules; admins edit and delete them."""

    rate_limits: list[dict] = []  # noqa: RUF012 - Reflex state var
    error: str = ""

    form_open: bool = False
    editing_rate_limit_id: str = ""
    form_name: str = ""
    form_rate_limit_string: str = ""
    form_penalty_step_seconds: str = ""
    form_max_penalty_seconds: str = ""
    form_decay_after_successes: str = ""
    form_decay_step_seconds: str = ""
    form_error: str = ""

    deleting_rate_limit_id: str = ""

    @rx.event
    async def load_rate_limits(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            rate_limits = await api_client.list_rate_limits(auth.token)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.rate_limits = [
            {**rule, "penalty_text": forms.rate_limit_summary(rule)}
            for rule in rate_limits
        ]
        self.error = ""
        return None

    @rx.event
    def start_create(self):
        self._open_form({})

    @rx.event
    def start_edit(self, rate_limit: dict):
        self._open_form(rate_limit)

    def _open_form(self, rate_limit: dict) -> None:
        """Open the dialog on `rate_limit`, or empty to create one."""
        self.editing_rate_limit_id = rate_limit.get("id", "")
        self.form_name = rate_limit.get("name") or ""
        self.form_rate_limit_string = rate_limit.get("rate_limit_string", "")
        self.form_penalty_step_seconds = forms.optional_text(
            rate_limit.get("penalty_step_seconds")
        )
        self.form_max_penalty_seconds = forms.optional_text(
            rate_limit.get("max_penalty_seconds")
        )
        self.form_decay_after_successes = forms.optional_text(
            rate_limit.get("decay_after_successes")
        )
        self.form_decay_step_seconds = forms.optional_text(
            rate_limit.get("decay_step_seconds")
        )
        self.form_error = ""
        self.form_open = True

    @rx.event
    def set_form_open(self, is_open: bool):
        self.form_open = is_open

    @rx.event
    async def submit_form(self, form_data: dict):
        payload, error = forms.build_rate_limit_payload(form_data)
        if error:
            self.form_error = error
            return None
        auth = await self.get_state(AuthState)
        try:
            if self.editing_rate_limit_id:
                await api_client.update_rate_limit(
                    auth.token, self.editing_rate_limit_id, payload
                )
            else:
                await api_client.create_rate_limit(auth.token, payload)
        except api_client.ApiError as exc:
            self.form_error = exc.message
            return None
        self.form_open = False
        return RateLimitsState.load_rate_limits

    @rx.event
    def start_delete(self, rate_limit_id: str):
        self.deleting_rate_limit_id = rate_limit_id

    @rx.event
    def set_delete_open(self, is_open: bool):
        if not is_open:
            self.deleting_rate_limit_id = ""

    @rx.event
    async def confirm_delete(self):
        rate_limit_id, self.deleting_rate_limit_id = self.deleting_rate_limit_id, ""
        auth = await self.get_state(AuthState)
        try:
            await api_client.delete_rate_limit(auth.token, rate_limit_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return RateLimitsState.load_rate_limits

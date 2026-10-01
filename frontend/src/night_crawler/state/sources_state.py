import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState


class SourcesState(rx.State):
    """The Sources crawled data comes from; admins rename and delete."""

    sources: list[dict] = []  # noqa: RUF012 - Reflex state var
    error: str = ""

    form_open: bool = False
    editing_source_id: str = ""
    form_name: str = ""
    form_url: str = ""
    form_error: str = ""

    @rx.event
    async def load_sources(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            self.sources = await api_client.list_sources(auth.token)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.error = ""
        return None

    @rx.event
    def start_create(self):
        self._open_form({})

    @rx.event
    def start_edit(self, source: dict):
        self._open_form(source)

    def _open_form(self, source: dict) -> None:
        """Open the dialog on `source`, or empty to create one."""
        self.editing_source_id = source.get("id", "")
        self.form_name = source.get("name", "")
        self.form_url = source.get("url") or ""
        self.form_error = ""
        self.form_open = True

    @rx.event
    def set_form_open(self, is_open: bool):
        self.form_open = is_open

    @rx.event
    async def submit_form(self, form_data: dict):
        payload = {
            "name": form_data.get("name", "").strip(),
            "url": forms.blank_to_none(form_data.get("url")),
        }
        auth = await self.get_state(AuthState)
        try:
            if self.editing_source_id:
                await api_client.update_source(
                    auth.token, self.editing_source_id, payload
                )
            else:
                await api_client.create_source(auth.token, payload)
        except api_client.ApiError as exc:
            self.form_error = exc.message
            return None
        self.form_open = False
        return SourcesState.load_sources

    @rx.event
    async def delete_source(self, source_id: str):
        auth = await self.get_state(AuthState)
        try:
            await api_client.delete_source(auth.token, source_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return SourcesState.load_sources

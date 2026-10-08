import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import get_session


class UsersState(rx.State):
    """User accounts, a page at a time; the API lets only admins in."""

    users: list[dict] = []  # noqa: RUF012 - Reflex state var
    offset: int = 0
    has_more: bool = False
    error: str = ""

    form_open: bool = False
    editing_user_id: str = ""
    form_email: str = ""
    form_role: str = "user"
    form_error: str = ""

    disabling_user_id: str = ""
    disabling_email: str = ""

    @rx.event
    async def load_users(self):
        auth = await get_session(self)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            page = await api_client.list_users(auth.token, self.offset)
        except api_client.ApiError as exc:
            self.users = []
            self.has_more = False
            self.error = exc.message
            return None
        self.users = page["items"]
        self.has_more = page["has_more"]
        self.error = ""
        return None

    @rx.event
    def next_page(self):
        self.offset += api_client.USERS_PAGE_SIZE
        return UsersState.load_users

    @rx.event
    def previous_page(self):
        self.offset = max(self.offset - api_client.USERS_PAGE_SIZE, 0)
        return UsersState.load_users

    @rx.event
    def start_create(self):
        self._open_form({})

    @rx.event
    def start_edit(self, user: dict):
        self._open_form(user)

    def _open_form(self, user: dict) -> None:
        """Open the dialog on `user`, or empty to create one."""
        self.editing_user_id = user.get("id", "")
        self.form_email = user.get("email", "")
        self.form_role = user.get("role", "user")
        self.form_error = ""
        self.form_open = True

    @rx.event
    def set_form_open(self, is_open: bool):
        self.form_open = is_open

    @rx.event
    def set_form_role(self, role: str):
        self.form_role = role

    @rx.event
    async def submit_form(self, form_data: dict):
        payload, error = forms.build_user_payload(
            form_data, self.form_role, is_new=not self.editing_user_id
        )
        if error:
            self.form_error = error
            return None
        auth = await get_session(self)
        try:
            if self.editing_user_id:
                await api_client.update_user(auth.token, self.editing_user_id, payload)
            else:
                await api_client.create_user(auth.token, payload)
        except api_client.ApiError as exc:
            self.form_error = exc.message
            return None
        self.form_open = False
        return UsersState.load_users

    @rx.event
    def start_disable(self, user: dict):
        self.disabling_user_id = user["id"]
        self.disabling_email = user["email"]

    @rx.event
    def set_disable_open(self, is_open: bool):
        if not is_open:
            self.disabling_user_id = ""

    @rx.event
    async def confirm_disable(self):
        user_id, self.disabling_user_id = self.disabling_user_id, ""
        auth = await get_session(self)
        try:
            await api_client.disable_user(auth.token, user_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return UsersState.load_users

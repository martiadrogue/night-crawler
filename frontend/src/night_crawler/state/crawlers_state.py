import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState

DEFAULT_FIELDS_TEXT = "item_id, name"


class CrawlersState(rx.State):
    """The crawlers list, and the dialog creating or editing one."""

    crawlers: list[dict] = []  # noqa: RUF012 - Reflex state var
    source_options: list[dict] = []  # noqa: RUF012 - Reflex state var
    dataset_options: list[dict] = []  # noqa: RUF012 - Reflex state var
    error: str = ""
    is_loading: bool = False

    form_open: bool = False
    editing_crawler_id: str = ""
    form_title: str = ""
    form_source_id: str = ""
    form_dataset_id: str = ""
    form_queue: str = forms.CRAWLER_QUEUES[0]
    form_fields: str = DEFAULT_FIELDS_TEXT
    form_schedule: str = ""
    form_error: str = ""

    deleting_crawler_id: str = ""

    context_open: bool = False
    context_crawler_id: str = ""
    context_crawler_title: str = ""
    context_rows: list[dict] = []  # noqa: RUF012 - Reflex state var
    context_error: str = ""
    context_editing_key: str = ""
    context_form_value: str = ""
    context_form_version: int = 0

    @rx.event
    async def load_crawlers(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            yield rx.redirect("/login")
            return
        self.is_loading = True
        yield
        try:
            crawlers = await api_client.list_crawlers(auth.token)
            sources = await api_client.list_sources(auth.token)
            datasets = await api_client.list_datasets(auth.token)
            self.error = ""
        except api_client.ApiError as exc:
            self.error = exc.message
            self.is_loading = False
            return
        source_names = forms.names_by_id(sources)
        dataset_names = forms.names_by_id(datasets)
        self.crawlers = [
            {
                **crawler,
                "source_name": source_names.get(crawler["source_id"], "?"),
                "dataset_name": dataset_names.get(crawler["dataset_id"], "?"),
            }
            for crawler in crawlers
        ]
        self.source_options = forms.id_options(sources, "name")
        self.dataset_options = forms.id_options(datasets, "name")
        self.is_loading = False

    @rx.event
    def start_create(self):
        self.editing_crawler_id = ""
        self.form_title = ""
        self.form_source_id = (
            self.source_options[0]["value"] if self.source_options else ""
        )
        self.form_dataset_id = (
            self.dataset_options[0]["value"] if self.dataset_options else ""
        )
        self.form_queue = forms.CRAWLER_QUEUES[0]
        self.form_fields = DEFAULT_FIELDS_TEXT
        self.form_schedule = ""
        self.form_error = ""
        self.form_open = True

    @rx.event
    def start_edit(self, crawler: dict):
        self.editing_crawler_id = crawler["id"]
        self.form_title = crawler["title"]
        self.form_source_id = crawler["source_id"]
        self.form_dataset_id = crawler["dataset_id"]
        self.form_queue = crawler["queue"]
        self.form_fields = ", ".join(crawler.get("fields", []))
        self.form_schedule = crawler.get("schedule") or ""
        self.form_error = ""
        self.form_open = True

    @rx.event
    def set_form_open(self, is_open: bool):
        self.form_open = is_open

    @rx.event
    def set_form_source_id(self, source_id: str):
        self.form_source_id = source_id

    @rx.event
    def set_form_dataset_id(self, dataset_id: str):
        self.form_dataset_id = dataset_id

    @rx.event
    def set_form_queue(self, queue: str):
        self.form_queue = queue

    @rx.event
    async def submit_form(self, form_data: dict):
        payload, error = forms.build_crawler_payload(
            form_data,
            {
                "source_id": self.form_source_id,
                "dataset_id": self.form_dataset_id,
                "queue": self.form_queue,
            },
        )
        if error:
            self.form_error = error
            return
        auth = await self.get_state(AuthState)
        try:
            if self.editing_crawler_id:
                await api_client.update_crawler(
                    auth.token, self.editing_crawler_id, payload
                )
            else:
                await api_client.create_crawler(auth.token, payload)
        except api_client.ApiError as exc:
            self.form_error = exc.message
            return
        self.form_open = False
        return CrawlersState.load_crawlers

    @rx.event
    async def open_instructions(self, crawler_id: str):
        """Open the editor on the draft, else on the published version.

        When every version is archived, open a new draft; the API clones
        it from the latest archived version, or starts it empty.
        """
        auth = await self.get_state(AuthState)
        try:
            version_id = (
                forms.editable_version_id(
                    await api_client.list_versions(auth.token, crawler_id)
                )
                or (await api_client.create_draft(auth.token, crawler_id))["id"]
            )
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.error = ""
        return rx.redirect(f"/versions/{version_id}")

    @rx.event
    def start_delete(self, crawler_id: str):
        self.deleting_crawler_id = crawler_id

    @rx.event
    def set_delete_open(self, is_open: bool):
        if not is_open:
            self.deleting_crawler_id = ""

    @rx.event
    async def confirm_delete(self):
        crawler_id, self.deleting_crawler_id = self.deleting_crawler_id, ""
        auth = await self.get_state(AuthState)
        try:
            await api_client.delete_crawler(auth.token, crawler_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return
        return CrawlersState.load_crawlers

    @rx.event
    async def open_context(self, crawler: dict):
        """Open the Context dialog on a crawler's latest run."""
        self.context_crawler_id = crawler["id"]
        self.context_crawler_title = crawler["title"]
        self._reset_context_form()
        self.context_open = True
        await self._load_context()

    @rx.event
    def set_context_open(self, is_open: bool):
        self.context_open = is_open

    @rx.event
    def start_context_add(self):
        self._reset_context_form()

    @rx.event
    def start_context_edit(self, row: dict):
        """Edit a key; a secret's value is never put back on screen."""
        self.context_editing_key = row["key"]
        self.context_form_value = "" if row["is_secret"] else row["value_text"]
        self.context_form_version += 1

    @rx.event
    async def submit_context(self, form_data: dict):
        key = self.context_editing_key or form_data.get("key", "").strip()
        if not key:
            self.context_error = "Name the key, e.g. parish[] or google_api_key."
            return
        value = forms.parse_context_value(form_data.get("value", ""))
        auth = await self.get_state(AuthState)
        try:
            await api_client.set_context_value(
                auth.token, self.context_crawler_id, key, value
            )
        except api_client.ApiError as exc:
            self.context_error = exc.message
            return
        self._reset_context_form()
        await self._load_context()

    @rx.event
    async def delete_context_key(self, key: str):
        auth = await self.get_state(AuthState)
        try:
            await api_client.delete_context_value(
                auth.token, self.context_crawler_id, key
            )
        except api_client.ApiError as exc:
            self.context_error = exc.message
            return
        self._reset_context_form()
        await self._load_context()

    async def _load_context(self) -> None:
        """Fetch the Context; a crawler that never ran has none yet."""
        auth = await self.get_state(AuthState)
        try:
            context = await api_client.get_context(auth.token, self.context_crawler_id)
        except api_client.ApiError as exc:
            self.context_rows = []
            self.context_error = exc.message
            return
        self.context_rows = forms.context_rows(context["values"])
        self.context_error = ""

    def _reset_context_form(self) -> None:
        """Go back to adding a new key, with empty inputs."""
        self.context_editing_key = ""
        self.context_form_value = ""
        self.context_form_version += 1

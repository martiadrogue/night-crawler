import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState


class CrawlerDetailState(rx.State):
    """One crawler and its versions: new draft, publish, delete.

    A published version is only archived by publishing a draft over it.
    """

    crawler: dict = {}  # noqa: RUF012 - Reflex state var
    source_name: str = ""
    dataset_name: str = ""
    versions: list[dict] = []  # noqa: RUF012 - Reflex state var
    error: str = ""
    deleting_version_id: str = ""

    @rx.var
    def has_draft(self) -> bool:
        return any("draft" == version["status"] for version in self.versions)

    @rx.event
    async def load_crawler(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            self.crawler = await api_client.get_crawler(auth.token, self.crawler_id)
            versions = await api_client.list_versions(auth.token, self.crawler_id)
            sources = await api_client.list_sources(auth.token)
            datasets = await api_client.list_datasets(auth.token)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.source_name = forms.names_by_id(sources).get(
            self.crawler["source_id"], "?"
        )
        self.dataset_name = forms.names_by_id(datasets).get(
            self.crawler["dataset_id"], "?"
        )
        self.versions = sorted(
            versions, key=lambda version: version["created_at"], reverse=True
        )
        self.error = ""
        return None

    @rx.event
    async def create_draft(self):
        auth = await self.get_state(AuthState)
        try:
            draft = await api_client.create_draft(auth.token, self.crawler_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return rx.redirect(f"/versions/{draft['id']}")

    @rx.event
    async def publish(self, version_id: str):
        auth = await self.get_state(AuthState)
        await self._call(api_client.publish_version, auth.token, version_id)
        return CrawlerDetailState.load_crawler

    async def _call(self, action, token: str, version_id: str) -> None:
        """Run a version transition, keeping any error to show."""
        try:
            await action(token, self.crawler_id, version_id)
            self.error = ""
        except api_client.ApiError as exc:
            self.error = exc.message

    @rx.event
    def start_delete(self, version_id: str):
        self.deleting_version_id = version_id

    @rx.event
    def set_delete_open(self, is_open: bool):
        if not is_open:
            self.deleting_version_id = ""

    @rx.event
    async def confirm_delete(self):
        version_id, self.deleting_version_id = self.deleting_version_id, ""
        auth = await self.get_state(AuthState)
        try:
            await api_client.delete_version(auth.token, version_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        return CrawlerDetailState.load_crawler

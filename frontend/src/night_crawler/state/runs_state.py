import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import AuthState

PAGE_SIZE = 50


class RunsState(rx.State):
    """Every crawler's runs: pending, running, or ended, with stats."""

    runs: list[dict] = []  # noqa: RUF012 - Reflex state var
    summary: dict[str, str] = forms.runs_summary([])
    status_filter: str = forms.ALL_STATUSES
    parsing_filter: str = forms.ALL_STATUSES
    queue_filter: str = forms.ALL_STATUSES
    title_filter: str = ""
    offset: int = 0
    has_more: bool = False
    error: str = ""

    @rx.event
    async def load_runs(self):
        auth = await self.get_state(AuthState)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        params = forms.execution_params(self._filters(), self.offset)
        try:
            page = await api_client.list_executions(auth.token, params)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.runs = [_display(run) for run in page["items"]]
        self.summary = forms.runs_summary(page["items"])
        self.has_more = page["has_more"]
        self.error = ""
        return None

    def _filters(self) -> dict:
        """Return the filters as `forms.execution_params` reads them."""
        return {
            "status": self.status_filter,
            "parsing_status": self.parsing_filter,
            "queue": self.queue_filter,
            "crawler_title": self.title_filter,
        }

    @rx.event
    def set_status_filter(self, status: str):
        self.status_filter = status
        return self._reload_first_page()

    @rx.event
    def set_parsing_filter(self, parsing_status: str):
        self.parsing_filter = parsing_status
        return self._reload_first_page()

    @rx.event
    def set_queue_filter(self, queue: str):
        self.queue_filter = queue
        return self._reload_first_page()

    @rx.event
    def set_title_filter(self, title: str):
        self.title_filter = title
        return self._reload_first_page()

    def _reload_first_page(self):
        """Go back to the first page and reload with the new filters."""
        self.offset = 0
        return RunsState.load_runs

    @rx.event
    def next_page(self):
        self.offset += PAGE_SIZE
        return RunsState.load_runs

    @rx.event
    def previous_page(self):
        self.offset = max(self.offset - PAGE_SIZE, 0)
        return RunsState.load_runs

    @rx.event
    async def download_csv(self, execution_id: str):
        """Hand the browser the run's dataset CSV as a file."""
        auth = await self.get_state(AuthState)
        try:
            csv_text = await api_client.download_execution_csv(auth.token, execution_id)
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.error = ""
        # Bytes travel base64-encoded, so the CSV's CRLF endings survive.
        return rx.download(data=csv_text.encode(), filename=f"{execution_id}.csv")

    @rx.var
    def is_filtered(self) -> bool:
        """Tell whether a filter is set: the page is then capped, not paged."""
        params = forms.execution_params(self._filters(), 0)
        return params["offset"] is None


def _display(run: dict) -> dict:
    """Return a run with the texts its table row shows."""
    return {
        **run,
        "started_text": forms.short_time(run["started_at"]),
        "waited_text": forms.format_duration(
            forms.seconds_between(run["created_at"], run["started_at"])
        ),
        "ran_text": forms.format_duration(
            forms.seconds_between(run["started_at"], run["finished_at"])
        ),
        "has_csv": forms.has_csv(run),
        "requests_text": (
            f"{run['metrics']['request_count']} / {run['metrics']['error_count']}"
        ),
    }

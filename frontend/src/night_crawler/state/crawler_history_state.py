from datetime import UTC, datetime

import reflex as rx

from night_crawler import api_client, forms
from night_crawler.state.auth_state import get_session

HISTORY_DAYS = 30


class CrawlerHistoryState(rx.State):
    """One crawler's last 30 days of runs, test runs excluded.

    The window loads once; filtering and paging stay in memory.
    """

    crawler: dict = {}  # noqa: RUF012 - Reflex state var
    rows: list[dict] = []  # noqa: RUF012 - Reflex state var
    counts: dict[str, int] = {}  # noqa: RUF012 - Reflex state var
    is_truncated: bool = False
    summary: dict[str, str] = {}  # noqa: RUF012 - Reflex state var
    outcome_filter: str = forms.ALL_OUTCOMES
    page: int = 0
    error: str = ""

    @rx.event
    async def load_history(self):
        auth = await get_session(self)
        if not auth.is_authenticated:
            return rx.redirect("/login")
        try:
            crawler = await api_client.get_crawler(auth.token, self.crawler_id)
            history = await api_client.get_execution_history(
                auth.token, self.crawler_id, days=HISTORY_DAYS
            )
            summary = await api_client.get_execution_summary(
                auth.token, self.crawler_id
            )
        except api_client.ApiError as exc:
            self.error = exc.message
            return None
        self.crawler = crawler
        self.rows = forms.history_rows(history["runs"])
        self.counts = history["counts"]
        self.is_truncated = history["is_truncated"]
        # Naive UTC, like the API's timestamps.
        now = datetime.now(UTC).replace(tzinfo=None)
        self.summary = forms.history_summary(summary, now)
        self.page = 0
        self.error = ""
        return None

    @rx.event
    def set_outcome_filter(self, outcome: str):
        self.outcome_filter = outcome
        self.page = 0

    @rx.event
    def next_page(self):
        self.page += 1

    @rx.event
    def previous_page(self):
        self.page = max(self.page - 1, 0)

    @rx.event
    def export_csv(self):
        """Hand the browser the filtered window's runs as a CSV file."""
        return rx.download(
            data=forms.build_history_csv(self._filtered()).encode(),
            filename=forms.history_csv_filename(self.crawler.get("title", "")),
        )

    def _filtered(self) -> list[dict]:
        """Return the window's rows under the selected outcome."""
        return forms.filter_runs_by_outcome(self.rows, self.outcome_filter)

    @rx.var
    def visible_rows(self) -> list[dict]:
        return forms.page_slice(self._filtered(), self.page)

    @rx.var
    def showing_text(self) -> str:
        return forms.showing_text(self.page, len(self._filtered()))

    @rx.var
    def has_next_page(self) -> bool:
        shown = (self.page + 1) * forms.HISTORY_TABLE_PAGE_SIZE
        return shown < len(self._filtered())

    @rx.var
    def chip_options(self) -> list[dict]:
        return forms.chip_options(self.counts, self.outcome_filter)

    @rx.var
    def chart_points(self) -> list[dict]:
        return forms.chart_points(self.rows, self.outcome_filter)

    @rx.var
    def chart_floor(self) -> int:
        return forms.chart_floor(self.chart_points)

    @rx.var
    def chart_series(self) -> dict[str, list[dict]]:
        return forms.chart_series(self.chart_points, self.chart_floor)

    @rx.var
    def chart_x_domain(self) -> list[float]:
        """Half a step of room each side, so end points aren't clipped."""
        return [-0.5, len(self.chart_points) - 0.5]

    @rx.var
    def chart_first_date(self) -> str:
        points = self.chart_points
        return points[0]["date_label"] if points else ""

    @rx.var
    def chart_last_date(self) -> str:
        points = self.chart_points
        return points[-1]["date_label"] if points else ""

    @rx.var
    def schedule_text(self) -> str:
        return forms.schedule_text(self.crawler.get("schedule"))

import reflex as rx

from night_crawler import forms
from night_crawler.components.fields import choice, labelled
from night_crawler.components.nav import error_callout, page_shell, status_badge
from night_crawler.state.runs_state import RunsState


def _stat_card(label: str, value: rx.Var, hint: str) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="2", weight="medium", color_scheme="gray"),
            rx.heading(value, size="7"),
            rx.text(hint, size="1", color_scheme="gray"),
            spacing="1",
        ),
        min_width="12em",
    )


def _stats() -> rx.Component:
    return rx.hstack(
        _stat_card("Succeeded", RunsState.summary["success_rate"], "of the runs shown"),
        _stat_card("Failed", RunsState.summary["failed"], "runs shown"),
        _stat_card(
            "Average wait",
            RunsState.summary["avg_wait"],
            "in the queue, runs shown that started",
        ),
        spacing="3",
        wrap="wrap",
    )


def _filters() -> rx.Component:
    """Every filter and Refresh on one line, under the cards."""
    return rx.hstack(
        labelled(
            "Crawler name",
            rx.debounce_input(
                rx.input(
                    value=RunsState.title_filter,
                    on_change=RunsState.set_title_filter,
                    placeholder="Part of the title",
                    width="100%",
                ),
                debounce_timeout=400,
            ),
        ),
        labelled(
            "Queue",
            choice(
                forms.QUEUE_FILTERS, RunsState.queue_filter, RunsState.set_queue_filter
            ),
        ),
        labelled(
            "Status",
            choice(
                forms.EXECUTION_STATUS_FILTERS,
                RunsState.status_filter,
                RunsState.set_status_filter,
            ),
        ),
        labelled(
            "Parsing status",
            choice(
                forms.PARSING_STATUS_FILTERS,
                RunsState.parsing_filter,
                RunsState.set_parsing_filter,
            ),
        ),
        rx.button("Refresh", on_click=RunsState.load_runs, variant="soft"),
        spacing="3",
        align="end",
        width="100%",
    )


def _row(run: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.code(run["id"], size="1", variant="ghost", white_space="nowrap")
        ),
        rx.table.cell(
            rx.link(
                rx.cond(run["crawler_title"], run["crawler_title"], "(deleted)"),
                href="/crawlers/" + run["crawler_id"].to(str),
            )
        ),
        rx.table.cell(status_badge(run["status"])),
        rx.table.cell(status_badge(run["parsing_status"])),
        rx.table.cell(run["queue"]),
        rx.table.cell(rx.text(run["waited_text"], size="1")),
        rx.table.cell(rx.text(run["started_text"], size="1")),
        rx.table.cell(rx.text(run["ran_text"], size="1")),
        rx.table.cell(rx.text(run["requests_text"], size="1")),
        rx.table.cell(
            rx.button(
                "CSV",
                size="1",
                variant="soft",
                disabled=~run["has_csv"].to(bool),
                on_click=RunsState.download_csv(run["id"]),
            )
        ),
    )


def _pager() -> rx.Component:
    return rx.cond(
        RunsState.is_filtered,
        rx.cond(
            RunsState.has_more,
            rx.text(
                "Showing the 50 newest matching runs.", size="2", color_scheme="gray"
            ),
        ),
        rx.hstack(
            rx.button(
                "Previous",
                on_click=RunsState.previous_page,
                variant="soft",
                disabled=RunsState.offset == 0,
            ),
            rx.button(
                "Next",
                on_click=RunsState.next_page,
                variant="soft",
                disabled=~RunsState.has_more,
            ),
            spacing="2",
        ),
    )


@rx.page(
    route="/runs",
    title="Runs · Night Crawler",
    on_load=RunsState.load_runs,
)
def runs() -> rx.Component:
    return page_shell(
        rx.vstack(
            rx.heading("Runs", size="7"),
            rx.text(
                "Every crawler's runs, newest first: pending (waiting for a "
                "worker), running, or ended, with the status of parsing their "
                "harvest into the dataset CSV. Test runs are included, on the "
                "testing queue. The cards cover the runs shown below; Waited is "
                "the time in the queue before a worker started it.",
                size="2",
                color_scheme="gray",
            ),
            error_callout(RunsState.error),
            _stats(),
            _filters(),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Execution ID"),
                        rx.table.column_header_cell("Crawler"),
                        rx.table.column_header_cell("Status"),
                        rx.table.column_header_cell("Parsing"),
                        rx.table.column_header_cell("Queue"),
                        rx.table.column_header_cell("Waited"),
                        rx.table.column_header_cell("Started"),
                        rx.table.column_header_cell("Ran for"),
                        rx.table.column_header_cell("Requests / errors"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(RunsState.runs, _row)),
                width="100%",
            ),
            _pager(),
            spacing="4",
            width="100%",
        )
    )

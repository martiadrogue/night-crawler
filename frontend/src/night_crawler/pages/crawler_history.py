import reflex as rx
from reflex.vars import FunctionStringVar

from night_crawler import forms
from night_crawler.components.nav import breadcrumbs, error_callout, page_shell
from night_crawler.state.crawler_history_state import CrawlerHistoryState

# Recharts formats a scatter tooltip per axis; each point carries its
# own texts, so a "no data" run never shows the floor it is drawn at.
TOOLTIP_FORMATTER = FunctionStringVar.create(
    '(value, name, item) => name === "Run" '
    '? [item.payload.label, "Run"] '
    ': [item.payload.completeness_text, "Completeness"]'
)

OUTCOME_COLORS = (
    ("success", "var(--green-9)"),
    ("verification_failed", "var(--amber-9)"),
    ("failed", "var(--red-9)"),
)


def _stat(
    label: str, value: rx.Var, unit: rx.Var, color_scheme: str | None = None
) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="1", weight="medium", color_scheme="gray"),
            rx.hstack(
                rx.heading(value, size="7", color_scheme=color_scheme),
                rx.text(unit, size="2", color_scheme="gray"),
                align="baseline",
                spacing="2",
            ),
            spacing="1",
        ),
        flex="1",
        min_width="12em",
    )


def _stats() -> rx.Component:
    summary = CrawlerHistoryState.summary
    return rx.hstack(
        _stat("Current streak", summary["streak"], summary["streak_unit"], "green"),
        _stat(
            "Last verification failure",
            summary["verification_failure"],
            summary["verification_failure_unit"],
            "amber",
        ),
        _stat("Last failed run", summary["failure"], summary["failure_unit"], "red"),
        _stat("Success rate", summary["success_rate"], summary["success_hint"]),
        spacing="3",
        wrap="wrap",
        width="100%",
    )


def _outcome_badge(run: rx.Var) -> rx.Component:
    outcome = run["outcome"]
    return rx.badge(
        rx.match(
            outcome,
            ("success", rx.icon("check", size=12)),
            ("verification_failed", rx.icon("circle-alert", size=12)),
            ("failed", rx.icon("x", size=12)),
            rx.icon("loader", size=12),
        ),
        run["outcome_label"],
        color_scheme=rx.match(
            outcome,
            ("success", "green"),
            ("verification_failed", "amber"),
            ("failed", "red"),
            "blue",
        ),
        white_space="nowrap",
    )


def _row(run: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.hstack(
                rx.text(run["date_text"], size="2", weight="medium"),
                rx.cond(
                    run["is_latest"].to(bool),
                    rx.badge("Latest", size="1", variant="soft"),
                ),
                spacing="2",
                align="center",
                white_space="nowrap",
            )
        ),
        rx.table.cell(rx.code(run["start_text"], variant="ghost")),
        rx.table.cell(rx.code(run["end_text"], variant="ghost")),
        rx.table.cell(rx.code(run["duration_text"], variant="ghost")),
        rx.table.cell(_outcome_badge(run)),
        rx.table.cell(
            rx.code(run["records_text"], variant="ghost"), text_align="right"
        ),
        rx.table.cell(
            rx.code(
                run["completeness_text"],
                variant="ghost",
                color_scheme=rx.cond(
                    "verification_failed" == run["outcome"], "amber", "gray"
                ),
            ),
            text_align="right",
        ),
    )


def _table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Execution date"),
                rx.table.column_header_cell("Start time (UTC)"),
                rx.table.column_header_cell("End time (UTC)"),
                rx.table.column_header_cell("Duration"),
                rx.table.column_header_cell("Status"),
                rx.table.column_header_cell("Records extracted", text_align="right"),
                rx.table.column_header_cell("Completeness rate", text_align="right"),
            )
        ),
        rx.table.body(rx.foreach(CrawlerHistoryState.visible_rows, _row)),
        width="100%",
    )


def _footer() -> rx.Component:
    return rx.hstack(
        rx.text(CrawlerHistoryState.showing_text, size="2", color_scheme="gray"),
        rx.spacer(),
        rx.button(
            "Previous",
            on_click=CrawlerHistoryState.previous_page,
            variant="soft",
            disabled=CrawlerHistoryState.page == 0,
        ),
        rx.button(
            "Next",
            on_click=CrawlerHistoryState.next_page,
            variant="soft",
            disabled=~CrawlerHistoryState.has_next_page,
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _chip(chip: rx.Var) -> rx.Component:
    return rx.button(
        rx.cond(
            forms.ALL_OUTCOMES != chip["value"],
            rx.box(
                width="8px",
                height="8px",
                border_radius="50%",
                background=rx.match(chip["value"], *OUTCOME_COLORS, "var(--gray-9)"),
            ),
        ),
        chip["label"],
        rx.text(chip["count"], color_scheme="gray", size="1"),
        size="1",
        radius="full",
        color_scheme="gray",
        variant=rx.cond(chip["is_selected"].to(bool), "solid", "outline"),
        on_click=CrawlerHistoryState.set_outcome_filter(chip["value"].to(str)),
    )


def _series(key: str, fill: str, shape: str, opacity: float) -> rx.Component:
    return rx.recharts.scatter(
        rx.recharts.error_bar(
            data_key="stem",
            direction="y",
            width=0,
            stroke="var(--gray-6)",
            stroke_width=1,
            custom_attrs={"strokeOpacity": opacity},
        ),
        data=CrawlerHistoryState.chart_series[key],
        fill=fill,
        shape=shape,
        custom_attrs={"fillOpacity": opacity},
        is_animation_active=False,
    )


def _chart() -> rx.Component:
    return rx.recharts.scatter_chart(
        *(_series(*series) for series in forms.CHART_SERIES),
        rx.recharts.x_axis(
            data_key="x",
            name="Run",
            type_="number",
            domain=CrawlerHistoryState.chart_x_domain,
            tick=False,
            tick_line=False,
            height=4,
        ),
        rx.recharts.y_axis(
            data_key="y",
            name="Completeness",
            domain=[CrawlerHistoryState.chart_floor, 100],
            allow_data_overflow=True,
            tick_count=3,
            unit="%",
            width=48,
        ),
        rx.recharts.graphing_tooltip(custom_attrs={"formatter": TOOLTIP_FORMATTER}),
        height=180,
        width="100%",
        margin={"top": 8, "right": 8, "bottom": 0, "left": 0},
    )


def _chart_card() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("Runs · last 30 days", size="4"),
            rx.spacer(),
            rx.foreach(CrawlerHistoryState.chip_options, _chip),
            spacing="2",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            CrawlerHistoryState.chart_points,
            rx.vstack(
                _chart(),
                rx.hstack(
                    rx.text(CrawlerHistoryState.chart_first_date, size="1"),
                    rx.spacer(),
                    rx.text(
                        "Completeness per run · × no data",
                        size="1",
                        color_scheme="gray",
                    ),
                    rx.spacer(),
                    rx.text(CrawlerHistoryState.chart_last_date, size="1"),
                    width="100%",
                    padding_left="48px",
                ),
                spacing="1",
                width="100%",
            ),
            rx.text(
                "No run has ended in the last 30 days.",
                size="2",
                color_scheme="gray",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _header() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("Execution history", size="7"),
            rx.text(CrawlerHistoryState.schedule_text, size="2", color_scheme="gray"),
            spacing="1",
        ),
        rx.spacer(),
        rx.button("Refresh", on_click=CrawlerHistoryState.load_history, variant="soft"),
        rx.button(
            "Export CSV", on_click=CrawlerHistoryState.export_csv, variant="outline"
        ),
        spacing="2",
        align="center",
        width="100%",
    )


@rx.page(
    route="/crawlers/[crawler_id]/history",
    title="Execution history · Night Crawler",
    on_load=CrawlerHistoryState.load_history,
)
def crawler_history() -> rx.Component:
    return page_shell(
        rx.vstack(
            breadcrumbs(
                [
                    ("Crawlers", "/crawlers"),
                    (
                        CrawlerHistoryState.crawler["title"].to(str),
                        "/crawlers/" + CrawlerHistoryState.crawler_id,
                    ),
                ]
            ),
            _header(),
            error_callout(CrawlerHistoryState.error),
            _stats(),
            rx.card(
                rx.vstack(
                    _chart_card(),
                    rx.separator(size="4"),
                    _table(),
                    _footer(),
                    rx.cond(
                        CrawlerHistoryState.is_truncated,
                        rx.text(
                            "Only the newest 1,000 runs of the last 30 days are "
                            "shown; the counts still cover them all.",
                            size="1",
                            color_scheme="gray",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
                width="100%",
            ),
            rx.text(
                "Runs of the last 30 days, newest first, without test runs. "
                "Times are UTC. Success: the run succeeded and its rows passed "
                "validation; Verification failed: it succeeded but its rows "
                "did not; cancelled runs count as failed. Completeness rate: "
                "the share of filled cells in the rows kept.",
                size="1",
                color_scheme="gray",
            ),
            spacing="4",
            width="100%",
        )
    )

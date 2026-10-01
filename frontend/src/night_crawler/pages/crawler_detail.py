import reflex as rx

from night_crawler.components.nav import (
    breadcrumbs,
    error_callout,
    page_shell,
    status_badge,
)
from night_crawler.state.crawler_detail_state import CrawlerDetailState


def _actions(version: rx.Var) -> rx.Component:
    status = version["status"]
    return rx.hstack(
        rx.link(
            rx.button(
                rx.cond("draft" == status, "Edit", "View"), size="1", variant="soft"
            ),
            href="/versions/" + version["id"].to(str),
        ),
        rx.cond(
            "draft" == status,
            rx.button(
                "Publish",
                size="1",
                color_scheme="green",
                on_click=CrawlerDetailState.publish(version["id"]),
            ),
        ),
        rx.cond(
            "published" != status,
            rx.button(
                "Delete",
                size="1",
                color_scheme="red",
                variant="soft",
                on_click=CrawlerDetailState.start_delete(version["id"]),
            ),
        ),
        spacing="2",
    )


def _row(version: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(status_badge(version["status"])),
        rx.table.cell(version["created_at"].to(str)),
        rx.table.cell(
            rx.cond(version["published_at"], version["published_at"].to(str), "—")
        ),
        rx.table.cell(_actions(version)),
    )


def _delete_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete version"),
            rx.alert_dialog.description(
                "This deletes the version with its templates, selectors, and aids."
            ),
            rx.hstack(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft")),
                rx.alert_dialog.action(
                    rx.button(
                        "Delete",
                        color_scheme="red",
                        on_click=CrawlerDetailState.confirm_delete,
                    )
                ),
                justify="end",
            ),
        ),
        open=CrawlerDetailState.deleting_version_id != "",
        on_open_change=CrawlerDetailState.set_delete_open,
    )


@rx.page(
    route="/crawlers/[crawler_id]",
    title="Crawler · Night Crawler",
    on_load=CrawlerDetailState.load_crawler,
)
def crawler_detail() -> rx.Component:
    crawler = CrawlerDetailState.crawler
    return page_shell(
        rx.vstack(
            breadcrumbs([("Crawlers", "/crawlers")]),
            rx.hstack(
                rx.heading(crawler["title"].to(str), size="7"),
                rx.spacer(),
                rx.button(
                    "New draft",
                    on_click=CrawlerDetailState.create_draft,
                    disabled=CrawlerDetailState.has_draft,
                ),
                width="100%",
                align="center",
            ),
            rx.text(
                CrawlerDetailState.source_name,
                " · ",
                CrawlerDetailState.dataset_name,
                " · schedule ",
                rx.code(
                    rx.cond(crawler["schedule"], crawler["schedule"].to(str), "manual")
                ),
                " · queue ",
                rx.code(crawler["queue"].to(str)),
                color_scheme="gray",
            ),
            error_callout(CrawlerDetailState.error),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Status"),
                        rx.table.column_header_cell("Created"),
                        rx.table.column_header_cell("Published"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(CrawlerDetailState.versions, _row)),
                width="100%",
            ),
            rx.text(
                "Publishing a draft archives the published version. The schedule "
                "runs the published version; with none, it waits.",
                size="2",
                color_scheme="gray",
            ),
            _delete_dialog(),
            spacing="4",
            width="100%",
        )
    )

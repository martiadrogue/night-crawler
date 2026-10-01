import reflex as rx

from night_crawler.components.fields import labelled
from night_crawler.components.nav import error_callout, page_shell
from night_crawler.state.auth_state import AuthState
from night_crawler.state.sources_state import SourcesState


def _form_dialog() -> rx.Component:
    key = SourcesState.editing_source_id
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    SourcesState.editing_source_id != "", "Edit source", "New source"
                )
            ),
            rx.form(
                rx.vstack(
                    labelled(
                        "Name (unique, e.g. TheFork)",
                        rx.input(
                            name="name",
                            default_value=SourcesState.form_name,
                            required=True,
                            key=key,
                            width="100%",
                        ),
                    ),
                    labelled(
                        "Website (optional)",
                        rx.input(
                            name="url",
                            default_value=SourcesState.form_url,
                            key=key,
                            width="100%",
                        ),
                    ),
                    error_callout(SourcesState.form_error),
                    rx.hstack(
                        rx.dialog.close(
                            rx.button("Cancel", variant="soft", type="button")
                        ),
                        rx.button("Save", type="submit"),
                        justify="end",
                        width="100%",
                    ),
                    spacing="3",
                    width="100%",
                ),
                on_submit=SourcesState.submit_form,
            ),
            max_width="32em",
        ),
        open=SourcesState.form_open,
        on_open_change=SourcesState.set_form_open,
    )


def _row(source: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(source["name"]),
        rx.table.cell(
            rx.cond(source["url"], rx.code(source["url"].to(str)), "—"),
        ),
        rx.table.cell(
            rx.cond(
                "admin" == AuthState.role,
                rx.hstack(
                    rx.button(
                        "Edit",
                        size="1",
                        variant="soft",
                        on_click=SourcesState.start_edit(source),
                    ),
                    rx.button(
                        "Delete",
                        size="1",
                        variant="soft",
                        color_scheme="red",
                        on_click=SourcesState.delete_source(source["id"]),
                    ),
                    spacing="2",
                ),
            )
        ),
    )


@rx.page(
    route="/sources",
    title="Sources · Night Crawler",
    on_load=SourcesState.load_sources,
)
def sources() -> rx.Component:
    return page_shell(
        rx.vstack(
            rx.hstack(
                rx.heading("Sources", size="7"),
                rx.spacer(),
                rx.button("New source", on_click=SourcesState.start_create),
                width="100%",
                align="center",
            ),
            rx.text(
                "The websites crawled data comes from. Every crawler is linked "
                "to one; its datasets' records are keyed on it plus each item's "
                "source_id. Only admins can edit or delete a source, and one "
                "still used by a crawler can't be deleted.",
                size="2",
                color_scheme="gray",
            ),
            error_callout(SourcesState.error),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Name"),
                        rx.table.column_header_cell("Website"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(SourcesState.sources, _row)),
                width="100%",
            ),
            _form_dialog(),
            spacing="4",
            width="100%",
        )
    )

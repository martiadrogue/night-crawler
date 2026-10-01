import reflex as rx

from night_crawler import forms
from night_crawler.components.fields import id_choice
from night_crawler.components.nav import error_callout, page_shell
from night_crawler.state.crawlers_state import CrawlersState


def _labelled(label: str, control: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"), control, spacing="1", width="100%"
    )


def _choice(options: list[str], value, on_change) -> rx.Component:
    return rx.select(options, value=value, on_change=on_change, width="100%")


def _form() -> rx.Component:
    key = CrawlersState.editing_crawler_id
    return rx.form(
        rx.vstack(
            _labelled(
                "Title",
                rx.input(
                    name="title",
                    default_value=CrawlersState.form_title,
                    required=True,
                    key=key,
                    width="100%",
                ),
            ),
            rx.hstack(
                _labelled(
                    "Source (where the dataset comes from)",
                    rx.cond(
                        CrawlersState.source_options.length() > 0,
                        id_choice(
                            CrawlersState.source_options,
                            CrawlersState.form_source_id,
                            CrawlersState.set_form_source_id,
                        ),
                        rx.text(
                            "No sources yet: ",
                            rx.link("create one", href="/sources"),
                            " first.",
                            size="2",
                            color_scheme="red",
                        ),
                    ),
                ),
                _labelled(
                    "Dataset",
                    rx.cond(
                        CrawlersState.dataset_options.length() > 0,
                        id_choice(
                            CrawlersState.dataset_options,
                            CrawlersState.form_dataset_id,
                            CrawlersState.set_form_dataset_id,
                        ),
                        rx.text(
                            "No datasets yet: ",
                            rx.link("create one", href="/datasets"),
                            " first.",
                            size="2",
                            color_scheme="red",
                        ),
                    ),
                ),
                width="100%",
            ),
            _labelled(
                "Fields (the dataset fields this crawler downloads, in CSV "
                "order, comma separated; must include the required ones)",
                rx.input(
                    name="fields",
                    default_value=CrawlersState.form_fields,
                    key=key,
                    width="100%",
                    font_family="monospace",
                ),
            ),
            rx.hstack(
                _labelled(
                    "Schedule (cron, e.g. 0 6 * * *; runs once a version is "
                    "published; empty for manual runs only)",
                    rx.input(
                        name="schedule",
                        default_value=CrawlersState.form_schedule,
                        key=key,
                        width="100%",
                        font_family="monospace",
                    ),
                ),
                rx.box(
                    _labelled(
                        "Queue (every run)",
                        _choice(
                            forms.CRAWLER_QUEUES,
                            CrawlersState.form_queue,
                            CrawlersState.set_form_queue,
                        ),
                    ),
                    width="12em",
                ),
                align="end",
                width="100%",
            ),
            error_callout(CrawlersState.form_error),
            rx.hstack(
                rx.dialog.close(rx.button("Cancel", variant="soft", type="button")),
                rx.button("Save", type="submit"),
                justify="end",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        on_submit=CrawlersState.submit_form,
    )


def _form_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    CrawlersState.editing_crawler_id != "",
                    "Schedule crawler",
                    "New crawler",
                )
            ),
            _form(),
            max_width="40em",
        ),
        open=CrawlersState.form_open,
        on_open_change=CrawlersState.set_form_open,
    )


def _delete_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete crawler"),
            rx.alert_dialog.description(
                "This deletes the crawler with its versions, templates, and "
                "executions. Imported data is kept."
            ),
            rx.hstack(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft")),
                rx.alert_dialog.action(
                    rx.button(
                        "Delete",
                        color_scheme="red",
                        on_click=CrawlersState.confirm_delete,
                    )
                ),
                justify="end",
            ),
        ),
        open=CrawlersState.deleting_crawler_id != "",
        on_open_change=CrawlersState.set_delete_open,
    )


def _context_row(row: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.code(row["key"])),
        rx.table.cell(
            rx.text(
                row["value_text"],
                font_family="monospace",
                size="1",
                white_space="pre-wrap",
                word_break="break-all",
            )
        ),
        rx.table.cell(
            rx.hstack(
                rx.button(
                    "Edit",
                    size="1",
                    variant="soft",
                    on_click=CrawlersState.start_context_edit(row),
                ),
                rx.button(
                    "Delete",
                    size="1",
                    variant="soft",
                    color_scheme="red",
                    on_click=CrawlersState.delete_context_key(row["key"]),
                ),
                spacing="2",
            )
        ),
    )


def _context_form() -> rx.Component:
    key = CrawlersState.context_form_version.to(str)
    is_editing = CrawlersState.context_editing_key != ""
    return rx.form(
        rx.vstack(
            rx.heading(
                rx.cond(
                    is_editing, "Edit " + CrawlersState.context_editing_key, "Add a key"
                ),
                size="3",
            ),
            rx.cond(
                is_editing,
                rx.fragment(),
                _labelled(
                    "Key (end it with [] for a list to fan out over)",
                    rx.input(
                        name="key",
                        default_value="",
                        key=key,
                        width="100%",
                        font_family="monospace",
                    ),
                ),
            ),
            _labelled(
                'Value (JSON, e.g. 3, true, ["ad", "ca"]; anything else is text)',
                rx.text_area(
                    name="value",
                    default_value=CrawlersState.context_form_value,
                    key=key,
                    rows="3",
                    width="100%",
                    font_family="monospace",
                ),
            ),
            rx.hstack(
                rx.cond(
                    is_editing,
                    rx.button(
                        "Cancel edit",
                        variant="soft",
                        type="button",
                        on_click=CrawlersState.start_context_add,
                    ),
                ),
                rx.button("Save", type="submit"),
                justify="end",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        on_submit=CrawlersState.submit_context,
        reset_on_submit=False,
    )


def _context_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Context · " + CrawlersState.context_crawler_title),
            rx.dialog.description(
                "The values of the crawler's latest run, which its next run "
                "inherits. Keys ending in [] are lists a template fans out over. "
                "Values of keys that look secret (key, token, secret, password) "
                "stay hidden; you can still replace or delete them.",
                size="2",
                color_scheme="gray",
            ),
            rx.vstack(
                error_callout(CrawlersState.context_error),
                rx.cond(
                    CrawlersState.context_rows.length() > 0,
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("Key"),
                                rx.table.column_header_cell("Value"),
                                rx.table.column_header_cell(""),
                            )
                        ),
                        rx.table.body(
                            rx.foreach(CrawlersState.context_rows, _context_row)
                        ),
                        width="100%",
                    ),
                ),
                _context_form(),
                rx.hstack(
                    rx.dialog.close(rx.button("Close", variant="soft")),
                    justify="end",
                    width="100%",
                ),
                spacing="4",
                width="100%",
                margin_top="1em",
            ),
            max_width="48em",
        ),
        open=CrawlersState.context_open,
        on_open_change=CrawlersState.set_context_open,
    )


def _row(crawler: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.button(
                crawler["title"],
                size="1",
                variant="ghost",
                color_scheme="blue",
                padding="0",
                on_click=CrawlersState.open_instructions(crawler["id"]),
            )
        ),
        rx.table.cell(crawler["source_name"]),
        rx.table.cell(crawler["dataset_name"]),
        rx.table.cell(
            rx.cond(
                crawler["schedule"],
                rx.code(crawler["schedule"]),
                rx.text("manual", color_scheme="gray"),
            )
        ),
        rx.table.cell(crawler["queue"]),
        rx.table.cell(
            rx.hstack(
                rx.button(
                    "Schedule",
                    size="1",
                    variant="soft",
                    on_click=CrawlersState.start_edit(crawler),
                ),
                rx.button(
                    "Instructions",
                    size="1",
                    variant="soft",
                    color_scheme="violet",
                    on_click=CrawlersState.open_instructions(crawler["id"]),
                ),
                rx.button(
                    "Context",
                    size="1",
                    variant="soft",
                    color_scheme="teal",
                    on_click=CrawlersState.open_context(crawler),
                ),
                rx.button(
                    "Delete",
                    size="1",
                    variant="soft",
                    color_scheme="red",
                    on_click=CrawlersState.start_delete(crawler["id"]),
                ),
                spacing="2",
            )
        ),
    )


@rx.page(
    route="/crawlers",
    title="Crawlers · Night Crawler",
    on_load=CrawlersState.load_crawlers,
)
def crawlers() -> rx.Component:
    return page_shell(
        rx.vstack(
            rx.hstack(
                rx.heading("Crawlers", size="7"),
                rx.spacer(),
                rx.button("New crawler", on_click=CrawlersState.start_create),
                width="100%",
                align="center",
            ),
            error_callout(CrawlersState.error),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Title"),
                        rx.table.column_header_cell("Source"),
                        rx.table.column_header_cell("Dataset"),
                        rx.table.column_header_cell("Schedule"),
                        rx.table.column_header_cell("Queue"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(CrawlersState.crawlers, _row)),
                width="100%",
            ),
            rx.cond(
                (CrawlersState.crawlers.length() == 0) & ~CrawlersState.is_loading,
                rx.text("No crawlers yet.", color_scheme="gray"),
            ),
            _form_dialog(),
            _delete_dialog(),
            _context_dialog(),
            spacing="4",
            width="100%",
        )
    )

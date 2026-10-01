import reflex as rx

from night_crawler.components.fields import labelled
from night_crawler.components.nav import error_callout, page_shell
from night_crawler.state.auth_state import AuthState
from night_crawler.state.datasets_state import DatasetsState


def _text_field(name: str, value, key, **props) -> rx.Component:
    return rx.input(
        name=name,
        default_value=value,
        key=key,
        width="100%",
        font_family="monospace",
        **props,
    )


def _form_dialog() -> rx.Component:
    key = DatasetsState.editing_dataset_id
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    DatasetsState.editing_dataset_id != "",
                    "Edit dataset",
                    "New dataset",
                )
            ),
            rx.form(
                rx.vstack(
                    labelled(
                        "Name (unique, e.g. venues)",
                        _text_field(
                            "name", DatasetsState.form_name, key, required=True
                        ),
                    ),
                    labelled(
                        "Fields, in CSV order (JSON list; each: name, type "
                        "string|integer|float|boolean, is_required, is_unique, "
                        "pattern regex). item_id must be required and unique.",
                        rx.text_area(
                            name="fields_text",
                            default_value=DatasetsState.form_fields_text,
                            key=key,
                            rows="14",
                            width="100%",
                            font_family="monospace",
                        ),
                    ),
                    error_callout(DatasetsState.form_error),
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
                on_submit=DatasetsState.submit_form,
            ),
            max_width="44em",
        ),
        open=DatasetsState.form_open,
        on_open_change=DatasetsState.set_form_open,
    )


def _row(dataset: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(dataset["name"], weight="medium")),
        rx.table.cell(
            rx.text(dataset["fields_text"].to(str), font_family="monospace", size="1")
        ),
        rx.table.cell(
            rx.cond(
                "admin" == AuthState.role,
                rx.hstack(
                    rx.button(
                        "Edit",
                        size="1",
                        variant="soft",
                        on_click=DatasetsState.start_edit(dataset),
                    ),
                    rx.button(
                        "Delete",
                        size="1",
                        variant="soft",
                        color_scheme="red",
                        on_click=DatasetsState.delete_dataset(dataset["id"]),
                    ),
                    spacing="2",
                ),
            )
        ),
    )


@rx.page(
    route="/datasets",
    title="Datasets · Night Crawler",
    on_load=DatasetsState.load_datasets,
)
def datasets() -> rx.Component:
    return page_shell(
        rx.vstack(
            rx.hstack(
                rx.heading("Datasets", size="7"),
                rx.spacer(),
                rx.button("New dataset", on_click=DatasetsState.start_create),
                width="100%",
                align="center",
            ),
            rx.text(
                "What a crawler downloads: each field's type, pattern, and whether "
                "it is required (*) or unique per source (!). A crawler picks a "
                "source and a dataset, and lists which of its fields it "
                "downloads, so one dataset can be fed by many sources. Every "
                "dataset has item_id, the item's own ID on its website, required "
                "and unique. Only admins can edit or delete a dataset; one still "
                "used by a crawler can't be deleted, and an edit can't break a "
                "linked crawler's fields.",
                size="2",
                color_scheme="gray",
            ),
            error_callout(DatasetsState.error),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Name"),
                        rx.table.column_header_cell("Fields"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(DatasetsState.datasets, _row)),
                width="100%",
            ),
            _form_dialog(),
            spacing="4",
            width="100%",
        )
    )

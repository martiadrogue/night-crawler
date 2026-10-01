import reflex as rx

from night_crawler import forms
from night_crawler.components.fields import (
    checkbox_field,
    choice,
    labelled,
    optional_id_choice,
)
from night_crawler.components.nav import (
    breadcrumbs,
    error_callout,
    page_shell,
)
from night_crawler.components.rate_limit_fields import rate_limit_fields
from night_crawler.state.version_editor_state import VersionEditorState

State = VersionEditorState


def _mono_input(name: str, value, key, **props) -> rx.Component:
    return rx.input(
        name=name,
        default_value=value,
        key=key,
        width="100%",
        font_family="monospace",
        **props,
    )


def _json_area(name: str, value, key, rows: str = "6") -> rx.Component:
    return rx.text_area(
        name=name,
        default_value=value,
        key=key,
        rows=rows,
        width="100%",
        font_family="monospace",
    )


# --- Settings ------------------------------------------------------------------
def _settings() -> rx.Component:
    key = State.version["id"].to(str) + State.version["updated_at"].to(str)
    return rx.card(
        rx.form(
            rx.hstack(
                checkbox_field(
                    "is_host_session_sharing_enabled",
                    "Share cookies and headers per host",
                    State.version["is_host_session_sharing_enabled"].to(bool),
                    key,
                ),
                rx.button("Save settings", type="submit", disabled=State.is_archived),
                align="end",
                spacing="4",
                width="100%",
            ),
            on_submit=State.save_settings,
        ),
        width="100%",
    )


# --- Templates -----------------------------------------------------------------
def _template_row(template: rx.Var) -> rx.Component:
    template_id = template["id"].to(str)
    is_root = template_id == State.version["message_template_root_id"].to(str)
    return rx.table.row(
        rx.table.cell(rx.cond(is_root, rx.badge("root", color_scheme="violet"), "")),
        rx.table.cell(rx.code(template["action"].to(str))),
        rx.table.cell(
            rx.link(
                rx.text(
                    rx.cond(template["url"], template["url"].to(str), "(no URL yet)"),
                    font_family="monospace",
                    size="2",
                ),
                on_click=State.toggle_template(template_id),
                cursor="pointer",
                weight=rx.cond(
                    template_id == State.selected_template_id, "bold", "regular"
                ),
            )
        ),
        rx.table.cell(
            rx.text(template["aid_label"].to(str), size="2", color_scheme="gray")
        ),
        rx.table.cell(
            rx.button(
                rx.cond(
                    template_id == State.selected_template_id,
                    rx.icon("chevron-down", size=14),
                    rx.icon("chevron-right", size=14),
                ),
                "Selectors (",
                template["selector_count"].to(str),
                ")",
                size="1",
                variant="ghost",
                on_click=State.toggle_template(template_id),
            )
        ),
        rx.table.cell(
            rx.cond(
                ~State.is_archived,
                rx.hstack(
                    rx.button(
                        "Edit",
                        size="1",
                        variant="soft",
                        on_click=State.start_edit_template(template),
                    ),
                    rx.cond(
                        ~is_root,
                        rx.button(
                            "Make root",
                            size="1",
                            variant="soft",
                            on_click=State.set_root_template(template_id),
                        ),
                    ),
                    rx.cond(
                        ~is_root,
                        rx.button(
                            "Delete",
                            size="1",
                            variant="soft",
                            color_scheme="red",
                            on_click=State.delete_template(template_id),
                        ),
                    ),
                    spacing="2",
                ),
            )
        ),
        background=rx.cond(
            template_id == State.selected_template_id, "var(--accent-3)", "transparent"
        ),
    )


def _template_with_selectors(template: rx.Var) -> rx.Component:
    """A template's row, and under it its selectors when it is open."""
    return rx.fragment(
        _template_row(template),
        rx.cond(
            template["id"].to(str) == State.selected_template_id,
            rx.table.row(
                rx.table.cell(
                    rx.box(
                        _selectors(),
                        padding="0.75em",
                        border_left="3px solid var(--accent-8)",
                        background="var(--gray-2)",
                    ),
                    col_span=6,
                )
            ),
        ),
    )


def _templates() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.spacer(),
            rx.button(
                "Version history",
                variant="soft",
                on_click=State.open_version_history,
            ),
            rx.button(
                rx.icon("flask-conical", size=16),
                "Test run",
                variant="outline",
                on_click=State.run_test,
            ),
            rx.button(
                "New template",
                on_click=State.start_create_template,
                disabled=State.is_archived,
            ),
            width="100%",
        ),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell(""),
                    rx.table.column_header_cell("Action"),
                    rx.table.column_header_cell("URL"),
                    rx.table.column_header_cell("Aid"),
                    rx.table.column_header_cell(""),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(rx.foreach(State.templates, _template_with_selectors)),
            width="100%",
        ),
        width="100%",
    )


def _template_dialog() -> rx.Component:
    key = State.editing_template_id
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    State.editing_template_id != "", "Edit template", "New template"
                )
            ),
            rx.form(
                rx.vstack(
                    labelled(
                        "Action",
                        choice(
                            forms.TEMPLATE_ACTIONS,
                            State.template_action,
                            State.set_template_action,
                        ),
                    ),
                    labelled(
                        "URL — placeholders like {{parish}}; a list fans out, "
                        "one request per element",
                        _mono_input(
                            "url",
                            State.template_url,
                            key,
                            required=True,
                            on_blur=State.note_template_url,
                        ),
                    ),
                    labelled("Body", _json_area("body", State.template_body, key, "4")),
                    labelled(
                        "Headers (JSON object)",
                        _json_area("headers_text", State.template_headers_text, key),
                    ),
                    _aid_section(key),
                    error_callout(State.template_form_error),
                    _dialog_buttons(),
                    spacing="3",
                    width="100%",
                ),
                on_submit=State.submit_template,
            ),
            max_width="44em",
        ),
        open=State.template_form_open,
        on_open_change=State.set_template_form_open,
    )


def _domain_rate_limit_dialog() -> rx.Component:
    """Create the rule for the template URL's domain, then select it."""
    key = State.rate_limit_form_version.to(str)
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("New rate limit for " + State.rate_limit_form_name),
            rx.dialog.description(
                "No rate limit is named after this domain yet. Saving creates "
                "it and selects it on the template's aid.",
                size="2",
                color_scheme="gray",
            ),
            rx.form(
                rx.vstack(
                    rate_limit_fields(
                        {
                            "name": State.rate_limit_form_name,
                            "rate_limit_string": "",
                            "penalty_step_seconds": "",
                            "max_penalty_seconds": "",
                            "decay_after_successes": "",
                            "decay_step_seconds": "",
                        },
                        key,
                        "Name: the domain it is for",
                    ),
                    error_callout(State.rate_limit_form_error),
                    _dialog_buttons(),
                    spacing="3",
                    width="100%",
                    margin_top="1em",
                ),
                on_submit=State.submit_domain_rate_limit,
            ),
            max_width="36em",
        ),
        open=State.rate_limit_form_open,
        on_open_change=State.set_rate_limit_form_open,
    )


def _dialog_buttons() -> rx.Component:
    return rx.hstack(
        rx.dialog.close(rx.button("Cancel", variant="soft", type="button")),
        rx.button("Save", type="submit"),
        justify="end",
        width="100%",
    )


# --- Selectors -----------------------------------------------------------------
def _selector_row(selector: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.text(
                rx.cond(selector["title"], selector["title"].to(str), "—"),
                weight="bold",
            )
        ),
        rx.table.cell(
            rx.text(selector["tree_label"].to(str), font_family="monospace", size="2")
        ),
        rx.table.cell(selector["type"].to(str)),
        rx.table.cell(selector["source"].to(str)),
        rx.table.cell(rx.code(selector["target"].to(str))),
        rx.table.cell(
            rx.cond(
                ~State.is_archived,
                rx.hstack(
                    rx.button(
                        "Edit",
                        size="1",
                        variant="soft",
                        on_click=State.start_edit_selector(selector),
                    ),
                    rx.button(
                        "Delete",
                        size="1",
                        variant="soft",
                        color_scheme="red",
                        on_click=State.delete_selector(selector["id"].to(str)),
                    ),
                    spacing="2",
                ),
            ),
        ),
        background=rx.cond(
            selector["is_dataset_field"], "var(--green-2)", "transparent"
        ),
    )


def _selectors() -> rx.Component:
    """The open template's message selectors, as a tree."""
    return rx.vstack(
        rx.hstack(
            rx.text("Message selectors", size="2", weight="medium"),
            rx.spacer(),
            rx.button(
                "New selector",
                size="2",
                on_click=State.start_create_selector,
                disabled=State.is_archived,
            ),
            width="100%",
        ),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Title"),
                    rx.table.column_header_cell("Path"),
                    rx.table.column_header_cell("Type"),
                    rx.table.column_header_cell("Source"),
                    rx.table.column_header_cell("Target"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(rx.foreach(State.selectors, _selector_row)),
            width="100%",
        ),
        rx.cond(
            State.selectors.length() == 0,
            rx.text("No selectors yet.", size="2", color_scheme="gray"),
        ),
        rx.text(
            "Green-tinted rows match the crawler's Fields and feed the "
            "dataset; other titles go to the Context. "
            "Under an iterator or click, values are kept as lists, one per match.",
            size="1",
            color_scheme="gray",
        ),
        width="100%",
    )


def _selector_dialog() -> rx.Component:
    key = State.editing_selector_id
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    State.editing_selector_id != "", "Edit selector", "New selector"
                )
            ),
            rx.form(
                rx.vstack(
                    rx.hstack(
                        labelled(
                            "Type",
                            choice(
                                forms.SELECTOR_TYPES,
                                State.selector_type,
                                State.set_selector_type,
                            ),
                        ),
                        labelled(
                            "Source",
                            choice(
                                forms.SELECTOR_SOURCES,
                                State.selector_source,
                                State.set_selector_source,
                            ),
                        ),
                        width="100%",
                    ),
                    labelled(
                        "Path — CSS, XPath, JMESPath, a regex for headers/url, or a "
                        "placeholder name for context",
                        _mono_input("path", State.selector_path, key, required=True),
                    ),
                    rx.hstack(
                        labelled(
                            "Target (__text or an attribute)",
                            _mono_input("target", State.selector_target, key),
                        ),
                        labelled(
                            "Title", _mono_input("title", State.selector_title, key)
                        ),
                        width="100%",
                    ),
                    labelled(
                        "Parent",
                        optional_id_choice(
                            State.parent_options,
                            State.selector_parent_id,
                            State.set_selector_parent_id,
                        ),
                    ),
                    rx.cond(
                        "pagination" == State.selector_type,
                        labelled(
                            "Pagination config (JSON)",
                            _json_area("config_text", State.selector_config_text, key),
                        ),
                    ),
                    error_callout(State.selector_form_error),
                    _dialog_buttons(),
                    spacing="3",
                    width="100%",
                ),
                on_submit=State.submit_selector,
            ),
            max_width="44em",
        ),
        open=State.selector_form_open,
        on_open_change=State.set_selector_form_open,
    )


# --- Aid (inside the template dialog) ------------------------------------------
def _render_mode_choice() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(width="100%"),
        rx.select.content(
            *[rx.select.item(label, value=value) for value, label in forms.RENDER_MODES]
        ),
        value=State.aid_render_mode,
        on_change=State.set_aid_render_mode,
    )


def _aid_section(key) -> rx.Component:
    """The template's aid; left at the defaults, none is stored."""
    return rx.vstack(
        rx.divider(),
        rx.text("Message aid (request settings)", size="2", weight="medium"),
        _aid_fields(key),
        rx.text(
            "Empty fields use the defaults: TTL 20 s, no proxy or rate limit, "
            "any status below 400 succeeds (Success codes, when set, name "
            "exactly which statuses do), and a request failing with 429, "
            "500, 502, 503 or 504 is retried up to 3 times (waiting 1 s, 2 s, "
            "4 s) before it counts as failed.",
            size="1",
            color_scheme="gray",
        ),
        spacing="2",
        width="100%",
    )


def _aid_fields(key) -> rx.Component:
    return rx.grid(
        labelled("Render mode", _render_mode_choice()),
        labelled("TTL (seconds)", _mono_input("ttl", State.aid_ttl, key)),
        labelled(
            "Proxy",
            optional_id_choice(
                State.proxy_options, State.aid_proxy_id, State.set_aid_proxy_id
            ),
        ),
        labelled(
            "Rate limit (per domain)",
            rx.vstack(
                optional_id_choice(
                    State.rate_limit_options,
                    State.aid_rate_limit_id,
                    State.set_aid_rate_limit_id,
                ),
                rx.button(
                    "Add rate limit",
                    type="button",
                    size="1",
                    variant="soft",
                    on_click=State.add_domain_rate_limit,
                ),
                spacing="1",
                width="100%",
            ),
        ),
        labelled("Retry codes", _mono_input("retry_codes", State.aid_retry_codes, key)),
        labelled(
            "Success codes (200, 204 …)",
            _mono_input("success_codes", State.aid_success_codes, key),
        ),
        labelled(
            "Max retry attempts",
            _mono_input("max_retry_attempts", State.aid_max_retry_attempts, key),
        ),
        columns="2",
        spacing="3",
        width="100%",
    )


@rx.page(
    route="/versions/[version_id]",
    title="Version · Night Crawler",
    on_load=VersionEditorState.load_version,
)
def version_editor() -> rx.Component:
    return page_shell(
        rx.vstack(
            breadcrumbs(
                [
                    ("Crawlers", "/crawlers"),
                    (
                        "Version History",
                        "/crawlers/" + State.version["crawler_id"].to(str),
                    ),
                ]
            ),
            rx.hstack(
                rx.vstack(
                    rx.heading("Instructions", size="7", margin="0"),
                    rx.text(State.subtitle, size="4", color_scheme="gray"),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.cond(
                    State.is_draft,
                    rx.button(
                        rx.icon("rocket", size=16),
                        "Publish",
                        color_scheme="green",
                        on_click=State.publish,
                    ),
                ),
                align="center",
                width="100%",
            ),
            rx.cond(
                State.notice != "",
                rx.callout(State.notice, icon="info", color_scheme="green"),
            ),
            rx.cond(
                State.is_published,
                rx.callout(
                    "This version is live. Any edit creates a draft and opens it.",
                    icon="info",
                ),
            ),
            rx.cond(
                State.is_archived,
                rx.callout("Archived versions are read-only.", icon="lock"),
            ),
            error_callout(State.error),
            _settings(),
            rx.heading("Message templates", size="5"),
            _templates(),
            _template_dialog(),
            _domain_rate_limit_dialog(),
            _selector_dialog(),
            spacing="4",
            width="100%",
        )
    )

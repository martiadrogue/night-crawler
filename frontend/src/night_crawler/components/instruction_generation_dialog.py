"""The Instructions page's "Generate from prompt" button and dialog."""

import reflex as rx

from night_crawler.components.nav import error_callout, status_badge
from night_crawler.state.instruction_generation_state import (
    InstructionGenerationState,
)

State = InstructionGenerationState

PROMPT_PLACEHOLDER = (
    "What should this crawler get? e.g. comedy shows in Barcelona on "
    "atrapalo.com: name, date, price"
)


def generate_button() -> rx.Component:
    """Open the dialog; an archived version can't take new instructions."""
    return rx.button(
        rx.icon("sparkles", size=16),
        "Generate from prompt",
        variant="soft",
        on_click=State.set_generation_form_open(True),
        disabled=State.is_archived,
    )


def generation_dialog() -> rx.Component:
    """Ask for a prompt, then follow the job and its test run."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Generate from prompt"),
            rx.dialog.description(
                "An AI agent browses the site to get this data, writes the "
                "instructions from what it did, then starts a test run. It "
                "can take several minutes; closing this dialog doesn't stop it.",
                size="2",
                color_scheme="gray",
            ),
            rx.form(
                rx.vstack(
                    rx.callout(
                        "Generating replaces this draft's templates, selectors, "
                        "and aids, like an import. On a published version it "
                        "opens a new draft instead, and the published one stays "
                        "as it is.",
                        icon="triangle_alert",
                        color_scheme="amber",
                        size="1",
                    ),
                    rx.text_area(
                        name="prompt",
                        default_value=State.generation_prompt,
                        key=State.generation_form_key,
                        placeholder=PROMPT_PLACEHOLDER,
                        rows="5",
                        width="100%",
                    ),
                    rx.text(
                        "Fields it will extract: ",
                        rx.code(State.crawler_fields_text),
                        size="2",
                        color_scheme="gray",
                    ),
                    _progress(),
                    error_callout(State.generation_error),
                    _result(),
                    _buttons(),
                    spacing="3",
                    width="100%",
                    margin_top="1em",
                ),
                on_submit=State.submit_generation,
                reset_on_submit=False,
            ),
            max_width="36em",
        ),
        open=State.generation_form_open,
        on_open_change=State.set_generation_form_open,
    )


def _progress() -> rx.Component:
    """A spinner while it runs, and the API's status as one line."""
    return rx.cond(
        (State.generation_status_line != "") & ~State.has_generation_failed,
        rx.hstack(
            rx.cond(State.is_generation_busy, rx.spinner(size="2")),
            rx.text(State.generation_status_line, size="2", weight="medium"),
            align="center",
            spacing="2",
        ),
    )


def _result() -> rx.Component:
    """Warnings, Context keys to set, and the test run, once known."""
    return rx.vstack(
        rx.foreach(
            State.generation_warnings,
            lambda warning: rx.callout(
                warning, icon="info", color_scheme="yellow", size="1", width="100%"
            ),
        ),
        rx.cond(
            State.required_context_keys.length() > 0,
            rx.callout(
                rx.text(
                    "These instructions need values only the crawler's Context "
                    "holds. Set them in the Crawlers page → Context before "
                    "running: ",
                    rx.foreach(
                        State.required_context_keys,
                        lambda key: rx.code(key, margin_right="0.4em"),
                    ),
                ),
                icon="key-round",
                size="1",
                width="100%",
            ),
        ),
        _test_run(),
        spacing="2",
        width="100%",
    )


def _test_run() -> rx.Component:
    """The test run's status and counts, and its Sample CSV."""
    return rx.cond(
        State.generation_execution.contains("status"),
        rx.hstack(
            rx.text("Test run", size="2", weight="medium"),
            status_badge(State.generation_execution["status"].to(str)),
            rx.text(State.generation_run_counts, size="2", color_scheme="gray"),
            rx.spacer(),
            rx.cond(
                State.has_generation_csv,
                rx.button(
                    rx.icon("download", size=14),
                    "Sample CSV",
                    size="1",
                    variant="soft",
                    type="button",
                    on_click=State.download_generation_sample_csv,
                ),
            ),
            align="center",
            width="100%",
        ),
    )


def _buttons() -> rx.Component:
    return rx.hstack(
        rx.dialog.close(rx.button("Close", variant="soft", type="button")),
        rx.button(
            rx.icon("sparkles", size=16),
            "Generate",
            type="submit",
            loading=State.is_generation_busy,
            disabled=State.is_generation_busy | State.is_archived,
        ),
        justify="end",
        width="100%",
    )

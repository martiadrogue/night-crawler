import reflex as rx

from night_crawler.components.nav import error_callout, page_shell
from night_crawler.components.rate_limit_fields import rate_limit_fields
from night_crawler.state.auth_state import AuthState
from night_crawler.state.rate_limits_state import RateLimitsState


def _form_dialog() -> rx.Component:
    key = RateLimitsState.editing_rate_limit_id
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    RateLimitsState.editing_rate_limit_id != "",
                    "Edit rate limit",
                    "New rate limit",
                )
            ),
            rx.form(
                rx.vstack(
                    rate_limit_fields(
                        {
                            "name": RateLimitsState.form_name,
                            "rate_limit_string": RateLimitsState.form_rate_limit_string,
                            "penalty_step_seconds": (
                                RateLimitsState.form_penalty_step_seconds
                            ),
                            "max_penalty_seconds": RateLimitsState.form_max_penalty_seconds,
                            "decay_after_successes": (
                                RateLimitsState.form_decay_after_successes
                            ),
                            "decay_step_seconds": RateLimitsState.form_decay_step_seconds,
                        },
                        key,
                        "Name: the domain it is for (e.g. places.googleapis.com), "
                        "so template editors can find it",
                    ),
                    error_callout(RateLimitsState.form_error),
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
                on_submit=RateLimitsState.submit_form,
            ),
            max_width="36em",
        ),
        open=RateLimitsState.form_open,
        on_open_change=RateLimitsState.set_form_open,
    )


def _delete_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete rate limit"),
            rx.alert_dialog.description(
                "Templates and proxies that use this rule lose their rate "
                "limit; they are not deleted."
            ),
            rx.hstack(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft")),
                rx.alert_dialog.action(
                    rx.button(
                        "Delete",
                        color_scheme="red",
                        on_click=RateLimitsState.confirm_delete,
                    )
                ),
                justify="end",
            ),
        ),
        open=RateLimitsState.deleting_rate_limit_id != "",
        on_open_change=RateLimitsState.set_delete_open,
    )


def _row(rate_limit: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.cond(rate_limit["name"], rate_limit["name"].to(str), "—"),
        ),
        rx.table.cell(rx.code(rate_limit["rate_limit_string"].to(str))),
        rx.table.cell(rx.text(rate_limit["penalty_text"].to(str), size="1")),
        rx.table.cell(
            rx.cond(
                "admin" == AuthState.role,
                rx.hstack(
                    rx.button(
                        "Edit",
                        size="1",
                        variant="soft",
                        on_click=RateLimitsState.start_edit(rate_limit),
                    ),
                    rx.button(
                        "Delete",
                        size="1",
                        variant="soft",
                        color_scheme="red",
                        on_click=RateLimitsState.start_delete(rate_limit["id"]),
                    ),
                    spacing="2",
                ),
            )
        ),
    )


@rx.page(
    route="/rate-limits",
    title="Rate limits · Night Crawler",
    on_load=RateLimitsState.load_rate_limits,
)
def rate_limits() -> rx.Component:
    return page_shell(
        rx.vstack(
            rx.hstack(
                rx.heading("Rate limits", size="7"),
                rx.spacer(),
                rx.button("New rate limit", on_click=RateLimitsState.start_create),
                width="100%",
                align="center",
            ),
            rx.text(
                "Reusable rules a template's aid (per domain) or a proxy can "
                "point to. Name a rule after the domain it is for (e.g. "
                "places.googleapis.com): the template editor's Add rate limit "
                "finds it by that name. Anyone can create one; only admins "
                "can edit or delete one.",
                size="2",
                color_scheme="gray",
            ),
            error_callout(RateLimitsState.error),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Name"),
                        rx.table.column_header_cell("Limit"),
                        rx.table.column_header_cell("Penalty"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(RateLimitsState.rate_limits, _row)),
                width="100%",
            ),
            rx.cond(
                RateLimitsState.rate_limits.length() == 0,
                rx.text("No rate limits yet.", color_scheme="gray"),
            ),
            _form_dialog(),
            _delete_dialog(),
            spacing="4",
            width="100%",
        )
    )

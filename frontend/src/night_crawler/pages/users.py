import reflex as rx

from night_crawler import forms
from night_crawler.components.fields import choice, labelled
from night_crawler.components.nav import error_callout, page_shell
from night_crawler.state.users_state import UsersState


def _form_dialog() -> rx.Component:
    key = UsersState.editing_user_id
    is_editing = UsersState.editing_user_id != ""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(is_editing, "Edit user", "New user")),
            rx.form(
                rx.vstack(
                    labelled(
                        "Email",
                        rx.input(
                            name="email",
                            type="email",
                            default_value=UsersState.form_email,
                            key=key,
                            width="100%",
                        ),
                    ),
                    labelled(
                        rx.cond(
                            is_editing,
                            "New temporary password (leave blank to keep it)",
                            "Temporary password",
                        ),
                        rx.input(
                            name="password",
                            type="password",
                            key=key,
                            width="100%",
                        ),
                    ),
                    rx.text(
                        "At least 8 characters, with an uppercase letter, a "
                        "lowercase letter, and a digit. The user must choose a "
                        "new one at their next login.",
                        size="1",
                        color_scheme="gray",
                    ),
                    rx.cond(
                        is_editing,
                        labelled(
                            "Role",
                            choice(
                                list(forms.USER_ROLES),
                                UsersState.form_role,
                                UsersState.set_form_role,
                            ),
                        ),
                        rx.text(
                            "New accounts start as user; edit one to change "
                            "its role.",
                            size="1",
                            color_scheme="gray",
                        ),
                    ),
                    error_callout(UsersState.form_error),
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
                on_submit=UsersState.submit_form,
            ),
            max_width="28em",
        ),
        open=UsersState.form_open,
        on_open_change=UsersState.set_form_open,
    )


def _disable_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Disable user"),
            rx.alert_dialog.description(
                rx.text(
                    "Disable ",
                    rx.text.strong(UsersState.disabling_email),
                    "? They can no longer log in. Their crawlers, versions, "
                    "and runs stay. Accounts are never deleted.",
                )
            ),
            rx.hstack(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft")),
                rx.alert_dialog.action(
                    rx.button(
                        "Disable",
                        color_scheme="red",
                        on_click=UsersState.confirm_disable,
                    )
                ),
                justify="end",
            ),
        ),
        open=UsersState.disabling_user_id != "",
        on_open_change=UsersState.set_disable_open,
    )


def _row(user: rx.Var) -> rx.Component:
    is_enabled = user["is_enabled"].to(bool)
    return rx.table.row(
        rx.table.cell(user["email"].to(str)),
        rx.table.cell(rx.badge(user["role"].to(str), variant="soft")),
        rx.table.cell(
            rx.cond(
                is_enabled,
                rx.badge("Enabled", color_scheme="green", variant="soft"),
                rx.badge("Disabled", color_scheme="gray", variant="soft"),
            )
        ),
        rx.table.cell(
            rx.text(
                rx.cond(user["created_at"], user["created_at"].to(str), "—"), size="1"
            )
        ),
        rx.table.cell(
            rx.hstack(
                rx.button(
                    "Edit",
                    size="1",
                    variant="soft",
                    on_click=UsersState.start_edit(user),
                ),
                rx.cond(
                    is_enabled,
                    rx.button(
                        "Disable",
                        size="1",
                        variant="soft",
                        color_scheme="red",
                        on_click=UsersState.start_disable(user),
                    ),
                ),
                spacing="2",
            )
        ),
    )


@rx.page(
    route="/users",
    title="Users · Night Crawler",
    on_load=UsersState.load_users,
)
def users() -> rx.Component:
    return page_shell(
        rx.vstack(
            rx.hstack(
                rx.heading("Users", size="7"),
                rx.spacer(),
                rx.button("New user", on_click=UsersState.start_create),
                width="100%",
                align="center",
            ),
            rx.text(
                "Accounts, ordered by email, kept in Keycloak. Only admins can "
                "see or change them; accounts are disabled, never deleted, and "
                "the last enabled admin can't be demoted or disabled.",
                size="2",
                color_scheme="gray",
            ),
            error_callout(UsersState.error),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Email"),
                        rx.table.column_header_cell("Role"),
                        rx.table.column_header_cell("Status"),
                        rx.table.column_header_cell("Created"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(rx.foreach(UsersState.users, _row)),
                width="100%",
            ),
            rx.cond(
                (UsersState.users.length() == 0) & (UsersState.error == ""),
                rx.text("No users on this page.", color_scheme="gray"),
            ),
            rx.hstack(
                rx.button(
                    "Previous",
                    on_click=UsersState.previous_page,
                    variant="soft",
                    disabled=UsersState.offset == 0,
                ),
                rx.button(
                    "Next",
                    on_click=UsersState.next_page,
                    variant="soft",
                    disabled=~UsersState.has_more,
                ),
                spacing="2",
            ),
            _form_dialog(),
            _disable_dialog(),
            spacing="4",
            width="100%",
        )
    )

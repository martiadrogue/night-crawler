import reflex as rx

from night_crawler.components.nav import error_callout
from night_crawler.state.auth_state import AuthState


def auth_card(
    title: str, button: str, on_submit, footer_text: str, footer_link: tuple[str, str]
) -> rx.Component:
    """The login and register card: email, password, one button."""
    link_text, href = footer_link
    return rx.center(
        rx.card(
            rx.vstack(
                rx.heading(title, size="6"),
                rx.form(
                    rx.vstack(
                        rx.input(
                            name="email",
                            type="email",
                            placeholder="Email",
                            required=True,
                            width="100%",
                        ),
                        rx.input(
                            name="password",
                            type="password",
                            placeholder="Password",
                            required=True,
                            width="100%",
                        ),
                        error_callout(AuthState.error),
                        rx.button(
                            button,
                            type="submit",
                            width="100%",
                            loading=AuthState.is_loading,
                        ),
                        rx.text(footer_text, " ", rx.link(link_text, href=href)),
                        spacing="3",
                        width="100%",
                    ),
                    on_submit=on_submit,
                    reset_on_submit=True,
                ),
                spacing="4",
                width="100%",
            ),
            width="24em",
            padding="2em",
        ),
        min_height="100vh",
    )

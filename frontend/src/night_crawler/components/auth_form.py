import reflex as rx

from night_crawler.components.nav import error_callout
from night_crawler.state.auth_state import AuthState


def auth_card(title: str, *children: rx.Component) -> rx.Component:
    """The centred card the auth pages share, with `AuthState.error`."""
    return rx.center(
        rx.card(
            rx.vstack(
                rx.heading(title, size="6"),
                *children,
                error_callout(AuthState.error),
                spacing="4",
                width="100%",
            ),
            width="24em",
            padding="2em",
        ),
        min_height="100vh",
    )

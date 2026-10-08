import reflex as rx

from night_crawler.components.auth_form import auth_card
from night_crawler.state.auth_state import AuthState


@rx.page(
    route="/auth/callback",
    title="Logging in · Night Crawler",
    on_load=AuthState.finish_login,
)
def auth_callback() -> rx.Component:
    """Where Keycloak sends the browser back with the login's code."""
    return auth_card(
        "Logging in",
        rx.cond(
            AuthState.error == "",
            rx.spinner(),
            rx.link("Back to log in", href="/login"),
        ),
    )

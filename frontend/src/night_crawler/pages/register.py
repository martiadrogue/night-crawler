import reflex as rx

from night_crawler.components.auth_form import auth_card
from night_crawler.state.auth_state import AuthState


@rx.page(
    route="/register",
    title="Register · Night Crawler",
    on_load=AuthState.start_register,
)
def register() -> rx.Component:
    """Keycloak's sign-up page now; this route only sends you there."""
    return auth_card("Create an account", rx.spinner())

import reflex as rx

from night_crawler.components.auth_form import auth_card
from night_crawler.state.auth_state import AuthState


@rx.page(route="/login", title="Log in · Night Crawler")
def login() -> rx.Component:
    return auth_card(
        "Log in",
        "Log in",
        AuthState.handle_login,
        "No account?",
        ("Register", "/register"),
    )

import reflex as rx

from night_crawler.components.auth_form import auth_card
from night_crawler.state.auth_state import AuthState


@rx.page(route="/register", title="Register · Night Crawler")
def register() -> rx.Component:
    return auth_card(
        "Create an account",
        "Create account",
        AuthState.handle_register,
        "Already have an account?",
        ("Log in", "/login"),
    )

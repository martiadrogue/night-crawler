import reflex as rx

from night_crawler.components.auth_form import auth_card
from night_crawler.state.auth_state import AuthState


@rx.page(route="/login", title="Log in · Night Crawler")
def login() -> rx.Component:
    return auth_card(
        "Night Crawler",
        rx.text(
            "Accounts are kept by Keycloak, the identity provider Night "
            "Crawler shares with the Importer.",
            size="2",
            color_scheme="gray",
        ),
        rx.button("Log in", on_click=AuthState.start_login, width="100%"),
        rx.text(
            "No account? ",
            rx.link("Create one", on_click=AuthState.start_register, href="#"),
        ),
    )

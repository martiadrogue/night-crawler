import reflex as rx

from night_crawler.pages import (  # noqa: F401 - registers the pages
    auth_callback,
    crawler_detail,
    crawler_history,
    crawlers,
    datasets,
    login,
    rate_limits,
    register,
    runs,
    sources,
    users,
    version_editor,
)
from night_crawler.state.auth_state import AuthState


def index() -> rx.Component:
    return rx.center(rx.spinner(), min_height="100vh")


app = rx.App()
app.add_page(index, route="/", on_load=AuthState.redirect_from_index)

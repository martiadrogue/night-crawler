import reflex as rx

from night_crawler.state.auth_state import AuthState


def navbar() -> rx.Component:
    return rx.hstack(
        rx.link(rx.heading("Night Crawler", size="5"), href="/crawlers"),
        rx.spacer(),
        rx.cond(
            AuthState.is_authenticated,
            rx.hstack(
                rx.link("Crawlers", href="/crawlers"),
                rx.link("Runs", href="/runs"),
                rx.link("Sources", href="/sources"),
                rx.link("Datasets", href="/datasets"),
                rx.link("Rate limits", href="/rate-limits"),
                rx.text(AuthState.email, color_scheme="gray"),
                rx.button("Log out", on_click=AuthState.logout, variant="soft"),
                spacing="4",
                align="center",
            ),
        ),
        width="100%",
        padding="1em",
        border_bottom="1px solid var(--gray-5)",
        align="center",
    )


def breadcrumbs(
    items: list[tuple[str | rx.Var, str | rx.Var]],
) -> rx.Component:
    """Render linked ancestor locations as a breadcrumb trail."""
    parts = []
    for index, (label, href) in enumerate(items):
        if index:
            parts.append(rx.text("/", size="1", color_scheme="gray"))
        parts.append(rx.link(label, href=href, size="2"))
    return rx.hstack(
        *parts,
        align="center",
        spacing="2",
        flex_wrap="wrap",
    )


def page_shell(*children: rx.Component) -> rx.Component:
    return rx.vstack(
        navbar(),
        rx.container(
            *children,
            padding="2em",
            size="4",
            margin="0 auto",
            width="100%",
            min_width="min(100%, 20rem)",
            box_sizing="border-box",
        ),
        width="100%",
        spacing="0",
    )


def error_callout(message: rx.Var) -> rx.Component:
    return rx.cond(
        message != "",
        rx.callout(message, icon="triangle_alert", color_scheme="red", width="100%"),
    )


def status_badge(status: rx.Var) -> rx.Component:
    return rx.badge(
        status,
        color_scheme=rx.match(
            status,
            ("published", "green"),
            ("draft", "amber"),
            ("pending", "amber"),
            ("running", "blue"),
            ("parsing", "blue"),
            ("succeeded", "green"),
            ("parsed", "green"),
            ("failed", "red"),
            "gray",
        ),
    )

import reflex as rx

from night_crawler.forms import NO_SELECTION


def labelled(label: str, control: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"), control, spacing="1", width="100%"
    )


def choice(options: list[str], value, on_change, **props) -> rx.Component:
    """A select over fixed string options."""
    return rx.select(options, value=value, on_change=on_change, width="100%", **props)


def id_choice(options: rx.Var, value, on_change, **props) -> rx.Component:
    """A select over `{value, label}` pairs where one must be picked."""
    return rx.select.root(
        rx.select.trigger(placeholder="Pick one", width="100%"),
        rx.select.content(
            rx.foreach(
                options,
                lambda option: rx.select.item(option["label"], value=option["value"]),
            ),
        ),
        value=value,
        on_change=on_change,
        **props,
    )


def optional_id_choice(options: rx.Var, value, on_change, **props) -> rx.Component:
    """A select over `{value, label}` pairs, plus a "none" item.

    Radix selects can't hold "", so "none" is `NO_SELECTION`.
    """
    return rx.select.root(
        rx.select.trigger(width="100%"),
        rx.select.content(
            rx.select.item("— none —", value=NO_SELECTION),
            rx.foreach(
                options,
                lambda option: rx.select.item(option["label"], value=option["value"]),
            ),
        ),
        value=value,
        on_change=on_change,
        **props,
    )


def checkbox_field(name: str, label: str, checked, key) -> rx.Component:
    return rx.text(
        rx.checkbox(name=name, default_checked=checked, key=key),
        " ",
        label,
        as_="label",
        size="2",
    )

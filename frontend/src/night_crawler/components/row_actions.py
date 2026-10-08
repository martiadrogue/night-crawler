from dataclasses import dataclass
from typing import Any

import reflex as rx

MAX_VISIBLE_ACTIONS = 3
"""Buttons a table row shows; past that, 2 stay and the rest go to ⋯."""


@dataclass(frozen=True)
class RowAction:
    """One action of a table row: its label, event, and colour."""

    label: str
    on_click: Any
    color_scheme: str | None = None


def row_actions(actions: list[RowAction]) -> rx.Component:
    """Render a row's actions, folding the extra ones into a ⋯ menu."""
    if len(actions) <= MAX_VISIBLE_ACTIONS:
        return rx.hstack(*map(_button, actions), spacing="2")
    shown, folded = (
        actions[: MAX_VISIBLE_ACTIONS - 1],
        actions[MAX_VISIBLE_ACTIONS - 1 :],
    )
    return rx.hstack(*map(_button, shown), _menu(folded), spacing="2", align="center")


def _button(action: RowAction) -> rx.Component:
    return rx.button(
        action.label,
        size="1",
        variant="soft",
        color_scheme=action.color_scheme,
        on_click=action.on_click,
    )


def _menu(actions: list[RowAction]) -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(
            rx.icon_button(
                rx.icon("ellipsis", size=14),
                size="1",
                variant="soft",
                color_scheme="gray",
                aria_label="More actions",
            )
        ),
        rx.menu.content(
            *(
                rx.menu.item(
                    action.label,
                    on_click=action.on_click,
                    color_scheme=action.color_scheme,
                )
                for action in actions
            ),
            size="1",
        ),
    )

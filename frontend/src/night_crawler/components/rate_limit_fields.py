import reflex as rx

from night_crawler.components.fields import labelled

NUMBER_FIELDS = (
    ("Penalty step (s, default 0)", "penalty_step_seconds"),
    ("Max penalty (s, default 0)", "max_penalty_seconds"),
    ("Decay after successes (default 1)", "decay_after_successes"),
    ("Decay step (s, default 0)", "decay_step_seconds"),
)


def _input(name: str, value, key, **props) -> rx.Component:
    return rx.input(name=name, default_value=value, key=key, width="100%", **props)


def rate_limit_fields(values: dict, key, name_label: str) -> rx.Component:
    """A rate-limit rule's inputs, shared by every form that edits one.

    `values` maps each field name (`name`, `rate_limit_string`, and the
    `NUMBER_FIELDS`) to the state var holding its starting value.
    """
    numbers = [
        labelled(label, _input(name, values[name], key, type="number", min="0"))
        for label, name in NUMBER_FIELDS
    ]
    return rx.vstack(
        labelled(name_label, _input("name", values["name"], key)),
        labelled(
            "Limit (requests per window, e.g. 5/second, 50/minute)",
            _input(
                "rate_limit_string",
                values["rate_limit_string"],
                key,
                required=True,
                font_family="monospace",
            ),
        ),
        rx.text(
            "When a request is blocked, the wait grows by the penalty step, up "
            "to the maximum; after enough successes in a row it shrinks by the "
            "decay step. Blank fields use the defaults.",
            size="1",
            color_scheme="gray",
        ),
        rx.grid(*numbers, columns="2", spacing="3", width="100%"),
        spacing="3",
        width="100%",
    )

"""Which response statuses count as a successful request."""

FIRST_ERROR_STATUS = 400
"""Without success codes, any status below this one succeeds."""


def is_success_status(status: int, success_codes: tuple[str, ...] | None) -> bool:
    """Tell whether a response status counts as a success.

    With `success_codes`, exactly those statuses succeed (e.g. `"404"`
    for a page that is meant to be missing); without, any status below
    400 does.
    """
    if None is success_codes:
        return status < FIRST_ERROR_STATUS
    return str(status) in success_codes

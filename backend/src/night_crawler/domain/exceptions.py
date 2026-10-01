"""The `AppException` hierarchy for every controlled error.

The API layer's single exception handler maps `status_code` straight to
the HTTP response, so each subclass fixes a sensible default.
"""


class AppException(Exception):
    """Base of every controlled error.

    Attributes:
        message: Human-readable summary, safe to return to clients.
        status_code: HTTP status the API layer responds with.
    """

    message: str
    status_code: int

    def __init__(self, message: str, status_code: int) -> None:
        """Store the message and HTTP status."""
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ValidationException(AppException):
    """A client-caused error: bad input, missing, or denied."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        """Default to HTTP 400; pass 401/403/404/409 as needed."""
        super().__init__(message, status_code)


class ConfigurationException(AppException):
    """A required setting is missing or invalid; fails at startup."""

    def __init__(self, message: str) -> None:
        """Always HTTP 500: the deployment is at fault."""
        super().__init__(message, 500)


class ExternalServiceException(AppException):
    """An upstream service, including the database, failed."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        """Default to HTTP 502."""
        super().__init__(message, status_code)


class RequestFailedException(ExternalServiceException):
    """A crawl request failed, with a code the retry codes can match.

    Attributes:
        failure_code: The HTTP status as text (e.g. `"503"`),
            `"timeout"`, or `None` for any other failure (a dropped
            connection).
    """

    def __init__(self, message: str, failure_code: str | None = None) -> None:
        """Keep the failure's code next to its message."""
        super().__init__(message)
        self.failure_code = failure_code


class MissingPlaceholderException(ValidationException):
    """A template uses a placeholder the Context doesn't hold.

    Absent means neither `name` nor `name[]` exists. The run can't
    continue: no retry can make the value appear.
    """

    def __init__(self, placeholder: str) -> None:
        """Always HTTP 422; keep the placeholder name for callers."""
        super().__init__(f"Required placeholder is missing: {placeholder}", 422)
        self.placeholder = placeholder

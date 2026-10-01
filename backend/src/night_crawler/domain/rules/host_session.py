"""Session sharing between requests to the same host.

Within one run, every engine (httpx, Playwright, Patchright) captures
the cookies and shareable headers a request used, and every later
request to the same exact host starts from them. A template's own
headers always win over shared ones. Matching is by exact host only: a
cookie is never handed to another host, not even a subdomain.
"""

from urllib.parse import urlsplit

from night_crawler.domain.model.value_objects import SessionState

NON_SHAREABLE_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "content-type",
        "cookie",
        "connection",
        "transfer-encoding",
        "accept-encoding",
    }
)
"""Headers that describe one request, not the client sending it."""


def resolve_request_host(url: str) -> str | None:
    """Return the lower-cased exact host of `url`, if it has one."""
    host = urlsplit(url).hostname
    return None if None is host else host.lower()


def shareable_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return the headers a later request may reuse, names lower-cased.

    HTTP/2 pseudo-headers (`:authority`) and request-specific ones are
    dropped.
    """
    return {
        name.lower(): value
        for name, value in headers.items()
        if not name.startswith(":") and name.lower() not in NON_SHAREABLE_HEADERS
    }


def merge_session(
    existing: SessionState | None, captured: SessionState
) -> SessionState:
    """Fold one request's capture into the host's session.

    Newer values win key by key; nothing captured never erases what
    earlier requests saved.
    """
    if None is existing:
        return captured
    return SessionState(
        cookies={**existing.cookies, **captured.cookies},
        headers={**existing.headers, **captured.headers},
    )


def build_request_headers(
    template_headers: dict[str, str], session: SessionState | None
) -> dict[str, str]:
    """Return the headers to send: shared ones, then the template's.

    Shared cookies go into the `Cookie` header, merged with any cookie
    pairs the template sets itself (the template's win).
    """
    if None is session:
        return dict(template_headers)
    headers = {
        **_without_names(session.headers, set(map(str.lower, template_headers))),
        **_without_names(template_headers, {"cookie"}),
    }
    cookies = merge_cookies(session.cookies, template_headers)
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return headers


def merge_cookies(
    shared: dict[str, str], template_headers: dict[str, str]
) -> dict[str, str]:
    """Return shared cookies overlaid with the template's `Cookie`."""
    return {**shared, **parse_cookie_header(find_header(template_headers, "cookie"))}


def find_header(headers: dict[str, str], name: str) -> str | None:
    """Return a header's value, matching `name` case-insensitively."""
    return next((v for k, v in headers.items() if name == k.lower()), None)


def parse_cookie_header(raw: str | None) -> dict[str, str]:
    """Return the name/value pairs of a `Cookie` header value."""
    pairs = (pair.strip().split("=", 1) for pair in (raw or "").split(";"))
    return {pair[0]: pair[1] for pair in pairs if 2 == len(pair)}


def _without_names(headers: dict[str, str], names: set[str]) -> dict[str, str]:
    """Return `headers` minus the ones named in `names` (lower-case)."""
    return {k: v for k, v in headers.items() if k.lower() not in names}

"""The domain's fixed vocabulary: built-in datasets, columns, queues."""

from typing import Any

ITEM_ID_COLUMN = "item_id"
"""The column every dataset requires: the item's own ID on its website.

With the Crawler's Source it is the record's de-duplication key.
"""

_ITEM_ID_FIELD: dict[str, Any] = {
    "name": ITEM_ID_COLUMN,
    "is_required": True,
    "is_unique": True,
}
_URL_PATTERN = r"^https?://"

BUILT_IN_DATASETS: tuple[dict[str, Any], ...] = (
    {
        "name": "venues",
        "fields": [
            {"name": "row_type"},
            _ITEM_ID_FIELD,
            {"name": "source_url", "pattern": _URL_PATTERN},
            {"name": "name", "is_required": True},
            {"name": "address"},
            {"name": "location"},
            {"name": "categories"},
            {"name": "phone"},
            {"name": "website", "pattern": _URL_PATTERN},
            {"name": "reservation_url", "pattern": _URL_PATTERN},
            {"name": "menu_url", "pattern": _URL_PATTERN},
            {"name": "rating", "type": "float"},
            {"name": "review_count", "type": "integer"},
            {"name": "price_range"},
            {"name": "opening_hours"},
            {"name": "popular_times"},
            {"name": "live_occupancy", "type": "integer"},
            {"name": "attributes"},
            {"name": "about"},
        ],
    },
    {
        "name": "reviews",
        "fields": [
            _ITEM_ID_FIELD,
            {"name": "venue_item_id", "is_required": True},
            {"name": "reviewer_name"},
            {"name": "rating", "type": "integer"},
            {"name": "published_at"},
            {"name": "published_at_text"},
            {"name": "is_published_at_approximate", "type": "boolean"},
            {"name": "text"},
        ],
    },
    {
        "name": "menus",
        "fields": [
            _ITEM_ID_FIELD,
            {"name": "venue_item_id", "is_required": True},
            {"name": "source_url", "pattern": _URL_PATTERN},
            {"name": "section_name"},
            {"name": "section_description"},
            {"name": "item_name", "is_required": True},
            {"name": "item_description"},
            {"name": "item_price", "type": "float"},
            {"name": "item_currency"},
            {"name": "item_price_text"},
        ],
    },
)
"""The Datasets created at startup when missing (DOMAIN_MODEL §5.3).

Each field lists only what differs from `DatasetField`'s defaults. A
menu belongs to one venue and is keyed by it, so a menus Crawler
harvests the venue's ID as both `item_id` and `venue_item_id`.
"""

SCHEMA_FIELD_TYPES: tuple[str, ...] = ("string", "boolean", "integer", "float")
"""The types a Dataset field may declare."""

DEFAULT_SCHEMA_FIELD_TYPE = "string"

SELECTOR_SOURCES: tuple[str, ...] = ("content", "headers", "url", "context")
"""What a selector reads: the body, the response headers, the URL, or a
placeholder's value in the template's run."""

CONTEXT_SELECTOR_TYPES: tuple[str, ...] = ("value", "boolean")
"""The only selector types that may read the `context` source."""

DEFAULT_SELECTOR_SOURCE = "content"

EXECUTION_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)
"""A run's lifecycle: waiting for a worker, running, or ended."""

PARSING_STATUSES: tuple[str, ...] = ("pending", "parsing", "parsed", "failed")
"""Where a run's harvest stands on the way into its dataset CSV."""

EXECUTION_QUEUES: tuple[str, ...] = ("discovery", "priority", "real-time", "testing")
"""The Celery queues a run can be routed onto."""

DEFAULT_EXECUTION_QUEUE = "discovery"

TESTING_QUEUE = "testing"
"""Where test runs of any version go; never a Crawler's own queue."""

CRAWLER_QUEUES: tuple[str, ...] = tuple(
    queue for queue in EXECUTION_QUEUES if TESTING_QUEUE != queue
)
"""The queues a Crawler's scheduled and manual runs can use."""

IMPORT_QUEUE = "dataset-import"
"""Where dataset imports run; never a Crawler Version's queue."""

RENDER_MODES: tuple[str, ...] = ("none", "playwright", "stealth")
"""The engines a template can dispatch through.

`none` is plain httpx; `playwright` renders in Chromium; `stealth`
renders in Patchright, a Playwright fork that hides the automation
signals bot detection looks for.
"""

DEFAULT_RENDER_MODE = "none"

DEFAULT_TTL_SECONDS = 20
"""Per-dispatch timeout used when a Message Aid sets no `ttl`."""

DEFAULT_RETRY_CODES: tuple[str, ...] = ("429", "500", "502", "503", "504")
"""Failure codes retried when a Message Aid sets none.

Codes are strings so the list can also hold the `"timeout"` sentinel.
"""

DEFAULT_MAX_RETRY_ATTEMPTS = 3
"""Retries after a request's first try, when a Message Aid sets none."""

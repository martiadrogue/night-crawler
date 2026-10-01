"""Collections, indexes, and `$jsonSchema` validators.

There are no migrations: `initialize_database` runs at startup and is
idempotent. Adding an index or changing a validator here is picked up on
the next start; changing an existing index's options, or reshaping
existing documents, must be done by hand (or `make restart-db`).
"""

import logging
from typing import Any

from night_crawler.domain.model.constants import (
    CRAWLER_QUEUES,
    EXECUTION_QUEUES,
    EXECUTION_STATUSES,
    PARSING_STATUSES,
    RENDER_MODES,
    SELECTOR_SOURCES,
)
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid

logger = logging.getLogger(__name__)

_INTEGER_TYPES = ["int", "long"]


def _enum(*values: str) -> dict[str, Any]:
    """Return a validator rule accepting only `values`."""
    return {"enum": list(values)}


def _integer(minimum: int, is_nullable: bool = False) -> dict[str, Any]:
    """Return a validator rule for an integer of at least `minimum`."""
    bson_types = [*_INTEGER_TYPES, "null"] if is_nullable else _INTEGER_TYPES
    return {"bsonType": bson_types, "minimum": minimum}


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    """Return a `$jsonSchema` validator checking `properties`."""
    return {"$jsonSchema": {"bsonType": "object", "properties": properties}}


VALIDATORS: dict[str, dict[str, Any]] = {
    "users": _object(role=_enum("admin", "user", "viewer")),
    "sources": _object(),
    "datasets": _object(),
    "crawlers": _object(queue=_enum(*CRAWLER_QUEUES)),
    "crawler_versions": _object(status=_enum("draft", "published", "archived")),
    "message_templates": _object(
        action=_enum("GET", "POST", "PUT", "PATCH", "DELETE", "CLICK")
    ),
    "message_selectors": _object(
        type=_enum("value", "iterator", "boolean", "click", "select", "pagination"),
        source=_enum(*SELECTOR_SOURCES),
    ),
    "message_aids": _object(
        render_mode=_enum(*RENDER_MODES),
        ttl=_integer(1, is_nullable=True),
        max_retry_attempts=_integer(0, is_nullable=True),
    ),
    "message_aid_proxies": _object(),
    "message_aid_rate_limits": _object(
        penalty_step_seconds=_integer(0),
        max_penalty_seconds=_integer(0),
        decay_after_successes=_integer(1),
        decay_step_seconds=_integer(0),
    ),
    "crawler_executions": _object(
        status=_enum(*EXECUTION_STATUSES),
        parsing_status=_enum(*PARSING_STATUSES),
        queue=_enum(*EXECUTION_QUEUES),
        resume_count=_integer(0),
    ),
    "crawler_execution_contexts": _object(position=_integer(0, is_nullable=True)),
    "crawler_execution_datasets": _object(
        row_count=_integer(0),
        import_status=_enum("pending", "importing", "imported", "failed"),
    ),
}
"""Enum and range rules (DOMAIN_MODEL DM-5, DM-6), per collection."""

INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel("email", unique=True)],
    "sources": [IndexModel("name", unique=True)],
    "datasets": [IndexModel("name", unique=True)],
    "crawlers": [
        IndexModel("user_id"),
        IndexModel("source_id"),
        IndexModel("dataset_id"),
        IndexModel([("created_at", DESCENDING)]),
    ],
    "crawler_versions": [
        IndexModel([("crawler_id", ASCENDING), ("created_at", ASCENDING)]),
        IndexModel(
            "crawler_id",
            unique=True,
            partialFilterExpression={"status": "draft"},
            name="one_draft_per_crawler",
        ),
        IndexModel(
            "crawler_id",
            unique=True,
            partialFilterExpression={"status": "published"},
            name="one_published_per_crawler",
        ),
        IndexModel("user_id"),
    ],
    "message_templates": [IndexModel("crawler_version_id")],
    "message_selectors": [IndexModel("message_template_id")],
    "message_aids": [
        IndexModel("message_template_id", unique=True),
        IndexModel("selected_proxy_id"),
        IndexModel("rate_limit_id"),
    ],
    "message_aid_proxies": [IndexModel("rate_limit_id")],
    "message_aid_rate_limits": [],
    "crawler_executions": [
        IndexModel([("crawler_id", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel("crawler_version_id"),
        IndexModel([("created_at", DESCENDING)]),
        IndexModel([("status", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel([("parsing_status", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel([("queue", ASCENDING), ("created_at", DESCENDING)]),
    ],
    "crawler_execution_contexts": [
        IndexModel(
            [
                ("crawler_execution_id", ASCENDING),
                ("key", ASCENDING),
                ("position", ASCENDING),
            ],
            unique=True,
            name="one_value_per_key_and_position",
        ),
    ],
    "crawler_execution_datasets": [
        IndexModel("crawler_execution_id", unique=True),
    ],
}
"""Natural keys (DM-1, DM-3, DM-4, DM-7) and reference lookups."""


async def initialize_database(database: AsyncDatabase) -> None:
    """Create missing collections, then apply validators and indexes.

    Collections must exist before the first transaction: MongoDB can't
    create one with a validator inside a transaction.
    """
    existing = set(await database.list_collection_names())
    for name, validator in VALIDATORS.items():
        if name not in existing:
            await _create_collection(database, name, validator)
        else:
            await database.command("collMod", name, validator=validator)
        if INDEXES[name]:
            await database[name].create_indexes(INDEXES[name])
    logger.info("Database initialized: %s", database.name)


async def _create_collection(
    database: AsyncDatabase, name: str, validator: dict[str, Any]
) -> None:
    """Create a collection with its validator.

    Tolerates another process creating it first (several containers
    start at once); the validator is then applied with `collMod`.
    """
    try:
        await database.create_collection(name, validator=validator)
    except CollectionInvalid:
        await database.command("collMod", name, validator=validator)

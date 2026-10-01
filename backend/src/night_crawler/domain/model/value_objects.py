"""Value objects shared across the domain: no id, immutable."""

from dataclasses import dataclass, field
from typing import Any

from night_crawler.domain.model.constants import DEFAULT_SCHEMA_FIELD_TYPE


@dataclass(frozen=True)
class RenderedRequest:
    """One template run with every placeholder substituted.

    Attributes:
        action: HTTP method.
        url: Target URL.
        body: Request body, if any.
        headers: The template's own headers.
        fanned_out_values: The list element picked for each `name[]`
            placeholder in this run, keyed by bare name.
        placeholder_values: Every placeholder value this run used,
            single and fanned-out, keyed by bare name.
    """

    action: str
    url: str
    body: str | None
    headers: dict[str, Any]
    fanned_out_values: dict[str, Any] = field(default_factory=dict)
    placeholder_values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionState:
    """What one request shares with the next one to the same host.

    Captured by every engine and applied by every engine, so it flows
    between httpx and the headless browsers in both directions.

    Attributes:
        cookies: Cookie name to value.
        headers: Shareable request headers, lower-cased names (e.g.
            `user-agent`, `accept-language`, client hints, custom
            ones).
    """

    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Harvest:
    """What a selector tree read from one response.

    Attributes:
        rows: One row per match of the innermost iterator or click
            (one row when there is none), title to value.
        array_titles: Titles read inside an iterator or click; they
            become `title[]` lists in the Context.
    """

    rows: list[dict[str, Any]]
    array_titles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DatasetField:
    """One field a Dataset holds, and the rules its values follow.

    Attributes:
        name: The CSV column and the selector title that harvests it.
        type: One of `SCHEMA_FIELD_TYPES`.
        is_required: Every Crawler on the Dataset lists it in its
            `fields`, and a row without a value is dropped.
        is_unique: No two records of one Source share a value.
        pattern: A regex the value should match, or `None`.
    """

    name: str
    type: str = DEFAULT_SCHEMA_FIELD_TYPE
    is_required: bool = False
    is_unique: bool = False
    pattern: str | None = None


@dataclass(frozen=True)
class DatasetValidation:
    """What validating a run's dataset rows found (DOMAIN_MODEL §5.4).

    Attributes:
        rows_checked: Rows the run produced, before any was dropped.
        rows_dropped_missing_required: Rows dropped for an empty
            required field.
        rows_dropped_duplicate: Rows dropped for repeating a unique
            field's value; the first such row is kept.
        type_mismatches: Values not of their field's type, per field.
        pattern_mismatches: Values not matching their field's pattern,
            per field.
        empty_columns: The Crawler's fields with no value in any row.
        is_valid: No required drop, no mismatch, no empty column;
            duplicates alone don't make a dataset invalid.
    """

    rows_checked: int = 0
    rows_dropped_missing_required: int = 0
    rows_dropped_duplicate: int = 0
    type_mismatches: dict[str, int] = field(default_factory=dict)
    pattern_mismatches: dict[str, int] = field(default_factory=dict)
    empty_columns: tuple[str, ...] = ()
    is_valid: bool = True


@dataclass(frozen=True)
class RateLimitRule:
    """What the rate limiter enforces for one key.

    Built from a `MessageAidRateLimit` (DOMAIN_MODEL §4.8).

    Attributes:
        rate_limit_string: The sliding window, `limits` syntax (e.g.
            `5/second`).
        penalty_step_seconds: Extra wait added by each block.
        max_penalty_seconds: The most the extra wait can grow to.
        decay_after_successes: Successes in a row that shrink it.
        decay_step_seconds: How much each such streak removes.
    """

    rate_limit_string: str
    penalty_step_seconds: int
    max_penalty_seconds: int
    decay_after_successes: int
    decay_step_seconds: int


@dataclass(frozen=True)
class RateLimitTarget:
    """One rate-limit bucket a request waits on.

    Attributes:
        key: `domain:<host>` (the exact host) or `proxy:<id>`.
        rule: What that bucket enforces.
    """

    key: str
    rule: RateLimitRule

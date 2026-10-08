"""Keeping a browser agent's recording under its stored size cap.

A recording is stored on its Instruction Generation, one MongoDB
document of at most 16 MiB, and returned to clients on request, so it
is cut to a much smaller cap (`GENERATION_RECORDING_MAX_BYTES`).
"""

import json
from dataclasses import asdict, replace
from typing import Any

from night_crawler.domain.ports.browser_agent_recorder import (
    AgentRecording,
    AgentRequest,
)

DOCUMENT_RESOURCE_TYPE = "document"
"""The one resource type never dropped: the pages the agent read."""


def measure_recording(recording: AgentRecording) -> int:
    """Return the recording's size in bytes, as UTF-8 JSON."""
    return _measure(asdict(recording))


def cap_recording(recording: AgentRecording, max_bytes: int) -> AgentRecording:
    """Return the recording cut to at most `max_bytes`, if it can be.

    Response bodies go first, largest first, since they are the bulk
    and a few large ones usually do it. Then whole non-document
    requests (scripts, images, API calls), oldest first: the latest
    ones are closest to the data the agent ended on. Documents, steps,
    and the final result are always kept, so a recording made of
    those alone may stay over the cap. A cut recording is marked
    `is_truncated`.
    """
    size = measure_recording(recording)
    if size <= max_bytes:
        return recording
    requests, size = _drop_bodies(list(recording.requests), size, max_bytes)
    requests = _drop_oldest_non_documents(requests, size, max_bytes)
    return replace(recording, requests=tuple(requests), is_truncated=True)


def _drop_bodies(
    requests: list[AgentRequest], size: int, max_bytes: int
) -> tuple[list[AgentRequest], int]:
    """Drop response bodies, largest first, until `size` fits."""
    with_bodies = [i for i, request in enumerate(requests) if request.response_body]
    with_bodies.sort(key=lambda i: len(requests[i].response_body), reverse=True)
    for i in with_bodies:
        if size <= max_bytes:
            break
        bodiless = replace(
            requests[i], response_body=None, is_response_body_truncated=True
        )
        size -= _measure(asdict(requests[i])) - _measure(asdict(bodiless))
        requests[i] = bodiless
    return requests, size


def _drop_oldest_non_documents(
    requests: list[AgentRequest], size: int, max_bytes: int
) -> list[AgentRequest]:
    """Drop non-document requests, oldest first, until `size` fits."""
    kept = []
    for request in requests:
        if size > max_bytes and DOCUMENT_RESOURCE_TYPE != request.resource_type:
            # Each array element also takes its `, ` separator.
            size -= _measure(asdict(request)) + len(", ")
            continue
        kept.append(request)
    return kept


def _measure(value: Any) -> int:
    """Return the size of `value` in bytes, as UTF-8 JSON."""
    return len(json.dumps(value, ensure_ascii=False).encode())

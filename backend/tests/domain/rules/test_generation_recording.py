from dataclasses import replace

from night_crawler.domain.ports.browser_agent_recorder import (
    AgentFinalResult,
    AgentRecording,
    AgentRequest,
    AgentStep,
)
from night_crawler.domain.rules.generation_recording import (
    cap_recording,
    measure_recording,
)


def _request(url, resource_type, body=None):
    return AgentRequest(
        step_index=0,
        url=url,
        method="GET",
        resource_type=resource_type,
        status=200,
        response_body=body,
    )


def _recording(*requests):
    return AgentRecording(
        steps=(
            AgentStep(index=0, action="navigate", url="https://a", is_success=True),
        ),
        requests=tuple(requests),
        final_result=AgentFinalResult(data=[{"name": "A"}], is_success=True),
    )


def test_a_recording_under_the_cap_is_kept_whole():
    recording = _recording(_request("https://a/", "document", "x" * 100))

    assert recording == cap_recording(recording, measure_recording(recording))


def test_bodies_are_dropped_first_largest_first():
    recording = _recording(
        _request("https://a/", "document", "d" * 300),
        _request("https://a/api", "xhr", "j" * 1000),
        _request("https://a/logo.png", "image"),
    )

    capped = cap_recording(recording, measure_recording(recording) - 500)

    assert capped.is_truncated
    assert ["https://a/", "https://a/api", "https://a/logo.png"] == [
        request.url for request in capped.requests
    ]
    assert ["d" * 300, None, None] == [r.response_body for r in capped.requests]
    assert capped.requests[1].is_response_body_truncated
    assert measure_recording(capped) <= measure_recording(recording) - 500


def test_then_the_oldest_non_document_requests_are_dropped():
    document = _request("https://a/", "document", "d" * 50)
    old, new = _request("https://a/old.js", "script"), _request(
        "https://a/new.js", "script"
    )
    recording = _recording(old, document, new)
    bodiless = _recording(
        old, replace(document, response_body=None, is_response_body_truncated=True), new
    )

    capped = cap_recording(recording, measure_recording(bodiless) - 10)

    assert capped.is_truncated
    assert ["https://a/", "https://a/new.js"] == [r.url for r in capped.requests]
    assert None is capped.requests[0].response_body
    assert measure_recording(capped) <= measure_recording(bodiless) - 10


def test_document_requests_and_steps_are_never_dropped():
    recording = _recording(
        _request("https://a/", "document"), _request("https://a/x.js", "script")
    )

    capped = cap_recording(recording, 1)

    assert ["https://a/"] == [request.url for request in capped.requests]
    assert recording.steps == capped.steps
    assert recording.final_result == capped.final_result

"""Request and response models for Instruction Generations."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

GenerationStatus = Literal["pending", "running", "succeeded", "failed"]
"""Mirrors the domain's `INSTRUCTION_GENERATION_STATUSES`."""

Prompt = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class InstructionGenerationCreate(BaseModel):
    """Body asking the AI agent to write a version's instructions."""

    prompt: Prompt


class AgentStepOut(BaseModel):
    """One action of the browser agent (DOMAIN_MODEL §4.16)."""

    model_config = ConfigDict(from_attributes=True)

    index: int
    action: str | None
    params: dict[str, Any]
    target_xpath: str | None
    url: str | None
    is_success: bool
    error: str | None


class AgentRequestOut(BaseModel):
    """One request the browser agent's browser made."""

    model_config = ConfigDict(from_attributes=True)

    step_index: int
    url: str
    method: str
    resource_type: str | None
    request_headers: dict[str, str]
    post_body: str | None
    status: int | None
    response_headers: dict[str, str]
    response_body: str | None
    is_response_body_truncated: bool
    failure: str | None


class AgentFinalResultOut(BaseModel):
    """What the browser agent extracted."""

    model_config = ConfigDict(from_attributes=True)

    data: Any
    is_success: bool


class AgentRecordingOut(BaseModel):
    """What the browser agent did, as stored on its generation."""

    model_config = ConfigDict(from_attributes=True)

    steps: list[AgentStepOut]
    requests: list[AgentRequestOut]
    final_result: AgentFinalResultOut
    is_truncated: bool


class FilteredRequestOut(BaseModel):
    """A recorded request instructions were written from, and why."""

    model_config = ConfigDict(from_attributes=True)

    url: str
    method: str
    status: int | None
    reasons: list[str]


class InstructionGenerationOut(BaseModel):
    """An Instruction Generation as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    crawler_id: str
    crawler_version_id: str | None
    user_id: str
    prompt: str
    status: GenerationStatus
    error: str | None
    result_version_id: str | None
    test_execution_id: str | None
    instructions_yaml: str | None
    recording: AgentRecordingOut | None = None
    filtered_requests: list[FilteredRequestOut] = []
    required_context_keys: list[str] = []
    warnings: list[str] = []
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

"""Server-side HTTP client for the Night Crawler API.

Every call runs inside a Reflex event handler on the Reflex backend,
never in the browser: the browser only talks to Reflex over its state
websocket, so the API needs no CORS setup. Logging in is Keycloak's
(`oidc_client.py`); every function here takes its access token first.
"""

import os
import re
from typing import Any
from urllib.parse import quote

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TIMEOUT_SECONDS = 15.0
TRANSPORT: httpx.AsyncBaseTransport | None = None
"""Replaced in tests with `httpx.MockTransport`; `None` uses the network."""
UNREACHABLE_MESSAGE = "The API is unreachable. Try again shortly."


class ApiError(Exception):
    """A non-2xx response, with the API's message."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"{status_code}: {message}")


def _extract_message(status_code: int, body: object, raw_text: str) -> str:
    fallback = raw_text or f"Request failed with status {status_code}"
    if not isinstance(body, dict):
        return fallback
    # The API's own errors: {"message": "..."} (api/exception_handler.py).
    if "message" in body:
        return str(body["message"])
    # FastAPI request validation: {"detail": [{"loc": [...], "msg": ...}]}.
    if "detail" in body:
        return _detail_message(body["detail"])
    return fallback


def _detail_message(detail: object) -> str:
    """Return FastAPI's `detail`, joining validation errors."""
    if not isinstance(detail, list):
        return str(detail)
    return "; ".join(
        f"{'.'.join(str(part) for part in item.get('loc', []))}: "
        f"{item.get('msg', '')}"
        for item in detail
    )


async def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json: object | None = None,
    params: dict | None = None,
) -> Any:
    response = await _send(method, path, token=token, json=json, params=params)
    return response.json() if response.content else None


async def _send(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json: object | None = None,
    params: dict | None = None,
    text: str | None = None,
) -> httpx.Response:
    """Send one request and return the response, raising on errors.

    `text` is sent as is, as YAML, instead of `json`. An API that can't
    be reached (down, restarting, timing out) is an `ApiError` 503 too,
    so pages show it in their callout instead of crashing the handler.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if text is not None:
        headers["Content-Type"] = "application/yaml"
    try:
        async with httpx.AsyncClient(
            base_url=API_BASE_URL, timeout=TIMEOUT_SECONDS, transport=TRANSPORT
        ) as client:
            response = await client.request(
                method,
                path,
                json=json,
                content=text,
                params=_query(params),
                headers=headers,
            )
    except httpx.TransportError as exc:
        raise ApiError(503, UNREACHABLE_MESSAGE) from exc
    _raise_for_status(response)
    return response


def _query(params: dict | None) -> dict:
    """Return the query parameters, leaving out the unset ones."""
    return {key: value for key, value in (params or {}).items() if value is not None}


def _raise_for_status(response: httpx.Response) -> None:
    """Raise `ApiError` with the API's message for a non-2xx response."""
    if response.status_code < 400:
        return
    try:
        body = response.json()
    except ValueError:
        body = None
    raise ApiError(
        response.status_code,
        _extract_message(response.status_code, body, response.text),
    )


async def download_execution_sample_csv(
    token: str, execution_id: str
) -> tuple[str, str]:
    """Return a finished run's Sample CSV (at most 800 rows): name and text.

    The name is the API's (`Content-Disposition`), with the run's start
    time in it; `<execution_id>-sample.csv` if the API sends none.
    """
    response = await _send(
        "GET",
        f"/api/crawler-executions/{execution_id}/dataset-sample.csv",
        token=token,
    )
    filename = _attachment_filename(response) or f"{execution_id}-sample.csv"
    return filename, response.text


def _attachment_filename(response: httpx.Response) -> str | None:
    """Return the file name a `Content-Disposition` header gives, if any."""
    match = re.search(
        r'filename="([^"]+)"', response.headers.get("content-disposition", "")
    )
    return match.group(1) if match else None


# --- Crawler Context ---------------------------------------------------------
async def get_context(token: str, crawler_id: str) -> dict:
    """Return the latest run's Context, which the next run inherits."""
    return await _request("GET", f"/api/crawlers/{crawler_id}/context", token=token)


async def set_context_value(token: str, crawler_id: str, key: str, value) -> dict:
    return await _request(
        "PUT",
        f"/api/crawlers/{crawler_id}/context/{quote(key, safe='')}",
        token=token,
        json={"value": value},
    )


async def delete_context_value(token: str, crawler_id: str, key: str) -> None:
    await _request(
        "DELETE",
        f"/api/crawlers/{crawler_id}/context/{quote(key, safe='')}",
        token=token,
    )


# --- Crawler Executions ------------------------------------------------------
async def list_executions(token: str, params: dict) -> dict:
    """Return one page of every crawler's runs; `None` params are dropped."""
    return await _request("GET", "/api/crawler-executions", token=token, params=params)


async def get_execution_history(token: str, crawler_id: str, days: int = 30) -> dict:
    """Return a crawler's runs of the last `days` days, with outcome counts."""
    return await _request(
        "GET",
        f"/api/crawlers/{crawler_id}/execution-history",
        token=token,
        params={"days": days},
    )


async def get_execution_summary(token: str, crawler_id: str) -> dict:
    """Return a crawler's streak, success rate, and average duration."""
    return await _request(
        "GET", f"/api/crawlers/{crawler_id}/execution-summary", token=token
    )


# --- Crawlers ----------------------------------------------------------------
async def list_crawlers(
    token: str, source: str | None = None, dataset: str | None = None
) -> list[dict]:
    return await _request(
        "GET",
        "/api/crawlers",
        token=token,
        params={"source": source, "dataset": dataset},
    )


async def get_crawler(token: str, crawler_id: str) -> dict:
    return await _request("GET", f"/api/crawlers/{crawler_id}", token=token)


async def create_crawler(token: str, payload: dict) -> dict:
    return await _request("POST", "/api/crawlers", token=token, json=payload)


async def update_crawler(token: str, crawler_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/crawlers/{crawler_id}", token=token, json=payload
    )


async def delete_crawler(token: str, crawler_id: str) -> None:
    await _request("DELETE", f"/api/crawlers/{crawler_id}", token=token)


# --- Crawler Versions ----------------------------------------------------------
async def list_versions(token: str, crawler_id: str) -> list[dict]:
    return await _request("GET", f"/api/crawlers/{crawler_id}/versions", token=token)


async def get_version(token: str, version_id: str) -> dict:
    return await _request("GET", f"/api/crawler-versions/{version_id}", token=token)


async def create_draft(token: str, crawler_id: str) -> dict:
    return await _request(
        "POST", f"/api/crawlers/{crawler_id}/versions/draft", token=token
    )


async def publish_version(token: str, crawler_id: str, version_id: str) -> dict:
    return await _request(
        "POST",
        f"/api/crawlers/{crawler_id}/versions/{version_id}/publish",
        token=token,
    )


async def update_version(token: str, version_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/crawler-versions/{version_id}", token=token, json=payload
    )


async def set_root_template(token: str, version_id: str, template_id: str) -> dict:
    return await _request(
        "PUT",
        f"/api/crawler-versions/{version_id}/root-template",
        token=token,
        json={"message_template_id": template_id},
    )


async def delete_version(token: str, version_id: str) -> None:
    await _request("DELETE", f"/api/crawler-versions/{version_id}", token=token)


async def export_instructions(token: str, version_id: str) -> str:
    """Return a version's instructions as YAML text."""
    response = await _send(
        "GET", f"/api/crawler-versions/{version_id}/instructions", token=token
    )
    return response.text


async def import_instructions(token: str, version_id: str, text: str) -> dict:
    """Replace a version's instructions; return the version it landed on.

    A published version lands on a new draft.
    """
    response = await _send(
        "PUT",
        f"/api/crawler-versions/{version_id}/instructions",
        token=token,
        text=text,
    )
    return response.json()


async def create_test_execution(token: str, version_id: str) -> dict:
    return await _request(
        "POST", f"/api/crawler-versions/{version_id}/test-executions", token=token
    )


async def get_execution(token: str, execution_id: str) -> dict:
    return await _request("GET", f"/api/crawler-executions/{execution_id}", token=token)


# --- Instruction Generations -------------------------------------------------
async def create_instruction_generation(
    token: str, version_id: str, prompt: str
) -> dict:
    """Ask the AI agents to write a version's instructions; return the job.

    The API answers 202 with the pending generation, to poll.
    """
    return await _request(
        "POST",
        f"/api/crawler-versions/{version_id}/instruction-generations",
        token=token,
        json={"prompt": prompt},
    )


async def get_instruction_generation(token: str, generation_id: str) -> dict:
    """Return a generation, without its recording, for polling."""
    return await _request(
        "GET", f"/api/instruction-generations/{generation_id}", token=token
    )


# --- Message Templates -------------------------------------------------------
async def list_templates(token: str, version_id: str) -> list[dict]:
    return await _request(
        "GET", f"/api/crawler-versions/{version_id}/templates", token=token
    )


async def create_template(token: str, version_id: str, payload: dict) -> dict:
    return await _request(
        "POST",
        f"/api/crawler-versions/{version_id}/templates",
        token=token,
        json=payload,
    )


async def update_template(token: str, template_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/templates/{template_id}", token=token, json=payload
    )


async def delete_template(token: str, template_id: str) -> None:
    await _request("DELETE", f"/api/templates/{template_id}", token=token)


# --- Message Selectors -------------------------------------------------------
async def list_selectors(token: str, template_id: str) -> list[dict]:
    return await _request("GET", f"/api/templates/{template_id}/selectors", token=token)


async def create_selector(token: str, template_id: str, payload: dict) -> dict:
    return await _request(
        "POST", f"/api/templates/{template_id}/selectors", token=token, json=payload
    )


async def update_selector(token: str, selector_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/selectors/{selector_id}", token=token, json=payload
    )


async def delete_selector(token: str, selector_id: str) -> None:
    await _request("DELETE", f"/api/selectors/{selector_id}", token=token)


# --- Message Aids ------------------------------------------------------------
async def get_aid(token: str, template_id: str) -> dict | None:
    """Return the template's aid, or `None` when it has none."""
    try:
        return await _request("GET", f"/api/templates/{template_id}/aid", token=token)
    except ApiError as exc:
        if 404 == exc.status_code:
            return None
        raise


async def put_aid(token: str, template_id: str, payload: dict) -> dict:
    return await _request(
        "PUT", f"/api/templates/{template_id}/aid", token=token, json=payload
    )


async def delete_aid(token: str, template_id: str) -> None:
    await _request("DELETE", f"/api/templates/{template_id}/aid", token=token)


# --- Sources -----------------------------------------------------------------
async def list_sources(token: str) -> list[dict]:
    return await _request("GET", "/api/sources", token=token)


async def create_source(token: str, payload: dict) -> dict:
    return await _request("POST", "/api/sources", token=token, json=payload)


async def update_source(token: str, source_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/sources/{source_id}", token=token, json=payload
    )


async def delete_source(token: str, source_id: str) -> None:
    await _request("DELETE", f"/api/sources/{source_id}", token=token)


# --- Datasets ----------------------------------------------------------------
async def list_datasets(token: str) -> list[dict]:
    return await _request("GET", "/api/datasets", token=token)


async def create_dataset(token: str, payload: dict) -> dict:
    return await _request("POST", "/api/datasets", token=token, json=payload)


async def update_dataset(token: str, dataset_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/datasets/{dataset_id}", token=token, json=payload
    )


async def delete_dataset(token: str, dataset_id: str) -> None:
    await _request("DELETE", f"/api/datasets/{dataset_id}", token=token)


# --- Shared resources (read-only here) -----------------------------------------
async def list_proxies(token: str) -> list[dict]:
    return await _request("GET", "/api/proxies", token=token)


async def list_rate_limits(token: str) -> list[dict]:
    return await _request("GET", "/api/rate-limits", token=token)


async def create_rate_limit(token: str, payload: dict) -> dict:
    return await _request("POST", "/api/rate-limits", token=token, json=payload)


async def update_rate_limit(token: str, rate_limit_id: str, payload: dict) -> dict:
    return await _request(
        "PATCH", f"/api/rate-limits/{rate_limit_id}", token=token, json=payload
    )


async def delete_rate_limit(token: str, rate_limit_id: str) -> None:
    await _request("DELETE", f"/api/rate-limits/{rate_limit_id}", token=token)


# --- Users (admin only) ------------------------------------------------------
USERS_PAGE_SIZE = 50


async def list_users(token: str, offset: int) -> dict:
    """Return one page of users, ordered by email."""
    return await _request(
        "GET",
        "/api/users",
        token=token,
        params={"limit": USERS_PAGE_SIZE, "offset": offset},
    )


async def create_user(token: str, payload: dict) -> dict:
    return await _request("POST", "/api/users", token=token, json=payload)


async def update_user(token: str, user_id: str, payload: dict) -> dict:
    return await _request("PATCH", f"/api/users/{user_id}", token=token, json=payload)


async def disable_user(token: str, user_id: str) -> None:
    """Disable the account; the API never deletes one."""
    await _request("DELETE", f"/api/users/{user_id}", token=token)

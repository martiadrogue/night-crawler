"""Routes exporting and importing a version's instructions file.

The file travels as YAML only; a body sent as JSON is refused, even
though YAML would read it. Reading and writing the YAML is the
service's (`crawler_instructions_service`), shared with the AI
agents worker. The rules of the file are in DOMAIN_MODEL §5.9.
"""

from fastapi import Depends, Request, Response
from fastapi.routing import APIRouter
from night_crawler.domain.exceptions import ValidationException
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.presentation.api.dependencies import (
    get_current_user,
    get_read_repositories,
    get_write_repositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_instructions import CrawlerInstructionsCreate
from night_crawler.schemas.crawler_version import CrawlerVersionOut
from night_crawler.services import crawler_instructions_service

router = APIRouter(tags=["Crawler Instructions"])

MAX_INSTRUCTIONS_BYTES = 1024 * 1024
"""The largest file accepted; real instructions are a few KiB."""

YAML_MEDIA_TYPE = "application/yaml"


async def read_instructions_file(request: Request) -> CrawlerInstructionsCreate:
    """Read the request body as a YAML instructions file.

    Raises:
        ValidationException: the body is sent as JSON (415), is over
            1 MiB (413), or is not a valid instructions file (422).
    """
    if request.headers.get("content-type", "").startswith("application/json"):
        raise ValidationException("Instructions files are YAML, not JSON.", 415)
    body = await request.body()
    if len(body) > MAX_INSTRUCTIONS_BYTES:
        raise ValidationException("Instructions file is larger than 1 MiB.", 413)
    return crawler_instructions_service.parse_instructions_text(body)


@router.get(
    "/api/crawler-versions/{version_id}/instructions",
    response_class=Response,
    responses={200: {"content": {YAML_MEDIA_TYPE: {}}}},
)
async def export_instructions(
    version_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> Response:
    """Download a version's instructions as a YAML file.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing.
    """
    return Response(
        content=await crawler_instructions_service.export_instructions_text(
            read_repositories, current_user, version_id
        ),
        media_type=YAML_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f'attachment; filename="instructions-{version_id}.yaml"'
            )
        },
    )


@router.put(
    "/api/crawler-versions/{version_id}/instructions",
    response_model=CrawlerVersionOut,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {YAML_MEDIA_TYPE: {}},
        }
    },
)
async def import_instructions(
    version_id: str,
    # Authenticated first, so an anonymous body is never parsed.
    current_user: UserOut = Depends(get_current_user),
    instructions: CrawlerInstructionsCreate = Depends(read_instructions_file),
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
) -> CrawlerVersionOut:
    """Replace a version's instructions with an uploaded YAML file.

    A published version is forked into a draft that takes the file;
    the response is the version the file landed on.

    Raises:
        ValidationException: 404 if the version, its Crawler, or an
            aid's proxy or rate limit is missing; 409 if it is archived,
            or published with a draft already open; 413 if the file is
            over 1 MiB; 415 if it is sent as JSON; 422 if it is
            malformed or its keys don't link.
    """
    return await crawler_instructions_service.import_instructions(
        write_repositories, current_user, version_id, instructions
    )

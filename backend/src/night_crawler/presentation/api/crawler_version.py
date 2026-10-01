"""Routes for Crawler Versions: drafts, publishing, and settings.

Settings routes on a published version auto-fork a draft to hold the
change.
"""

from fastapi import Depends, status
from fastapi.routing import APIRouter
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
from night_crawler.schemas.crawler_version import (
    CrawlerVersionOut,
    CrawlerVersionRootTemplateUpdate,
    CrawlerVersionUpdate,
)
from night_crawler.services import crawler_version_service

router = APIRouter(tags=["Crawler Versions"])


@router.get(
    "/api/crawlers/{crawler_id}/versions", response_model=list[CrawlerVersionOut]
)
async def get_versions(
    crawler_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[CrawlerVersionOut]:
    """List a Crawler's versions, oldest first.

    Raises:
        ValidationException: 404 if the Crawler is missing.
    """
    return await crawler_version_service.get_versions(
        read_repositories, current_user, crawler_id
    )


@router.post(
    "/api/crawlers/{crawler_id}/versions/draft",
    response_model=CrawlerVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    crawler_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerVersionOut:
    """Open a draft cloned from the published version.

    Raises:
        ValidationException: 404 if the Crawler is missing; 409 if a
            draft is open.
    """
    return await crawler_version_service.create_draft(
        write_repositories, current_user, crawler_id
    )


@router.post(
    "/api/crawlers/{crawler_id}/versions/{version_id}/publish",
    response_model=CrawlerVersionOut,
)
async def publish_draft(
    crawler_id: str,
    version_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerVersionOut:
    """Publish a draft, archiving the current version.

    Raises:
        ValidationException: 404 if the Crawler or version is missing;
            409 if it is not a draft.
    """
    return await crawler_version_service.publish_draft(
        write_repositories, current_user, crawler_id, version_id
    )


@router.get("/api/crawler-versions/{version_id}", response_model=CrawlerVersionOut)
async def get_version(
    version_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerVersionOut:
    """Get one version.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing.
    """
    return await crawler_version_service.get_version(
        read_repositories, current_user, version_id
    )


@router.patch("/api/crawler-versions/{version_id}", response_model=CrawlerVersionOut)
async def update_version(
    version_id: str,
    version_input: CrawlerVersionUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerVersionOut:
    """Update a version's Proxy Ladder or host sharing.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing; 409 if it is archived, or published with a draft
            already open.
    """
    return await crawler_version_service.update_version(
        write_repositories, current_user, version_id, version_input
    )


@router.put(
    "/api/crawler-versions/{version_id}/root-template",
    response_model=CrawlerVersionOut,
)
async def set_version_root_template(
    version_id: str,
    root_template_input: CrawlerVersionRootTemplateUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerVersionOut:
    """Point the root at another template of the version.

    Raises:
        ValidationException: 404 if the version, its Crawler, or the
            template in it is missing; 409 if it is archived, or
            published with a draft already open.
    """
    return await crawler_version_service.set_version_root_template(
        write_repositories,
        current_user,
        version_id,
        root_template_input.message_template_id,
    )


@router.delete(
    "/api/crawler-versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_version(
    version_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> None:
    """Delete a draft or archived version and its template tree.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing; 409 if it is published or has been run.
    """
    await crawler_version_service.delete_version(
        write_repositories, current_user, version_id
    )

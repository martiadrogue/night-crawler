"""Routes for a Crawler's current Context (its latest execution's)."""

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
from night_crawler.schemas.crawler_context import (
    CrawlerContextOut,
    CrawlerContextValueUpdate,
)
from night_crawler.services import crawler_context_service

router = APIRouter(
    prefix="/api/crawlers/{crawler_id}/context", tags=["Crawler Context"]
)


@router.get("", response_model=CrawlerContextOut)
async def get_context(
    crawler_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerContextOut:
    """Get the latest execution's Context, which the next run inherits.

    Raises:
        ValidationException: 404 if the Crawler is missing or has no
            execution yet.
    """
    return await crawler_context_service.get_context(
        read_repositories, current_user, crawler_id
    )


@router.put("/{key}", response_model=CrawlerContextOut)
async def set_context_value(
    crawler_id: str,
    key: str,
    value_input: CrawlerContextValueUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerContextOut:
    """Create or replace one key; a `name[]` key takes a list.

    Raises:
        ValidationException: 404 if the Crawler is missing or has no
            execution yet; 400 if the key or value breaks the rules.
    """
    return await crawler_context_service.set_context_value(
        write_repositories, current_user, crawler_id, key, value_input
    )


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_context_value(
    crawler_id: str,
    key: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> None:
    """Delete one key, if present.

    Raises:
        ValidationException: 404 if the Crawler is missing or has no
            execution yet.
    """
    await crawler_context_service.delete_context_value(
        write_repositories, current_user, crawler_id, key
    )

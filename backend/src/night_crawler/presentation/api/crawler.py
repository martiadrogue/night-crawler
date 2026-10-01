"""Routes for Crawlers."""

from fastapi import Depends, Query, status
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
from night_crawler.schemas.crawler import (
    CrawlerCreate,
    CrawlerOut,
    CrawlerUpdate,
    SortField,
    SortOrder,
)
from night_crawler.services import crawler_service

router = APIRouter(prefix="/api/crawlers", tags=["Crawlers"])


@router.post("", response_model=CrawlerOut, status_code=status.HTTP_201_CREATED)
async def create_crawler(
    crawler_input: CrawlerCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerOut:
    """Create a Crawler with an empty first draft.

    Raises:
        ValidationException: 400 if the fields don't fit the dataset;
            409 if it is active and scheduled with nothing published.
    """
    return await crawler_service.create_crawler(
        write_repositories, current_user, crawler_input
    )


@router.get("", response_model=list[CrawlerOut])
async def get_crawlers(
    source_id: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    sort_by: SortField = Query(default="created_at"),
    order: SortOrder = Query(default="desc"),
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[CrawlerOut]:
    """List Crawlers, newest first.

    Always filterable, so it returns one capped page and never
    paginates.
    """
    return await crawler_service.get_crawlers(
        read_repositories,
        current_user,
        source_id=source_id,
        dataset_id=dataset_id,
        sort_by=sort_by,
        order=order,
    )


@router.get("/{crawler_id}", response_model=CrawlerOut)
async def get_crawler(
    crawler_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerOut:
    """Get one Crawler.

    Raises:
        ValidationException: 404 if the Crawler is missing.
    """
    return await crawler_service.get_crawler_out(
        read_repositories, current_user, crawler_id
    )


@router.patch("/{crawler_id}", response_model=CrawlerOut)
async def update_crawler(
    crawler_id: str,
    crawler_input: CrawlerUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerOut:
    """Partially update a Crawler.

    Raises:
        ValidationException: 404 if the Crawler is missing; 400 if the
            fields don't fit the dataset; 409 if it would activate a
            schedule with nothing published.
    """
    return await crawler_service.update_crawler(
        write_repositories, current_user, crawler_id, crawler_input
    )


@router.delete("/{crawler_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_crawler(
    crawler_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> None:
    """Delete a Crawler and everything it owns.

    Raises:
        ValidationException: 404 if the Crawler is missing.
    """
    await crawler_service.delete_crawler(write_repositories, current_user, crawler_id)

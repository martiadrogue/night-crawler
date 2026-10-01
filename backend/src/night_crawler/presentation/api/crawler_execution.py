"""Routes for starting Crawler Executions and inspecting them."""

from fastapi import Depends, Query, Response, status
from fastapi.routing import APIRouter
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.presentation.api.dependencies import (
    get_current_user,
    get_execution_dispatcher,
    get_read_repositories,
    get_write_repositories,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler_execution import (
    CrawlerExecutionCreate,
    CrawlerExecutionOut,
    CrawlerExecutionQuery,
    CrawlerExecutionsPageOut,
    ExecutionStatus,
)
from night_crawler.services import crawler_execution_service

router = APIRouter(tags=["Crawler Executions"])


@router.post(
    "/api/crawlers/{crawler_id}/executions",
    response_model=CrawlerExecutionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution(
    crawler_id: str,
    execution_input: CrawlerExecutionCreate | None = None,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
    execution_dispatcher: AbstractExecutionDispatcher = Depends(
        get_execution_dispatcher
    ),
) -> CrawlerExecutionOut:
    """Create a pending run of the published version and enqueue it.

    The optional body seeds the run's Context (e.g. `parish[]`).

    Raises:
        ValidationException: 404 if the Crawler is missing; 409 if
            nothing is published; 400 if the Context is invalid.
    """
    return await crawler_execution_service.create_execution(
        write_repositories,
        current_user,
        execution_dispatcher,
        crawler_id,
        execution_input,
    )


@router.post(
    "/api/crawler-versions/{version_id}/test-executions",
    response_model=CrawlerExecutionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_execution(
    version_id: str,
    execution_input: CrawlerExecutionCreate | None = None,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
    execution_dispatcher: AbstractExecutionDispatcher = Depends(
        get_execution_dispatcher
    ),
) -> CrawlerExecutionOut:
    """Create a test run of this exact version on the `testing` queue.

    Any status works: draft, published, or archived. The optional body
    seeds the run's Context. A test run is never the Context later runs
    inherit.

    Raises:
        ValidationException: 404 if the version or its Crawler is
            missing; 400 if the Context is invalid.
    """
    return await crawler_execution_service.create_test_execution(
        write_repositories,
        current_user,
        execution_dispatcher,
        version_id,
        execution_input,
    )


@router.get(
    "/api/crawlers/{crawler_id}/executions",
    response_model=list[CrawlerExecutionOut],
)
async def get_executions(
    crawler_id: str,
    status_filter: ExecutionStatus | None = Query(default=None, alias="status"),
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[CrawlerExecutionOut]:
    """List a Crawler's runs, newest first; one capped page.

    Raises:
        ValidationException: 404 if the Crawler is missing.
    """
    return await crawler_execution_service.get_executions(
        read_repositories, current_user, crawler_id, status=status_filter
    )


@router.get("/api/crawler-executions", response_model=CrawlerExecutionsPageOut)
async def get_all_executions(
    query: CrawlerExecutionQuery = Depends(),
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerExecutionsPageOut:
    """List every Crawler's runs, newest first.

    Filtered by `status`, `parsing_status`, `queue`, or
    `crawler_title` (a case-insensitive part of the title), it is one
    page of up to 50; unfiltered, it paginates up to 300 runs deep.
    """
    return await crawler_execution_service.get_all_executions(
        read_repositories, current_user, query
    )


@router.get(
    "/api/crawler-executions/{execution_id}/dataset.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def download_execution_csv(
    execution_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> Response:
    """Download a finished run's dataset CSV as a file.

    Raises:
        ValidationException: 404 if the run, its Crawler, or its CSV is
            missing; a run has a CSV only once it has finished.
    """
    csv_file = await crawler_execution_service.get_execution_csv(
        read_repositories, current_user, execution_id
    )
    return Response(
        content=csv_file.csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{csv_file.filename}"'},
    )


@router.get(
    "/api/crawler-executions/{execution_id}", response_model=CrawlerExecutionOut
)
async def get_execution(
    execution_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> CrawlerExecutionOut:
    """Get one run.

    Raises:
        ValidationException: 404 if the run or its Crawler is missing.
    """
    return await crawler_execution_service.get_execution(
        read_repositories, current_user, execution_id
    )

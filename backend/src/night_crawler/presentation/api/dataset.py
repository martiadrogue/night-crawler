"""Routes for Datasets; updates and deletes are admin only."""

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
    require_admin,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.dataset import DatasetCreate, DatasetOut, DatasetUpdate
from night_crawler.services import dataset_service

router = APIRouter(prefix="/api/datasets", tags=["Datasets"])


@router.post("", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    dataset_input: DatasetCreate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> DatasetOut:
    """Create a Dataset.

    Raises:
        ValidationException: 400 if the definition is invalid (e.g. no
            required `item_id`); 409 if another Dataset has this name.
    """
    return await dataset_service.create_dataset(write_repositories, dataset_input)


@router.get("", response_model=list[DatasetOut])
async def get_datasets(
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> list[DatasetOut]:
    """List every Dataset, by name."""
    return await dataset_service.get_datasets(read_repositories)


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str,
    read_repositories: AbstractReadRepositories = Depends(get_read_repositories),
    current_user: UserOut = Depends(get_current_user),
) -> DatasetOut:
    """Get one Dataset.

    Raises:
        ValidationException: 404 if the Dataset is missing.
    """
    return await dataset_service.get_dataset(read_repositories, dataset_id)


@router.patch("/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: str,
    dataset_input: DatasetUpdate,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> DatasetOut:
    """Partially update a Dataset (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the Dataset is
            missing; 400 if the definition is invalid; 409 if another
            Dataset has the new name or a linked Crawler's fields would
            no longer fit.
    """
    return await dataset_service.update_dataset(
        write_repositories, dataset_id, dataset_input
    )


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: str,
    write_repositories: AbstractWriteRepositories = Depends(get_write_repositories),
    _: UserOut = Depends(require_admin),
) -> None:
    """Delete a Dataset no Crawler uses (admin only).

    Raises:
        ValidationException: 403 for non-admins; 404 if the Dataset is
            missing; 409 while a Crawler is linked to it.
    """
    await dataset_service.delete_dataset(write_repositories, dataset_id)

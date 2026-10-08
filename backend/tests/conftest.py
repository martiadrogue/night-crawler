import asyncio
import http.server
import json
import threading
import uuid
from collections.abc import AsyncGenerator, Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from night_crawler.core.config import get_settings
from night_crawler.core.di import REPOSITORY_FACTORIES
from night_crawler.domain.bundles.repository_factories import RepositorySetFactories
from night_crawler.domain.exceptions import (
    ExternalServiceException,
    ValidationException,
)
from night_crawler.domain.model.entities import CrawlerExecution
from night_crawler.domain.ports.dataset_export_storage import (
    AbstractDatasetExportStorage,
)
from night_crawler.domain.ports.execution_dispatcher import (
    AbstractExecutionDispatcher,
)
from night_crawler.domain.ports.execution_metrics import AbstractExecutionMetrics
from night_crawler.domain.ports.repository_sets import (
    AbstractReadRepositories,
    AbstractWriteRepositories,
)
from night_crawler.domain.ports.user_directory import (
    AbstractUserDirectory,
    DirectoryUser,
    DirectoryUserChanges,
)
from night_crawler.infrastructure.db.read_repositories import MongoReadRepositories
from night_crawler.infrastructure.db.schema import initialize_database
from night_crawler.infrastructure.db.write_repositories import MongoWriteRepositories
from night_crawler.infrastructure.external.jwks_token_verifier import (
    JwksTokenVerifier,
)
from night_crawler.schemas.auth import UserOut
from night_crawler.schemas.crawler import CrawlerCreate, CrawlerOut
from night_crawler.schemas.source import SourceCreate, SourceOut
from night_crawler.services import crawler_service, dataset_service, source_service
from pymongo import AsyncMongoClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_database_name() -> Generator[str, None, None]:
    """
    One throwaway MongoDB database per test session, with every index
    and validator in place, dropped at the end (R3.5.4). Creating one
    per test would churn thousands of WiredTiger files.
    """
    database_name = f"night_crawler_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_run_on_database(database_name, initialize_database))
    try:
        yield database_name
    finally:
        asyncio.run(_run_on_database(database_name, _drop_database))


async def _run_on_database(database_name, action) -> None:
    # A client of its own: an async client is bound to the event loop
    # that first uses it, and each test runs on a fresh loop.
    client = AsyncMongoClient(get_settings().mongo_url)
    try:
        await action(client[database_name])
    finally:
        await client.close()


async def _drop_database(database) -> None:
    await database.client.drop_database(database.name)


@pytest.fixture
async def mongo_database(
    test_database_name,
) -> AsyncGenerator[tuple[AsyncMongoClient, str], None]:
    """A client on the test database, emptied before each test."""
    client = AsyncMongoClient(get_settings().mongo_url)
    database = client[test_database_name]
    for collection_name in await database.list_collection_names():
        await database[collection_name].delete_many({})
    try:
        yield client, test_database_name
    finally:
        await client.close()


@pytest.fixture
async def write_repositories(
    mongo_database,
) -> AsyncGenerator[AbstractWriteRepositories, None]:
    """
    Write repositories on the test database. Services commit themselves;
    teardown rolls back, since a failed write inside a transaction makes
    MongoDB abort it and a final commit would then fail.
    """
    client, database_name = mongo_database
    async with MongoWriteRepositories(
        client, database_name, REPOSITORY_FACTORIES
    ) as repositories:
        yield repositories
        await repositories.rollback()


@pytest.fixture
async def read_repositories(mongo_database) -> AbstractReadRepositories:
    """Read repositories on the test database: no transaction."""
    client, database_name = mongo_database
    return MongoReadRepositories(client, database_name, REPOSITORY_FACTORIES)


class RecordingDispatcher(AbstractExecutionDispatcher):
    """Keeps every dispatch instead of enqueuing it."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[str, str]] = []

    async def dispatch(self, execution_id: str, queue: str) -> None:
        self.dispatched.append((execution_id, queue))


@pytest.fixture
def execution_dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


class RecordingExecutionMetrics(AbstractExecutionMetrics):
    """Keeps every finished run instead of exporting metrics."""

    def __init__(self) -> None:
        self.finished: list[CrawlerExecution] = []

    def record_finished(self, execution: CrawlerExecution) -> None:
        self.finished.append(execution)


@pytest.fixture
def execution_metrics() -> RecordingExecutionMetrics:
    return RecordingExecutionMetrics()


class RecordingExportStorage(AbstractDatasetExportStorage):
    """Keeps every exported CSV, by path, instead of writing files.

    With `is_failing`, every save raises, like a full or read-only disk;
    with `is_move_failing`, only moving to `validated/` does.
    """

    def __init__(self) -> None:
        self.exports: dict[str, str] = {}
        self.is_failing = False
        self.is_move_failing = False

    async def save(self, file_stem: str, csv_content: str) -> str:
        if self.is_failing:
            raise ExternalServiceException("Disk full.")
        path = f"/exports/raw/{file_stem}.csv"
        self.exports[path] = csv_content
        return path

    async def move_to_validated(self, file_stem: str) -> str:
        if self.is_move_failing:
            raise ExternalServiceException("Cannot move.")
        path = f"/exports/validated/{file_stem}.csv"
        self.exports[path] = self.exports.pop(f"/exports/raw/{file_stem}.csv")
        return path

    async def read(self, file_path: str) -> str:
        if file_path not in self.exports:
            raise ExternalServiceException("No such file.")
        return self.exports[file_path]


@pytest.fixture
def export_storage() -> RecordingExportStorage:
    return RecordingExportStorage()


@pytest.fixture
async def repository_factories(mongo_database) -> RepositorySetFactories:
    """Open read or write repositories on the test database, like a task."""
    client, database_name = mongo_database
    return RepositorySetFactories(
        open_read=lambda: MongoReadRepositories(
            client, database_name, REPOSITORY_FACTORIES
        ),
        open_write=lambda: MongoWriteRepositories(
            client, database_name, REPOSITORY_FACTORIES
        ),
    )


VENUES_FIELDS = ["item_id", "name", "rating"]


@pytest.fixture
def member() -> UserOut:
    return UserOut(
        id="member-1",
        email="member@example.com",
        role="user",
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture
def admin() -> UserOut:
    return UserOut(
        id="admin-1",
        email="admin@example.com",
        role="admin",
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture
async def source(write_repositories) -> SourceOut:
    """A Source every test crawler is linked to by default."""
    return await source_service.create_source(
        write_repositories, SourceCreate(name="Google Maps")
    )


@pytest.fixture
async def dataset_ids(write_repositories) -> dict[str, str]:
    """The built-in datasets, created as at startup, by name."""
    await dataset_service.seed_built_in_datasets(write_repositories)
    datasets = await dataset_service.get_datasets(write_repositories)
    return {dataset.name: dataset.id for dataset in datasets}


@pytest.fixture
def create_crawler(write_repositories, member, source, dataset_ids):
    async def _create(dataset: str = "venues", **overrides) -> CrawlerOut:
        crawler_input = CrawlerCreate(
            **{
                "title": "Andorra venues",
                "source_id": source.id,
                "dataset_id": dataset_ids[dataset],
                "fields": VENUES_FIELDS,
                **overrides,
            }
        )
        return await crawler_service.create_crawler(
            write_repositories, member, crawler_input
        )

    return _create


TEST_ISSUER = "http://keycloak.test/realms/night-crawler"
TEST_AUDIENCE = "night-crawler-api"
TEST_KEY_ID = "test-key"


class _JwksHandler(http.server.BaseHTTPRequestHandler):
    """Serve the test JWKS, standing in for Keycloak's certs endpoint."""

    jwks_body = b""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.jwks_body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    """The RSA key test tokens are signed with; its public half is served."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks_url(signing_key) -> Generator[str, None, None]:
    """A local HTTP server's JWKS URL publishing `signing_key`, never Keycloak."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    handler = type(
        "JwksHandler",
        (_JwksHandler,),
        {"jwks_body": json.dumps({"keys": [{**jwk, "kid": TEST_KEY_ID}]}).encode()},
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/certs"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def create_token_verifier(jwks_url):
    """Build a verifier for test tokens, on `jwks_url` unless given one."""

    def _create_token_verifier(url: str | None = None) -> JwksTokenVerifier:
        return JwksTokenVerifier(url or jwks_url, TEST_ISSUER, TEST_AUDIENCE)

    return _create_token_verifier


@pytest.fixture
def token_verifier(create_token_verifier) -> JwksTokenVerifier:
    return create_token_verifier()


@pytest.fixture
def issue_token(signing_key):
    """Sign a Keycloak-shaped access token; keyword arguments override claims."""

    def _issue_token(roles: list[str] | None = None, key=None, **claims: object) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": "kc-user-1",
            "email": "dora@example.com",
            "iss": TEST_ISSUER,
            "aud": [TEST_AUDIENCE, "account"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "realm_access": {"roles": ["user"] if None is roles else roles},
        }
        payload.update(claims)
        return jwt.encode(
            payload,
            key or signing_key,
            algorithm="RS256",
            headers={"kid": TEST_KEY_ID},
        )

    return _issue_token


class FakeUserDirectory(AbstractUserDirectory):
    """Hold accounts in memory, keeping emails unique as Keycloak does."""

    def __init__(self) -> None:
        self.users: dict[str, DirectoryUser] = {}
        self.temporary_passwords: dict[str, str] = {}

    def add(
        self,
        user_id: str,
        email: str,
        role: str | None = "user",
        is_enabled: bool = True,
    ) -> DirectoryUser:
        """Store an account straight away, as if it already existed."""
        user = DirectoryUser(user_id, email, role, is_enabled, datetime(2026, 1, 1))
        self.users[user_id] = user
        return user

    async def get_all(self, limit: int, offset: int) -> list[DirectoryUser]:
        by_email = sorted(self.users.values(), key=lambda user: user.email)
        return by_email[offset : offset + limit]

    async def get_by_id(self, user_id: str) -> DirectoryUser | None:
        return self.users.get(user_id)

    async def create(
        self, email: str, role: str, temporary_password: str
    ) -> DirectoryUser:
        self._ensure_email_free(email)
        user = self.add(f"kc-{len(self.users) + 1}", email, role)
        self.temporary_passwords[user.id] = temporary_password
        return user

    async def update(
        self, user_id: str, changes: DirectoryUserChanges
    ) -> DirectoryUser:
        user = self._get_or_404(user_id)
        if changes.email and changes.email != user.email:
            self._ensure_email_free(changes.email)
        if changes.temporary_password:
            self.temporary_passwords[user_id] = changes.temporary_password
        updated = replace(
            user, email=changes.email or user.email, role=changes.role or user.role
        )
        self.users[user_id] = updated
        return updated

    async def disable(self, user_id: str) -> None:
        self.users[user_id] = replace(self._get_or_404(user_id), is_enabled=False)

    async def count_enabled_by_role(self, role: str) -> int:
        return sum(
            1 for user in self.users.values() if role == user.role and user.is_enabled
        )

    async def aclose(self) -> None:
        pass

    def _get_or_404(self, user_id: str) -> DirectoryUser:
        if user_id not in self.users:
            raise ValidationException("User not found.", 404)
        return self.users[user_id]

    def _ensure_email_free(self, email: str) -> None:
        if any(email == user.email for user in self.users.values()):
            raise ValidationException("Email already taken", 400)


@pytest.fixture
def user_directory() -> FakeUserDirectory:
    return FakeUserDirectory()

"""Application settings read from the environment."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings; secrets have no defaults."""

    app_name: str = Field(default="Night Crawler API")
    app_description: str = Field(default="Night Crawler API")
    app_version: str = Field(default="0.1.0")
    app_env: str = Field(default="development")
    root_path: str = Field(default="")
    cors_allow_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000"
    )

    # Injected by Compose (`x-mongo-env`) from `MONGO_USER`,
    # `MONGO_PASSWORD`, and `MONGO_DATABASE` in `.env`.
    mongo_url: str = Field(default="mongodb://db:27017/?replicaSet=rs0")
    mongo_database: str = Field(default="night_crawler")

    # Required: `core/di.py` refuses to start without it, since signing
    # tokens with a well-known fallback would let anyone forge one.
    jwt_secret: str = Field(default="")
    jwt_algorithm: str = Field(default="HS256")

    # RabbitMQ, the Celery broker (`RABBITMQ_*` in `.env`).
    rabbitmq_user: str = Field(default="")
    rabbitmq_password: str = Field(default="")
    rabbitmq_host: str = Field(default="rabbitmq")

    # Redis, where every worker's rate-limit windows and penalties live.
    redis_url: str = Field(default="redis://redis:6379/0")

    # Where each Crawler Execution's CSV is exported: to `raw/` first,
    # moved to `validated/` once the run is parsed (DOMAIN_MODEL §5.3).
    dataset_export_dir: str = Field(default="/var/lib/night_crawler/csv")

    # Optional startup seed for a bootstrap admin account (see
    # `services/user_service.py::seed_admin_user`). Both MUST be set
    # together to opt in, so no image ships a guessable default admin.
    admin_seed_email: str = Field(default="")
    admin_seed_password: str = Field(default="")

    @property
    def broker_url(self) -> str:
        """Return the RabbitMQ broker URL."""
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:5672//"
        )

    # `extra="ignore"`: the root `.env` is shared across every compose
    # service (including the frontend's `API_BASE_URL`), so this model
    # must not reject keys it doesn't declare.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Return the settings, read from the environment once."""
    return Settings()

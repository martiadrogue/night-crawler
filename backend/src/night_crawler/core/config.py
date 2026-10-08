"""Application settings read from the environment."""

from functools import lru_cache
from urllib.parse import quote

from pydantic import Field, SecretStr
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

    # Injected by Compose (`x-app-env`) from `MONGO_USER`,
    # `MONGO_PASSWORD`, and `MONGO_DATABASE` in `.env`.
    mongo_url: str = Field(default="mongodb://db:27017/?replicaSet=rs0")
    mongo_database: str = Field(default="night_crawler")

    # Keycloak, which issues the access tokens the API accepts. Tokens
    # name the browser-facing issuer even when a container fetched
    # them; the keys are fetched over the Docker network.
    oidc_issuer: str = Field(default="http://localhost:8180/realms/night-crawler")
    oidc_jwks_url: str = Field(
        default=(
            "http://keycloak:8080/realms/night-crawler/protocol/openid-connect/certs"
        )
    )
    # The `aud` a token must carry: the API's own client id.
    oidc_audience: str = Field(default="night-crawler-api")

    # Keycloak's Admin REST API, where accounts are managed, reached as
    # the API's service account. Compose maps the secret from
    # `KC_NIGHT_CRAWLER_API_SECRET`; without it every user route is a
    # 502.
    keycloak_url: str = Field(default="http://keycloak:8080")
    keycloak_realm: str = Field(default="night-crawler")
    keycloak_admin_client_id: str = Field(default="night-crawler-api")
    keycloak_admin_client_secret: SecretStr = Field(default=SecretStr(""))

    # RabbitMQ, the Celery broker (`RABBITMQ_*` in `.env`).
    rabbitmq_user: str = Field(default="")
    rabbitmq_password: str = Field(default="")
    rabbitmq_host: str = Field(default="rabbitmq")
    # Production shares one RabbitMQ between the apps, a vhost each: their
    # queue names overlap (`dataset-import`).
    rabbitmq_vhost: str = Field(default="/")

    # Redis, where every worker's rate-limit windows and penalties live.
    redis_url: str = Field(default="redis://redis:6379/0")

    # Where each Crawler Execution's CSV is exported: to `raw/` first,
    # moved to `validated/` once the run is parsed (DOMAIN_MODEL §5.3).
    dataset_export_dir: str = Field(default="/var/lib/night_crawler/csv")

    # Where traces and metrics are pushed over OTLP/HTTP (Grafana
    # Alloy, `http://alloy:4318`); empty turns telemetry off. Set by
    # `make up-observability` (core/telemetry.py).
    otel_exporter_otlp_endpoint: str = Field(default="")

    # The browser agent of Instruction Generations: a Browser Use
    # agent on Gemini (`core/di.py::create_gemini_chat_model`).
    # Without a key every generation fails; nothing else needs one.
    gemini_api_key: SecretStr = Field(default=SecretStr(""))
    # Google's alias for its newest Flash model: pinned ids such as
    # `gemini-2.5-flash` answer 404 to projects created after they
    # closed to new users.
    gemini_model: str = Field(default="gemini-flash-latest")
    # Gemini's free-tier quota for `gemini_model`, shared by every
    # worker (`llm:<model>` rate-limit keys). Google shows free-tier
    # values only per project, in AI Studio's rate-limit page
    # (aistudio.google.com/rate-limit), and changes them without
    # notice: these are gemini-2.5-flash's there, read 2026-10-06
    # (ai.google.dev/gemini-api/docs/rate-limits no longer lists
    # them). Check your model's, and lower them if Gemini answers 429.
    gemini_requests_per_minute: int = Field(default=15, gt=0)
    gemini_requests_per_day: int = Field(default=1500, gt=0)
    gemini_tokens_per_minute: int = Field(default=1_000_000, gt=0)
    # Retries of a call Gemini rate-limits (429), after its first try.
    gemini_max_retry_attempts: int = Field(default=3, ge=0)

    # Instruction synthesis: files Gemini may write per generation
    # before it fails, and how much of each response body (and of all
    # bodies) it is shown.
    synthesis_max_attempts: int = Field(default=3, gt=0)
    synthesis_body_max_bytes: int = Field(default=16 * 1024, gt=0)
    synthesis_total_body_max_bytes: int = Field(default=128 * 1024, gt=0)
    # Analytics and ads hosts (and their subdomains) the recording
    # filter drops before tracing where the data came from.
    synthesis_ignored_hosts: str = Field(
        default=(
            "google-analytics.com,analytics.google.com,googletagmanager.com,"
            "doubleclick.net,googlesyndication.com,googleadservices.com,"
            "connect.facebook.net,bat.bing.com,clarity.ms,"
            "hotjar.com,hotjar.io,segment.io,segment.com,mixpanel.com,"
            "amplitude.com,sentry.io,nr-data.net,newrelic.com,criteo.com,"
            "criteo.net,adnxs.com,taboola.com,outbrain.com,"
            "scorecardresearch.com,quantserve.com,adsrvr.org,"
            "cookielaw.org,onetrust.com,cookiebot.com,analytics.tiktok.com"
        )
    )

    @property
    def synthesis_ignored_host_names(self) -> tuple[str, ...]:
        """Return `synthesis_ignored_hosts` as host names."""
        return tuple(
            host.strip().lower()
            for host in self.synthesis_ignored_hosts.split(",")
            if host.strip()
        )

    agent_max_steps: int = Field(default=40, gt=0)
    # Listing pages the agent visits: it samples the site.
    agent_max_pages: int = Field(default=5, gt=0)
    agent_timeout_seconds: float = Field(default=600, gt=0)
    # Per response body kept in a recording (pages and API calls only).
    agent_response_body_max_bytes: int = Field(default=64 * 1024, gt=0)
    # A stored recording, well under MongoDB's 16 MiB document limit.
    generation_recording_max_bytes: int = Field(default=1024 * 1024, gt=0)

    @property
    def broker_url(self) -> str:
        """Return the RabbitMQ broker URL."""
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:5672/{quote(self.rabbitmq_vhost, safe='')}"
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

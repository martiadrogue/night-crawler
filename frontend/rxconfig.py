import reflex as rx

config = rx.Config(
    app_name="night_crawler",
    telemetry_enabled=False,
    frontend_port=3000,
    backend_port=8000,
    # Browser-facing URL of *this* Reflex app's own backend (its state
    # websocket), not the FastAPI API. The default is the dev host port
    # (docker-compose.override.yml); Reflex overrides it from the
    # REFLEX_API_URL env var, which production sets to its public URL.
    api_url="http://localhost:8001",
    cors_allowed_origins=["http://localhost:3000"],
    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(accent_color="indigo", radius="medium")
        )
    ],
    disable_plugins=[rx.plugins.SitemapPlugin],
)

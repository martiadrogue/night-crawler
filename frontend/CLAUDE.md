# Night Crawler Frontend Rules

The Reflex web UI for the Night Crawler API. It lives in its own container
(`frontend`) and talks to FastAPI only over HTTP.

## Documentation & Guides
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the UI is built: pages, states, the API client, routing, auth, and the draft/publish/archive flow.
- See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the rules every change here must follow (`FR-*` IDs) and the checklist.
- The backend's rules are in the root [CLAUDE.md](../CLAUDE.md) and [docs/](../docs/). The API is the source of truth: the UI never repeats a business rule the API already checks.

## Working in This Folder
- Treat every `MUST`/`MUST NOT` in docs/CONTRIBUTING.md as enforced.
- Before considering a change done, from the repo root: `make format`, `make lint`, `make test-frontend`, and check the UI in a browser (http://localhost:3000). Reflex hot-reloads the mounted `src/night_crawler/`; a compile error shows in `docker logs reflex_frontend_dev`.
- If a change adds a page, a state, or an API call, update docs/ARCHITECTURE.md. If a backend endpoint changes shape, update `api_client.py` and its tests in the same change.

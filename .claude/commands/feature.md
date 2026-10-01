---
description: Build a new backend feature using TDD, following the layered architecture in docs/
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(docker compose exec -T web pytest:*), Bash(docker compose exec -T web python -m pytest:*), Bash(make format:*), Bash(make lint:*), Bash(make test:*), Bash(make complexity:*), Bash(docker compose restart:*)
argument-hint: "[Brief feature description]"
---

## User Input

The user has provided information about the feature to build: **$ARGUMENTS**

## Do this first

1. Read `docs/ARCHITECTURE.md`, `docs/DOMAIN_MODEL.md`, `docs/BUSINESS_RULES.md`, and `docs/CONTRIBUTING.md`, then read one existing feature close to the request and copy its shape (e.g. `message_aid_rate_limit`: route, service, schema, repository, tests).
2. Decide, from the description:
   - which **entities and ports** in `domain/` it touches, or needs added
   - the **use cases** in `services/` (one module per use case, async functions, no classes)
   - who calls it: any authenticated user, or **admin only** (`Depends(require_admin)`); and whether it also needs a worker task or a Reflex page
3. Write a short plan (5-8 lines: entities, use cases, routes, schema changes, tests) and go ahead. Only stop to ask if the request is ambiguous or destructive (e.g. dropping data).

## 1. Write Tests First

Cover the happy path, the main rule violations, and authorization. Keep them minimal. Tests mirror the source path: `backend/tests/<layer>/test_<module>.py`.

- **Domain** - pure functions and value objects, no fixtures needed.
- **Services** - use the fakes in `backend/tests/services/conftest.py`; spec mocks against the abstract `domain/` ports, never concrete classes (R3.5.1).
- **Repositories** - against a disposable MongoDB database (unique name per test session, dropped afterwards) on the Compose `db` service, from `backend/tests/infrastructure/db/conftest.py`.
- **API** - through the test client; clean up any `app.dependency_overrides` in teardown (R3.5.3), and assert **403** for non-admins on admin-only routes.
- Async tests use `@pytest.mark.anyio` and the `anyio_backend` fixture (R3.5.2).

## 2. Run Tests (expect failure)

```bash
docker compose exec -T web pytest backend/tests/path/to/test_module.py -q
```

## 3. Implement, bottom-up

Only move to the next layer when the current layer's tests pass. Match the naming, comment density, and idioms of the neighbouring code.

**Domain** (`domain/`) - standard library only.
- Entities are dataclasses with a surrogate UUID `id`; never mutate them in place, use `dataclasses.replace` (R1.4.2). Value objects are `@dataclass(frozen=True)`.
- Ports are `Abstract...` classes; declare every exception an implementation may raise in its docstring (R1.2.5).
- Controlled errors derive from `AppException` (`ValidationException` for client errors).

**Services** (`services/`)
- Async functions only. Signature: injected dependencies first (`read_repositories` for read-only use cases or `write_repositories` for any use case that writes, then `current_user`, ports), then at most 3 data parameters (R3.2.2); bundle more into a schema or a frozen `domain/` value object.
- Accept and return schemas; map entities to schemas here. Call another use case's service instead of touching its persistence.

**Infrastructure** (`infrastructure/`)
- One adapter class per file, named after the technology (`MongoXRepository`). `save()` returns a fresh entity. Convert driver errors into `AppException` subclasses before they leave the adapter.
- Index and `$jsonSchema` validator changes go in `infrastructure/db/schema.py`. There are no migrations: indexes and validators are created at startup (idempotent), but reshaping existing documents or changing an existing index's options must be applied to the dev database by hand (or `make restart-db`) - say so in the summary.
- Bind any new adapter only in `core/di.py`.

**Presentation API** (`presentation/api/`) and **schemas** (`schemas/`)
- One router per resource; handlers only call services - no `try/except`, the global handler formats errors.
- DTO suffixes: `Base`, `Create`, `Update` (all optional), `Query`, `Out`.
- Filterable listings return one capped page; unfiltered ones paginate (`domain/pagination.py`).

**Worker / frontend**, if needed: Celery tasks in `presentation/worker/tasks.py` with an explicit `name="night_crawler.tasks.<func>"`; Reflex pages under `frontend/`.

## 4. Run Tests (expect pass)

```bash
docker compose exec -T web pytest backend/tests/path/to/test_module.py -q
make test
```

Iterate until the whole suite passes.

## 5. Format, lint, complexity

```bash
make format
make lint
make complexity
```

Lint must pass, including the docstring rules (§3.3: Google style, 72-column doc lines). Complexity must be grade A, or B with a one-line justification comment. If the feature adds a task, a schedule, or a setting, restart the workers: `docker compose restart celery_worker celery_beat`.

## 6. Docs

If the feature adds a route, task, setting, or layer change, update `README.md` / `docs/ARCHITECTURE.md`; if it adds an entity or enforces a new rule, update `docs/DOMAIN_MODEL.md` / `docs/BUSINESS_RULES.md`.

## Rules

- Tests first; never skip the failing run.
- Keep tests minimal; keep the change focused on the requested feature.
- Do not modify unrelated files.
- Do not commit (the user runs `/commit-message`). Never stage `.env`.
- Never print API keys or secrets.
- Finish with: what was built, the files touched, the test count, lint/complexity status, and any assumption the user should confirm.

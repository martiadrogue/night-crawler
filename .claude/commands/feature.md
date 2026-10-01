---
description: Build a new backend feature using TDD, following the layered architecture in docs/
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(docker compose exec -T web pytest:*), Bash(docker compose exec -T web python -m pytest:*), Bash(make format:*), Bash(make lint:*), Bash(make test:*), Bash(make complexity:*), Bash(docker compose restart:*)
argument-hint: "[Brief feature description]"
---

## User Input

The user has provided information about the feature to build: **$ARGUMENTS**

## Do this first

1. Read `docs/CONTRIBUTING.md` (the rules; every `MUST` applies) and `docs/ARCHITECTURE.md` (what exists and how it runs). From `docs/DOMAIN_MODEL.md` read §1 (vocabulary), §2.1 (where code goes in `domain/`), and only the entity and rule sections the feature touches; from `docs/BUSINESS_RULES.md` only the requirements it touches.
2. Read one existing feature close to the request and copy its shape (e.g. `message_aid_rate_limit`: route, service, schema, repository, tests).
3. Decide which entities and ports it touches or adds, its use cases, who calls it (any authenticated user, or admin only with `Depends(require_admin)`), and whether it needs a worker task or a Reflex page.
4. Write a short plan (5-8 lines: entities, use cases, routes, schema changes, tests) and go ahead. Only stop to ask if the request is ambiguous or destructive (e.g. dropping data).

## 1. Write tests first

Cover the happy path, the main rule violations, and authorization (**403** for non-admins on admin-only routes). Keep them minimal and follow CONTRIBUTING R2.4.7 and §3.5. Fixtures: service fakes in `backend/tests/services/conftest.py`, disposable MongoDB in `backend/tests/conftest.py`.

## 2. Run the tests (expect failure)

```bash
docker compose exec -T web pytest backend/tests/path/to/test_module.py -q
```

## 3. Implement, bottom-up

Domain, then services, then infrastructure, then `presentation/` and `schemas/`; move to the next layer only when the current layer's tests pass. Follow CONTRIBUTING §1–§3 and match the naming, comment density, and idioms of the neighbouring code.

Index and `$jsonSchema` changes go in `infrastructure/db/schema.py`. There are no migrations: reshaping existing documents or changing an existing index's options must be applied to the dev database by hand (or `make restart-db`); say so in the summary.

## 4. Run the tests (expect pass)

```bash
docker compose exec -T web pytest backend/tests/path/to/test_module.py -q
```

Then run the "done" checks in `CLAUDE.md` and iterate until they all pass. If the feature changes worker code, a task, a schedule, or a setting, restart the workers: `docker compose restart celery_worker celery_beat`.

## 5. Docs

Update the docs as CONTRIBUTING R3.3.15 requires: routes, tasks, settings, and layers in `README.md` / `docs/ARCHITECTURE.md`; entities and their behavior in `docs/DOMAIN_MODEL.md`; business requirements in `docs/BUSINESS_RULES.md`.

## Rules

- Tests first; never skip the failing run.
- Keep the change focused on the requested feature; do not modify unrelated files.
- Do not commit (the user runs `/commit-message`). Never stage `.env`.
- Never print API keys or secrets.
- Finish with: what was built, the files touched, the test count, lint/complexity status, and any assumption the user should confirm.

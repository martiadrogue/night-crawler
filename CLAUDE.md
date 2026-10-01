# Night Crawler Project Rules

## Documentation & Guides
- See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for architecture/layering rules, coding standards, naming conventions, and the PR checklist — the source of truth for how code in this repo must be written.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the services, container connectivity, project structure, layers, and background job pipeline.
- See [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) for the ubiquitous language, entities, relationships (ER diagram), enums/defaults, and structural invariants (`DM-*`).
- See [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md) for the business requirements: target sources and fields, deduplication, incremental updates, fault tolerance, and deliverables.
- See [README.md](README.md) for the project overview, setup, Makefile commands, and API reference.

## Working in This Repo
- Treat every `MUST`/`MUST NOT` rule in CONTRIBUTING.md as enforced, not aspirational — read the relevant section before writing or reviewing backend code.
- Before considering a change done: `make format`, `make lint`, `make test` (see README.md's Makefile Commands table), plus CONTRIBUTING.md's Pull Request Checklist.
- If a change alters architecture, endpoints, or standards, update README.md/docs/ARCHITECTURE.md/docs/DOMAIN_MODEL.md/docs/BUSINESS_RULES.md/docs/CONTRIBUTING.md themselves rather than re-describing the change here.

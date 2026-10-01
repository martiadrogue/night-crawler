# Night Crawler Project Rules

## Documentation & Guides
- See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for architecture/layering rules, coding standards, and naming conventions — the source of truth for how code in this repo must be written.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the services, container connectivity, project structure, layers, and background job pipeline.
- See [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) for the ubiquitous language, entities, relationships (ER diagram), enums/defaults, and structural invariants (`DM-*`).
- See [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md) for the business requirements: target sources and fields, deduplication, incremental updates, fault tolerance, and deliverables.
- See [README.md](README.md) for the project overview, setup, and the commands to run it.

## Working in This Repo
- Treat every `MUST`/`MUST NOT` rule in CONTRIBUTING.md as enforced, not aspirational — read the relevant section before writing or reviewing backend code.
- A backend change is done when:
  - `make format` and `make lint` pass (Ruff also checks the docstring rules, CONTRIBUTING §3.3);
  - `make complexity` shows grade A, or B with a one-line justification (R3.1.4);
  - `make test` passes;
  - the docs it affects are updated (R3.3.15).
- Record changes in those docs themselves, never here. Each topic has one home: rules in CONTRIBUTING.md, entity behavior in DOMAIN_MODEL.md, what exists and how it runs in ARCHITECTURE.md (linking to the others).

# Contributing Guide

This guide defines concrete, strictly enforced rules for contributing to this codebase. Requirements follow [RFC 2119](https://www.ietf.org/rfc/rfc2119.txt) (`MUST`, `SHOULD`, `MAY`, etc.).

**Prerequisite:** Python version in `pyproject.toml` (`requires-python`) and `Dockerfile` MUST match. `pyproject.toml` is authoritative; `Dockerfile` MUST be updated if they disagree.

---

## Standards Followed
- **Style:** [PEP 8](https://peps.python.org/pep-0008/) via Black (88-char limit, double quotes).
- **Docstrings:** [PEP 257](https://peps.python.org/pep-0257/) + Google style (`Args:`, `Returns:`, `Raises:`).
- **Type Hints:** [PEP 484](https://peps.python.org/pep-0484/), [PEP 526](https://peps.python.org/pep-0526/), [PEP 604](https://peps.python.org/pep-0604/) (`X | None`), [PEP 673](https://peps.python.org/pep-0673/) (`Self`).
- **Versioning:** [SemVer 2.0.0](https://semver.org/).
- **Architecture:** Clean/Hexagonal Architecture, SOLID, Repository (with read and write repository sets; write sets follow the Unit of Work pattern), Composition Root.
- **Persistence:** Surrogate Key Pattern for all entity primary keys.

---

## 1. Architecture Rules

### 1.1 Layering & Dependencies
Dependencies MUST flow in one direction only:
`presentation/` → `services/` → `domain/` ← `infrastructure/` | `schemas/` (consumed only by `presentation/` & `services/`)

*`core/` is the sole exception (Composition Root): it imports both `domain/` abstractions and `infrastructure/` implementations.*

| Layer | Package | MAY Import | MUST NOT Import | Accepts | Returns |
|---|---|---|---|---|---|
| Presentation | `presentation/` | `services/`, `schemas/`, abstract `domain/` stubs, `core/di.py` composition functions | Concrete `infrastructure/` | External requests/messages | External responses/acknowledgements |
| Application | `services/` | `domain/` abstractions, `schemas/` | Concrete `infrastructure/`, `presentation/` | Schemas | Schemas |
| Domain | `domain/` | *Nothing else* | `services/`, `infrastructure/`, `presentation/`, `schemas/`, 3rd-party frameworks | Primitives/Entities | Primitives/Entities |
| Infrastructure | `infrastructure/` | `domain/` | `schemas/`, `presentation/` | Domain entities | Domain entities |
| Composition Root | `core/` | Everything | — | — | — |

- **R1.1.1:** `domain/` MUST NOT import web, database driver (PyMongo/BSON), HTTP, task queue, or validation libraries (std-lib only).
- **R1.1.2:** Abstract stubs for `infrastructure/` dependencies used by HTTP routes MUST live in `presentation/api/dependencies.py` and raise `NotImplementedError`.
- **R1.1.3:** Binding concrete adapters to domain interfaces MUST happen ONLY in `core/di.py`; FastAPI dependencies are bound via `app.dependency_overrides`. Tests modifying `dependency_overrides` MUST clean up in `try/finally` or teardown.
- **R1.1.4:** Domain abstract base classes (`ABC`) MUST own shared constructor state (e.g., TTLs).

### 1.2 SOLID Rules
- **SRP (S):**
  - **R1.2.1:** Files in `infrastructure/db/` contain exactly one repository class for one resource.
  - **R1.2.2:** `services/` modules are async function collections (no classes), one module per use case. Service functions MUST NOT handle another use case's persistence; call that service function instead. Value objects a use case passes between its steps (parameter/result bundles, sets of ports) live in `domain/bundles/` as frozen dataclasses.
- **Open/Closed (O):**
  - **R1.2.3:** Add behavior by creating new implementations of `domain/` interfaces. Never modify `services/`.
- **Liskov Substitution (L):**
  - **R1.2.4:** Concrete classes MUST match domain interface signatures, async status, and parameter/return types strictly.
  - **R1.2.5:** Concrete implementations MUST ONLY raise exceptions declared in the domain interface's docstrings (or subclasses thereof).
- **Interface Segregation (I):**
  - **R1.2.6:** Domain interfaces MUST expose minimal, cohesive methods (e.g., single "resolve and fetch" over multi-step calls).
  - **R1.2.7:** Do not add unused methods to domain contracts; split into separate interfaces instead.
- **Dependency Inversion (D):**
  - **R1.2.8:** `services/` MUST depend only on abstract domain types (`Abstract...`) for I/O.
  - **R1.2.9:** Concrete `infrastructure/` classes MUST ONLY be instantiated inside `core/di.py`.

### 1.3 Side Effects & Purity
- **R1.3.1:** Transformation, validation, and normalization functions in `domain/` and `services/` MUST be pure, synchronous (`def`), and perform zero I/O, clock reads, or behavior-changing logging.
- **R1.3.2:** All I/O must originate in `infrastructure/`.
- **R1.3.3:** All I/O functions MUST be `async def` and use async client libraries. Blocking calls in `async def` are strictly prohibited.

### 1.4 State & Immutability
- **R1.4.1:** Value objects (no `id`) MUST use `@dataclass(frozen=True)`.
- **R1.4.2:** Entities (with `id`) MAY use non-frozen `@dataclass`, but MUST NOT be mutated in place. Repositories' `save()` MUST construct and return a new instance.
- **R1.4.3:** Mutable module-level state is prohibited outside `core/di.py` (which allows single long-lived client singletons for pooling). Per-instance state (e.g., `self._cache`) is allowed.
- **R1.4.4:** Read config via an `@lru_cache` settings singleton. Direct `os.environ` reads in `services/` or `domain/` are prohibited.
- **R1.4.5 Surrogate Key Pattern:** Every entity's primary key MUST be a surrogate key (`id: str`, UUIDv4) — never a natural/business key. Natural/business keys (e.g. `User.email`, a dataset record's `source` + `item_id`) MUST instead be enforced via a unique index on the collection. The UUID is stored as the document's `_id` (string) and mapped to `id` by the repository. See `docs/DOMAIN_MODEL.md` DM-1.

### 1.5 Data Access
- **R1.5.1 Repository sets:** Services reach storage only through a repository set, never a single repository in isolation:
  - `AbstractRepositories` — the shared port holding every repository attribute (`users`, `crawlers`, …).
  - `AbstractReadRepositories(AbstractRepositories)` — no transaction, no `commit()`/`rollback()`. Write methods (`save`, `save_all`, `delete`, `delete_*`, `clear_*`) MUST raise `ConfigurationException`.
  - `AbstractWriteRepositories(AbstractRepositories)` — one session and transaction across every repository (Unit of Work): `commit()` on success, `rollback()` on error.
- **R1.5.2 Choosing a set:** A use case that only reads MUST take `read_repositories: AbstractReadRepositories`. A use case that writes MUST take `write_repositories: AbstractWriteRepositories` for the whole operation, including its reads. A read helper shared by both (e.g. `get_crawler`) MUST be typed `AbstractRepositories`.
- **R1.5.3 Routes:** A route injects the set its service function takes (R1.5.2): `get_read_repositories` or `get_write_repositories`. Every `GET` route is read-only; a `POST` that only reads (e.g. login) also takes read repositories. Authentication (`get_current_user`) uses read repositories. A read helper shared by both kinds of use case is typed `AbstractRepositories` and its parameter is named `repositories`.
- **R1.5.4 Consistency:** Read repositories give no snapshot across queries; data may change between reads. A read that needs a consistent snapshot MUST use write repositories.

### 1.6 Error Handling
- **R1.6.1:** Controlled errors MUST derive from standard base class `AppException(message: str, status_code: int)`. Raising `Exception`, `ValueError`, or `RuntimeError` for business errors is prohibited.
- **R1.6.2:** Standard subclasses: Client errors (default HTTP `400`) and External service errors (default HTTP `502`).
- **R1.6.3:** A single global handler catches `AppException`. Route handlers MUST NOT use local `try/except` for response formatting. Non-`AppException` errors log tracebacks at `error` level and return generic `500`s.
- **R1.6.4:** Infrastructure adapters MUST convert 3rd-party HTTP/database errors into typed `AppException` subclasses before leaving the adapter.
- **R1.6.5:** Swallow-and-continue (catching exception to log and proceed) is prohibited. Non-acting observers MUST re-raise. *Exception — per-item isolation:* a loop over independent items (e.g. import rows) MAY catch a typed `AppException` for one item and continue, only if the failure is **recorded**, not just logged (e.g. counted in `import_metrics.rows_rejected` with its reason, or saved as a Crawler Execution Failure). Required by the BRD's error isolation.
- **R1.6.6:** Bare `except:` and unhandled `except Exception:` without re-raising or logging with tracebacks are prohibited.
- **R1.6.7 Missing data is not an error:** Extraction and normalization MUST return `None` (or an empty collection) for a missing optional field, never raise. Only a missing `required` field (`docs/DOMAIN_MODEL.md` §5.4) is a parsing failure.

---

## 2. Naming Conventions

### 2.1 Case Styles & Type Hints
- **Classes / Schemas / Exceptions:** `PascalCase` (Domain interfaces prefixed with `Abstract`).
- **Functions / Methods / Modules:** `snake_case`.
- **Compile-time Constants:** `UPPER_SNAKE_CASE`.
- **Runtime Configuration Attributes:** `snake_case` (lowercase).
- **Non-Python Files (Docker, CI):** `kebab-case`.
- **Directories / Packages:** lowercase, single word (`snake_case` if unavoidable).
- **R2.1.1:** Use `X | None` (not `Optional[X]`) and `Self` for self-returning methods.

### 2.2 Semantic Naming
- **R2.2.1 Booleans:** MUST start with `is_`, `has_`, `can_`, or `should_`.
- **R2.2.2 Functions/Methods:** MUST start with an active verb (`get_`, `create_`, `validate_`, `normalize_`, `calculate_`).
- **R2.2.3 Repositories:** Reads = `get_all()`, `get_by_<field>()`. Writes = `save()` (insert or upsert by natural key, returns the new instance), `save_all()` (bulk upsert, e.g. an import batch), `delete()`. Reference clean-up on delete (`SET NULL`, `CASCADE`, `RESTRICT` in `docs/DOMAIN_MODEL.md` §3.1) = `clear_<reference>()` / `delete_by_<reference>()`, called inside the same Unit of Work.
- **R2.2.4 DTO Suffixes:** `Base`, `Create`, `Update` (all fields optional), `Query` (or `QueryBy<Field>`), `Out`.
- **R2.2.5 Middleware:** Custom request/response middleware classes MUST use `_middleware` suffix. Framework lifecycle hooks such as FastAPI `lifespan` are not request/response middleware and are not required to follow this suffix. Routes use `verb + resource`.
- **R2.2.6 Tasks:** Background tasks MUST specify explicit `name="<package>.tasks.<func_name>"`.
- **R2.2.7 Document Variables:** Map raw MongoDB documents to entities using prefix `db_` (e.g., `db_user`).

### 2.3 Abbreviations
- **R2.3.1:** Arbitrary word truncations are prohibited (e.g., use `user_repository`, not `usr_repo`).
- **R2.3.2:** Allowed acronyms: `id`, `url`, `http`, `json`, `csv`, `db`, `jwt`, `ttl`, `api`. Repository sets are never abbreviated: use `read_repositories` / `write_repositories`, not `uow`.

### 2.4 File & Folder Structure
- **R2.4.1 `infrastructure/`:** One adapter class per file. File named after abstraction (`<resource>_repository.py`). Class named after technology (`Mongo<Resource>Repository`).
- **R2.4.2 `domain/`:** Grouped by kind: `model/` (`constants.py`, `entities.py`, `value_objects.py` shared across the domain), `ports/` (abstract I/O interfaces and their result types), `rules/` (pure business logic, with any value object only that rule uses), `bundles/` (step bundles, R1.2.2); `exceptions.py` stays at the root. See `docs/DOMAIN_MODEL.md` §2.1 for how to tell the kinds apart.
- **R2.4.3 `schemas/`:** One file per resource containing all DTO suffixes.
- **R2.4.4 `services/`:** One file per use case with `async def` functions.
- **R2.4.5 `presentation/`:** Inbound adapters are grouped by transport: `api/` has one router file per resource, exporting `router = APIRouter()`; `worker/` contains Celery task entrypoints.
- **R2.4.6 `core/`:** Settings, logging, and `di.py` only.
- **R2.4.7 Tests:** One-to-one mapping in `backend/tests/` path: `backend/tests/<path>/test_<module>.py`.

---

## 3. Code Style & Formatting

### 3.1 Tools & Quality
- **R3.1.1 Format:** Black (default config).
- **R3.1.2 Lint:** Ruff (`pyproject.toml`). Exceptions: dependency injection calls allowed in defaults; naive datetimes allowed in tests. Ruff also enforces §3.3's docstring rules (`D` with the Google convention, `W505` at 72 columns) for `backend/src`; tests and the frontend are excluded.
- **R3.1.3 Workflow:** Contributors MUST run `make format` (runs formatter then linter autofix). `make lint` checks linting only.
- **R3.1.4 Complexity:** Checked via `make complexity`. Floor is Grade **A**. Grade **C** MUST be refactored. Grade **B** SHOULD be refactored unless justified in comments.

### 3.2 Design Requirements
- **R3.2.1 Length:** Keep bodies ~30 lines or less.
- **R3.2.2 Parameters:** Max 3 *required* positional **data** parameters (excluding `self`/`cls`). Bundle additional parameters into a schema when they form an HTTP payload, otherwise into a frozen `domain/` value object. *Exemptions:* injected dependencies don't count: `presentation/api/` route dependency injections (`Depends(...)`), and in `services/` the repository set (`read_repositories`, `write_repositories`, or `repositories`), the acting user (`current_user`), and domain ports or port bundles (e.g. `RequestExecutors`). Required dependencies MUST come before data parameters (optional ones with defaults stay last).
- **R3.2.3 Guard Clauses:** Validate and exit/raise early. No wrapping happy paths inside big `if` statements.
- **R3.2.4 Nesting:** Max 2 indentation levels deep (excluding `def` line and 1 `try`/`with` wrapper).
- **R3.2.5 Yoda Conditions:** Equality/identity comparisons against a constant or literal MUST place the constant/literal on the left (e.g. `if 3 == x:`, `if None is x:`, `if "active" == status:`). Comparisons between two variables are unaffected.

### 3.3 Comments & Documentation

#### Docstrings
- **R3.3.1 Coverage:** Every public module, class, function, and method MUST have a docstring. Private (`_`-prefixed) ones SHOULD have one only when their behavior is not obvious from name and signature.
- **R3.3.2 Format:** Docstrings MUST use triple double quotes `"""` ([PEP 257](https://peps.python.org/pep-0257/)).
- **R3.3.3 Style:** Docstrings MUST use Google style (`Args:`, `Returns:`, `Raises:`). NumPy and reStructuredText styles are prohibited.
- **R3.3.4 Exceptions:** `Raises:` MUST list every exception the function raises or deliberately lets propagate, with the condition that triggers it (see R1.2.5).
- **R3.3.5 Types:** Type hints are the only source of type information. All public signatures MUST be fully annotated, and docstrings MUST NOT repeat types in `Args:`/`Returns:` — describe meaning, units, and constraints instead.
- **R3.3.6 One-line docstrings:** A simple, self-explanatory function MUST use a single-line docstring under 72 characters, written as an imperative summary (`"""Return the user's active crawlers."""`).
- **R3.3.7 Multi-line docstrings:** MUST start with a one-line summary, then a blank line, then the details and `Args:`/`Returns:`/`Raises:` sections.

#### Comments
- **R3.3.8 Naming first:** Use clear naming instead of explanatory comments.
- **R3.3.9 Why, not what:** Comments MUST explain **why** (intent, constraints, workarounds), never **what** the code does.
- **R3.3.10 Inline comments:** SHOULD fit on one line. Place them on the line above the target, or at the end of the line separated by at least two spaces (`x = 1  # why`).

#### Length & Depth
- **R3.3.11 Line length:** Docstring and comment lines MUST NOT exceed 72 characters ([PEP 8](https://peps.python.org/pep-0008/#maximum-line-length)). Code lines keep Black's 88.
- **R3.3.12 Depth vs. brevity:** Document non-obvious edge cases, invariants, and failure modes thoroughly. Omit anything that restates the code, the signature, or the call sites.
- **R3.3.13 Adapters:** Concrete implementations SHOULD document adapter-specific behavior (units, miss/hit rules).

#### Project Documentation
- **R3.3.14 README:** The root `README.md` MUST cover installation, usage examples, and the commands needed to run the project, and link to `docs/` for architecture, domain model, and business rules. The docs MUST also explain the strategies the BRD asks for (discovery, deduplication, incremental updates, resuming jobs, dynamic content) and list known limitations and trade-offs (`docs/BUSINESS_RULES.md` §6).
- **R3.3.15 Docs stay current:** A change to architecture, entities, or business rules MUST update the matching file in `docs/` (`ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `BUSINESS_RULES.md`) in the same PR.

### 3.4 Clean Code
- **R3.4.1:** Commented-out code is prohibited.
- **R3.4.2:** Unused imports and variables are prohibited unless explicitly justified inline for public exports.
- **R3.4.3:** Unreachable code is prohibited.
- **R3.4.4:** `print()` is prohibited in source tree. Use `logging.getLogger(__name__)`.

### 3.5 Testing Standards
- **R3.5.1:** Mocking layer boundaries MUST spec against abstract `domain/` interfaces, not concrete classes.
- **R3.5.2:** Async tests MUST use project async markers and the `anyio_backend` fixture.
- **R3.5.3:** Route tests MUST clean up `dependency_overrides` mutations.
- **R3.5.4:** Adapter tests SHOULD use disposable backends over mocking the DB layer itself: a throwaway MongoDB database (unique name, dropped after the session) on the Compose `db` service, and a temp directory for CSV export storage.

---

## 4. Pull Request Checklist

### Architecture & Dependencies
- [ ] No framework imports in `domain/` (R1.1.1).
- [ ] Dependencies wired ONLY in `core/di.py` (R1.1.3, R1.2.9).
- [ ] `services/` does not import I/O libraries directly (R1.3.2).
- [ ] All I/O functions are `async def` using async drivers (R1.3.3).
- [ ] Value objects frozen; entities not mutated in place (R1.4.1, R1.4.2).
- [ ] No global mutable state outside `core/di.py` (R1.4.3).
- [ ] Entity primary keys are surrogate UUIDs; natural keys use unique indexes (R1.4.5).
- [ ] Read-only use cases take `read_repositories`; any use case that writes takes `write_repositories` for all of it (R1.5.1–R1.5.4).

### Errors & Exceptions
- [ ] Business/I/O errors derive from `AppException` (R1.6.1, R1.6.2).
- [ ] Route handlers do not wrap responses in local `try/except` (R1.6.3).
- [ ] External/DB driver exceptions converted in adapter layer (R1.6.4).
- [ ] No swallowed exceptions or bare `except:` statements; per-item failures are recorded (R1.6.5, R1.6.6).
- [ ] Missing optional fields become `None`, never an exception (R1.6.7).

### Naming & Organization
- [ ] Cases match guidelines (`PascalCase`, `snake_case`, `UPPER_SNAKE_CASE`) (§2.1).
- [ ] Booleans use prefixes (`is_`, `has_`, `can_`, `should_`); functions use active verbs (R2.2.1, R2.2.2).
- [ ] DTOs use valid suffixes (`Base`, `Create`, `Update`, `Query`, `Out`) (R2.2.4).
- [ ] Uses `X | None` union syntax (R2.1.1).
- [ ] Files and tests follow layer structure (R2.4.1–R2.4.7).

### Code Style & Quality
- [ ] Formatted via `make format` (R3.1.3).
- [ ] No dead code, unused imports, or `print()` calls (§3.4).
- [ ] Complexity grade **A** (or justified **B**) via `make complexity` (R3.1.4).
- [ ] Max 2 nesting levels; guard clauses used (R3.2.3, R3.2.4).
- [ ] Constant/literal comparisons use Yoda condition ordering (R3.2.5).
- [ ] Max 3 required positional data params; injected dependencies come first and are exempt (R3.2.2).
- [ ] Public modules/classes/functions have Google-style `"""` docstrings, with `Raises:` complete and no types repeated (R3.3.1–R3.3.5).
- [ ] Simple functions use one-line docstrings; multi-line ones have summary + blank line (R3.3.6, R3.3.7).
- [ ] Comments state *why*, fit one line where possible, and docstring/comment lines are ≤ 72 chars (R3.3.9–R3.3.11).

### Testing & Documentation
- [ ] Test doubles spec'd against domain interfaces (R3.5.1).
- [ ] Async test markers and `anyio_backend` used (R3.5.2).
- [ ] `dependency_overrides` cleaned up in test teardowns (R3.5.3).
- [ ] Adapter tests use disposable backends (R3.5.4).
- [ ] `make test` passes with full coverage.
- [ ] `docs/` updated if architecture, entities, or business rules changed (R3.3.15).

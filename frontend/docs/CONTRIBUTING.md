# Contributing to the Frontend

Rules for code under `frontend/`. `MUST`/`MUST NOT` are enforced in review.
For the backend, see the root [docs/CONTRIBUTING.md](../../docs/CONTRIBUTING.md).

## 1. Architecture

- **FR1.1** The UI MUST talk to FastAPI only through `api_client.py`,
  from event handlers (server side). Components MUST NOT call the API, and
  the browser never does.
- **FR1.2** `api_client.py` MUST have one small async function per
  endpoint, taking the token first (except `register` and `login`),
  returning the decoded JSON (or `None` for an empty body), and raising
  `ApiError` for any non-2xx. No retries, no caching.
- **FR1.3** Business rules (who may do what, version lifecycle, cron
  validity, selector config) MUST NOT be re-implemented in the UI. Send the
  request and show the API's message. The UI MAY disable controls to guide
  the user (e.g. read-only archived versions); the API still decides.
- **FR1.4** Turning form input into API payloads MUST live in `forms.py`
  as pure functions (no Reflex, no I/O) returning `(payload, error)`.
  Filling a form from an entity MAY stay in the state's `start_edit_*`
  handler when it is only defaults (`or ""`) and `json.dumps`.
- **FR1.5** Each page has one `rx.State` in `state/`, which MAY be shared
  (`AuthState` serves `/`, `/login`, and `/register`); one page module per
  route, in `pages/`; reusable pieces in `components/`.

## 2. State and Events

- **FR2.1** Every page behind login MUST have an `on_load` handler that
  redirects to `/login` without a token, then loads its data. `/login`
  and `/register` have none.
- **FR2.2** Every `api_client` call MUST sit in a `try` catching
  `ApiError`, shown in the page's or dialog's error var; handlers MUST NOT
  let it escape.
- **FR2.3** State vars holding API data MUST be plain `dict`/`list[dict]`
  as the API returns them; derived values are `@rx.var`s.
- **FR2.4** Do not declare a var named like a dynamic route arg
  (`crawler_id`, `version_id`); Reflex creates it and refuses shadowing.
- **FR2.5** After a mutation, reload from the API instead of patching
  local lists. After editing a published version, follow the forked draft
  (`VersionEditorState._after_change`).
- **FR2.6** Tokens and passwords MUST NOT be logged or rendered.

## 3. Components

- **FR3.1** Pages MUST be wrapped in `page_shell` (auth pages excepted).
- **FR3.2** Forms MUST use uncontrolled inputs with `default_value` and a
  `key` that changes when the edited item changes; selects are controlled
  through state setters.
- **FR3.3** Optional-id selects MUST use `optional_id_choice` and
  `forms.NO_SELECTION`.
- **FR3.4** Use Radix components (`rx.*`) and theme tokens
  (`var(--gray-5)`, `color_scheme=`); no custom CSS files.

## 4. Style and Quality

- **FR4.1** Black and Ruff (repo `pyproject.toml`) MUST pass; the docstring
  rules are not enforced here, but a helper whose name doesn't say it all
  gets a one-line docstring.
- **FR4.2** Cyclomatic complexity MUST be grade A (`radon cc`), or B with a
  one-line comment saying why.
- **FR4.3** Every public function in `forms.py` and `api_client.py` MUST
  be covered by `frontend/tests/` (pytest + anyio; `httpx.MockTransport`
  via `api_client.TRANSPORT`, never the network). A new endpoint function
  gets a row in `test_api_client.py`'s `ENDPOINTS` table.
- **FR4.4** Names follow the backend's ubiquitous language (crawler,
  version, message template/selector/aid), never "job".

## 5. Pull Request Checklist

- [ ] `make format` and `make lint` pass.
- [ ] `make test-frontend` passes; new helpers are tested.
- [ ] `docker compose exec -T web radon cc frontend/src -n B` prints nothing (or each B is justified).
- [ ] The frontend compiles (`docker logs reflex_frontend_dev` shows "App running") and the changed flow was clicked through in a browser.
- [ ] `frontend/docs/ARCHITECTURE.md` lists any new page, state, or API call.

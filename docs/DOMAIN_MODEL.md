# Domain Model

This document describes Night Crawler's domain: its vocabulary, entities, value objects, relationships, and the structural invariants that always hold. It is extracted from `backend/src/night_crawler/domain/` (entities) and `infrastructure/db/schema.py` (indexes and validators) — when the two disagree with this file, the code wins and this file must be updated.

What the system must deliver — target sources, fields, deduplication, incremental updates, fault tolerance — lives in [BUSINESS_RULES.md](BUSINESS_RULES.md). How the code is layered lives in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Ubiquitous Language

| Term | Meaning |
|---|---|
| **Crawler** | A named crawl definition pairing one **source** (where the data comes from) with one target **dataset** (what it downloads): its `fields`, the dataset fields it downloads, and an optional cron `schedule` that always runs the published version (an empty schedule means manual runs only). |
| **Dataset** | What we expect to download, stored as a record: its **fields**. `venues`, `reviews`, and `menus` are built in; more can be added. Every Crawler is linked to exactly one; one Dataset can be fed from many Sources. |
| **Dataset field** | One field of a Dataset: its `name`, `type`, `pattern` (the regex its values should match), and whether it is required (every Crawler on the Dataset lists it in its `fields`, and a row without it is dropped) or unique (never repeated within one Source). `item_id` is always required and unique. |
| **Source** | The origin of the data: a website crawled data comes from (e.g. TheFork), stored as a record. Every Crawler is linked to exactly one. A Source feeds zero or more Datasets and a Dataset is fed by zero or more Sources; that pairing is never stored on its own, it is whatever the Crawlers pair. |
| **Crawler Version** | A snapshot of a Crawler's request tree, identified by its UUID and ordered by `created_at`. Exactly one lifecycle status: `draft`, `published`, or `archived`. A published version is archived only when a draft is published over it; it can't be archived on its own. |
| **Message Template** | One outbound request node (`action`, `url`, `body`, `headers`) in a Crawler Version. Every version has exactly one **root template**. |
| **Message Selector** | An extraction rule on a template: `value`, `boolean`, `iterator`, `click`, `select`, or `pagination`. Selectors nest via `parent_selector_id`; a selector's `title` names what it harvests. |
| **Message Aid** | Optional per-template execution settings: proxy, render mode, TTL, ban/retry codes, retry budgets, rate limit. |
| **Proxy** (`MessageAidProxy`) | An admin-managed, pooled proxy credential. |
| **Rate Limit** (`MessageAidRateLimit`) | A reusable sliding-window + penalty/decay rule, applied per domain or per proxy. |
| **Crawler Execution** | One run of a Crawler Version. Tracks an execution `status`, a separate `parsing_status`, and run `metrics`. |
| **Crawler Execution Context** | Key/value state harvested (or externally supplied) during one Crawler Execution. Iterator keys end in `[]`. It is also the run's **checkpoint**: an interrupted execution resumes from it. |
| **Placeholder** | `{{name}}` inside a template's action/url/body/headers, resolved from the Crawler Execution Context. |
| **Fan-out** | Running one template once per combination of array (`key[]`) placeholder values. |
| **Self-fed placeholder** | A template placeholder that one of the template's own selectors harvests. The template runs again while it changes: per combination for a single value (e.g. a page token), and for each new element of a list (e.g. links) — §5.8. |
| **Instruction Generation** | A request for AI agents to write a Crawler Version's instructions from a natural-language **prompt**. It runs on the `ai-agents` queue: a browser agent gets the data while it is **recorded**, a synthesizer turns the recording into an instructions file, which is imported like an uploaded one (§5.9), then a test run of the result starts. It runs no instructions itself, so it is not a Crawler Execution. |
| **Filtered recording** | The requests of an Agent recording that led to its extracted data, each with why it was kept (`carries final data`, `feeds <url>`, `sets cookie <name>`). What instructions are written from (§4.16). |
| **Agent recording** | What the browser agent did for one Instruction Generation: its steps, every request its browser made (tied to the step that made it), and the data it extracted. What instructions are written from (§4.16). |
| **Execution dataset** | The CSV one Crawler Execution produces from harvests whose selector title matches one of the Crawler's fields. The crawl's only output. |
| **Dataset import** | The separate process that loads a finished execution dataset into the Crawler's target Dataset collection. The only writer of `dataset_*`. |
| **Dataset collection** | A Dataset's final, deduplicated store of crawled data: `dataset_venues`, `dataset_reviews`, `dataset_menus`. It outlives the Crawlers and Executions that fed it. |
| **Dataset record** | One Venue, Review, or Menu document. Identified by its **natural key**: its Source + its `item_id` (the website's own ID for the item; a menu's is its venue's), so the same ID on two websites never merges. |
| **Upsert** | How the import writes a dataset record by natural key: insert if unknown, otherwise update in place. Never a second copy. |
| **Content hash** | A hash of a record's normalized, non-volatile fields. Equal hash = unchanged record. |
| **Sighting** | An imported row for a record that already exists. Always bumps `last_seen_at`; bumps `updated_at` only when the content hash changes. |
| **Render mode** | Which engine dispatches a template: `none` (httpx), `playwright`, or `stealth` (Patchright). |
| **Proxy Ladder** | The opt-in escalation strategy for blocked dispatches (direct → cookie harvest → IP rotation). |

---

## 2. Aggregates

The model splits into six groups. Each aggregate root owns the lifecycle of the entities beneath it — deleting the root deletes them.

| Aggregate | Root | Owns | Purpose |
|---|---|---|---|
| **Identity** | `User` | — | Who can act, and with which role. Kept in Keycloak, not in MongoDB (§4.1). |
| **Crawler definition** | `Crawler` | `CrawlerVersion` → `MessageTemplate` → `MessageSelector` (tree), `MessageAid` (0..1) | *What* to crawl and how. |
| **Shared resources** | `Source`, `Dataset`, `MessageAidProxy`, `MessageAidRateLimit` | — | Pools referenced by crawlers and never owned by one; any user creates them, only admins edit or delete them. |
| **Execution** | `CrawlerExecution` | `CrawlerExecutionContext`, `CrawlerExecutionFailure`, `CrawlerExecutionResponse`, `CrawlerExecutionDataset` | One run of a Crawler Version: its checkpoint, metrics, debug trail, and the CSV it produced. |
| **Instruction generation** | `InstructionGeneration` | — | One request for AI agents to write a version's instructions: its prompt, the browser agent's recording, progress, the draft it landed on, and the test run of that draft. Owned by its Crawler: deleting the Crawler deletes it. |
| **Dataset records** | `DatasetVenue` | `DatasetReview` (many), `DatasetMenu` (0..1) | The final crawled data, filled only by the dataset import. Not owned by any Crawler or Execution. |

### 2.1 How `domain/` is organized

Code in `domain/` is grouped by *kind*, not by aggregate:

| Folder | Holds | Ask: is it… |
|---|---|---|
| `model/` | `entities.py`, `value_objects.py` (shared ones), `constants.py` | …a business object with an `id` (entity), an immutable value used across the domain (value object), or fixed vocabulary (constant)? |
| `ports/` | `Abstract…` interfaces, plus the result types they return | …something that does I/O? The domain only declares it; `infrastructure/` implements it. |
| `rules/` | Pure functions, plus value objects only that rule uses (e.g. `ProxyLadderState`) | …a decision computed from data, with no I/O, clock, or framework? |
| `bundles/` | Frozen dataclasses a use case passes between its steps | …a parameter or result bundle for `services/` rather than a business concept? |
| `exceptions.py` | The `AppException` hierarchy | …an error a rule or port raises? |

Everything in `domain/` imports only the standard library and other `domain/` modules, and nothing in it is mutated in place.

---

## 3. Entity Relationships

```mermaid
erDiagram
    USER ||--o{ CRAWLER : creates
    SOURCE ||--o{ CRAWLER : "feeds the datasets of"
    DATASET ||--o{ CRAWLER : "shapes the CSV of"
    SOURCE }o..o{ DATASET : "paired by crawlers"
    SOURCE ||--o{ DATASET_VENUE : keys
    SOURCE ||--o{ DATASET_REVIEW : keys
    SOURCE ||--o{ DATASET_MENU : keys
    USER ||--o{ CRAWLER_VERSION : owns
    CRAWLER ||--|{ CRAWLER_VERSION : "has versions"
    CRAWLER ||--o{ CRAWLER_EXECUTION : "is run as"
    CRAWLER_VERSION ||--|{ MESSAGE_TEMPLATE : contains
    CRAWLER_VERSION |o--|| MESSAGE_TEMPLATE : "root template"
    CRAWLER_VERSION ||--o{ CRAWLER_EXECUTION : "executed by"
    MESSAGE_TEMPLATE ||--o{ MESSAGE_SELECTOR : extracts
    MESSAGE_SELECTOR |o--o{ MESSAGE_SELECTOR : "parent of"
    MESSAGE_TEMPLATE ||--o| MESSAGE_AID : "configured by"
    MESSAGE_AID }o--o| MESSAGE_AID_PROXY : "selected proxy"
    MESSAGE_AID }o--o| MESSAGE_AID_RATE_LIMIT : "domain rate limit"
    MESSAGE_AID_PROXY }o--o| MESSAGE_AID_RATE_LIMIT : "proxy rate limit"
    CRAWLER ||--o{ INSTRUCTION_GENERATION : "is written by"
    USER ||--o{ INSTRUCTION_GENERATION : asks
    CRAWLER_VERSION |o--o{ INSTRUCTION_GENERATION : "targeted by"
    CRAWLER_VERSION |o--o{ INSTRUCTION_GENERATION : "result of"
    INSTRUCTION_GENERATION }o--o| CRAWLER_EXECUTION : "tested by"
    CRAWLER_EXECUTION ||--o{ CRAWLER_EXECUTION_CONTEXT : holds
    CRAWLER_EXECUTION ||--o| CRAWLER_EXECUTION_FAILURE : "failed with"
    CRAWLER_EXECUTION ||--o{ CRAWLER_EXECUTION_RESPONSE : logs
    CRAWLER_EXECUTION ||--o| CRAWLER_EXECUTION_DATASET : produces
    CRAWLER_EXECUTION_FAILURE }o--o| MESSAGE_TEMPLATE : "failing template"
    CRAWLER_EXECUTION_RESPONSE }o--o| MESSAGE_TEMPLATE : "dispatched by"
    CRAWLER_EXECUTION |o--o{ DATASET_VENUE : "last imported from"
    CRAWLER_EXECUTION |o--o{ DATASET_REVIEW : "last imported from"
    CRAWLER_EXECUTION |o--o{ DATASET_MENU : "last imported from"
    DATASET_VENUE ||--o{ DATASET_REVIEW : "reviewed in"
    DATASET_VENUE ||--o| DATASET_MENU : "serves"
```

### 3.1 Relationship rules

MongoDB has no foreign keys. A reference is a string field holding the target's `_id`. The delete behaviour below (`CASCADE`, `SET NULL`, `RESTRICT`) is carried out by the repositories inside one write-repositories transaction, so it stays all-or-nothing.

| From → To | Cardinality | On delete of the target (write-transaction behaviour) |
|---|---|---|
| Crawler → User (`user_id`, creator) | many → 1 | **Never deleted** — users are only disabled; their Crawlers stay (BUSINESS_RULES §9) |
| Crawler → Dataset (`dataset_id`) | many → **1** (required) | **`RESTRICT`** — a Dataset a Crawler uses can't be deleted, and an edit that would break a linked Crawler's fields is refused |
| Crawler → Source (`source_id`) | many → **1** (required) | **`RESTRICT`** — a Source a Crawler uses can't be deleted; relink the Crawler first |
| Source ↔ Dataset | many ↔ many, **derived** | No reference of its own: a Source feeds the Datasets its Crawlers target, and a Dataset is fed by its Crawlers' Sources |
| Dataset Venue / Review / Menu → Source (`source`) | many → 1 | **`RESTRICT`** — part of the natural key |
| Crawler Version → Crawler | many → 1 | `CASCADE` |
| Crawler Version → User (`user_id`, owner) | many → 1 | **Never deleted** — as above |
| Crawler Version → root Message Template (`message_template_root_id`) | 1 → 1 | **Not maintained** (see DM-12) |
| Message Template → Crawler Version | many → 1 | `CASCADE` |
| Message Selector → Message Template | many → 1 | `CASCADE` |
| Message Selector → parent Message Selector | many → 0..1 | `CASCADE` — deleting a selector deletes its subtree |
| Message Aid → Message Template | **1 → 1** (unique) | `CASCADE` |
| Message Aid → Proxy (`selected_proxy_id`) | many → 0..1 | `SET NULL` |
| Message Aid → Rate Limit (`rate_limit_id`) | many → 0..1 | `SET NULL` |
| Proxy → Rate Limit (`rate_limit_id`) | many → 0..1 | `SET NULL` |
| Crawler Execution → Crawler | many → 1 | `CASCADE` |
| Crawler Execution → Crawler Version | many → 1 | **`RESTRICT`** — a version that has been run cannot be deleted |
| Crawler Execution Context → Crawler Execution | many → 1, unique per (`crawler_execution_id`, `key`) | `CASCADE` |
| Crawler Execution Failure → Crawler Execution | **1 → 1** (unique) | `CASCADE` |
| Crawler Execution Response → Crawler Execution | many → 1 | `CASCADE` |
| Crawler Execution Dataset → Crawler Execution | **1 → 1** (unique) | `CASCADE` — the exported file on disk is kept |
| Crawler Execution Failure / Response → Message Template | many → 0..1 | `SET NULL` — history survives template deletion |
| Instruction Generation → Crawler | many → 1 | `CASCADE` |
| Instruction Generation → Crawler Version (`crawler_version_id`, targeted; `result_version_id`, landed on) | many → 0..1 each | `SET NULL` — unlike a Crawler Execution, a generation never keeps a version from being deleted |
| Instruction Generation → Crawler Execution (`test_execution_id`) | many → 0..1 | **Not maintained** — executions are only deleted with their Crawler, which deletes its generations too |
| Instruction Generation → User (`user_id`, who asked) | many → 1 | **Never deleted** — the worker looks the user up in Keycloak and acts as them, even once disabled; an id Keycloak doesn't know fails the generation (`User not found.`) |
| Dataset Venue / Review / Menu → Crawler (`crawler_id`) | many → 0..1 | `SET NULL` — crawled data survives its Crawler |
| Dataset Venue / Review / Menu → Crawler Execution (`last_execution_id`) | many → 0..1 | `SET NULL` — crawled data survives its Execution |
| Dataset Review → Dataset Venue (`venue_id`) | many → 1 | `CASCADE` |
| Dataset Menu → Dataset Venue (`venue_id`) | **1 → 1** (unique) | `CASCADE` |

### 3.2 Collections

Each entity is stored in its own collection. The surrogate `id` is stored as the document's `_id`.

| Entity | Collection |
|---|---|
| User | — (Keycloak's `night-crawler` realm) |
| Crawler | `crawlers` |
| Crawler Version | `crawler_versions` |
| Message Template | `message_templates` |
| Message Selector | `message_selectors` |
| Message Aid | `message_aids` |
| Message Aid Proxy | `message_aid_proxies` |
| Message Aid Rate Limit | `message_aid_rate_limits` |
| Crawler Execution | `crawler_executions` |
| Crawler Execution Context | `crawler_execution_contexts` |
| Crawler Execution Failure | `crawler_execution_failures` |
| Crawler Execution Response | `crawler_execution_responses` |
| Crawler Execution Dataset | `crawler_execution_datasets` |
| Instruction Generation | `instruction_generations` |
| Dataset Venue | `dataset_venues` |
| Dataset Review | `dataset_reviews` |
| Dataset Menu | `dataset_menus` |

---

## 4. Entities

All entities use a surrogate `id` (UUIDv4 string) and carry `created_at`/`updated_at` (naive UTC) unless noted. Only non-obvious attributes are listed.

### 4.1 User

Kept in Keycloak's `night-crawler` realm, not in MongoDB: the API only
stores its `id` in `user_id` references, and reaches the account
through `AbstractUserDirectory` (`domain/ports/user_directory.py`).

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `id` | str | — | Keycloak's id; the access token's `sub`. |
| `email` | str | — | Unique (Keycloak enforces it); also the Keycloak username. |
| `role` | enum | `user` | `admin` · `user` · `viewer`: the most privileged of the account's effective realm roles; `None` if it holds none. |
| `is_enabled` | bool | `true` | `false` once disabled; never deleted (BUSINESS_RULES §9). |
| `created_at` | datetime | — | Keycloak's creation time; `None` for accounts imported with the realm file. |

The API knows who is calling from Keycloak's access token alone
([ARCHITECTURE: Authentication](ARCHITECTURE.md#authentication)) and has
no `users` collection. Every `user_id` written since the move to
Keycloak holds a Keycloak id; ones written before hold the UUIDs of the
`users` collection the API used to keep, which Keycloak doesn't know.

### 4.2 Crawler

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `user_id` | Ref User | — | Creator. |
| `title` | str(255) | — | |
| `source_id` | Ref Source | — | Required; must exist. Every dataset record imported from it is keyed on this Source. Not versioned. |
| `dataset_id` | Ref Dataset | — | Required; must exist. What it downloads; its `fields` are checked against it. |
| `fields` | list[str] | — | At least one. Which Dataset fields each execution downloads, in CSV order ([§5.4](#54-crawler-fields)). Not versioned. |
| `schedule` | str \| null | `null` | 5-field cron expression. |
| `queue` | enum | `discovery` | One of `CRAWLER_QUEUES` (every execution queue but `testing`): where every run of the Crawler, scheduled or manual, is sent. Part of its schedule, not versioned. |

### 4.3 Crawler Version

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `crawler_id` | Ref Crawler | — | |
| `user_id` | Ref User | — | Owner: whoever created the draft. |
| `status` | enum | `draft` | `draft` · `published` · `archived`. `published` → `archived` only by publishing another draft. |
| `message_template_root_id` | str \| null | — | Points at a template of this same version. |
| `published_at` | datetime \| null | `null` | Set on publish. |
| `is_proxy_ladder_enabled` | bool | `false` | |
| `is_host_session_sharing_enabled` | bool | `true` | |

### 4.4 Message Template

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `crawler_version_id` | Ref Crawler Version | — | |
| `action` | enum | — | `GET` · `POST` · `PUT` · `PATCH` · `DELETE` · `CLICK`. |
| `url` | str(2048) | — | May contain placeholders. |
| `body` | text \| null | `null` | May contain placeholders. |
| `headers` | JSON | `{}` | String values may contain placeholders. |

### 4.5 Message Selector

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `message_template_id` | Ref Message Template | — | |
| `parent_selector_id` | Ref Message Selector \| null | `null` | `null` = top-level. |
| `type` | enum | — | `value` · `iterator` · `boolean` · `click` · `select` · `pagination`. |
| `path` | text | — | Read according to `source` (below). |
| `target` | str | `__text` | For HTML matches: `__text` reads the element's text, anything else reads that attribute. For `select`: the option value to pick. |
| `title` | str \| null | `null` | Harvest name: a Context key, a CSV field (matches one of the Crawler's `fields`, §5.4), or a placeholder source. Never ends in `[]` (refused, 422): under an `iterator`, `click`, or `select` the Context key becomes `title[]` on its own, and templates still use `{{title}}`. |
| `config` | JSON \| null | `null` | A `pagination` selector's settings (§5.7); required for that type, forbidden for the others. |
| `source` | enum | `content` | What `path` reads: `content` · `headers` · `url` · `context`. |

How `path` reads, by `source` and response:

| `source` | Response | `path` is | Value |
|---|---|---|---|
| `content` | HTML | XPath when it starts with `/`, `./`, `../`, or `(`; otherwise a CSS selector | The first match, read by `target` |
| `content` | JSON (`Content-Type` contains `json`) | JMESPath | The result as is (lists and objects included) |
| `headers` | any | A regex, matched against each response header written as `name: value` with the name lower-cased (cookies are `set-cookie:` lines) | The first capture group `(...)`, or the whole match without one |
| `url` | any | A regex over the final URL (after redirects) | Same |
| `context` | any | A placeholder name | That placeholder's value in the template's run (e.g. the `place_id` a detail page was fanned out over); `boolean` tells whether it has one |

An `iterator` over HTML whose match is a `<script>` holding JSON (a page's schema.org JSON-LD, `type="application/ld+json"`) gives its children that JSON, read with JMESPath: e.g. an XPath iterator `//script[@type='application/ld+json'][contains(., 'ComedyEvent')]`, then a child iterator `[?"@type" == 'ComedyEvent']` and leaves like `startDate`. JSON-LD that doesn't parse gives its children nothing.

JMESPath paths also have `format_epoch(seconds, format, timezone)`, for sites that give dates as Unix seconds: it returns the moment as `strftime` text in an IANA timezone, e.g. `format_epoch(start, '%Y-%m-%d %H:%M:%S', 'Europe/Madrid')` → `2026-10-08 20:30:00`. Seconds may be a number or numeric text; a value it can't read, or an unknown timezone, gives an empty value (`infrastructure/external/content_harvest.py`). `placeholder(name)` returns the run's value for one of the template's placeholders, so a JSON value can be combined with it, e.g. `join('', ['https://www.atrapalo.com', placeholder('show_path'), '#', startDate])`. `format_iso(text, format, timezone)` does the same for ISO 8601 text, e.g. schema.org's `startDate` `2026-10-08T19:30:00+02:00`: a moment with an offset is converted to the timezone, one without is taken as already in it.

A `headers`/`url` path must compile as a regex (checked on write). Only `value` and `boolean` selectors can read `context` (`CONTEXT_SELECTOR_TYPES`, checked on write); the placeholder must be one the template's request uses.

Selector roles:
- `value` / `boolean` **harvest**: the first match, or whether anything matched.
- `iterator` **repeats** its children once per match, each scoped to that match (an HTML node, a JSON item, or a regex match string for `headers`/`url`). Each match is one row; children's titles become `title[]` lists.
- `click` / `select` **act** on each match of a live page in turn, then run their children against the **whole page** as it is after that action (not only inside the match). Each action is one row, like an iterator. httpx has no live page: it runs the children once against the page as fetched, and their titles are still `title[]` lists (of one element).
- `pagination` **discovers** how many pages to fetch (§5.7; stored, not run yet).

### 4.6 Message Aid

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `message_template_id` | Ref Message Template | — | Unique — at most one aid per template. |
| `selected_proxy_id` | Ref Proxy \| null | `null` | `null` = no proxy. |
| `render_mode` | enum | `none` | `none` · `playwright` · `stealth`. |
| `ttl` | int \| null | `null` | Seconds, > 0. |
| `retry_codes` | list[str] \| null | `null` | Failure codes retried: status codes as strings, or `"timeout"`. `null` = `DEFAULT_RETRY_CODES`. |
| `success_codes` | list[str] \| null | `null` | Status codes that count as a successful response, as strings. When set, exactly these succeed (e.g. `404` for a page meant to be missing, which is then harvested); any other status fails. `null` = any status below 400 (`domain/rules/response_status.py`). |
| `max_retry_attempts` | int \| null | `null` | ≥ 0. Retries after a request's first try; `0` never retries. `null` = `DEFAULT_MAX_RETRY_ATTEMPTS`. |
| `rate_limit_id` | Ref Rate Limit \| null | `null` | Domain-scoped rate limit. |

**Retries.** A request that fails with one of the retry codes (the HTTP status, or `timeout`) is sent again, up to `max_retry_attempts` times, waiting 1 s, 2 s, 4 s, … (at most 30 s) between tries (`domain/rules/request_retries.py`). It counts as failed only once its retries are used up; a later success counts as a success. Any other failure (a code not listed, a dropped connection) fails at once. A request that fails for good stops the whole execution, which ends `failed`.

### 4.7 Message Aid Proxy

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `url` | str(2048) | — | |
| `user` | str \| null | `null` | |
| `password` | str | — | Write-only: never returned by the API. |
| `headers` | JSON | `{}` | |
| `rate_limit_id` | Ref Rate Limit \| null | `null` | Proxy-scoped rate limit. |

### 4.8 Message Aid Rate Limit

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `name` | str \| null | `null` | |
| `rate_limit_string` | str | — | `limits` window syntax, e.g. `50/minute`. |
| `penalty_step_seconds` | int | — | ≥ 0. |
| `max_penalty_seconds` | int | `0` | ≥ 0. |
| `decay_after_successes` | int | — | > 0. |
| `decay_step_seconds` | int | `0` | ≥ 0. |

Holds configuration only; the live window and penalty state lives in Redis.

**Applying it.** A Message Aid's rule limits the exact host of each request its template sends (key `domain:<host>`); a proxy's rule limits every request through that proxy (key `proxy:<id>`). Every try waits for a slot in the key's moving window, after any penalty. A failure with one of the template's retry codes is a block: the penalty grows by `penalty_step_seconds`, up to `max_penalty_seconds` (`0` turns penalties off). Every `decay_after_successes` successes in a row take `decay_step_seconds` off it, never below zero (`domain/rules/rate_limits.py`). Keys are shared by every run and worker; a penalty untouched for a day resets. If the limiter's store (Redis) is unreachable, the run fails rather than sending unpaced requests.

**LLM keys.** The same limiter holds a hosted model's quota, which the provider grants per project and model, not per worker, so every Gemini call of every Instruction Generation, from the browser agent or the synthesizer, shares one budget per model (`domain/rules/llm_rate_limits.py`). These keys come from settings, not from a stored Message Aid Rate Limit:

| Key | Rule | How a call uses it |
|---|---|---|
| `llm:<model>:day` | `GEMINI_REQUESTS_PER_DAY`/day | Takes a slot first, never waiting for one. A spent budget fails the call at once. |
| `llm:<model>:tokens` | `GEMINI_TOKENS_PER_MINUTE`/minute | The call's tokens, counted after it, even past the budget. While the current minute's budget is spent, the next call waits for it to reset. |
| `llm:<model>:minute` | `GEMINI_REQUESTS_PER_MINUTE`/minute | Waited on last, with a penalty: each 429 adds 10 s, up to 60 s, and every 5 successes in a row take 10 s off. |

A 429 is retried up to `GEMINI_MAX_RETRY_ATTEMPTS` times, after Gemini's own retry delay when it gives one, else after the Message Aid retry backoff (§4.6). Then the call fails with `Gemini rate limit exhausted`. A spent day, ours or Google's, fails it with `Gemini daily request budget spent; try again tomorrow`. Either failure fails the Instruction Generation (§4.16): it never waits for another day.

### 4.9 Crawler Execution

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `crawler_id` | Ref Crawler | — | |
| `crawler_version_id` | Ref Crawler Version | — | `RESTRICT`. |
| `status` | enum | `pending` | `pending` · `running` · `succeeded` · `failed` · `cancelled`. |
| `parsing_status` | enum | `pending` | `pending` · `parsing` · `parsed` · `failed`. |
| `queue` | enum | `discovery` | The queue actually dispatched to: the Crawler's when the run is created, or `testing` for a test run of any version. |
| `started_at` / `finished_at` | datetime \| null | `null` | Duration = `finished_at − started_at`. |
| `resume_count` | int | `0` | ≥ 0. Times this execution was resumed from its checkpoint after an interruption. |
| `metrics` | embedded | all `0` | Run metrics, below. |

`metrics` fields, all int ≥ 0:

| Field | Meaning |
|---|---|
| `request_count` | Requests sent, each counted once however many times it was retried. |
| `error_count` | Requests that still failed after their retries. Error rate = `error_count / request_count`. |
| `retry_count` | Retries sent on top of `request_count`. |
| `records_skipped` | Venues not fetched in detail because listing signals showed no change (§5.5). Written as `sighting` rows. |

Insert/update/unchanged counts belong to the import, so they live on the Crawler Execution Dataset (§4.12).

When a run finishes (`succeeded` or `failed`), it is also recorded for monitoring through the `AbstractExecutionMetrics` port, after its transaction commits: its status, duration, and these counters, per Crawler and queue ([ARCHITECTURE §Observability](ARCHITECTURE.md#observability)).

**Run history.** A Crawler's history is its runs on every queue it can run on (`CRAWLER_QUEUES`), so test runs of its versions stay out unless the `testing` queue is asked for; runs on a queue its schedule no longer uses stay in. Its summary (`domain/rules/execution_history.py`) counts only **ended** runs (`succeeded`, `failed`, `cancelled`); `pending` and `running` ones are skipped:

| Term | Meaning |
|---|---|
| **Successful run** | `status` is `succeeded` **and** `parsing_status` is `parsed`: it ran to the end and its rows passed validation (§5.4). A run that succeeded with invalid rows is not successful. |
| **Run outcome** | What a run came to, returned on every Crawler Execution as `outcome` (`resolve_run_outcome`): `success` (a successful run), `verification_failed` (`succeeded`, but its rows did not pass validation), `failed` (`failed` or `cancelled`), or `in_progress` (`pending` or `running`). |
| **Consecutive successful runs** (streak) | Successful runs since the newest ended run that was not successful, over the whole history. Reads past the newest `SUMMARY_WINDOW` (30) ended runs only while the streak lasts, `STREAK_SCAN_SIZE` (200) at a time. |
| **Success rate** | Share of the last 30 ended runs that were successful, 0 to 1; none before any run ended. |
| **Average completion time** | Mean duration (`finished_at − started_at`) of the last 30 successful runs; none without any. |
| **Last verification failure** / **Last failure** | When the newest `verification_failed` run, and the newest `failed` or `cancelled` run, finished (one newest-first read each). |
| **Average completeness** | Mean completeness rate (§5.4) of the last 30 successful runs that have one; none without any. |
| **History window** | The runs created in the last `days` days (1–90, default 30), newest first, up to `HISTORY_WINDOW_MAX_RUNS` (1,000), with how many came to each Run outcome over the whole window, past the cap too (`count_outcomes`). |
| **Records extracted** | The run's dataset `row_count` (§4.12): rows written to its CSV after validation dropped any. |

### 4.10 Crawler Execution Context

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `crawler_execution_id` | Ref Crawler Execution | — | |
| `key` | str | — | `name` = one value; `name[]` = a list. |
| `value` | primitive | — | String, number, boolean, or `null`. Objects and lists harvested into a scalar key are stored as JSON text. |
| `position` | int \| null | `null` | `null` for a `name` key; the element's index for a `name[]` key. Unique per (execution, key, position): one entry per `name`, one per element of a `name[]`. |
| `active_value` | JSON \| null | `null` | Iterator element in flight during the last dispatch. The resume point after an interruption. |

Where values come from, in order:
1. **Inherited:** a new execution starts with the Context of the Crawler's latest execution, **without the keys selectors harvest**. A key is harvested when a selector of the version being run has its title (`name` and `name[]` alike), unless the title is one of the Crawler's `fields` (`domain/rules/context_inheritance.py`). So every run harvests those afresh, and a selector that misses can't silently reuse the previous run's values; credentials, API keys, and other keys no selector writes still carry over. Test runs (queue `testing`) are skipped: they inherit like any run, dropping the keys their own version harvests, but no later run inherits from them. The latest execution keeps its full Context; only what the next run starts from changes. Edge: a key written by a selector a newer version removed is no longer harvested for that version, so it is inherited like a user value until it is deleted from the Context.
2. **Seeded:** `POST .../executions` with `{"context": {...}}` replaces inherited keys, e.g. a `parish[]` list to fan out over, or an API key a header uses. Seeding is applied after the harvested keys are dropped, so it can set a harvested key for that one run.
3. **Harvested:** a selector whose `title` is not one of the Crawler's fields writes its key. The first harvest of a key in a run replaces the value the run started with (which, for a harvested key, can only be a seeded one); later harvests in the same run extend `[]` lists with the values not already in them; a miss never erases a value. A harvested `[]` list holds each value once, in order of first harvest: a repeat, within one response (e.g. sibling iterators, whose rows cross-join) or across responses, is skipped (`domain/rules/selector_tree.py::append_unique`). Values compare as stored, types included (`1`, `"1"`, and `true` stay apart; objects and lists by their JSON text). Runs stored before this rule keep their repeats until the key is next harvested.

The Crawler's current Context (its latest execution's) is read and edited with `GET /api/crawlers/{id}/context` and `PUT`/`DELETE .../context/{key}`; the next execution inherits the edits. `GET` also returns `harvested_keys`, the keys the published version's selectors write (none while nothing is published); `PUT` on one of them is refused (409), since the next run would drop the edit; seed it when starting a run instead. `DELETE` works on any key. Seeded and edited keys can't start with `_`, take primitives, and `[]` keys take lists of primitives. Execution responses list only `context_keys`; the context endpoint returns values.

### 4.11 Execution records (one per Crawler Execution unless noted)

| Entity | Key attributes | Notes |
|---|---|---|
| **Crawler Execution Failure** | `message_template_id?`, `error_message`, `response_status_code/text/headers?`, `validation_errors[]` | Debug snapshot; overwritten on each new failure. |
| **Crawler Execution Response** *(many)* | `message_template_id?`, `url`, `status_code?`, `status_text?`, `headers?`, `body_snippet?` | One per physical dispatch. No `updated_at` — append-only. |

### 4.12 Crawler Execution Dataset

The CSV one Crawler Execution produced (at most one per execution), plus the state of its import. Format in [§5.3](#53-execution-dataset-csv).

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `crawler_execution_id` | Ref Crawler Execution | — | Unique — at most one dataset per execution. |
| `fields` | list[str] | — | The CSV columns, in order: the Crawler's `fields` at run time. |
| `file_path` | str \| null | `null` | The CSV file, its only copy (the CSV is never stored in MongoDB), written through `AbstractDatasetExportStorage` when the run finishes: first to `<dataset_export_dir>/raw/<crawler_id>_<crawler_execution_id>_<started>.csv` (`<started>`: when the run started, UTC, e.g. `20261001T114123Z`), then moved to `<dataset_export_dir>/validated/…` (same name) when the run is `parsed`. `null` when the export failed, which fails the run (§5.3); a failed move leaves it in `raw/`. Documents written before this change may still hold an unused `csv_content` field. |
| `row_count` | int | `0` | ≥ 0. Rows, header excluded. |
| `import_status` | enum | `pending` | `pending` · `importing` · `imported` · `failed`. |
| `imported_at` | datetime \| null | `null` | Set when `import_status` becomes `imported`. |
| `import_error` | text \| null | `null` | Why the last import attempt failed. |
| `import_metrics` | embedded | all `0` | Import counters, below. All int ≥ 0. |
| `validation` | embedded \| null | `null` | What validating the rows found (`DatasetValidation`, §5.4): `rows_checked`, `rows_dropped_missing_required`, `rows_dropped_duplicate`, `type_mismatches` and `pattern_mismatches` (per field), `empty_columns`, `is_valid`, `completeness_rate` (absent from reports saved before it existed, returned as `null`). Returned on every Crawler Execution as `validation`. |

`import_metrics` fields:

| Field | Meaning |
|---|---|
| `records_inserted` | Rows whose natural key was new. |
| `records_updated` | Rows for known records whose content hash changed. |
| `records_unchanged` | Rows for known records with the same content hash, and `sighting` rows (only `last_seen_at` moved). |
| `rows_rejected` | Rows that could not be imported: missing natural key, unknown `venue_item_id`, bad type, or older than the stored record (DM-18). |

### 4.13 Dataset records

The final place where crawled data lives. Written **only by the dataset import**, never by a crawl. Records are **upserted** by natural key, never duplicated, and never deleted by deleting a Crawler or Execution. Every field the source doesn't provide is stored as `null` (or `[]`/`{}` for collections) — a missing field never fails the run.

Every dataset record carries these tracking fields:

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `source` | Ref Source | — | The writing Crawler's Source; half of the natural key. |
| `crawler_id` | Ref Crawler \| null | — | Crawler of the last imported file. `SET NULL`. |
| `last_execution_id` | Ref Crawler Execution \| null | — | Execution of the last imported file. `SET NULL`. |
| `content_hash` | str | — | Hash of the normalized content fields (§5.5). |
| `created_at` | datetime | — | When the import first inserted it. |
| `last_seen_at` | datetime | — | `started_at` of the newest execution whose file contained it, changed or not. |
| `updated_at` | datetime | — | **Last time its content changed.** Moves only when `content_hash` changes. |

#### Dataset Venue (`dataset_venues`)

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `item_id` | str | — | The website's own ID for the venue (Google place ID, TheFork/OpenTable restaurant ID). Unique with `source`. |
| `source_url` | str(2048) | — | Canonical detail page. |
| `name` | str | — | Required. |
| `address` | str \| null | `null` | |
| `location` | `{latitude, longitude}` \| null | `null` | Used to plan and re-plan discovery grids. |
| `categories` | list[str] | `[]` | Venue categories/tags. |
| `phone`, `website`, `reservation_url`, `menu_url` | str \| null | `null` | |
| `rating` | float \| null | `null` | 0–5. |
| `review_count` | int \| null | `null` | ≥ 0. |
| `price_range` | str \| null | `null` | As shown by the source, e.g. `€€` or `10–20 €`. |
| `opening_hours` | JSON \| null | `null` | Weekday → list of `{open, close}` ranges. |
| `popular_times` | JSON \| null | `null` | Weekday → hour → busyness %. |
| `live_occupancy` | int \| null | `null` | Busyness % at crawl time. **Volatile** — excluded from `content_hash`. |
| `attributes` | JSON | `{}` | Group → list[str]. Groups: `accessibility`, `amenities`, `service_options`, `highlights`, `payment_options`, `dining_options`, plus any extra group the source shows. |
| `about` | JSON \| null | `null` | Free-form "About" details. |
| `last_crawled_at` | datetime \| null | `null` | Last full detail-page crawl (not just a listing sighting). Drives re-crawl scheduling. |

#### Dataset Review (`dataset_reviews`)

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `venue_id` | Ref Dataset Venue | — | The reviewed venue. `CASCADE`. |
| `item_id` | str | — | The website's review ID. Unique with `source`. Required: for a website without review IDs, the crawl must harvest another stable value (e.g. the review's permalink). |
| `reviewer_name` | str \| null | `null` | |
| `rating` | int \| null | `null` | 1–5. |
| `published_at` | datetime \| null | `null` | Exact date, or one computed from relative text. |
| `published_at_text` | str \| null | `null` | Raw text, e.g. `hace 2 meses`. |
| `is_published_at_approximate` | bool | `false` | `true` when `published_at` was computed from relative text. |
| `text` | text \| null | `null` | |

#### Dataset Menu (`dataset_menus`)

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `item_id` | str | — | Always its venue's `item_id`: the menus Crawler harvests the venue's ID as both `item_id` and `venue_item_id`. Unique with `source` — at most one menu per venue. |
| `venue_id` | Ref Dataset Venue | — | Unique. `CASCADE`. |
| `source_url` | str(2048) \| null | `null` | Where the menu was read (may be an external site). |
| `sections` | list[embedded] | `[]` | Each: `name`, `description?`, `items[]`. |

Each menu item: `name`, `description?`, `price?` (float), `currency?`, `price_text?` (raw).

---

### 4.14 Source

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `name` | str(255) | — | Unique, e.g. `TheFork`. |
| `url` | str(2048) \| null | `null` | The website, for reference. |

A Source has no Dataset list: the Datasets it feeds are those of the Crawlers linked to it (§3.1).

Managed through `/api/sources`: any user creates and lists them; only admins rename or delete them, and a Source still linked to a Crawler can't be deleted.

### 4.15 Dataset

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `name` | str(255) | — | Unique, e.g. `venues`. |
| `fields` | list[Dataset field] | — | The fields a Crawler picks from, in CSV order. No duplicate names; must include `item_id`, required and unique. |

Each Dataset field (`DatasetField`, embedded):

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `name` | str(255) | — | Not blank. The CSV column, and the `title` of the selector that harvests it. |
| `type` | enum | `string` | One of `SCHEMA_FIELD_TYPES`: `string` · `boolean` · `integer` · `float`. |
| `is_required` | bool | `false` | Every Crawler on the Dataset must list it in its `fields`; a row without a value is dropped (§5.4). |
| `is_unique` | bool | `false` | No two records of one Source share a value (DM-19). |
| `pattern` | str \| null | `null` | A regex the value should match; must compile. |

`type` and `pattern` are checked for validity when saved, and every value is checked against them when a run ends (§5.4).

Managed through `/api/datasets`: any user creates and lists them; only admins edit or delete them. A Dataset still linked to a Crawler can't be deleted, and an edit that would make a linked Crawler's `fields` invalid is refused (409).

### 4.16 Instruction Generation

| Attribute | Type | Default | Constraints / notes |
|---|---|---|---|
| `crawler_id` | Ref Crawler | — | |
| `crawler_version_id` | Ref Crawler Version \| null | — | The version it targets; must not be archived when it is created (409). `null` once deleted. |
| `user_id` | Ref User | — | Who asked; the worker acts as this user. |
| `prompt` | str | — | 1–4000 characters after trimming. |
| `status` | enum | `pending` | `pending` · `running` · `succeeded` · `failed` (`INSTRUCTION_GENERATION_STATUSES`). |
| `error` | str \| null | `null` | Why it failed. |
| `result_version_id` | Ref Crawler Version \| null | `null` | The draft the agent's file landed on. Set once imported, even if the test run then can't start. |
| `test_execution_id` | Ref Crawler Execution \| null | `null` | The test run of that draft (`testing` queue). |
| `instructions_yaml` | text \| null | `null` | The synthesized file, cut at 256 KiB: the one imported, or the last attempt when none was valid. |
| `recording` | embedded \| null | `null` | The browser agent's recording (below), cut to `GENERATION_RECORDING_MAX_BYTES`. Saved before synthesis, and kept when the generation fails. Returned only by `GET /api/instruction-generations/{id}?include=recording`, so polling stays small. |
| `filtered_requests` | list[embedded] | `[]` | The requests instructions were written from (below): each one's `url` (cut at 2,048 characters), `method`, `status`, and `reasons`, at most 100. Saved before synthesis. |
| `required_context_keys` | list[str] | `[]` | Placeholders the file uses for redacted credential headers (e.g. `authorization`); only the Crawler's Context can fill them. |
| `warnings` | list[str] | `[]` | What to do before the result can run, e.g. `Set authorization in the crawler's Context before running.` for a required key the Context lacks. |
| `started_at` / `finished_at` | datetime \| null | `null` | |

**Running it** (`services/instruction_generation_service.py::process_generation`, on the `ai-agents` queue):
1. `pending` → `running`; a generation that is not `pending` (a redelivered task) is skipped.
2. The browser agent (`AbstractBrowserAgentRecorder`) gets the prompt, the Crawler's `fields`, and the targeted version's current instructions file as a hint, browses to get exactly those fields, and returns its recording. The recording is saved on `recording`, capped. No transaction is open meanwhile: the agent may take minutes.
3. The whole, uncapped recording is **filtered** down to the requests that led to the data (below), and their summary is saved on `filtered_requests`. A recording whose agent did not get the data (`final_result.is_success` false), or whose responses carry none of it (an empty chain), fails here, before any Gemini call.
4. The **synthesizer** (`AbstractInstructionSynthesizer`) gets a `SynthesisRequest`: the prompt, the Crawler's `fields`, the current file as a starting point, and the filtered requests. The recording is a sample of the first pages, so the file writes a listing's recorded pages as one template that repeats over its next-page value (§5.8), not one template per page. It returns a whole file, plus the `required_context_keys` it used for redacted credentials. Each file is **checked**: read like an upload (`parse_instructions_text`: YAML only, no aliases, the §5.9 schema), the import's link checks (`find_instruction_problems`), and every template `{{placeholder}}` must be a selector `title` in the file, a key of the Crawler's current Context (`name` or `name[]`), or a required Context key. A file with problems is sent back with its problems, up to `SYNTHESIS_MAX_ATTEMPTS` files (default 3). The last invalid file is saved on `instructions_yaml`, and the generation fails with `Instructions still invalid after N attempts: <every problem>`.
5. The valid file is saved on `instructions_yaml`, with `required_context_keys`, and `warnings` for each of them the Context lacks. It is imported anyway: a test run will then fail on the missing placeholder, which shows what to set. The import (`import_instructions`) replaces a draft in place, or forks a published version into a new draft, and every §5.9 check applies. `result_version_id` is saved.
6. A test run of that draft starts (`create_test_execution`), its id is saved, and the generation `succeeded`. How the test run goes is the run's own `status`, not the generation's.

Any failure along the way ends it `failed` with the reason in `error`, keeping what the earlier steps saved; the import is one transaction, so a draft is never half-replaced. A browser agent that fails (times out, crashes, or stops on its model's or browser's error) still has what it recorded until then saved. One that only ends without the data (out of steps, or it says it failed) has its recording saved too, then fails at step 3. A missing `GEMINI_API_KEY` fails it with `GEMINI_API_KEY must be set.` before any browser starts, and a spent Gemini quota with `Gemini rate limit exhausted` or `Gemini daily request budget spent; try again tomorrow` (§4.8), keeping the recording so far.

**The recording** (`AgentRecording`, value objects in `domain/ports/browser_agent_recorder.py`):

| Part | Fields | Notes |
|---|---|---|
| `steps[]` | `index`, `action` (`navigate`, `click`, `input`, `scroll`, `extract`, `done`, …), `params`, `target_xpath`, `url`, `is_success`, `error` | One per agent action, in order. `url` is the page's URL after the step; `target_xpath` the element acted on, when the agent exposes it. |
| `requests[]` | `step_index`, `url`, `method`, `resource_type`, `request_headers`, `post_body`, `status`, `response_headers`, `response_body`, `is_response_body_truncated`, `failure` | Every request the agent's browser made, oldest first, tied to the step during which it was made; each redirect hop is its own. `status` is `null` on failure, and `failure` holds the network error or `aborted`. Bodies are kept for `document`, `xhr`, and `fetch` only, cut at `AGENT_RESPONSE_BODY_MAX_BYTES`. `Authorization`, `Proxy-Authorization`, `X-Api-Key`, and `X-Goog-Api-Key` keep their name, with the value `<redacted>`. `Cookie` and `Set-Cookie` keep each cookie's name, never its value (`sid=<redacted>; lang=<redacted>`; a `Set-Cookie` line's attributes are dropped), so the filter can tell who set a cookie. |
| `final_result` | `data`, `is_success` | What the agent extracted: its answer parsed as JSON (rows keyed by the Crawler's fields), or its text when not JSON. |
| `is_truncated` | — | Whether the cap below dropped anything. |

**The cap** (`domain/rules/generation_recording.py::cap_recording`): a stored recording takes at most `GENERATION_RECORDING_MAX_BYTES` (default 1 MiB, measured as UTF-8 JSON, well under MongoDB's 16 MiB document limit). Over it, response bodies are dropped first, largest first; then whole non-document requests, oldest first. Steps, the final result, and document requests are always kept, so a recording of those alone may stay over the cap.

**The filter** (`domain/rules/recording_filter.py::filter_recording`, pure) keeps the requests that led to the data, in time order, each with why (`KeptRequest.reasons`) and the values behind it (`values`):

1. **Noise is dropped**:
   - failures and aborts, unfinished requests, statuses ≥ 400, and 3xx redirects with no body;
   - `OPTIONS` preflights, and resource types `image`, `font`, `stylesheet`, `script`, `media`, `websocket`, `manifest`, `ping`;
   - hosts of `SYNTHESIS_IGNORED_HOSTS` (analytics and ads) and their subdomains;
   - exact duplicates (same method, URL, body), keeping the last.
2. **Failed attempts are dropped**: the requests of a step with `is_success` false, and of a step the next one repeats (same action on the same `target_xpath`), so only the last try of a retried action stays.
3. **Lineage** runs backwards from `final_result`:
   - **Seed:** its scalar values (strings and numbers as text, at least 3 characters) are searched in the remaining `document`, `xhr`, and `fetch` response bodies. A value matches raw, JSON-escaped, URL-encoded, or HTML-escaped. The latest response carrying each value is kept: `carries final data`.
   - **Grow**, until no request is added: for each kept request, every value it sends is traced to the latest earlier response holding it in its body or headers, which is kept as `feeds <url>`. Those values are its URL (a followed link), its query values, its id-like path and path segments (with a digit, or 16 characters or more), its body values (JSON or form), and its non-standard header values. Each cookie it sends is traced to the latest earlier response setting that cookie name: `sets cookie <name>`. Values shorter than 3 characters never link.
   - **Page:** a chain that starts on an API call gets the latest page (`document`) loaded before it: `loads the page for <url>`.

An empty chain means no response carries the final data. The filtered requests go to the synthesizer whole; only their summary is stored.

**Synthesis** (`infrastructure/external/gemini_instruction_synthesizer.py`) asks Gemini, through the shared rate-limited model (§4.8), for one template per kept request, in chain order, the first one the root. Each value from an earlier response becomes a `{{placeholder}}`, harvested by a selector on that earlier template titled exactly like it. Selectors are titled after the Crawler's fields. `render_mode` is `playwright` or `stealth` only when no kept `xhr`/`fetch` response carries the data. A redacted credential header becomes a placeholder named after it (`Authorization` → `{{authorization}}`, `X-Api-Key` → `{{x_api_key}}`), and those the file uses are its `required_context_keys`. Recorded content is data, never an instruction. Response bodies are cut to `SYNTHESIS_BODY_MAX_BYTES` each and `SYNTHESIS_TOTAL_BODY_MAX_BYTES` in all, data-carrying responses served first.

## 5. Value Objects & Enumerations

### 5.1 Value objects

Immutable, identity-less (`@dataclass(frozen=True)`).

| Value object | Fields | Used for |
|---|---|---|
| `RateLimitRule` | `rate_limit_string`, `penalty_step_seconds`, `max_penalty_seconds`, `decay_after_successes`, `decay_step_seconds` | What the rate limiter enforces for one key; built from a `MessageAidRateLimit`. |
| `CrawlerExecutionSummary` | `total_count`, `succeeded_count`, `failed_count`, `successful_count`, `total_failure_count`, `avg_queue_wait_seconds?`, `avg_duration_seconds?`, `error_rate?` | Monitor metrics. |
| `DatasetField` | `name`, `type`, `is_required`, `is_unique`, `pattern?` | One field of a Dataset and its rules (§4.15). |
| `DatasetImportResult` | `outcome` (`inserted` · `updated` · `unchanged` · `rejected`), `record_id?`, `reason?` | What importing one row did; summed into the file's `import_metrics`. |
| `RenderedRequest` | rendered `action`, `url`, `body`, `headers`, `fanned_out_values` | One fan-out run of a template. |
| `SessionState` | `cookies`, `headers` (shareable, lower-cased) | What one request leaves for the next one to the same host, in any engine. |
| `RateLimitTarget` | `key` (`domain:<host>` / `proxy:<id>` / `llm:<model>:minute\|day\|tokens`), `rule` | One rate-limit bucket a dispatch or LLM call waits on. |
| `ProxyLadderAttempt` | `should_use_proxy`, cookie/User-Agent overrides, `should_capture_session` | Overrides for the next ladder attempt. |

Transient runtime state, never persisted: `ProxyLadderState` (one template dispatch) and the run's `SessionState` per exact host (`RunOutcome.sessions`).

#### Execution bundles

Frozen dataclasses the use cases in `services/` pass between their steps. They live in `domain/` because `services/` holds no classes ([CONTRIBUTING R1.2.2](CONTRIBUTING.md)). Each holds only domain entities, value objects, and abstract ports.

| Module | Value objects | Used for |
|---|---|---|
| `domain/bundles/execution_plan.py` | `ScheduledCrawler`, `ExecutionPlan`, `TemplateRun`, `RunOutcome` | Which published version a Beat tick runs; a run's dependency-ordered templates with their selectors, aids, proxies, and seeded Context; one fan-out run of a template; where a run stands (Context, sessions per host, counters, failure). |
| `domain/bundles/request_executors.py` | `RequestExecutors` (ports: httpx, Playwright, Patchright) | The engine per `render_mode`. |
| `domain/bundles/repository_factories.py` | `RepositorySetFactories` | How a task opens short-lived read or write repositories, so no transaction stays open during a run. |

### 5.2 Enumerations & constants

| Name | Values | Source |
|---|---|---|
| `BUILT_IN_DATASETS` | The `venues`, `reviews`, and `menus` definitions (§5.3), created at startup when missing | `domain/model/constants.py` |
| `ITEM_ID_COLUMN` | `item_id` — a required, unique field of every Dataset | `domain/model/constants.py` |
| `SCHEMA_FIELD_TYPES` | `string` (default), `boolean`, `integer`, `float` — a Dataset field's `type` | `domain/model/constants.py` |
| `SELECTOR_SOURCES` | `content` (default), `headers`, `url`, `context` | `domain/model/constants.py` |
| `CONTEXT_SELECTOR_TYPES` | `value`, `boolean` — the selector types that may read `context` | `domain/model/constants.py` |
| `IMPORT_QUEUE` | `dataset-import` — where import tasks run; not a Crawler Version queue | `domain/model/constants.py` |
| `AI_AGENTS_QUEUE` | `ai-agents` — where Instruction Generations run; not an execution queue | `domain/model/constants.py` |
| `INSTRUCTION_GENERATION_STATUSES` | `pending` (default), `running`, `succeeded`, `failed` — an Instruction Generation's `status` | `domain/model/constants.py` |
| `DATASET_SAMPLE_SIZE` | `800` — rows in a run's Sample CSV (§5.3) | `domain/model/constants.py` |
| `EXECUTION_STATUSES` | `pending` (default), `running`, `succeeded`, `failed`, `cancelled` — a Crawler Execution's `status` | `domain/model/constants.py` |
| `PARSING_STATUSES` | `pending` (default), `parsing`, `parsed`, `failed` — a Crawler Execution's `parsing_status` | `domain/model/constants.py` |
| `EXECUTION_QUEUES` | `discovery` (default), `priority`, `real-time`, `testing` | `domain/model/constants.py` |
| `CRAWLER_QUEUES` | `EXECUTION_QUEUES` without `testing` (`TESTING_QUEUE`), which only test runs use | `domain/model/constants.py` |
| `RENDER_MODES` | `none` (default), `playwright`, `stealth` | `domain/model/constants.py` |
| `DEFAULT_RETRY_CODES` | `429`, `500`, `502`, `503`, `504` | `domain/model/constants.py` |
| `DEFAULT_TTL_SECONDS` | `20` | `domain/model/constants.py` |
| `DEFAULT_MAX_RETRY_ATTEMPTS` | `3` | `domain/model/constants.py` |
| Code sentinel | `"timeout"`: valid in ban/retry code lists, in neither default | `domain/rules/ban_resolution.py` |
| Iterator key suffix | `[]` | `domain/rules/selector_tree.py` |
| Reserved key prefix | `_`: system-written Context keys, e.g. `_pagination`; never treated as user input | `domain/rules/execution_context.py` |
| Placeholder syntax | `{{ name }}` (whitespace allowed) | `domain/rules/placeholders.py` |

### 5.3 Execution dataset (CSV)

A crawl writes its harvests to one CSV per execution. It never touches `dataset_*`.

- **Columns:** the Crawler's `fields`, in order (§5.4). Each must be a field of the Crawler's Dataset.
- **Rows:** one per match of the innermost `iterator` holding the field selectors (one venue per result card, one review per review block, one menu item per item). A harvested row with none of the Crawler's fields (a page with nothing to harvest, e.g. a show with no scheduled dates) is not a row.
- **Format:** UTF-8, RFC 4180, header row. An empty cell is `null`. A value harvested as an object or a list is JSON-encoded; text is written as is.
- **Storage:** a file, the CSV's only copy, written through `AbstractDatasetExportStorage` when the run finishes and recorded in `file_path`: to `raw/` first, moved to `validated/` only once the run is `parsed`. MongoDB keeps the path, row count, and validation report, never the CSV itself, so a run's CSV has no size limit. `GET /api/crawler-executions/{id}/dataset.csv` serves the file. A failed export fails the run (`Dataset CSV export failed: …`, added to any earlier failure), since nothing else holds the rows; its Context, counters, and validation report are still saved, and it has no CSV to download (404). A failed move is logged and changes nothing: the CSV stays in `raw/`.
- **Resume:** a resumed execution keeps adding rows to the same CSV. Repeated rows are harmless: the import upserts.
- **Sample CSV:** for a data quality check, `GET /api/crawler-executions/{id}/dataset-sample.csv` serves, from the same file, the header and at most `DATASET_SAMPLE_SIZE` (800) rows, which is what the Runs page downloads. The rows are evenly spaced through the whole CSV, row `⌊i × rows ÷ 800⌋` for each `i` (e.g. about every 62nd row of 50,000), not taken from the top: a crawl's rows follow how the site was walked, so the top would miss a listing's later pages or a fan-out's later values, where gaps and layout changes tend to show up. They keep their CSV order, and the same CSV always gives the same sample (`domain/rules/dataset_sample.py`). A CSV of 800 rows or fewer comes back whole. It downloads named like the run's CSV file, with the run's start time, plus `-sample`: `<crawler_id>_<execution_id>_<started>-sample.csv` (e.g. `…_20261007T065600Z-sample.csv`). 800 rows estimate how often a field is empty or malformed within about ±3.5% (95% confidence), whatever the run's size.

The built-in Datasets (`BUILT_IN_DATASETS`, created at startup when missing; editable like any Dataset):

In the Fields column, a type in brackets is any type but `string`, and *(URL)* is the pattern `^https?://`. `item_id` is required and unique in all three.

| Dataset | Fields | Required | One row per |
|---|---|---|---|
| `venues` | `row_type`, `item_id`, `source_url` *(URL)*, `name`, `address`, `location`, `categories`, `phone`, `website` *(URL)*, `reservation_url` *(URL)*, `menu_url` *(URL)*, `rating` [float], `review_count` [integer], `price_range`, `opening_hours`, `popular_times`, `live_occupancy` [integer], `attributes`, `about` | `item_id`, `name` | Venue seen |
| `reviews` | `item_id`, `venue_item_id`, `reviewer_name`, `rating` [integer], `published_at`, `published_at_text`, `is_published_at_approximate` [boolean], `text` | `item_id`, `venue_item_id` | Review |
| `menus` | `item_id`, `venue_item_id`, `source_url` *(URL)*, `section_name`, `section_description`, `item_name`, `item_description`, `item_price` [float], `item_currency`, `item_price_text` | `item_id`, `venue_item_id`, `item_name` | Menu item |

- **`row_type`** (venues only, optional): `full` = detail page crawled; `sighting` = seen in a listing but skipped (§5.5). Missing = `full`.
- **Menus:** the import groups a venue's rows into `sections[]` → `items[]`, keeping CSV order. A menu in the CSV replaces the stored one whole.
- **Item id:** every dataset's CSV has a required, unique `item_id` column, the item's own ID on its website, filled by a selector titled `item_id` (a `context` selector when the ID is a placeholder, e.g. the fanned-out `place_id`). Together with the Crawler's Source it is the record's de-duplication key. A Dataset never fills `item_id` from another field: mapping content to fields is the Crawler's job. A menus Crawler harvests the venue's ID twice, with one selector titled `item_id` and one titled `venue_item_id`, so all three built-ins are keyed the same way.
- **Linking:** `reviews` and `menus` rows carry `venue_item_id`. The import resolves it to `venue_id` using the Crawler's Source, so the venues must be imported first (run the venues Crawler before the reviews/menus ones).

### 5.3.1 Import

A separate Celery task, `import_execution_dataset`, on `IMPORT_QUEUE`:

1. Runs when a Crawler Execution ends `succeeded` or `failed` (a failed run's rows are still valid). Never for `cancelled`.
2. Reads the run's CSV file (`file_path`, through `AbstractDatasetExportStorage`) and targets the collection of the Crawler's Dataset (`dataset_venues`, `dataset_reviews`, or `dataset_menus`). A custom Dataset's CSV is produced and stored like any other, but has no record collection yet (open point).
3. Per row: validate, compute `content_hash`, then upsert (§5.5). One write-repositories transaction per batch of rows.
4. Sets `import_status`, `import_metrics`, and `imported_at`. On error: `failed` plus `import_error`. A failed import can be re-run safely.

### 5.4 Crawler fields

`Crawler.fields` lists which of the Dataset's fields each execution downloads, e.g. `["item_id", "name", "address", "rating"]`:

- They are the CSV columns, in order. A selector whose `title` matches a field feeds the CSV instead of the Context.
- Every field must be a field of the Crawler's Dataset, listed once, and every required field must be present (§4.15).
- A field's type, pattern, and whether it is required or unique belong to the Dataset, not the Crawler. A value that comes from a placeholder is read by a `context` selector (§4.5).

A field is `null` when not harvested.

#### Validation

When a run ends, its rows are validated against the Dataset's fields before the CSV is written (`domain/rules/dataset_validation.py`); `parsing_status` becomes `parsed` only after validation, and only when the run succeeded and the report `is_valid`:

| Check | Scope | Effect on the row | Fails parsing |
|---|---|---|---|
| A required field is empty (`null`, `""`, `[]`, `{}`) | row | Dropped | Yes |
| A unique field repeats an earlier row's value | row | Dropped; the first row is kept | No |
| A value isn't of its field's `type` | row | Kept as harvested | Yes |
| A value doesn't match its field's `pattern` (`re.search`) | row | Kept as harvested | Yes |
| One of the Crawler's `fields` is empty in every row (also: no rows at all) | dataset | — | Yes |

Types read text too, since HTML values are text: `"9.8"` is a `float`, `"12"` an `integer`, `"true"`/`"false"` a `boolean`; a `string` field takes any value, objects and lists included. Empty values are never type or pattern mismatches. Uniqueness is checked within the run's rows, not against stored records. The report is stored as the Crawler Execution Dataset's `validation`.

The report also gives the run's **completeness rate**: the share of filled cells (not empty, as above) in the rows kept after the drops, over kept rows × the Crawler's `fields`, from 0 to 1; `null` when no row is kept. Dropped rows never count. It only describes the data: it never fails parsing, which stays decided by the checks above, so a run can be `verification_failed` with a high rate, or successful with a low one.

### 5.5 Change detection

Done by the import. What a record's `content_hash` covers, so a Sighting can tell "changed" from "unchanged":

| Dataset | Hashed | Not hashed |
|---|---|---|
| Venues | Every field in §4.13 except those on the right. Lists (`categories`, `attributes` groups) are sorted; strings trimmed. | Tracking fields, `source_url`, `live_occupancy`, `last_crawled_at` |
| Reviews | `reviewer_name`, `rating`, `text`, `published_at_text` | Tracking fields, `published_at` (drifts when computed from relative text) |
| Menus | `sections` (in source order) | Tracking fields, `source_url` |

During the crawl, a venue whose listing signals (`rating`, `review_count`) match the stored record is not fetched in detail. It is written as a `sighting` row and counted in `records_skipped`; its import only moves `last_seen_at`.

### 5.6 Domain exceptions

| Exception | Default status | Meaning |
|---|---|---|
| `AppException` | — | Base of every controlled error (`message`, `status_code`). |
| `ValidationException` | 400 | Client-caused: bad input, not found (404), conflict (409), forbidden (403), unauthenticated (401). |
| `ConfigurationException` | 500 | A required setting is missing or invalid (e.g. `MONGO_URL`); raised at startup. |
| `ExternalServiceException` | 502 | Downstream failure; carries the downstream response plus `is_banned` / `is_timeout`. |
| `MissingPlaceholderException` | 422 | A referenced placeholder is absent from the Context. |

### 5.7 Pagination discovery

**Not built yet** (ARCHITECTURE, Background Job Pipeline): a `pagination` selector and its `config` are validated and stored, but runs don't execute it, so nothing writes `_pagination`. To walk pages today, use a self-fed placeholder (§5.8). The design:

A `pagination` selector's `path` finds the page-metadata container; its `config` says where the numbers are inside it and how to cap the result:

```json
{
  "output_key": "_pagination",
  "range_key": "page",
  "primitive_mappings": {
    "total_items":  { "path": "total_count", "regex_clean": "\\d+" },
    "page_size":    { "path": "per_page" },
    "current_page": { "path": "page" }
  },
  "circuit_breaker": { "max_limit_cap": 50, "fallback_page_size": 20 }
}
```

Paths are JMESPath for JSON and XPath for HTML, relative to the container. Only `total_items` is required. The reduced result is stored in the Context under `_pagination`:

| Field | Meaning |
|---|---|
| `total_items`, `page_size`, `start_page` | Cleaned integers; `page_size` falls back to `fallback_page_size`, `start_page` to 1. |
| `computed_total_pages` | `ceil(total_items / page_size)`, or `null` without a total. |
| `max_limit_cap`, `effective_pages` | The cap, and `min(computed_total_pages, max_limit_cap)`. |
| `generated_range` | Pages `start_page`…`effective_pages`, exposed to placeholders as `range_key[]`. |

The `config` is validated by `PaginationConfigBase` (`schemas/message_selector.py`); the run-time reduction has no domain code yet.

### 5.8 Repeating templates

A template runs again when it feeds itself: one of its placeholders is the `title` of one of its **own** selectors (`domain/rules/template_repeats.py`). Values harvested by *other* templates never make a template repeat, so templates still run once each, in dependency order.

- **Single value** (selector outside any `iterator`/`click`/`select`), e.g. a cursor page token. Each fan-out combination repeats on its own: send, read the value from that response, send the same combination again with it. It stops when the response has no value, an empty one, or one this combination already sent (unchanged or alternating). The value starts as `""` in every combination, whatever the previous run left in the Context, and is cleared before each request, so a token is only ever sent with the search that produced it.
- **List** (selector under an `iterator`/`click`/`select`), e.g. links to follow. After the template's combinations, every element it appended to the list it fans out over runs too, once per distinct value, until no new elements appear. A list nothing filled yet starts as `[""]`, so the template still runs once; since a harvested list is never inherited (§4.10), that is how every run starts unless an earlier template or a seed filled it.

There is no cap on repeats: an API that keeps returning new tokens, or a site with endless distinct links, keeps the run going.

Google Places Text Search, for example, pages with: `nextPageToken` in `X-Goog-FieldMask`, a `value` selector with path `nextPageToken` titled `next_page_token`, and `"pageToken": "{{next_page_token}}"` in the body. Each search then follows its own pages (Google stops at 3) and every page's places feed the CSV.

### 5.9 Instructions file

A Crawler Version's instructions (its settings, templates, aids, and selectors) can be written as one YAML file instead of form by form: `GET /api/crawler-versions/{version_id}/instructions` downloads it, `PUT` on the same path uploads one. The file is YAML only: a body sent as JSON (`Content-Type: application/json`) is refused (415). The file has flat top-level blocks: no entry is nested in another; entries point at each other by **keys**, names local to the file that are never stored.

```yaml
format: night-crawler/instructions/v1
settings:
  root: search                       # the root template's key
  is_host_session_sharing_enabled: true
templates:
  search:
    action: GET
    url: https://example.com/search?q={{query}}
  detail:
    action: GET
    url: https://example.com/items/{{item_id}}
aids:
  search:                            # the aid of template `search`
    render_mode: playwright
    ttl: 30
selectors:
  results:
    template: search
    type: iterator
    path: //li[@class='result']
  item_id:
    template: search
    parent: results                  # nested under `results`
    type: value
    path: ./@data-id
    target: data-id
    title: item_id                   # fills `{{item_id}}` in `detail`
  name:
    template: detail
    type: value
    path: //h1
    title: name                      # a Crawler field: goes to the CSV
```

| Block | Entry | Fields | Links |
|---|---|---|---|
| `format` | — | `night-crawler/instructions/v1`; may be left out on upload | A new value marks a breaking change. |
| `settings` | one mapping | `root`, `is_proxy_ladder_enabled` (`false`), `is_host_session_sharing_enabled` (`true`) | `root` is a template key; unset, the first template is the root. |
| `templates` | one per Message Template | `action`, `url`, `body`, `headers` (§4.4) | At least one. |
| `aids` | at most one per template | the Message Aid's fields (§4.6), `selected_proxy_id` and `rate_limit_id` as ids | Keyed by its template's key. |
| `selectors` | one per Message Selector | `template`, `parent`, `type`, `path`, `source`, `target`, `title`, `config` (§4.5) | `template` is a template key; `parent` is the key of a selector on the same template. |

Rules:
- **Keys** match `[A-Za-z0-9_][A-Za-z0-9_.-]*` (at most 100 characters) and are unique per block, so a template and a selector may share one. A key is not a `title`: only `title` names what a selector harvests (§4.5), and a selector without one harvests nothing under its key.
- **What links templates** is never a key: a template uses what another harvested when one of its `{{placeholders}}` is the `title` of a selector on that other template, which also orders the run (ARCHITECTURE, Background Job Pipeline). Templates have no parent; only selectors nest (`parent`), as deep as needed, each level one more entry in the same flat block.
- **Fields left out take their defaults**, the same as the API's (DM-13), and an export leaves out every value at its default, so a file holds only what was set. Unknown fields are refused, so a typo never passes silently.
- **An import replaces the whole tree**: every template, aid, and selector of the version is deleted and the file's are created, in one transaction, with new ids. A draft takes the file in place; a published version is forked into a new draft that takes it, and the response is that draft; an archived version is refused (409). An import is never a merge: to change one selector, export, edit, and import.
- **Checks on import:** the file is at most 1 MiB (413). Every field is checked as its API route checks it (422, field by field). Then every link: a key that names nothing, a parent on another template, selectors nesting in a cycle, or a `context` selector that is not a `value`/`boolean` one (422, every problem listed at once, e.g. ``selectors.b: no selector `a` ``). Proxies and rate limits must exist (404). YAML aliases (`&anchor`/`*alias`) are refused (422), so a small file can't expand into a huge one.
- **Export names keys** `template_1`, `template_2`, … with the root first, since templates have no name. A selector's key is its `title` when no other selector in the version has it, else `<template key>.<title or type>` (`template_1.iterator`), numbered `_2`, `_3`, … on a clash. Selectors are written per template, each parent right before its children (`domain/rules/selector_nesting.py`), so the file reads in the order a response is read. Keys chosen by hand are not kept: a re-export renames them this way.
- **Not in the file:** the Crawler's `fields`, `schedule`, and `queue` (not versioned), proxies and rate limits themselves (shared resources, referenced by id; a proxy's password never leaves the API), and the Crawler Execution Context (§4.10: it belongs to runs, and may hold credentials).

---

## 6. Structural Invariants

These always hold, enforced by the database or by construction. What the system must deliver is in [BUSINESS_RULES.md](BUSINESS_RULES.md).

| ID | Invariant | Enforced by |
|---|---|---|
| DM-1 | Every entity's primary key is a surrogate UUIDv4; natural keys (`CrawlerExecutionContext`'s `crawler_execution_id` + `key`, `DatasetVenue`/`DatasetReview`/`DatasetMenu`'s `source` + `item_id`) are unique indexes. | Schema, [CONTRIBUTING R1.4.5](CONTRIBUTING.md) |
| DM-2 | Entities are never mutated in place by repositories: `save()` returns a new instance. Value objects are frozen. | [CONTRIBUTING R1.4.1–R1.4.2](CONTRIBUTING.md) |
| DM-3 | A Crawler has at most one `draft` and at most one `published` Crawler Version. | Partial unique indexes on `crawler_id` (one filtered on `status: draft`, one on `status: published`) |
| DM-4 | Versions have no number; they are ordered by `created_at`. A new draft clones the published version, else the newest archived one (only in older data, since nothing archives a version without publishing another), else starts empty with a root template. | `crawler_version_service`, `domain/rules/version_lifecycle.py` |
| DM-5 | Every enum attribute holds only its listed values (dataset, import status, row type, version status, queue, action, selector type, render mode, execution status, parsing status). | Collection `$jsonSchema` validators, `Literal` schemas |
| DM-6 | `max_retry_attempts` ≥ 0 when set; `ttl` > 0 when set; rate-limit steps and max penalty ≥ 0; `decay_after_successes` > 0; `resume_count`, dataset `row_count`, and every `metrics`/`import_metrics` counter ≥ 0; venue `rating` 0–5; review `rating` 1–5; `review_count` ≥ 0. | Collection `$jsonSchema` validators |
| DM-7 | A template has at most one Message Aid; a Crawler Execution has at most one Failure and one Crawler Execution Dataset; a Dataset Venue has at most one Dataset Menu. | Unique indexes on the reference field |
| DM-8 | Within a Crawler Execution, a `name` Context key has one entry and each element of a `name[]` key one entry. | Unique index on (execution, key, position) |
| DM-9 | Deleting a Crawler removes everything it owns: versions, templates, selectors, aids, executions, execution records, and Instruction Generations. It never removes dataset records. | Repository cascade in one write transaction |
| DM-10 | A Crawler Version referenced by any Crawler Execution cannot be deleted. | Existence check in the same write transaction |
| DM-11 | Deleting a shared resource (proxy, rate limit), a template, a version, a Crawler, or an Execution never deletes history or crawled data: references to it become `null` (a version's, on Instruction Generations). | `update_many` to `null` in the same write transaction |
| DM-12 | `message_template_root_id` always points at a template of the same version. Unlike other references it is not maintained on delete, so the service layer enforces it. | `crawler_version_service` |
| DM-13 | Settings defaults: a new Crawler gets queue `discovery`; a new version gets ladder off, host-session sharing on. Request settings live only on the Message Aid: a template without an aid (or an aid field left `null`) behaves as render mode `none`, TTL 20 s, no proxy, no rate limit, `DEFAULT_RETRY_CODES`, and 3 retry attempts. | Entity defaults |
| DM-14 | A dataset record exists once per natural key. Writes are upserts, so re-crawling never duplicates venues, reviews, or menus. | Unique indexes, dataset import |
| DM-15 | A dataset record's `updated_at` moves only when its `content_hash` changes; `last_seen_at` moves on every sighting. `created_at` ≤ `updated_at` ≤ `last_seen_at`. | Dataset import |
| DM-16 | Deleting a Dataset Venue deletes its reviews and menu. | Repository cascade in one write transaction |
| DM-17 | A crawl writes only its execution dataset (CSV); `dataset_*` collections are written only by the dataset import. A Crawler's `fields` are drawn from its Dataset's fields and include every required one; a Dataset's `item_id` is always required and unique. | `RequestExecutors` has no dataset repository port; `crawler_service` field validation |
| DM-18 | Importing is idempotent and order-safe: re-importing a file changes nothing, and a row from an execution that started before the record's `last_seen_at` is rejected, so an older file never overwrites newer data. | Dataset import |
| DM-19 | Within one Source, no two records of a Dataset share a value for a field marked `is_unique`; `item_id` is always unique, so with the Source it is the natural key. | Dataset definition validation (`item_id`); dataset import (not built yet) |
| DM-20 | An Instruction Generation only ever writes a version through the instructions import (§5.9), and only its browser agent browses; it runs no instructions itself: it never counts as a Crawler Execution, never passes on a Context, and never keeps a version from being deleted. Its result is checked by an ordinary test run. | `instruction_generation_service`; `SET NULL` on version delete |

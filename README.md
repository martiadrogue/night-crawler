# Night Crawler

A configurable crawler platform. You define crawlers in the UI or through
the API, Celery workers run them, and the results are saved as CSV files.
The stack is FastAPI, Reflex, MongoDB, Redis and RabbitMQ, all in Docker.

## Requirements

You need Docker and Docker Compose.

## Setup

Copy the example environment file and fill in your own values:

```bash
cp .env_example .env
```

The stack also runs Keycloak, the identity provider that owns every
account: the API has no login, passwords, or users of its own. Set its `KC_*` and
`KEYCLOAK_DB_PASSWORD` keys: each `*_SECRET` to its own
`openssl rand -hex 32`, and `KC_SEED_ADMIN_EMAIL` / `KC_SEED_ADMIN_PASSWORD`
to the first admin of the `night-crawler` realm. The realm, its roles
and its clients come from `keycloak/realm-night-crawler.json`, imported
only on Keycloak's first start.

The API accepts only access tokens Keycloak issues. Their defaults
match the Compose stack:

| Key | Default | What it sets |
|---|---|---|
| `OIDC_ISSUER` | `http://localhost:8180/realms/night-crawler` | The `iss` a token must carry: Keycloak's browser-facing URL, even for tokens fetched inside Docker. |
| `OIDC_JWKS_URL` | `http://keycloak:8080/realms/night-crawler/protocol/openid-connect/certs` | Where the API fetches Keycloak's signing keys. |
| `OIDC_AUDIENCE` | `night-crawler-api` | The client id a token's `aud` must include. |
| `KEYCLOAK_URL` | `http://keycloak:8080` | Where the API reaches Keycloak's Admin REST API to manage users. |
| `KEYCLOAK_REALM` | `night-crawler` | The realm whose accounts it manages. |
| `KEYCLOAK_ADMIN_CLIENT_ID` | `night-crawler-api` | The service account it manages them as. |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | `KC_NIGHT_CRAWLER_API_SECRET` | Secret. Compose sets it from that key; without it every `/api/users` route answers 502. |

Admins manage users at `/api/users`; users are disabled, never deleted
(see [BUSINESS_RULES §9](docs/BUSINESS_RULES.md#9-user-accounts)).

Instruction Generations (an AI agent writes a crawler's instructions
from a prompt) need a Gemini API key; everything else works without one:

| Key | Default | What it sets |
|---|---|---|
| `GEMINI_API_KEY` | empty | Secret. Without it, every generation fails with `GEMINI_API_KEY must be set.` |
| `GEMINI_MODEL` | `gemini-flash-latest` | The Gemini (Flash) model the browser agent and the synthesizer run on. Google's alias for its newest Flash model; pinned ids such as `gemini-2.5-flash` answer 404 to newer projects. |
| `GEMINI_REQUESTS_PER_MINUTE` | `15` | That model's quota, shared by every worker. The defaults are `gemini-2.5-flash`'s free tier as AI Studio showed it on 2026-10-06; check your model's at aistudio.google.com/rate-limit, since Google changes them. |
| `GEMINI_REQUESTS_PER_DAY` | `1500` | Once spent, generations fail with `Gemini daily request budget spent; try again tomorrow`. |
| `GEMINI_TOKENS_PER_MINUTE` | `1000000` | Calls wait for the next minute once it is spent. |
| `GEMINI_MAX_RETRY_ATTEMPTS` | `3` | Retries of a call Gemini rate-limits (429) before the generation fails with `Gemini rate limit exhausted`. |
| `AGENT_MAX_STEPS` | `40` | The most actions the browser agent takes per generation. |
| `AGENT_MAX_PAGES` | `5` | The most listing pages the browser agent visits per generation; it samples the site, it does not download the catalog. |
| `AGENT_TIMEOUT_SECONDS` | `600` | The most a browser agent run may take. |
| `AGENT_RESPONSE_BODY_MAX_BYTES` | `65536` | The most of each page or API response body kept in a recording. |
| `SYNTHESIS_MAX_ATTEMPTS` | `3` | Instructions files Gemini may write per generation, each sent back with its problems, before the generation fails. |
| `SYNTHESIS_BODY_MAX_BYTES` | `16384` | The most of each recorded response body Gemini is shown. |
| `SYNTHESIS_TOTAL_BODY_MAX_BYTES` | `131072` | The most of all recorded response bodies Gemini is shown, data-carrying ones first. |
| `SYNTHESIS_IGNORED_HOSTS` | built-in list | Comma-separated analytics and ads hosts (and their subdomains) dropped from recordings before tracing where the data came from. |
| `GENERATION_RECORDING_MAX_BYTES` | `1048576` | The most a stored recording may take (see [DOMAIN_MODEL §4.16](docs/DOMAIN_MODEL.md#416-instruction-generation)). |

After changing them, restart the worker: `docker compose restart celery_worker`.

## Run

```bash
make build   # build the images and start the stack
make up      # start it again later
make down    # stop it
```

Once the stack is up, open:

- UI: http://localhost:3000
- API: http://localhost:8000 (docs at `/docs`)
- RabbitMQ: http://localhost:15672
- Keycloak: http://localhost:8180 (admin console with the `KC_BOOTSTRAP_ADMIN_*` login)

**Log in** on the UI takes you to Keycloak's login page: sign in with the
realm's seeded admin (`KC_SEED_ADMIN_EMAIL`), or use **Create one** to
register. Access tokens last 5 minutes; the UI refreshes them by itself.
**Log out** also ends the Keycloak session.

Exported CSV files are saved to `var/csv/raw/` and `var/csv/validated/`.

A crawler's instructions can also be written as one YAML file: on its
Instructions page, **Export** downloads them and **Import** uploads an
edited file. The API does the same:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/crawler-versions/$VERSION_ID/instructions" -o instructions.yaml
curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/yaml" \
  --data-binary @instructions.yaml \
  "http://localhost:8000/api/crawler-versions/$VERSION_ID/instructions"
```

The file's rules are in [docs/DOMAIN_MODEL.md §5.9](docs/DOMAIN_MODEL.md#59-instructions-file).

## Moving accounts to Keycloak

A one-off, for a database that still has the `users` collection from
before Keycloak. It moves those accounts into the `night-crawler` realm,
each keeping its id, so the Crawlers, versions, and generations they own
stay theirs. Do it before dropping the collection.

1. Export the accounts:

   ```bash
   docker compose exec web python backend/scripts/export_users_to_keycloak.py
   ```

   This writes `var/keycloak/users-import.json` and
   `var/keycloak/temporary-passwords.csv` (both readable only by you).
   Old passwords can't be carried over: each account gets a random
   temporary password instead, listed in the CSV.
2. Open http://localhost:8180, log in with `KC_BOOTSTRAP_ADMIN_USERNAME`
   and `KC_BOOTSTRAP_ADMIN_PASSWORD`, and pick the **night-crawler**
   realm in the realm list at the top left.
3. Go to **Realm settings**, open the **Action** menu at the top right,
   and choose **Partial import**.
4. Browse to `var/keycloak/users-import.json`, tick **Users**, set
   **If a resource exists** to **Overwrite**, and click **Import**.
   Overwrite matters: an account that already exists in Keycloak with
   the same email, such as the realm's seeded admin, is replaced by the
   exported one, so it takes the old id that its data points to. Its
   Keycloak password is replaced too: from now on it logs in with its
   temporary password from the CSV, not `KC_SEED_ADMIN_PASSWORD`.
5. Give each user their temporary password. At their first login,
   Keycloak makes them choose a new one, and asks for their first and
   last name.
6. Delete both files in `var/keycloak/`, then drop the old collection:

   ```bash
   docker compose exec db sh -c 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_INITDB_DATABASE" --eval "db.users.drop()"'
   ```

## Monitoring

```bash
make up-observability   # the stack plus Prometheus, Loki, and Grafana
```

Then open Grafana at http://localhost:3030 (`GRAFANA_ADMIN_USER` /
`GRAFANA_ADMIN_PASSWORD` from `.env`, `admin` / `admin` if unset). The
**Night Crawler overview** dashboard shows worker health, runs per
crawler and how long they take, request results per host, rate-limit
waits, queue depth, API traffic, and recent warnings and errors. Paste
an execution id into the `execution_id` box to see that run's logs and
trace: every request, rate-limit wait, and database call, with timings.
In Grafana's Explore view, a log line's `trace_id` links to its trace.
Prometheus itself is at http://localhost:9090.

`make up-observability` also turns on the app's traces and metrics
(`OTEL_EXPORTER_OTLP_ENDPOINT`); a plain `make up` turns them off again.

## Useful commands

```bash
docker compose logs -f celery_worker   # follow the crawler logs (JSON lines)
make test                 # backend tests
make test-frontend        # frontend tests
make lint                 # lint checks
make format               # format the code
make restart-db           # reset the database
```

## More

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): services and layers
- [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md): what the crawler does
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md): coding rules
- [bruno/README.md](bruno/README.md): ready-made API requests
- [LICENSE](LICENSE)

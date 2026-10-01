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

Set `JWT_SECRET` to a random value (`openssl rand -hex 32`), or the API
won't start. `ADMIN_SEED_EMAIL` and `ADMIN_SEED_PASSWORD` create an admin
account on startup; leave them empty to skip it.

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

Sign in with the seeded admin account, or register a new user.

Exported CSV files are saved to `var/csv/raw/` and `var/csv/validated/`.

## Useful commands

```bash
docker compose logs -f celery_worker   # follow the crawler logs
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

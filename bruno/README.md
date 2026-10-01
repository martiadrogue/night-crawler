# Bruno collection

Requests for the Night Crawler API, for [Bruno](https://www.usebruno.com/).

## Setup

1. Open this `bruno/` folder as a collection in Bruno.
2. Select the `local` environment. `adminEmail` and `adminPassword` come
   from the seeded admin in the repo's `.env` (`ADMIN_SEED_EMAIL` /
   `ADMIN_SEED_PASSWORD`): `bruno/.env` is a symlink to it, and Bruno
   reads it through `{{process.env.…}}`. Fill in the one secret left:
   - `googleApiKey`: a Google Maps Platform key with the Places API (New)
     enabled. Only `real-cases/` needs it.
3. Start the API and the workers
   (`docker compose up -d db redis rabbitmq web celery_worker celery_beat`).

Run each folder with the Collection Runner, in order. Requests pass ids
and tokens to each other through environment variables
(`bru.setEnvVar`).

## Auth

The bearer auth lives once, in `collection.bru`: `Bearer {{token}}`.
Every request inherits it (`auth: inherit`, through its folder), except
login and register, which send none. Each folder starts by logging in as
the admin, which stores the session token in `token`. To send a single
request by hand, run a login request first. `token` is a secret
environment variable, so Bruno keeps it locally and it never lands in
`environments/local.bru`.

From the command line:

```bash
cd bruno
npx @usebruno/cli run users --env local
npx @usebruno/cli run real-cases -r --env local --env-var googleApiKey=...
```

## Rate limits

Rate limits are named after the domain they are for (e.g.
`places.googleapis.com`), like the template editor's **Add rate limit**
expects. Each "Find or create" request looks for the rule by that name
first: when it exists, its id is reused and the POST is skipped, so every
run shares one rule per domain.

## `users/`

Logs in as the admin, registers Ana (public), creates Bernat, Carla and
David (admin only), makes Carla an admin and David a viewer, lists the
users, and finishes by logging in as Ana. Emails get a per-run suffix,
so the folder can run again.

## `real-cases/`

`places-api/` collects every restaurant in Andorra. It makes sure the
**Google Maps** Source exists (creating it answers 409 when an earlier
run already did), looks up its id and the built-in `venues` Dataset's
id, then creates a crawler linked to both, builds and publishes its
version, and creates a `pending` execution. The execution is seeded with:

- `parish[]`: the 7 parishes.
- `category[]`: restaurants, bars, cafes, fast food, pizzerias, bakeries.
- `google_api_key`: from the `googleApiKey` variable. The API never
  returns Context values.

Google's Text Search returns at most 20 places per call (60 with paging).
So the search template fans out once per `category` × `parish` pair
(42 calls) instead of paging one Andorra-wide search. Overlapping
results are fine: the dataset import upserts by place id.

### `places-api/` — Google Places API

One Text Search template writes a `venues` row per place: id, name,
address, location, types, rating, review count, price level, website,
phone, Maps URL and opening hours. Rate limit: 5 requests/second, through
the `places.googleapis.com` rule.

### `thefork-barcelona/` — TheFork listing (all Barcelona restaurants)

TheFork's HTML pages are behind DataDome bot protection (403 / CAPTCHA,
even in a headless browser). The site's Next.js data endpoint, the JSON
it loads when you change page, is served to a plain request:

`https://www.thefork.es/_next/data/{build id}/es-ES/restaurantes/barcelona-c41710.json?p={page}`

The crawler needs nothing seeded: it finds both the build id and the pages
on every run.

1. **Build id** (requests 21-23). It changes on every TheFork deploy, so the
   crawler's first template asks for a missing file,
   `https://www.thefork.es/favicon-missing.ico`. TheFork answers with its
   Next.js 404 page, which is not behind DataDome and embeds
   `"buildId":"…"`. The template's Success codes are `404`, and an XPath
   cuts the id out into `thefork_build_id`.
2. **Pages** (request 19). The listing template asks for
   `?p={{next_page}}`, and its `next_page` selector reads the next page
   number from the response (`hasNext && sum([currentPage, `1`]) || null`).
   A template that fills its own placeholder repeats: the first request
   sends `?p=` (page 1), each response names the next page, and the run
   stops when none comes back (51 pages, 1,263 restaurants today), at most
   one page per second (the `www.thefork.es` rule).
3. **Rows**. An iterator over
   `pageProps.searchPageResultsFetchResult.list[].restaurant` writes a
   `venues` row per restaurant: TheFork id, name, address, location,
   cuisine, rating (out of 10), review count, price level (1–4), and the
   restaurant's page URL.

Opening hours and menus are on each restaurant's own data endpoint
(`…/es-ES/restaurante/{slug}-r{id}.json`), one request per restaurant;
not crawled yet.

## Limitations

- **Venues stop at the execution's CSV.** Each run writes its rows to
  `crawler_execution_datasets`; the import into `dataset_venues` isn't
  built yet.
- **Context carries over.** Each run inherits the previous run's
  Context, including `google_api_key`; rotate the key with
  `PUT /api/crawlers/{id}/context/google_api_key`.
- **Duplicates.** A place found by several searches is fetched once per
  search.
- **Crawler placeholders vs Bruno variables.** Template fields contain
  crawler placeholders (`{{parish}}`, `{{category}}`,
  `{{google_api_key}}`). Bruno leaves unknown variables
  as written, so don't create Bruno variables with those names.

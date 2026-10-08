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

### `comedy-clubhouse-events/` — The Comedy Clubhouse (Barcelona comedy events)

Every upcoming event at [The Comedy Clubhouse](https://thecomedyclubhouse.es/all-events/),
into a new `events` Dataset.

1. **Source and Dataset** (requests 02-05). There is no built-in Dataset
   for events, so request 04 creates `events` (409 when it already
   exists, then reused as it is). One row per event occurrence: a weekly
   show is one row per date.

   | Field | Type | Rules | From the API |
   |---|---|---|---|
   | `item_id` | string | required, unique | `id`, the WordPress id |
   | `name` | string | required | `title` |
   | `start_date` / `end_date` | string | `YYYY-MM-DD HH:MM:SS`; start required | local time |
   | `timezone` | string | | `Europe/Madrid` |
   | `all_day` | boolean | | |
   | `venue`, `address` | string | | venue name; street, postcode, city |
   | `categories`, `organizers` | string (lists) | | names |
   | `cost` | string | | the price as shown (`Free`, `&euro;10,00 – &euro;12,00`) |
   | `price_min` / `price_max` | float | | euros, 0 when free |
   | `image_url` | string | URL | poster |
   | `source_url` | string | required, unique, URL | the event's page |

2. **One request** (request 09). `/all-events/` is an Elementor widget
   that shows only the next 36 events. The site runs The Events Calendar,
   whose REST API returns every upcoming event (today until two years
   ahead) as JSON:
   `https://thecomedyclubhouse.es/wp-json/tribe/events/v1/events?per_page=1000`.
   `per_page=1000` returns them all at once (487 today, about 3.7 MB in
   about 11 s), so the template has a 60-second timeout and no
   pagination: the API refuses an empty `page=`, which rules out a
   template that feeds its own page number.
3. **Rows** (requests 10-25). An iterator over `events[]` writes one row
   per event. Prices come from `cost_details.values` (numbers), not from
   the `cost` text.

A run takes one request (the `thecomedyclubhouse.es` rule, at most one per
second), ends `parsed`, and needs nothing seeded.

Known gaps: titles, organizers and `cost` keep the HTML entities the site
sends (`&#8211;`, `&#038;`, `&euro;`); the site gives no venue
coordinates; past events and events more than two years ahead are not
listed; more than 1,000 upcoming events would be cut off.

### `english-standup-barcelona-events/` — English Stand Up Barcelona (upcoming shows)

The upcoming shows on [English Stand Up Barcelona](https://www.englishstandupbarcelona.com/#upcoming),
into the **same `events` Dataset** as `comedy-clubhouse-events/`: run that
folder first, since this one only looks the Dataset up (request 04).

1. **One HTML request** (request 08). The homepage's "#upcoming" section is
   the site's Squarespace event collection, `/events`, which lists the
   upcoming events (`article.eventlist-event--upcoming`, 3 today) before
   the past ones. Its JSON form (`/events?format=json`) has the same
   events, but with dates as epoch milliseconds, which JMESPath can't
   format; the HTML has the date and the local time, which XPath can.
2. **Rows** (requests 09-19). 10 of the Dataset's 15 fields: the listing
   shows no organizers, prices, or all-day flag.
   - `start_date` / `end_date`: the page shows `8:30 PM` whatever the
     language, so an XPath 1.0 expression turns the `<time>` element's
     `datetime` and that text into `2026-10-16 20:30:00` (hour `mod 12`,
     plus 12 for `PM`, padded); `timezone` is the site's own,
     `Europe/Madrid`.
   - `item_id` is the event's URL slug; `venue` the address line without
     its `(map)` link; `address` the Google Maps link's query;
     `categories` the first category, as text (one per event here).

A run takes one request (the `www.englishstandupbarcelona.com` rule) and
ends `parsed`.

Known gaps: an all-day event, or one shown without times, gets no valid
`start_date`, which fails parsing; an event ending after midnight would
get the end time on the start's date if the page dates it that way;
`categories` is text here but a list in the other crawler.

### `barcelona-comedy-club-events/` — Barcelona Comedy Club (next six months)

Every upcoming date at [Barcelona Comedy Club](https://barcelonacomedyclub.com/#entradas)
for the next six months, into the **same `events` Dataset** (run
`comedy-clubhouse-events/` first).

1. **One JSON request** (request 08). "#entradas" is an EventON weekly
   calendar that loads its events after the page, so the HTML has none.
   The template asks EventON directly, the way its own script does: a
   form `POST` to its REST route,
   `https://barcelonacomedyclub.com/wp-json/eventon/v1/data?action=init`
   (no login, no nonce, answered as `application/json`), asking for a list
   calendar of `number_of_months=6` from the current month,
   `event_past_future=future`: 82 dates of 7 shows today.
2. **Rows** (requests 09-17). One per date (`cals.c1.json[]`), 8 fields:
   - `start_date` / `end_date` use the engine's `format_epoch` JMESPath
     function (DOMAIN_MODEL §4.5). EventON's `event_start_unix` holds the
     local wall time written as UTC, so it is formatted in `'UTC'`: that
     matches the time in all 81 titles that state one, while
     `event_start_unix_utc` is hours off for some events.
   - `item_id` is `{event id}-{repeat index}`; `source_url` the show's
     page (`/?p={id}`) plus `#ri-{index}`, to stay unique per date: the
     response has no per-date URL.
   - `cost` is the online price as text (`10.24 €`, sometimes `12,24 €`);
     `price_max` the full price in euros.

Known gaps: no venue, address, categories or image (venues are a
separate WordPress taxonomy, not in this response); titles keep the
show time and some HTML entities; the `source_url` fragment doesn't
select the date on the site.

### `tinta-roja-events/` — Tinta Roja (stand-up shows)

Every upcoming stand-up date at [Tinta Roja](https://www.tinta-roja.cat/es/espectaculos-de-monologos-comicos-2),
into the **same `events` Dataset** (run `comedy-clubhouse-events/` first).
Two templates, plain HTML on httpx:

1. **Listing** (requests 08-11): the stand-up category page has one card
   per date (22 today, of 3 shows), but its dates have no year
   (`Vie. 09 de octubre - 20:00`). So it only collects each show once
   (a card is skipped when an earlier one has the same title) into
   `show_path[]`.
2. **Show pages** (requests 12-25): `https://www.tinta-roja.cat{{show_path}}`
   fans out once per show. Each page's "Otras fechas del evento" block
   lists every upcoming date with its year (`Vie 09 oct 26 - 20:00`),
   price and booking link: one row per date, 11 fields.
   - `start_date`: XPath 1.0 cuts the fixed-layout text by position and
     looks the month up in `'ene feb mar … dic'`, giving
     `2026-10-09 20:00:00` (checked for all 12 months).
   - `item_id` is `{show slug}@{start_date}`; `source_url` the date's own
     page (`?event_session_id=…`) when the site sells the tickets, else
     the show's page plus `#{date}` (Comedy de comptoir books on
     linktr.ee).
   - `price_min` / `price_max`: booking and box-office prices from
     `10€ con reserva, 13€ en taquilla`; `venue`, `address` and
     `timezone` are constants (every show is at the Tinta Roja).

A run takes 1 + one request per show (4 today, the `www.tinta-roja.cat`
rule) and ends `parsed`.

Known gaps: no end time (the site shows only doors opening); the date
cut relies on the `Vie 09 oct 26 - 20:00` layout, so a change to it
fails `start_date`'s pattern and with it parsing.

### `atrapalo-events/` — Atrápalo (stand-up listings, stealth browser)

Every stand-up performance Atrápalo lists for Barcelona
(`https://www.atrapalo.com/entradas/barcelona/monologos/es_ajax/p-1/`), into
the **same `events` Dataset** (run `comedy-clubhouse-events/` first).

Atrápalo answers every non-browser request, pages and AJAX alike, with a
JavaScript "Client Challenge". All three templates therefore run in a
stealth browser (`render_mode: "stealth"`, Patchright), which reads a
page only once it has stopped reloading itself, so the real page behind
the challenge is harvested. The site plainly doesn't want automated
clients: check its terms before running this regularly.

1. **Page 1** (requests 08-13): a fixed URL, `/es_ajax/` (where
   `/es_ajax/p-1/` redirects), 40 shows a page. It collects each card's
   `data-url` into `show_path[]` and the pagination links into
   `listing_page[]`, fresh on every run: as a run's first harvest of
   those keys, they replace what the previous run left.
2. **Other result pages** (requests 14-19): `/es_ajax/{{listing_page}}`
   fans out over page 1's links (`p-2/` …) and feeds itself from each
   page's own links; every distinct page runs once. (Page 1 has its own
   template because a self-feeding list starts from what the previous
   run left, which would skip page 1.)
3. **Show pages** (requests 20-32): one per distinct show. Each page's
   schema.org JSON-LD has a `ComedyEvent` per performance (an array, or
   a single object for a one-off show); an HTML iterator over that
   `<script>` reads it as JSON, so the fields use JMESPath:
   `format_iso(startDate, …, 'Europe/Madrid')` for `start_date`, venue,
   address and performers from the event, and `placeholder('show_path')`
   to build `item_id` and `source_url` (the show page plus
   `#{startDate}`). A show with no scheduled dates (open-date, on
   request) has no `ComedyEvent` and gives no rows.

Paced by the `www.atrapalo.com` rule, `20/minute` (one page every 3 s,
backing off on 429): about 187 requests and 10 minutes today (5 result
pages, 182 shows, ~750 performances). A 403 is not retried.

Known gaps: no end time, categories, or price per performance; the
"Barcelona" results include some shows elsewhere in the province (their
`address` says where); the listing's two iterators cross-join, repeating
values in the Context (each distinct page and show still runs once).

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

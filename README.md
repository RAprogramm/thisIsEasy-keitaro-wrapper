# Keitaro wrapper

A FastAPI + SQLAlchemy wrapper around the Keitaro Admin API. Two tools in one service:

- **Campaign creator**: name + geo code + offer ID → a campaign with two streams (`geo → Google`, `everyone else → offer`), with domain, group and source resolved through the Keitaro API.
- **Campaign editor**: load any campaign by ID, see per-offer statistics, add and remove offers; stream shares are rebalanced automatically.

The frontend is a single HTML page served by the same app — no build step.

[![CI](https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper/actions/workflows/ci.yml/badge.svg)](https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper/actions/workflows/ci.yml)

## Requirements

- Python 3.13+ (tested on 3.13, 3.14, 3.15)
- PostgreSQL 14+ (tested on 17)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start

```bash
createdb keitaro
git clone https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper.git
cd thisIsEasy-keitaro-wrapper
uv sync

cp .env.example .env        # set KEITARO_API_KEY (the key from the Keitaro admin panel)
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000, Swagger at http://localhost:8000/docs.

Without uv: `pip install -r requirements.txt` (pinned runtime dependencies) and run the
same commands without the `uv run` prefix.

## Settings (`.env`)

| Variable | Purpose |
|---|---|
| `KEITARO_URL` | tracker URL, defaults to `https://tlgk.host` |
| `KEITARO_API_KEY` | API key (never commit it) |
| `KEITARO_TIMEOUT` | per-request timeout in seconds, default `30` |
| `DATABASE_URL` | SQLAlchemy connection string, default `postgresql+psycopg:///keitaro` |
| `CAMPAIGN_PREFIX` | campaign name prefix, `test_surname_` |
| `GOOGLE_URL` | where the "geo → Google" stream redirects to |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/dictionaries` | domains, groups, sources, offers |
| POST | `/api/campaigns` | `{name, geo, offer_id, domain_id?, group_id?, source_id?}` — create a campaign |
| GET | `/api/campaigns` | campaigns created through the creator |
| GET | `/api/campaigns/{id}` | campaign, its streams, offers and statistics |
| POST | `/api/campaigns/{id}/offers` | `{offer_id, stream_id?}` — add an offer |
| DELETE | `/api/campaigns/{id}/offers/{offer_id}` | remove an offer |
| GET | `/healthz` | liveness probe for deploy and monitoring |

## How it works

The creator sends three objects to Keitaro: a campaign (`type: position`, with domain,
group and traffic source), then two streams. Keitaro evaluates streams by position, so
stream 1 (`country = GEO → redirect to Google`) catches the target country and stream 2
(no filters, `schema: landings`, the chosen offer at 100%) catches everyone else.

The editor reads the campaign streams, finds the offer stream (`schema: landings`), and
rewrites its offer list with a partial `PUT /streams/{id}`. Shares are split evenly; the
remainder of the division goes to the first offer. Per-offer numbers come from
`POST /report/build` grouped by `offer_id`, all time.

The local database stores only what this service itself produces: `campaigns` (created
through the creator) and `offer_changes` (the add/remove journal). Campaign configuration
and statistics live in Keitaro and are never duplicated.

## Design decisions

- **Keitaro is the source of truth.** The wrapper reads and mutates the tracker state
  directly; the local tables are a journal, not a cache, so they cannot go stale.
- **Partial stream updates.** `PUT /streams/{id}` in this Keitaro version updates only
  the fields sent — verified against the live API. The editor sends just the offer list,
  so stream names, filters and redirects survive offer edits.
- **Statistics errors are surfaced, not hidden.** If `report/build` fails, the response
  carries `stats_error` and the UI says the numbers are unreliable instead of showing
  plausible zeros.
- **The last offer of a stream cannot be removed** — a landings stream without offers is
  a broken campaign.
- **Defaults are explicit.** If no domain/group/source is chosen, the first dictionary
  entry is used and the response reports exactly which IDs were applied.
- **Guards before writes.** Unknown offer, unknown dictionary ID, duplicate offer and
  missing stream are all rejected before anything is created in Keitaro.

## Limitations

- **No authentication.** Anyone who can reach the port can create and modify campaigns
  in Keitaro; run it on a trusted network or behind a reverse proxy that adds auth.
- The editor targets the first `landings` stream of a campaign unless `stream_id` is
  given; campaigns with several offer streams need the explicit ID.
- Statistics are all-time only; there is no date-range picker.
- The wrapper is synchronous by design (internal tool scale); one Keitaro call per
  request, 30 s timeout, upstream failures map to 502.

## Development

```bash
uv sync
uv run pytest --cov=app --cov-fail-under=100   # 58 tests, ~0.5 s
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests alembic
uv run alembic upgrade head && uv run alembic check   # migrations match the models
```

Tests never touch the Keitaro network: HTTP is mocked with `respx`, endpoints run against
an in-process `FakeKeitaro`, and `pytest-socket` blocks all external sockets. Tests use
the database from `TEST_DATABASE_URL` (default `postgresql+psycopg:///keitaro_test`) and
never read `DATABASE_URL`, so a stray environment variable cannot point them at the
working database; CI runs them against a `postgres:17` service. CI also applies all
migrations to a fresh database and fails on any drift between them and the models.
`db/schema.sql` and `db/queries.sql` mirror the ORM schema and the queries the app issues;
CI analyzes them with [sql-query-analyzer](https://github.com/RAprogramm/sql-query-analyzer).
CI also re-exports `requirements.txt` from `uv.lock` and fails if the two have drifted.

## AI usage

The code was drafted by AI coding assistants from the task specification. The models that
took part:

- **Qwen3.8 Flash Next**

The author reviewed every change and verified the result against the live Keitaro test
tracker: campaign creation, stream inspection, editor guards and partial stream updates.

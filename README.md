# Keitaro wrapper

A FastAPI + SQLAlchemy wrapper around the Keitaro Admin API. Two tools in one service:

- **Campaign creator**: name + geo code + offer ID → a campaign with two streams (`geo → Google`, `everyone else → offer`), with domain, group and source resolved through the Keitaro API.
- **Campaign editor**: load any campaign by ID, see per-offer statistics, stage offer
  additions and removals, pin shares, then publish or discard — Keitaro is only touched
  on publish.

The frontend is a single HTML page served by the same app — no build step.

[![CI](https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper/actions/workflows/ci.yml/badge.svg)](https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/RAprogramm/thisIsEasy-keitaro-wrapper/graph/badge.svg)](https://codecov.io/gh/RAprogramm/thisIsEasy-keitaro-wrapper)
[![wakatime](https://wakatime.com/badge/github/RAprogramm/thisIsEasy-keitaro-wrapper.svg)](https://wakatime.com/badge/github/RAprogramm/thisIsEasy-keitaro-wrapper)

## Requirements

- Python 3.14+ (tested on 3.14 and 3.15)
- PostgreSQL 14+ (tested on 17)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start

**Option A — Docker (nothing to install locally):**

```bash
git clone https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper.git
cd thisIsEasy-keitaro-wrapper
cp .env.example .env        # set KEITARO_API_KEY (the key from the Keitaro admin panel)
docker compose up -d --build
```

This starts PostgreSQL 17 and the app; migrations apply automatically on container start.
Open http://localhost:8000, Swagger at http://localhost:8000/docs.

**Option B — local run (Python 3.14+ and PostgreSQL):**

`uv` provisions the interpreter automatically, so only PostgreSQL must already be running:

```bash
git clone https://github.com/RAprogramm/thisIsEasy-keitaro-wrapper.git
cd thisIsEasy-keitaro-wrapper
createdb keitaro
uv sync

cp .env.example .env        # set KEITARO_API_KEY (the key from the Keitaro admin panel)
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000, Swagger at http://localhost:8000/docs.

Shortcut: `make run` (runs `python -m app`) after `make migrate`.

Without uv: `pip install -r requirements.txt` (pinned runtime dependencies) and run the
same commands without the `uv run` prefix.

## Settings (`.env`)

| Variable | Purpose |
|---|---|
| `KEITARO_URL` | tracker URL, defaults to `https://tlgk.host` |
| `KEITARO_API_KEY` | API key (never commit it) |
| `KEITARO_TIMEOUT` | per-request timeout in seconds, default `30` |
| `DATABASE_URL` | SQLAlchemy connection string, default `postgresql+psycopg:///keitaro` |
| `GOOGLE_URL` | where the "geo → Google" stream redirects to |
| `DICTIONARIES_TTL` | lifetime of the cached dictionaries response, seconds, default `60` |
| `RATE_LIMIT_PER_MINUTE` | mutating requests per client IP per minute, default `120` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR`, default `INFO` |
| `LOG_FORMAT` | `text` or `json`, default `text` |
| `CORS_ORIGINS` | comma-separated allowed origins; empty disables CORS |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | SQLAlchemy pool size and overflow, defaults `5` / `10` |
| `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | pool checkout timeout and connection recycle, seconds, defaults `30` / `1800` |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/dictionaries` | domains, groups, sources, offers |
| GET | `/api/offers/search` | `?q=&limit=` — offers by name or exact ID, the autocomplete source |
| GET | `/api/campaigns/search` | `?q=&limit=` — Keitaro campaigns by name or exact ID, the editor picker |
| POST | `/api/campaigns` | `{name, geo, offer_id, domain_id?, group_id?, source_id?}` — create a campaign |
| GET | `/api/campaigns` | campaigns created through the creator |
| GET | `/api/campaigns/{id}` | campaign, its streams, offers and statistics |
| POST | `/api/campaigns/{id}/offers` | `{offer_id, stream_id?}` — add an offer |
| DELETE | `/api/campaigns/{id}/offers/{offer_id}` | remove an offer |
| POST | `/api/campaigns/{id}/offers/{offer_id}/restore` | bring an archived offer back |
| POST | `/api/campaigns/{id}/offers/{offer_id}/pin` | `?pinned=true|false` — pin an offer's share |
| POST | `/api/campaigns/{id}/push` | publish staged changes to Keitaro |
| POST | `/api/campaigns/{id}/cancel` | discard staged changes |
| GET | `/healthz` | liveness probe for deploy and monitoring |
| GET | `/readyz` | readiness probe; also checks the database connection |

## How it works

The creator sends three objects to Keitaro: a campaign (`type: position`, with domain,
group and traffic source), then two streams. Keitaro evaluates streams by position, so
stream 1 (`country = GEO → redirect to Google`) catches the target country and stream 2
(no filters, `schema: landings`, the chosen offer at 100%) catches everyone else.

The editor reads the campaign streams, finds the offer stream (`schema: landings`), and
rewrites its offer list with a partial `PUT /streams/{id}`. Shares are split evenly; the
remainder of the division goes to the first offer. Per-offer numbers come from
`POST /report/build` grouped by `offer_id`, all time.

Edits are staged locally: adding or removing an offer makes the stream "unpublished"
(yellow) and rebalances shares without touching Keitaro. `Опубликовать` pushes the staged
state, `Отменить` discards it. Removed offers stay in the wrapper as an archive with
`Вернуть`; offers deleted directly in Keitaro are marked as archived on the next load.
Weights can be pinned so they survive rebalancing.

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
- Statistics without `from`/`to` describe the whole history of a campaign.
- All I/O is async (a persistent `httpx2.AsyncClient` and the SQLAlchemy asyncio engine),
  but the calls inside one request are awaited in sequence, not in parallel; 30 s
  timeout per call, upstream failures map to 502.

## Scaling & state

The service runs as a single process and keeps two pieces of state in memory:

| State | Location | Why per-process is correct here |
|---|---|---|
| Keitaro dictionaries | `_dictionaries_cache` (TTL) | slow-changing reference data; seconds of staleness are invisible to users |
| Rate-limit counters | `rate_limit` middleware | coarse abuse guard, not a billing quota; over-admission costs nothing |

Everything that must be shared or survive a restart — campaigns, stream offers,
idempotency keys — lives in PostgreSQL, so the app itself is otherwise stateless.

Running two or more replicas (or `uvicorn --workers > 1`) makes both caches
per-replica: the dictionary hit rate drops with fleet size and the effective rate
limit becomes `limit × replicas`. For an internal tool that is acceptable. If it ever
stops being acceptable, the migration path is deliberately boring:

- dictionaries: shorten the TTL or move the cache to Redis/Valkey;
- rate limiting: a Postgres counter (the database is already deployed) or the reverse proxy;
- adopt either only after measuring hit rate, p99 and Keitaro request volume per
  replica — evidence, not speculation.

## Deployment

```bash
docker compose up -d --build   # postgres:17 + the app; migrations apply on start
```

Compose substitutes `KEITARO_API_KEY` (and optionally `KEITARO_URL`) from `.env` in the
project root, so create it first, as in the quick start.

The image is `python:3.14-slim` based, installs dependencies from `uv.lock`, runs as a
non-root user and reports health through `/healthz`.

## Development

```bash
uv sync
make test          # pytest with coverage, must stay at 100%
make lint          # ruff + mypy + yamllint + deptry + typos
make migrate       # alembic upgrade head
uv run alembic check                       # migrations match the models
make requirements  # re-export requirements.txt from uv.lock
make audit         # pip-audit against the locked environment
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
`tests/openapi_snapshot.json` freezes the HTTP contract: any endpoint or schema change
must be confirmed by regenerating the snapshot (`UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi.py`).

CI runs the suite on Python 3.14 and 3.15. Coverage is pinned to the `sysmon` core
in `[tool.coverage.run]` — the modern core that is the default on Python 3.14+; the legacy
`settrace` cores report lines executed after an `await` as missing
([coveragepy#2245](https://github.com/coveragepy/coveragepy/issues/2245)).

## AI usage

The code was drafted by AI coding assistants from the task specification. The models that
took part:

- **Qwen3.8 Flash Next**
- **MiMo-V2.6-Flash**

The author reviewed every change and verified the result against the live Keitaro test
tracker: campaign creation, stream inspection, editor guards and partial stream updates.

# Work Location Tracker

[![CI](https://github.com/simcax/swedan-homeoffice/actions/workflows/ci.yml/badge.svg)](https://github.com/simcax/swedan-homeoffice/actions/workflows/ci.yml)

Cross-platform app for Swedish residents working in Denmark to log their daily
work location — `home` (Sweden), `denmark` (office), `vacation`, or `sick` — and
track compliance with the 50% Denmark work requirement.

The project is a `uv` workspace monorepo:

- `backend/` — FastAPI + async SQLAlchemy + PostgreSQL REST API (deployed to Clever Cloud)
- `app/` — Flet cross-platform UI (desktop, web, mobile)

## Development

```bash
uv sync                       # install all workspace dependencies
uv run pytest -v              # run the full test suite
uv run ruff check .           # lint
uv run ruff format .          # format
uv build                      # build distributable packages
```

Python is pinned to `3.12` via `.python-version`.

## Running the Flet app

The `app/` package imports its modules via the `app.` prefix (e.g.
`from app.api_client import APIClient`), so it must be launched as a module from
the **workspace root** — not as a loose script. Running `uv run app/main.py`
fails with `ModuleNotFoundError: No module named 'app'` because that puts `app/`
itself on the import path.

Run it one of these ways from the repository root:

```bash
uv run python -m app.main            # desktop window
uv run flet run app/main.py          # Flet CLI (desktop + hot reload)
uv run flet run app/main.py --web    # run in the browser
```

### Configuring the backend URL

The app resolves its API base URL in this order: the `API_BASE_URL` environment
variable, then the value saved in the Settings screen (local storage), then the
default `http://127.0.0.1:8080`.

```bash
API_BASE_URL=https://your-backend.example.com uv run python -m app.main
```

## Running the full stack locally

The quickest way to try the app end to end is the dev script, which starts a
PostgreSQL database (Docker), runs migrations, starts the backend, then launches
the Flet app:

```bash
scripts/dev.sh            # database + backend + Flet app
scripts/dev.sh --no-app   # database + backend only (e.g. to curl the API)
```

Ctrl-C stops the backend the script started; the database keeps running in the
background. Stop and keep data with `docker compose down`, or wipe it with
`docker compose down -v`.

### Doing it by hand

If you'd rather run each piece yourself:

```bash
# 1. Start PostgreSQL (bundled docker-compose service)
docker compose up -d db

# 2. Start the backend. The backend reads DATABASE_URL from the process
#    environment ONLY — it does not auto-load .env (by design, Requirement 11.1).
DATABASE_URL=postgresql://wlt:wlt@127.0.0.1:5432/wlt \
  uv run uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload

# 3. Start the Flet app (defaults to http://127.0.0.1:8080)
uv run python -m app.main
```

> `uv run python -m backend.main` does **not** start the server — `backend/main.py`
> only exposes the ASGI `app`; it must be served by uvicorn as shown above.

### Environment variables

Copy `.env.example` to `.env` and fill in values as needed. `.env` is gitignored
and must never be committed. Because the backend does not read `.env`
automatically, either use `scripts/dev.sh` (which exports the values) or export
them yourself: `set -a; source .env; set +a`.

| Variable | Purpose | Local default |
|---|---|---|
| `DATABASE_URL` | Backend PostgreSQL connection string | `postgresql://wlt:wlt@127.0.0.1:5432/wlt` |
| `API_BASE_URL` | URL the Flet app targets | `http://127.0.0.1:8080` |

## Automating "work at office" check-ins

Use the authenticated check-in endpoint to create or update ("upsert") one day
as office work (`denmark` in the API model):

- **Endpoint:** `POST /api/v1/checkin`
- **Authentication:** `X-API-Key` header must match `APP_SHARED_SECRET`
- **Body:** none required
- **Query params (optional):**
  - `location` (defaults to `denmark`)
  - `date` as `YYYY-MM-DD` (defaults to today's Copenhagen local date)

Example request:

```bash
curl -X POST "https://your-backend.example.com/api/v1/checkin?location=denmark&date=2026-10-26" \
  -H "X-API-Key: ${APP_SHARED_SECRET}" \
  -H "Accept: application/json"
```

## CI/CD

Two GitHub Actions workflows drive continuous integration and deployment:

- **`.github/workflows/ci.yml`** — runs on every push and pull request to `main`.
  Three jobs: `lint` (`uv run ruff check .`), `test` (pytest against a PostgreSQL
  service container), and `build` (`uv build`).
- **`.github/workflows/deploy.yml`** — runs after CI succeeds on `main` and deploys
  to Clever Cloud via `clever deploy`.

### Required repository secrets

The deploy workflow needs Clever Cloud credentials stored as encrypted GitHub
secrets. Obtain them by running `clever login` locally, then set them once:

```bash
gh secret set CLEVER_TOKEN
gh secret set CLEVER_SECRET
```

These values are read from `~/.config/clever-cloud/clever-tools.json` after login.
Never commit them to the repository.

## Deployment (Clever Cloud)

A **single** Clever Cloud app hosts both the API and the Flet web UI (one
scaler, one PostgreSQL add-on). The backend serves the API under `/api/v1/...`
and mounts the Flet web client at `/` when `SERVE_FRONTEND` is enabled.

The app runs with these environment variables:

| Variable | Value |
|---|---|
| `CC_PYTHON_UV_SYNC_FLAGS` | `--locked --no-progress` |
| `CC_PYTHON_UV_RUN_COMMAND` | `.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080` |
| `CC_PRE_RUN_HOOK` | `uv run python -m backend.migrate` |
| `SERVE_FRONTEND` | `true` (mount the Flet web UI at `/`) |
| `API_BASE_URL` | the app's public URL (the co-hosted UI calls the same origin) |
| `POSTGRESQL_ADDON_*` | injected automatically by the PostgreSQL add-on |

### Database configuration (no `DATABASE_URL` indirection in production)

The backend resolves its connection string from `DATABASE_URL` when set
(local/CI), otherwise directly from the `POSTGRESQL_ADDON_*` variables the
PostgreSQL add-on injects at run time (`POSTGRESQL_ADDON_URI`, or the discrete
`_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_DB` parts). Do **not** set a
manual `DATABASE_URL="${POSTGRESQL_ADDON_URI}"` on Clever Cloud: that expansion
is empty during the build phase (the add-on variables are not injected then),
which previously broke the build-phase migration hook.

### Migrations run on the run instance, before serving

Migrations run via `CC_PRE_RUN_HOOK` — a **run-phase** hook that executes on the
run instance (where the add-on variables exist) just before the app starts.
This replaces the old `CC_POST_BUILD_HOOK`, which ran during the **build**
phase where `DATABASE_URL` / `POSTGRESQL_ADDON_*` are not available, causing
`sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from given URL
string` (an empty connection string).

`backend.migrate` validates the database configuration first and exits non-zero
on failure, so a mis-configured or failed migration aborts the deploy before
any instance serves on an out-of-date schema:

```bash
uv run python -m backend.migrate
```

Migrations are **not** run from the FastAPI lifespan: running them there would
race when more than one process starts at once (multiple uvicorn workers, or
`--reload`'s reloader plus worker). As a single pre-run step the schema is
brought current exactly once. The FastAPI app still validates the database
configuration on startup (and aborts if it is missing), so a mis-configured
deployment still fails fast.

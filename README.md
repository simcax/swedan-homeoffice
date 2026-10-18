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

The backend runs on Clever Cloud with these environment variables:

| Variable | Value |
|---|---|
| `CC_PYTHON_UV_SYNC_FLAGS` | `--locked --no-progress` |
| `CC_PYTHON_UV_RUN_COMMAND` | `.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080` |
| `CC_POST_BUILD_HOOK` | `uv run alembic -c backend/alembic.ini upgrade head` |
| `DATABASE_URL` | injected automatically by the PostgreSQL add-on |

The post-build hook runs from the repository root, so Alembic is pointed at the
config explicitly with `-c backend/alembic.ini`. Keeping the root as the working
directory ensures `alembic/env.py` can `import backend` while still locating the
migration scripts under `backend/alembic`.

### Migrations run once, before serving

`alembic upgrade head` runs **only** as this pre-start hook — it is **not** run
from the FastAPI lifespan. Running it in the lifespan would race when more than
one process starts at once (multiple uvicorn workers, or `--reload`'s reloader
plus worker), each calling `upgrade head` against the same database
concurrently. As a single pre-start step the schema is brought current exactly
once before any instance serves.

The equivalent of the post-build hook, with `DATABASE_URL` validation and a
non-zero exit on failure, is also available as a module entry point:

```bash
uv run python -m backend.migrate
```

The FastAPI app still validates `DATABASE_URL` on startup (and aborts if it is
missing), so a mis-configured deployment still fails fast — it just no longer
migrates from inside the request-serving processes.

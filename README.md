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
| `CC_POST_BUILD_HOOK` | `uv run alembic upgrade head` |
| `DATABASE_URL` | injected automatically by the PostgreSQL add-on |

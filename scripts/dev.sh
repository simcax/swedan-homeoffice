#!/usr/bin/env bash
#
# Run the full Work Location Tracker stack locally:
#   1. a PostgreSQL database (via docker compose)
#   2. the FastAPI backend (uvicorn on 127.0.0.1:8080)
#   3. the Flet desktop app (optional)
#
# Usage:
#   scripts/dev.sh            # db + backend + flet app
#   scripts/dev.sh --no-app   # db + backend only (e.g. to curl the API)
#   scripts/dev.sh --help
#
# The backend reads DATABASE_URL from the environment only (it does NOT read
# .env), so this script exports it explicitly. Stopping the script (Ctrl-C)
# shuts down the backend it started; the database keeps running in the
# background (stop it with `docker compose down`).

set -euo pipefail

# Resolve the repository root (this script lives in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# --- defaults (overridable via the environment) ------------------------------
DATABASE_URL="${DATABASE_URL:-postgresql://wlt:wlt@127.0.0.1:5432/wlt}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8080}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
RUN_APP=1

for arg in "$@"; do
  case "${arg}" in
    --no-app) RUN_APP=0 ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown argument: ${arg}" >&2; exit 2 ;;
  esac
done

export DATABASE_URL API_BASE_URL

# --- pick the docker compose command -----------------------------------------
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: docker compose is required but was not found." >&2
  exit 1
fi

BACKEND_PID=""

cleanup() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo
    echo ">> Stopping backend (pid ${BACKEND_PID})..."
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
  echo ">> The database is still running. Stop it with: ${COMPOSE[*]} down"
}
trap cleanup EXIT INT TERM

echo ">> Starting PostgreSQL (docker compose)..."
"${COMPOSE[@]}" up -d db

echo ">> Waiting for the database to become healthy..."
for _ in $(seq 1 30); do
  status="$("${COMPOSE[@]}" ps -q db | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  sleep 1
done
if [[ "${status:-}" != "healthy" ]]; then
  echo "ERROR: database did not become healthy in time." >&2
  exit 1
fi
echo ">> Database is ready."

echo ">> Running Alembic migrations..."
uv run python -m backend.migrate

echo ">> Starting backend on http://${BACKEND_HOST}:${BACKEND_PORT} ..."
uv run uvicorn backend.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload &
BACKEND_PID=$!

# Wait for the backend to answer before launching the app.
echo ">> Waiting for the backend to respond..."
backend_ready=0
for _ in $(seq 1 30); do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "ERROR: backend process exited during startup." >&2
    exit 1
  fi
  if curl -fs -o /dev/null "${API_BASE_URL}/openapi.json"; then
    backend_ready=1
    break
  fi
  sleep 1
done
if [[ "${backend_ready}" -ne 1 ]]; then
  echo "ERROR: backend did not respond at ${API_BASE_URL} in time." >&2
  exit 1
fi
echo ">> Backend is up."

if [[ "${RUN_APP}" -eq 1 ]]; then
  echo ">> Launching the Flet app (close its window or Ctrl-C to stop)..."
  uv run python -m app.main
else
  echo ">> --no-app set. Backend is running; press Ctrl-C to stop."
  wait "${BACKEND_PID}"
fi

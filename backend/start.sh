#!/usr/bin/env sh
# Railway / production entrypoint: apply migrations, then serve.
# Railway injects $PORT — default to 8000 for local docker runs.
set -e

echo "[start] running alembic upgrade head"
alembic upgrade head

PORT="${PORT:-8000}"
echo "[start] launching uvicorn on 0.0.0.0:${PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"

#!/usr/bin/env bash
# Start everything for local development: Redis (if not running), API, worker, web UI.
#   scripts/dev.sh        then open http://localhost:3010     (Ctrl+C stops everything)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
[ -x .venv/bin/python ] || { echo "Run the setup steps in README.md first (backend/.venv missing)."; exit 1; }
[ -f .env ] || { echo "Create backend/.env first (see README.md, 'Run it on your computer')."; exit 1; }
REDIS_PORT="$(grep -E '^REDIS_URL=' .env | sed -E 's|.*:([0-9]+)/.*|\1|')"; REDIS_PORT="${REDIS_PORT:-6379}"

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

if ! (exec 3<>"/dev/tcp/127.0.0.1/$REDIS_PORT") 2>/dev/null; then
  command -v redis-server >/dev/null || { echo "Redis isn't running on port $REDIS_PORT and redis-server isn't installed."; exit 1; }
  redis-server --port "$REDIS_PORT" --bind 127.0.0.1 --save "" --appendonly no >/dev/null & pids+=($!)
fi
.venv/bin/python -m app.cli init-db
.venv/bin/uvicorn app.asgi:app --host 127.0.0.1 --port 8010 --reload & pids+=($!)
.venv/bin/python ../worker/run_worker.py & pids+=($!)
(cd "$ROOT/frontend" && npx next dev -p 3010) & pids+=($!)
echo "Open http://localhost:3010  (API docs: http://127.0.0.1:8010/api/docs)"
wait

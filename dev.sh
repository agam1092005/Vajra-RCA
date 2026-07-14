#!/usr/bin/env bash
# Start the Vajra RCA backend + frontend for local development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "▶ backend (FastAPI + Socket.IO) on :8000"
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -e .
fi
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACK=$!

echo "▶ frontend (Next.js) on :3000"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev &
FRONT=$!

trap 'kill $BACK $FRONT 2>/dev/null || true' INT TERM
echo "▶ open http://localhost:3000"
wait

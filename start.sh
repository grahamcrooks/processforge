#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Free ports before starting
echo "Freeing ports 8001 and 5176..."
lsof -ti :8001 | xargs kill -9 2>/dev/null || true
lsof -ti :5176 | xargs kill -9 2>/dev/null || true
sleep 1

echo "Starting backend on port 8001..."
cd "$ROOT/backend"
source .venv/bin/activate
uvicorn main:app --reload --port 8001 &
BACKEND_PID=$!

echo "Starting frontend on port 5176..."
cd "$ROOT/frontend"
npm run dev -- --port 5176 &
FRONTEND_PID=$!

echo ""
echo "Process Forge v2 is running:"
echo "  Frontend: http://localhost:5176"
echo "  Backend:  http://localhost:8001"
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT
wait

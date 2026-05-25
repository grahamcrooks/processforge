#!/bin/bash
# Build script — produces a self-contained backend/ ready to deploy
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"
STATIC="$BACKEND/static"

echo "▶ Building frontend..."
cd "$FRONTEND"
npm install --silent
npm run build

echo "▶ Copying dist → backend/static..."
rm -rf "$STATIC"
cp -r "$FRONTEND/dist" "$STATIC"

echo "✓ Done. Deploy the backend/ folder."
echo ""
echo "  Set these environment variables on your host:"
echo "    ANTHROPIC_API_KEY=<your key>"
echo "    CORS_ORIGINS=[\"https://yourdomain.com\"]"
echo ""
echo "  Start command:"
echo "    cd backend && pip install -r requirements.txt"
echo "    uvicorn main:app --host 0.0.0.0 --port 8000"

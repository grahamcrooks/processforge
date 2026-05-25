#!/bin/bash
# Usage: ./deploy.sh ubuntu@<EC2-IP> [/path/to/key.pem]
set -e

REMOTE=${1:?Usage: ./deploy.sh user@host [key.pem]}
PEM=$2
SSH_OPTS=""
[ -n "$PEM" ] && SSH_OPTS="-i $PEM"

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "▶ Building frontend..."
"$ROOT/build.sh"

echo "▶ Uploading to $REMOTE..."
rsync -avz $SSH_OPTS \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  "$ROOT/backend/" "$REMOTE:/opt/processforge/backend/"

echo "▶ Installing dependencies..."
ssh $SSH_OPTS "$REMOTE" "
  cd /opt/processforge/backend
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt -q
"

echo "▶ Restarting service..."
ssh $SSH_OPTS "$REMOTE" "sudo systemctl restart processforge"

echo "✓ Deployed — $(date)"

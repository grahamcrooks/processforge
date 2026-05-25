#!/bin/bash
cat > "$(dirname "$0")/.env.local" <<EOF
DEV_MODE=false
API_MODEL=claude-sonnet-4-6
EOF
echo "✅ Switched to LIVE mode — using claude-sonnet-4-6."
echo "   Restart the app: cd ~/bupa-blueprint-app-v2 && ./start.sh"

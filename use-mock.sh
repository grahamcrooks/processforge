#!/bin/bash
cat > "$(dirname "$0")/.env.local" <<EOF
DEV_MODE=true
API_MODEL=claude-haiku-4-5-20251001
EOF
echo "✅ Switched to MOCK mode — no API calls will be made."
echo "   Restart the app: cd ~/bupa-blueprint-app-v2 && ./start.sh"

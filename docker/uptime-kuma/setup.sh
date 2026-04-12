#!/usr/bin/env bash
# Uptime Kuma — lightweight self-hosted monitoring
# Runs on port 3002 to avoid conflict with SvelteKit dev (3001)
#
# Usage: cd ~/home-hub/docker/uptime-kuma && bash setup.sh
set -euo pipefail

cd "$(dirname "$0")"
docker compose up -d

echo ""
echo "Uptime Kuma is starting at http://$(hostname -I | awk '{print $1}'):3002"
echo ""
echo "After first launch, configure monitors:"
echo "  1. Home Hub Backend — HTTP http://localhost:8000/health (60s)"
echo "  2. Pi-hole Admin    — HTTP http://localhost:8080/admin  (120s)"
echo "  3. Add a notification channel (Telegram, Pushover, etc.)"

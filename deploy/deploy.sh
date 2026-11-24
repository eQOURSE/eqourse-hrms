#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
"${compose[@]}" config --quiet
test -r /etc/letsencrypt/live/work.eqourse.com/fullchain.pem
test -r /etc/letsencrypt/live/work.eqourse.com/privkey.pem
test -d /var/www/horilla-acme

"${compose[@]}" build web scheduler
# Keep the single scheduler out of the release migration window.
"${compose[@]}" stop scheduler
"${compose[@]}" up -d --wait --wait-timeout 900
"${compose[@]}" exec -T nginx nginx -t
curl -fsS --max-time 15 https://work.eqourse.com/health/ >/dev/null
"${compose[@]}" ps

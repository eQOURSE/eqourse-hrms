#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
if [[ -f /etc/horilla/google-oidc-client-secret ]]; then
  compose+=(-f docker-compose.oidc.yml)
fi
"${compose[@]}" config --quiet
test -r /etc/letsencrypt/live/work.eqourse.com/fullchain.pem
test -r /etc/letsencrypt/live/work.eqourse.com/privkey.pem
test -d /var/www/horilla-acme

"${compose[@]}" build web scheduler
# Keep the single scheduler out of the release migration window.
"${compose[@]}" stop scheduler
# Wait on web, PostgreSQL, and Redis. The scheduler has no HTTP health check.
"${compose[@]}" up -d --wait --wait-timeout 1800 web
"${compose[@]}" up -d --force-recreate --no-deps nginx
"${compose[@]}" up -d scheduler
"${compose[@]}" exec -T nginx nginx -t
curl -fsS --retry 5 --retry-connrefused --max-time 15 https://work.eqourse.com/health/ >/dev/null
"${compose[@]}" ps

#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."

: "${BACKUP_AGE_RECIPIENT:?Set an age public recipient}"
: "${BACKUP_S3_URI:?Set the S3 backup prefix}"
: "${BACKUP_DRIVE_URI:?Set the rclone remote and horilla_backup path}"
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
archive="horilla-$(date -u +%Y%m%dT%H%M%SZ).tar.age"
scratch="$(mktemp -d)"
trap 'rm -f -- "$scratch/database.dump" "$scratch/media.tar.gz" "$scratch/$archive"; rmdir -- "$scratch"' EXIT

"${compose[@]}" exec -T db sh -ec 'pg_dump --format=custom -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$scratch/database.dump"
"${compose[@]}" exec -T web tar -czf - -C /app/media . > "$scratch/media.tar.gz"
tar -C "$scratch" -cf - database.dump media.tar.gz |
  age -r "$BACKUP_AGE_RECIPIENT" -o "$scratch/$archive"
# Attempt both copies even if one destination fails.
status=0
aws s3 cp --only-show-errors "$scratch/$archive" "${BACKUP_S3_URI%/}/$archive" || status=1
rclone copyto "$scratch/$archive" "${BACKUP_DRIVE_URI%/}/$archive" || status=1
exit "$status"

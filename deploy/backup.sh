#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."

: "${BACKUP_AGE_RECIPIENT:?Set an age public recipient}"
: "${BACKUP_S3_URI:?Set the S3 backup prefix}"
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
archive="horilla-$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid).tar.age"
scratch="$(mktemp -d)"
trap 'rm -f -- "$scratch/database.dump" "$scratch/media.tar.gz" "$scratch/$archive" "$scratch/drive-round-trip.age"; rmdir -- "$scratch"' EXIT

"${compose[@]}" exec -T db sh -ec 'pg_dump --format=custom -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$scratch/database.dump"
"${compose[@]}" exec -T web tar -czf - -C /app/media . > "$scratch/media.tar.gz"
tar -C "$scratch" -cf - database.dump media.tar.gz |
  age -r "$BACKUP_AGE_RECIPIENT" -o "$scratch/$archive"
# Attempt both configured copies even if one destination fails.
status=0
s3_path="${BACKUP_S3_URI%/}/$archive"
if aws s3 cp --only-show-errors "$scratch/$archive" "$s3_path"; then
    printf 'S3 backup uploaded: %s\n' "$s3_path"
else
    status=1
fi
if [[ -n "${BACKUP_DRIVE_URI:-}" ]]; then
    case "$BACKUP_DRIVE_URI" in
        *:) drive_path="$BACKUP_DRIVE_URI$archive" ;;
        *) drive_path="${BACKUP_DRIVE_URI%/}/$archive" ;;
    esac
    if rclone copyto --immutable "$scratch/$archive" "$drive_path"; then
        printf 'Drive backup uploaded: %s\n' "$archive"
        if [[ "${BACKUP_VERIFY_DRIVE:-0}" == 1 ]]; then
            if rclone copyto "$drive_path" "$scratch/drive-round-trip.age" &&
                cmp -s "$scratch/$archive" "$scratch/drive-round-trip.age"; then
                printf 'Drive round trip verified: %s\n' "$archive"
            else
                status=1
            fi
        fi
    else
        status=1
    fi
elif [[ "${BACKUP_VERIFY_DRIVE:-0}" == 1 ]]; then
    printf 'Set BACKUP_DRIVE_URI to verify a Drive backup.\n' >&2
    status=1
fi
exit "$status"

#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."

folder_id="${1:?Pass the approved Google Drive folder ID}"
parameter=/eqourse/hrms/google-drive-backup-credentials
environment=/etc/horilla/backup.env
config_dir=/etc/horilla/drive
config="$config_dir/rclone.conf"
remote=horilla-drive:
if systemctl is-active --quiet horilla-backup.service; then
    printf 'Wait for the current backup to finish.\n' >&2
    exit 1
fi
if grep -qE '^(RCLONE_CONFIG|BACKUP_DRIVE_URI)=' "$environment" &&
    ! (grep -Fxq "RCLONE_CONFIG=$config" "$environment" &&
       grep -Fxq "BACKUP_DRIVE_URI=$remote" "$environment"); then
    printf 'A Drive backup is already configured. Review its settings before replacing credentials.\n' >&2
    exit 1
fi

scratch="$(mktemp -d /etc/horilla/drive-setup.XXXXXX)"
trap 'rm -f -- "$scratch/credential.json" "$scratch/rclone.conf" "$scratch/backup.env"; rmdir -- "$scratch"' EXIT
aws ssm get-parameter --region ap-south-1 --name "$parameter" --with-decryption \
  --query Parameter.Value --output text --no-cli-pager > "$scratch/credential.json"
python3 - "$scratch/credential.json" "$scratch/rclone.conf" "$folder_id" <<'PY'
import configparser
import json
import sys
from pathlib import Path

secret = json.loads(Path(sys.argv[1]).read_text())
if secret["folder_id"] != sys.argv[3]:
    raise SystemExit("The stored credential is for a different Drive folder.")
config = configparser.ConfigParser(interpolation=None)
config["horilla-drive"] = {
    "type": "drive",
    "scope": "drive.file",
    "root_folder_id": secret["folder_id"],
    "client_id": secret["client_id"],
    "client_secret": secret["client_secret"],
    "token": json.dumps({
        # rclone 1.60 treats an empty access token as legacy data and drops
        # the refresh token. The expired timestamp forces a real refresh.
        "access_token": "expired",
        "token_type": "Bearer",
        "refresh_token": secret["refresh_token"],
        "expiry": "1970-01-01T00:00:00Z",
    }),
}
with Path(sys.argv[2]).open("w") as handle:
    config.write(handle)
PY
rm -f -- "$scratch/credential.json"

# Leave the current timer and S3 job in place until Drive passes a round trip.
set -a
source "$environment"
set +a
RCLONE_CONFIG="$scratch/rclone.conf" BACKUP_DRIVE_URI="$remote" BACKUP_VERIFY_DRIVE=1 \
    bash deploy/backup.sh

install -d -m 0700 "$config_dir"
install -m 0600 "$scratch/rclone.conf" "$config"
sed -E '/^(RCLONE_CONFIG|BACKUP_DRIVE_URI)=/d' "$environment" > "$scratch/backup.env"
printf '\nRCLONE_CONFIG=%s\nBACKUP_DRIVE_URI=%s\n' "$config" "$remote" >> "$scratch/backup.env"
install -m 0600 "$scratch/backup.env" "$environment"
install -m 0644 deploy/systemd/horilla-backup.service /etc/systemd/system/horilla-backup.service
systemctl daemon-reload
systemctl is-enabled horilla-backup.timer
systemctl is-active horilla-backup.timer

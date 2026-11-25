# Production deployment on a single EC2 host

Run these steps after AWS approval on a dedicated Linux host. Use a pinned checkout and Docker Compose v2 with `!reset` and `!override` support. The public entry point is Nginx on TCP 80/443. Use Session Manager for administration where configured. Keep PostgreSQL, Redis and Django on the internal Docker network. The alternate ALB/RDS design needs its own overlay, network policy, and proxy-trust settings.

## Environment and first deploy

```bash
umask 077
cp .env.dist .env
chmod 600 .env
```

Set `DEBUG=False`, `HORILLA_ENV=production`, `ALLOWED_HOSTS=work.eqourse.com`, `CSRF_TRUSTED_ORIGINS=https://work.eqourse.com`, `HORILLA_TRUSTED_PROXIES=nginx`, and `GUNICORN_WORKERS=2` as the initial load-test setting. Keep `DB_HOST=db`; use unique random values for `SECRET_KEY`, `DB_INIT_PASSWORD`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`. Match passwords in `DATABASE_URL` and `REDIS_URL`, using URL-safe random strings or URL-encoding. The overlay turns on secure redirects and starts with 300 seconds of HSTS. Increase the value after validating TLS and redirects.

Point the existing authoritative DNS provider's `work` record at the instance's static address. Install Certbot and make the webroot. Before starting Compose, issue the initial certificate with HTTP-01 in standalone mode while port 80 is free. Then switch renewal to webroot so Nginx can stay online. The deploy hook should run the last command below from the checkout after each successful renewal. Validate with `sudo certbot renew --dry-run`.

```bash
sudo install -d -m 0755 /var/www/horilla-acme
sudo certbot certonly --standalone -d work.eqourse.com
sudo bash deploy/deploy.sh
sudo certbot reconfigure --cert-name work.eqourse.com --webroot -w /var/www/horilla-acme
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T nginx nginx -s reload
```

Set up the first Superadmin via `docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py createsuperuser`. Verify HTTPS and the scheduler before onboarding. Run `python manage.py check --deploy` in the web container. Confirm that private media is served through Django and production sessions use secure cookies. Update during a release window. Take a verified pre-release backup and restore it with the last working commit if a schema change prevents rolling back the app alone.

## Google Workspace sign-in

Register `https://work.eqourse.com/auth/google/callback/` on the Internal Google Web OAuth client. Add `GOOGLE_OIDC_CLIENT_ID` to the host's `.env`. Use the instance's AWS role to materialize only the approved SecureString into a file readable by the web container's UID 1000.

```bash
sudo bash -c '
set -eu
umask 077
temp=$(mktemp /etc/horilla/google-oidc.XXXXXX)
trap '\''rm -f "$temp"'\'' EXIT
aws ssm get-parameter --region ap-south-1 \
  --name /eqourse/hrms/google-oidc-client-secret --with-decryption \
  --query Parameter.Value --output text --no-cli-pager > "$temp"
test -s "$temp"
chown 1000:1000 "$temp"
chmod 0400 "$temp"
mv -T "$temp" /etc/horilla/google-oidc-client-secret
'
```

The deployment script includes the Google Compose overlay when that file is present. For each approved employee, first create their active Horilla employee and user accounts. An authorized deployment operator can add a `horilla_auth.models.GoogleIdentity` row linking the Horilla user to their exact lowercase `@eqourse.com` address. The first successful login binds Google's stable subject to that row. Superadmins use the local recovery login. For a renamed or reassigned Google account, review and replace the approval explicitly. Removing an approval prevents subsequent Google sign-ins.

## Daily encrypted backup

Install `age`, AWS CLI and `rclone` on the host. Use the instance role for a dedicated encrypted, versioned S3 prefix and a restricted rclone credential for an approved Google Shared Drive folder. Set `BACKUP_AGE_RECIPIENT` to the public encryption recipient, `BACKUP_S3_URI` to the destination prefix, and `BACKUP_DRIVE_URI` to a remote path such as `workspace:horilla_backup`. Store the private recovery key outside the host. Protect the rclone configuration and the systemd service's environment file.

The unit files assume a checkout at `/opt/eqourse-hrms` and a root-readable `/etc/horilla/backup.env` with mode `0600`. Include `RCLONE_CONFIG` if the rclone configuration is outside the service account's home directory. Install the units and verify one backup before enabling the timer.

```bash
sudo install -m 0644 deploy/systemd/horilla-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start horilla-backup.service
sudo journalctl -u horilla-backup.service -n 30
sudo systemctl enable --now horilla-backup.timer
```

Alert if either copy fails or the latest backup is missing. The database dump is transaction-consistent. The media archive is taken immediately afterward. Quiesce writes for a coordinated recovery point before schema-changing releases. Keep a 30-day S3 lifecycle and a matching approved Drive retention policy. Test decryption, `pg_restore` and media restore into an isolated environment. Back up production configuration and credentials separately using the approved secret store.

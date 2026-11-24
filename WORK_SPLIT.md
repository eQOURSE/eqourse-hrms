# eQOURSE HRMS work split

The upstream baseline is Horilla's annotated tag `2.4.0` on its `2.0` branch, commit `6c15617b8297b7a6775daa6c29aefcc48b1eb29f`. Keep `upstream` pointed at `horilla/horilla-hr` and `origin` at `eQOURSE/eqourse-hrms`. Keep fork-specific changes small so future upstream updates can be reviewed separately.

## File ownership

| Owner | Exclusive paths and responsibilities |
| --- | --- |
| Bhavesh (`bhau23`) | `Dockerfile`, `docker-compose*.yml`, `docker/`, `deploy/`, `.env.dist`, `horilla/settings/`, `requirements.txt`, `.github/`, `horilla_auth/`, `horilla_audit/`, `horilla_backup/`, `horilla/client_ip.py`, `base/auth_backends.py`, and `horilla_api/authentication.py` and API authentication modules. Infrastructure, authentication, authorization, mail, backup, and audit. |
| Kartik | `attendance/`, `facedetection/`, `geofencing/`, `leave/`, `pms/`, `horilla_api/api_{urls,views}/attendance/`, `horilla_api/api_{urls,views}/mobile/`, `horilla_theme/`, `templates/login.html`, new `templates/eqourse/` and `static/eqourse/` assets. Punches, attendance policy, leave, and branding. |

Each owner also owns tests and migrations in their paths. Ask the applicable owner to make changes in their paths, including dependency changes for face capture. Changes to shared entry points such as `horilla/urls.py`, `base/urls.py`, `templates/navbar.html`, `horilla_api/__init__.py`, and this file require both developers to agree on one editor and one integration PR. Treat every other file as shared. Add small app-owned hooks to shared files and keep policy inside the owning app.

## Branches and review

- `main` is the production release branch. Promote a tested `develop` commit through a release PR after both developers sign off. Tag the approved deployment commit.
- `develop` integrates both tracks. Each developer pushes only to their track branch and opens PRs into `develop`. The other developer reviews the diff and must approve before merge. Request a fresh review after material changes. Require CI and resolved conversations. Apply matching GitHub branch protection before feature merges once Kartik has write access and can review.
- Each PR includes scope, verification, migration or configuration impact and rollback notes. Split cross-track prerequisites into an owner-authored PR before the dependent change. Merge `origin/develop` into your own branch after integration changes land. Keep production secrets, employee records, face frames, and GPS samples out of Git and PR evidence.

## Local setup for either track

On Windows use PowerShell and Docker Desktop in Linux-container mode. Clone into a separate checkout per developer. In an existing checkout, start at `git fetch origin`.

```powershell
git clone https://github.com/eQOURSE/eqourse-hrms.git
Set-Location eqourse-hrms
git fetch origin
Copy-Item .env.dist .env
docker compose up --build -d --wait
docker compose exec web python manage.py check
docker compose exec web python manage.py createsuperuser
```

Use `http://localhost:8000` with local demo users. The dev Compose service explicitly sets its Django, database, and Redis defaults, which take precedence over values in your local `.env`. Set a personal signing key and DB-init password when using `.env` for a direct Django run and use local databases and mail. Keep `.env` ignored. Use a separate throwaway environment for HTTPS tests on a mobile device. The production overlay and production values belong only on the deployment host.

## Track A commands and PR checklist

```powershell
git fetch origin
git switch feat/bhavesh-infra-auth-rbac
git merge origin/develop
docker compose exec web python manage.py test horilla_auth horilla_audit horilla_backup
git push -u origin feat/bhavesh-infra-auth-rbac
gh pr create --base develop --head feat/bhavesh-infra-auth-rbac --title "Configure production hosting and access controls"
```

- Verify Compose, Nginx host/TLS routing, sanitized client IP, one `run_scheduler`, health endpoints, restore, and certificate renewal. Test peak start-of-shift load and record memory, CPU credits, and punch latency.
- The pinned checkout does not expose the requested OIDC settings screen. Add a maintained OIDC client integration with an Internal Google OAuth app. Validate signature, issuer, audience, expiry, nonce, state, and verified `hd=eqourse.com`. Bind Google `sub` to a pre-approved active employee and reject domain lookalikes and disabled users. Keep a tested local Superadmin recovery login under 2FA and lockout.
- Use an idempotent Django role seed or document exact curated grants. Use Django superuser for Superadmin, HR for approved company HR operations, Finance for payroll only, Manager for assigned reports and delegated approvals, and Employee for self-service. Validate scope in views and APIs as well as navigation. Test cross-company, out-of-team, and out-of-role denials. Check Axes, protected 2FA enroll/recovery, audit events for role changes, sign-ins and attendance overrides, and audit visibility/retention.
- Test a dedicated Workspace sender over `smtp.gmail.com:587` with STARTTLS and an App Password if enabled by Workspace policy. Check leave, 2FA and attendance messages. Configure S3 and restricted Shared Drive `horilla_backup` delivery and prove isolated restore. Schedule one Drive upload path to avoid duplicates.

## Track B commands and PR checklist

```powershell
git fetch origin
git switch feat/kartik-attendance-face-geo
git merge origin/develop
docker compose exec web python manage.py showmigrations facedetection geofencing
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test attendance facedetection geofencing horilla_api leave pms
git push -u origin feat/kartik-attendance-face-geo
gh pr create --base develop --head feat/kartik-attendance-face-geo --title "Require verified attendance punches and apply eQOURSE branding"
```

- `horilla_api/__init__.py` already registers both add-ons. Verify clean and upgrade migrations. The pinned web views and API clock views already apply GPS when a fence is enabled. The API punch views do not independently require a face frame. Review face enrollment, image access, and permission wiring before enabling the feature.
- Use one shared server-side verification service before any employee self-punch writes. Reuse company fence resolution and existing attendance mutation rules. The browser captures a camera frame via `getUserMedia` and fresh coordinates and accuracy via `navigator.geolocation`. POST to a same-origin API route authenticated by session with CSRF protection. The native mobile client submits the same evidence using its existing authentication. Coordinate its release before requiring evidence on its existing API. Do not put an API token in browser storage.
- Require an active employee, effective company fence, present and usable coordinates and accuracy, and one detected face before calling the mutation. Make radius configurable per office from 100–200 m and define how measurement accuracy affects edge decisions. Fail closed on missing evidence and errors. Use compact bounded uploads and avoid retaining raw frames or coordinates beyond approved needs. If the policy requires identity or liveness, implement and validate those separately. Face presence and client-reported location alone cannot assure identity, liveness or device integrity.
- Route all legacy clock-in and clock-out entry points through the same check or disable them on the server. Keep privileged, audited corrections distinct. Test normal browser and device workflows, denied permissions, missing face/fence, inaccurate and outside coordinates, duplicate submits, and approval-scoped manual corrections.
- Configure local time, shifts, late and early grace periods, and leave approval routing with HR. Verify On-Break clock transitions and reporting, overnight shifts, delegated managers, and rejection/approval. Apply eQOURSE branding using small template/asset overrides, and verify the existing `pms/` app has clean migrations and a working menu/permission smoke test without changing Phase 2 behavior.

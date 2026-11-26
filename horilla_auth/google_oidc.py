"""Google Workspace sign-in for pre-approved Horilla accounts."""

import base64
import hashlib
import logging
import secrets
import time
from functools import partial
from pathlib import Path
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token

from .models import GoogleIdentity

logger = logging.getLogger(__name__)
SESSION_KEY = "google_oidc_attempt"
MAX_AGE_SECONDS = 600
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def enabled():
    return bool(
        settings.GOOGLE_OIDC_CLIENT_ID
        and settings.GOOGLE_OIDC_SECRET_FILE
        and settings.GOOGLE_OIDC_REDIRECT_URI
    )


def _private_response(response):
    response["Referrer-Policy"] = "no-referrer"
    return response


def _matches(expected, supplied):
    return isinstance(supplied, str) and secrets.compare_digest(
        expected.encode(), supplied.encode()
    )


@require_POST
@never_cache
def start(request):
    if not enabled():
        raise Http404
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    request.session[SESSION_KEY] = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "created": int(time.time()),
    }
    from attendance import phone_handoff

    handoff = request.POST.get("attendance_handoff")
    if phone_handoff.owner(handoff) is not None:
        request.session[SESSION_KEY]["attendance_handoff"] = handoff
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    params = {
        "client_id": settings.GOOGLE_OIDC_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OIDC_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "hd": settings.GOOGLE_OIDC_HOSTED_DOMAIN,
        "prompt": "select_account",
    }
    return _private_response(redirect(f"{AUTHORIZATION_URL}?{urlencode(params)}"))


def _verified_claims(code, verifier):
    client_secret = Path(settings.GOOGLE_OIDC_SECRET_FILE).read_text(
        encoding="utf-8"
    ).strip()
    if not client_secret:
        raise ValueError("Google OAuth credentials are unavailable")
    with requests.Session() as http:
        response = http.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_OIDC_CLIENT_ID,
                "client_secret": client_secret,
                "redirect_uri": settings.GOOGLE_OIDC_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
            timeout=8,
            allow_redirects=False,
        )
        response.raise_for_status()
        return verify_workspace_id_token(response.json()["id_token"], http)


def verify_workspace_id_token(token, http=None):
    """Verify an ID token issued to the eQOURSE Web OAuth client."""
    if http is None:
        with requests.Session() as session:
            return verify_workspace_id_token(token, session)
    return verify_oauth2_token(
        token,
        partial(Request(session=http), timeout=8),
        audience=settings.GOOGLE_OIDC_CLIENT_ID,
    )


def workspace_identity(claims):
    """Return the verified Workspace email and immutable Google subject."""
    domain = settings.GOOGLE_OIDC_HOSTED_DOMAIN
    email = claims.get("email")
    subject = claims.get("sub")
    if (
        claims.get("email_verified") is not True
        or claims.get("hd") != domain
        or not isinstance(email, str)
        or email.lower().rpartition("@")[2] != domain
        or not isinstance(subject, str)
        or not 0 < len(subject) <= 255
    ):
        return None
    return email.lower(), subject


def _approved_user(email, subject):
    with transaction.atomic():
        identity = (
            GoogleIdentity.objects.select_for_update()
            .filter(email=email)
            .first()
        )
        if not identity or identity.subject not in (None, subject):
            return None
        user = identity.user
        employee = getattr(user, "employee_get", None)
        if (
            user.is_superuser
            or not user.is_active
            or not employee
            or not employee.is_active
            or employee.email.lower() != email
        ):
            return None
        if identity.subject is None:
            identity.subject = subject
            identity.save(update_fields=["subject"])
        return user


def approved_workspace_user(identity):
    """Look up approval and bind the Google subject on first sign-in."""
    try:
        return _approved_user(*identity)
    except IntegrityError:
        return None


@require_GET
@never_cache
def callback(request):
    if not enabled():
        raise Http404
    attempt = request.session.pop(SESSION_KEY, None)
    code = request.GET.get("code", "")
    if (
        not attempt
        or not _matches(attempt["state"], request.GET.get("state"))
        or not 0 <= time.time() - attempt["created"] < MAX_AGE_SECONDS
        or not code
        or len(code) > 4096
    ):
        return _private_response(HttpResponseBadRequest(
            _("Google sign-in expired or was interrupted. Return to sign-in and try again.")
        ))

    try:
        claims = _verified_claims(code, attempt["verifier"])
    except (GoogleAuthError, requests.RequestException, OSError, ValueError, KeyError, TypeError):
        logger.info("Google token exchange or verification failed")
        messages.error(request, _("Google sign-in could not be verified. Please try again."))
        return _private_response(redirect("login"))

    identity = workspace_identity(claims)
    if not _matches(attempt["nonce"], claims.get("nonce")) or identity is None:
        logger.info("Google sign-in did not meet the Workspace account requirements")
        messages.error(request, _("Use your verified eQOURSE Google account to sign in."))
        return _private_response(redirect("login"))

    user = approved_workspace_user(identity)
    if user is None:
        logger.info("Google Workspace identity verified without an approved Horilla account")
        messages.warning(
            request,
            _("Google account verified. Your eQOURSE Work access has not been enabled. Contact HR."),
        )
        return _private_response(redirect("login"))

    login(request, user, backend="base.auth_backends.CompanyScopedBackend")
    logger.info("Google Workspace sign-in completed for Horilla user %s", user.pk)
    if attempt.get("attendance_handoff"):
        return _private_response(redirect(
            reverse("attendance-phone-check-in") + "#" + attempt["attendance_handoff"]
        ))
    return _private_response(redirect("home-page"))

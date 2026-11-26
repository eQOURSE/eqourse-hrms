"""Short-lived, account-bound QR links for web attendance."""

import re
import secrets

from django.core.cache import cache


TTL_SECONDS = 300
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32}")


def valid_token(value):
    return isinstance(value, str) and TOKEN_PATTERN.fullmatch(value) is not None


def issue(user_id):
    token = secrets.token_urlsafe(24)
    cache.set(f"attendance:phone-check-in:{token}", user_id, TTL_SECONDS)
    return token


def owner(token):
    if valid_token(token):
        return cache.get(f"attendance:phone-check-in:{token}")
    return None


def consume(token):
    cache.delete(f"attendance:phone-check-in:{token}")

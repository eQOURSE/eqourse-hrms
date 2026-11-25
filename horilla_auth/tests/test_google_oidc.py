from time import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from horilla_auth import google_oidc


@override_settings(
    GOOGLE_OIDC_CLIENT_ID="test-client",
    GOOGLE_OIDC_SECRET_FILE="/unused-in-tests",
    GOOGLE_OIDC_REDIRECT_URI="https://work.eqourse.com/auth/google/callback/",
)
class GoogleOIDCTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.claims = {
            "hd": "eqourse.com",
            "email": "staff@eqourse.com",
            "email_verified": True,
            "sub": "google-subject",
            "nonce": "login-nonce",
        }

    def callback(self, state="login-state"):
        request = self.factory.get(reverse("google-oidc-callback"), {
            "code": "sample-code",
            "state": state,
        })
        request.session = {
            google_oidc.SESSION_KEY: {
                "state": "login-state",
                "nonce": "login-nonce",
                "verifier": "login-verifier",
                "created": int(time()),
            }
        }
        request._messages = FallbackStorage(request)
        return request

    def test_start_uses_exact_callback_and_pkce(self):
        request = self.factory.post(reverse("google-oidc-start"))
        request.session = {}
        response = google_oidc.start(request)
        location = urlsplit(response["Location"])
        params = parse_qs(location.query)
        self.assertEqual(location.netloc, "accounts.google.com")
        self.assertEqual(params["redirect_uri"], [google_oidc.settings.GOOGLE_OIDC_REDIRECT_URI])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["state"], [request.session[google_oidc.SESSION_KEY]["state"]])

    @patch("horilla_auth.google_oidc._verified_claims")
    def test_fails_before_token_exchange_when_state_does_not_match(self, verify):
        request = self.callback("wrong-state")
        self.assertEqual(google_oidc.callback(request).status_code, 400)
        self.assertNotIn(google_oidc.SESSION_KEY, request.session)
        verify.assert_not_called()

    @patch("horilla_auth.google_oidc._approved_user")
    @patch("horilla_auth.google_oidc._verified_claims")
    def test_wrong_hosted_domain_never_consults_local_approval(self, verify, approved):
        verify.return_value = {**self.claims, "hd": "example.com"}
        response = google_oidc.callback(self.callback())
        self.assertEqual(response["Location"], reverse("login"))
        approved.assert_not_called()

    @patch("horilla_auth.google_oidc.login")
    @patch("horilla_auth.google_oidc._approved_user", return_value=None)
    @patch("horilla_auth.google_oidc._verified_claims")
    def test_verified_google_account_without_local_approval_cannot_log_in(
        self, verify, approved, login
    ):
        verify.return_value = self.claims
        response = google_oidc.callback(self.callback())
        self.assertEqual(response["Location"], reverse("login"))
        approved.assert_called_once_with("staff@eqourse.com", "google-subject")
        login.assert_not_called()

    @patch("horilla_auth.google_oidc.login")
    @patch("horilla_auth.google_oidc._approved_user")
    @patch("horilla_auth.google_oidc._verified_claims")
    def test_approved_google_identity_uses_the_existing_horilla_account(
        self, verify, approved, login
    ):
        verify.return_value = self.claims
        approved.return_value = Mock(pk=1)
        request = self.callback()
        response = google_oidc.callback(request)
        self.assertEqual(response["Location"], reverse("home-page"))
        login.assert_called_once_with(
            request, approved.return_value, backend="base.auth_backends.CompanyScopedBackend"
        )

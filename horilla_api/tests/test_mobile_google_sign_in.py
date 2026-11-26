from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla_auth.models import GoogleIdentity

LOGIN_URL = "/api/v1/auth/google/"


@override_settings(GOOGLE_OIDC_CLIENT_ID="web-oauth-client", GOOGLE_OIDC_HOSTED_DOMAIN="eqourse.com")
class MobileGoogleSignInTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.email = "mobile-pilot@eqourse.com"
        self.user = make_user("mobile-pilot", email=self.email)
        self.company = make_company("Mobile pilot")
        self.employee = make_employee(company=self.company, user=self.user, email=self.email)
        self.claims = {
            "email": self.email,
            "email_verified": True,
            "hd": "eqourse.com",
            "sub": "pilot-google-subject",
        }
        verifier = patch("horilla_auth.google_oidc.verify_oauth2_token")
        self.verify = verifier.start()
        self.addCleanup(verifier.stop)
        self.verify.return_value = self.claims

    def login(self):
        return self.client.post(LOGIN_URL, {"id_token": "pilot-token"}, format="json")

    def approve(self, subject=None):
        return GoogleIdentity.objects.create(user=self.user, email=self.email, subject=subject)

    def test_approved_employee_receives_a_mobile_session(self):
        identity = self.approve()
        response = self.login()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employee"]["id"], self.employee.pk)
        self.assertEqual(response.data["company_id"], self.company.pk)
        self.assertEqual(str(AccessToken(response.data["access"])["user_id"]), str(self.user.pk))
        self.assertTrue(response.data["refresh"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.verify.call_args.kwargs["audience"], "web-oauth-client")
        identity.refresh_from_db()
        self.assertEqual(identity.subject, self.claims["sub"])

    def test_employee_without_google_approval_is_denied(self):
        self.assertEqual(self.login().status_code, 403)
        self.assertFalse(GoogleIdentity.objects.filter(user=self.user).exists())

    def test_inactive_employee_is_denied_even_with_approval(self):
        self.approve()
        type(self.employee)._base_manager.filter(pk=self.employee.pk).update(is_active=False)
        self.assertEqual(self.login().status_code, 403)

    def test_inactive_user_is_denied_even_with_approval(self):
        self.approve()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.login().status_code, 403)

    def test_superadmin_is_denied_even_with_approval(self):
        self.approve()
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertEqual(self.login().status_code, 403)

    def test_subject_must_match_previously_bound_identity(self):
        identity = self.approve(subject="original-subject")
        self.assertEqual(self.login().status_code, 403)
        identity.refresh_from_db()
        self.assertEqual(identity.subject, "original-subject")

    def test_workspace_membership_and_verified_email_are_required(self):
        self.approve()
        for change in ({"hd": None}, {"email_verified": False}, {"sub": ""}, {"email": "pilot@example.com"}):
            with self.subTest(change=change):
                self.verify.return_value = {**self.claims, **change}
                self.assertEqual(self.login().status_code, 403)

    def test_bad_token_and_bad_request_do_not_mint_a_session(self):
        self.approve()
        self.verify.side_effect = ValueError("invalid token or wrong audience")
        self.assertEqual(self.login().status_code, 401)
        self.verify.reset_mock()
        response = self.client.post(LOGIN_URL, {"id_token": ["wrong type"]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.verify.assert_not_called()

    @override_settings(GOOGLE_OIDC_CLIENT_ID="")
    def test_disabled_without_client_configuration(self):
        self.assertEqual(self.login().status_code, 503)
        self.verify.assert_not_called()

import json
from unittest.mock import patch
from urllib.parse import urlsplit

from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from attendance import laptop_punch, phone_handoff
from attendance.models import AttendanceGeneralSetting
from attendance.views import phone_check_in
from horilla.testkit import make_company, make_employee, make_user


class PhoneCheckInTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.company = make_company("QR office")
        self.user = make_user("qr-user")
        make_employee(company=self.company, user=self.user, email="qr-user@test.horilla")
        AttendanceGeneralSetting._base_manager.update_or_create(
            company_id=self.company, defaults={"enable_check_in": True}
        )
        self.token = phone_handoff.issue(self.user.pk)
        self.addCleanup(phone_handoff.consume, self.token)

    def request(self, route, user=None, token=None):
        request = self.factory.post(
            reverse(route), {"handoff": token or self.token},
            HTTP_HX_REQUEST="true", HTTP_X_PUNCH_CLIENT="1",
        )
        request.user = user or self.user
        request.session = {"selected_company": str(self.company.pk)}
        return request

    def test_start_returns_a_same_site_qr_and_does_not_create_attendance(self):
        response = phone_check_in.start(self.request("attendance-phone-check-in-start"))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        url = urlsplit(data["url"])
        self.addCleanup(phone_handoff.consume, url.fragment)
        self.assertEqual(url.path, reverse("attendance-phone-check-in"))
        self.assertEqual(phone_handoff.owner(url.fragment), self.user.pk)
        self.assertTrue(data["image"].startswith("data:image/svg+xml;base64,"))
        self.assertFalse(phone_check_in._already_in(self.user.employee_get.pk))

    def test_expired_or_wrong_account_cannot_verify(self):
        self.assertEqual(phone_check_in.verify(
            self.request("attendance-phone-check-in-verify", token="A" * 32)
        ).status_code, 403)
        other = make_user("other-qr-user")
        make_employee(company=self.company, user=other, email="other-qr-user@test.horilla")
        self.assertEqual(phone_check_in.verify(
            self.request("attendance-phone-check-in-verify", user=other)
        ).status_code, 403)

    def test_missing_gps_is_rejected_by_normal_punch_validation(self):
        response = phone_check_in.submit(self.request("attendance-phone-check-in-submit"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Location evidence is required", json.loads(response.content)["error"])
        self.assertEqual(phone_handoff.owner(self.token), self.user.pk)

    @patch("attendance.views.phone_check_in.clock_in", return_value=JsonResponse({}))
    @patch("attendance.views.phone_check_in._already_in", side_effect=(False, True))
    def test_a_successful_punch_consumes_the_code(self, _online, punch):
        request = self.request("attendance-phone-check-in-submit")
        self.assertEqual(phone_check_in.submit(request).status_code, 200)
        self.assertEqual(phone_check_in.submit(request).status_code, 403)
        punch.assert_called_once_with(request)

    @override_settings(ATTENDANCE_LAPTOP_OFFICE_IP="203.0.113.7")
    @patch("attendance.views.phone_check_in.render_to_string", return_value="updated controls")
    @patch("attendance.views.phone_check_in._session_key", return_value="issuer-session")
    def test_only_the_issuing_office_laptop_session_gets_approved(self, session, _render):
        token = phone_handoff.issue(self.user.pk, issuer="issuer-session")
        self.addCleanup(phone_handoff.consume, token)
        request = self.factory.post(
            reverse("attendance-phone-check-in-status"), {"handoff": token},
            REMOTE_ADDR="203.0.113.7",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        )
        request.user, request.session = self.user, {}
        self.assertEqual(json.loads(phone_check_in.status(request).content), {"saved": False})
        entry = phone_handoff.pending(token)
        phone_handoff.consume(token)
        phone_handoff.finish(token, entry)
        session.return_value = "another-session"
        self.assertEqual(phone_check_in.status(request).status_code, 403)
        session.return_value = "issuer-session"
        self.assertEqual(json.loads(phone_check_in.status(request).content), {
            "saved": True, "controls": "updated controls",
        })
        self.assertTrue(laptop_punch.approved(request, self.user.employee_get))
        request.META["REMOTE_ADDR"] = "203.0.113.8"
        self.assertFalse(laptop_punch.approved(request, self.user.employee_get))
        request.META["REMOTE_ADDR"] = "203.0.113.7"
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0 (Linux; Android 16) Mobile"
        del request.headers
        self.assertFalse(laptop_punch.approved(request, self.user.employee_get))

    @patch("attendance.views.clock_in_out.validate_punch_evidence")
    def test_qr_submission_cannot_select_the_laptop_limit(self, validate):
        from attendance.views.clock_in_out import _validate_web_punch

        request = self.factory.post("/", {"punch_method": "laptop"})
        request.phone_attendance_handoff = True
        _validate_web_punch(request, self.user.employee_get, "check-in")
        validate.assert_called_once_with(request, self.user.employee_get, "check-in")

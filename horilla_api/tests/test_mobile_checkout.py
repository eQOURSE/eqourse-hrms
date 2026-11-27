from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from attendance.models import Attendance, AttendanceActivity, AttendanceGeneralSetting
from attendance.punch_security import PunchEvidenceError
from base.models import AttendanceAllowedIP, EmployeeShiftDay
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

CHECKOUT = "/api/v1/attendance/clock-out/"
HOME = "/api/v1/mobile/home/"


class MobileCheckoutTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Checkout office")
        user = make_user("checkout-user")
        self.employee = make_employee(
            company=self.company, user=user, email="checkout@test.horilla"
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
        )
        self.policy, _ = AttendanceGeneralSetting._base_manager.update_or_create(
            company_id=self.company, defaults={"enable_check_in": True}
        )
        today = timezone.localdate()
        self.checked_out_at = timezone.make_aware(datetime.combine(today, datetime.min.time())).replace(
            hour=10, minute=1, second=14
        )
        checked_in_at = self.checked_out_at - timedelta(minutes=8)
        shift_day, _ = EmployeeShiftDay.objects.get_or_create(day=today.strftime("%A").lower())
        self.activity = AttendanceActivity.objects.create(
            employee_id=self.employee,
            attendance_date=today,
            clock_in_date=today,
            clock_in=checked_in_at.time(),
            in_datetime=checked_in_at,
        )
        self.summary = Attendance.objects.create(
            employee_id=self.employee,
            attendance_date=today,
            attendance_clock_in_date=today,
            attendance_clock_in=checked_in_at.time(),
            attendance_day=shift_day,
        )
        self.evidence = {
            "latitude": 25.1440503,
            "longitude": 75.8441003,
            "accuracy": 14.84,
            "captured_at": self.checked_out_at - timedelta(seconds=8),
        }

    @patch("horilla_api.api_views.attendance.views.validate_punch_evidence")
    def test_bearer_checkout_saves_evidence_and_stops_home_timer(self, validate):
        validate.return_value = self.evidence
        self.assertTrue(self.client.get(HOME).data["punch"]["is_clocked_in"])
        with patch("horilla_api.api_views.attendance.views.django_timezone.localtime",
                   return_value=self.checked_out_at):
            response = self.client.post(CHECKOUT, {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.activity.refresh_from_db()
        self.summary.refresh_from_db()
        self.assertEqual(self.activity.out_datetime, self.checked_out_at)
        for record in (self.activity, self.summary):
            self.assertEqual(record.clock_out_latitude, self.evidence["latitude"])
            self.assertEqual(record.clock_out_longitude, self.evidence["longitude"])
            self.assertEqual(record.clock_out_accuracy, self.evidence["accuracy"])
            self.assertEqual(record.clock_out_location_at, self.evidence["captured_at"])
        home = self.client.get(HOME).data["punch"]
        self.assertFalse(home["is_clocked_in"])
        self.assertIsNone(home["last_activity_at"])
        repeated = self.client.post(CHECKOUT, {}, format="json")
        self.assertEqual(repeated.status_code, 400)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.out_datetime, self.checked_out_at)

    @patch("horilla_api.api_views.attendance.views.validate_punch_evidence")
    def test_policy_failure_never_reports_success(self, validate):
        self.policy.enable_check_in = False
        self.policy.save(update_fields=["enable_check_in"])
        self.assertEqual(self.client.post(CHECKOUT, {}, format="json").status_code, 403)
        self.policy.enable_check_in = True
        self.policy.save(update_fields=["enable_check_in"])
        AttendanceAllowedIP._base_manager.update_or_create(
            company_id=self.company,
            defaults={"is_enabled": True, "additional_data": {"allowed_ips": ["203.0.113.1"]}},
        )
        self.assertEqual(self.client.post(CHECKOUT, {}, format="json").status_code, 403)
        validate.assert_not_called()
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.out_datetime)

    @patch("horilla_api.api_views.attendance.views.validate_punch_evidence",
           side_effect=PunchEvidenceError("Face mismatch"))
    def test_face_failure_leaves_the_punch_open(self, _validate):
        response = self.client.post(CHECKOUT, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Face mismatch", response.data["error"])
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.out_datetime)

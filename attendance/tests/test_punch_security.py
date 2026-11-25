from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from attendance.punch_security import PunchEvidenceError, validate_punch_evidence
from facedetection.verification import FaceVerificationError
from horilla.testkit import make_company


class PunchEvidenceTests(TestCase):
    def setUp(self):
        self.company = make_company("Punch Co")
        self.employee = MagicMock()
        self.employee.get_company.return_value = self.company
        self.now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    def request(self, latitude="12.9716", longitude="77.5946"):
        return SimpleNamespace(
            data={
                "latitude": latitude,
                "longitude": longitude,
                "location_timestamp": str(self.now_ms),
                "accuracy": "8",
                "face_image": object(),
            },
            FILES={},
        )

    @patch("geofencing.models.Nominatim")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_office_inside_radius_is_accepted(self, _remote, verify, _nominatim):
        from geofencing.models import GeoFencing

        _nominatim.return_value.reverse.return_value = MagicMock()
        GeoFencing.objects.create(
            company_id=self.company,
            latitude=12.9716,
            longitude=77.5946,
            radius_in_meters=150,
            start=True,
        )
        evidence = validate_punch_evidence(self.request(), self.employee, "check-in")
        self.assertEqual(evidence["latitude"], 12.9716)
        verify.assert_called_once()

    @patch("geofencing.models.Nominatim")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_office_outside_radius_is_rejected(self, _remote, _verify, _nominatim):
        from geofencing.models import GeoFencing

        _nominatim.return_value.reverse.return_value = MagicMock()
        GeoFencing.objects.create(
            company_id=self.company,
            latitude=12.9716,
            longitude=77.5946,
            radius_in_meters=150,
            start=True,
        )
        with self.assertRaisesRegex(PunchEvidenceError, "approved office radius"):
            validate_punch_evidence(
                self.request("13.0827", "80.2707"), self.employee, "check-in"
            )

    @patch("geofencing.models.Nominatim")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=True)
    def test_authorised_wfh_can_punch_outside_radius(self, _remote, _verify, _nominatim):
        from geofencing.models import GeoFencing

        _nominatim.return_value.reverse.return_value = MagicMock()
        GeoFencing.objects.create(
            company_id=self.company,
            latitude=12.9716,
            longitude=77.5946,
            radius_in_meters=150,
            start=True,
        )
        evidence = validate_punch_evidence(
            self.request("13.0827", "80.2707"), self.employee, "check-out"
        )
        self.assertTrue(evidence["remote_authorized"])

    @patch("attendance.punch_security.verify_employee_face")
    def test_missing_location_is_rejected_before_attendance_changes(self, _verify):
        request = self.request()
        request.data.pop("location_timestamp")
        with self.assertRaisesRegex(PunchEvidenceError, "fresh GPS"):
            validate_punch_evidence(request, self.employee, "check-in")

    @patch("attendance.punch_security.is_remote_workday", return_value=True)
    @patch(
        "attendance.punch_security.verify_employee_face",
        side_effect=FaceVerificationError("Face mismatch. Please try again."),
    )
    def test_face_mismatch_is_rejected(self, _verify, _remote):
        with self.assertRaisesRegex(PunchEvidenceError, "Face mismatch"):
            validate_punch_evidence(self.request(), self.employee, "check-in")

    @patch("attendance.punch_security.is_remote_workday", return_value=True)
    @patch(
        "attendance.punch_security.verify_employee_face",
        side_effect=FaceVerificationError("A face photo is required for this punch."),
    )
    def test_missing_face_evidence_is_rejected(self, _verify, _remote):
        request = self.request()
        request.data["face_image"] = None
        with self.assertRaisesRegex(PunchEvidenceError, "face photo is required"):
            validate_punch_evidence(request, self.employee, "check-out")

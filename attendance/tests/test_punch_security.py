from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from attendance.punch_security import PunchEvidenceError, validate_punch_evidence
from facedetection.verification import FaceVerificationError
from horilla.testkit import make_company


@override_settings(GOOGLE_MAPS_API_KEY="")
class PunchEvidenceTests(TestCase):
    def setUp(self):
        from geofencing.models import GeoFencing

        self.company = make_company("Punch Co")
        self.employee = MagicMock()
        self.employee.get_company.return_value = self.company
        self.now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with patch("geofencing.models.Nominatim") as nominatim:
            nominatim.return_value.reverse.return_value = MagicMock()
            self.fence = GeoFencing.objects.create(
                company_id=self.company,
                latitude=25.14402,
                longitude=75.84506,
                radius_in_meters=50,
                start=True,
            )

    def request(self, latitude="25.14402", longitude="75.84506", accuracy="8"):
        return SimpleNamespace(
            data={
                "latitude": latitude,
                "longitude": longitude,
                "location_timestamp": str(self.now_ms),
                "accuracy": accuracy,
                "face_image": object(),
            },
            FILES={},
        )

    @patch("geofencing.models.Nominatim")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_office_inside_radius_is_accepted(self, _remote, verify, _nominatim):
        evidence = validate_punch_evidence(self.request(), self.employee, "check-in")
        self.assertEqual(evidence["latitude"], 25.14402)
        verify.assert_called_once()

    @patch("geofencing.models.Nominatim")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_office_outside_radius_is_rejected(self, _remote, _verify, _nominatim):
        with self.assertRaisesRegex(PunchEvidenceError, "outside the approved"):
            validate_punch_evidence(
                self.request("25.14492", "75.84506"), self.employee, "check-in"
            )

    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_office_check_out_inside_radius_is_accepted(self, _remote, verify):
        evidence = validate_punch_evidence(self.request(), self.employee, "check-out")
        self.assertEqual(evidence["action"], "check-out")
        verify.assert_called_once()

    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_office_check_out_outside_radius_is_rejected(self, _remote, _verify):
        with self.assertRaisesRegex(PunchEvidenceError, "outside the approved"):
            validate_punch_evidence(
                self.request("25.14492", "75.84506"), self.employee, "check-out"
            )

    @patch("attendance.punch_security.geodesic")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_check_in_uses_distance_plus_accuracy_boundary(
        self, _remote, verify, distance
    ):
        distance.return_value.meters = 40
        for accuracy in ("9", "10"):
            with self.subTest(accuracy=accuracy):
                evidence = validate_punch_evidence(
                    self.request(accuracy=accuracy), self.employee, "check-in"
                )
                self.assertEqual(evidence["distance_meters"], 40)
        self.assertEqual(verify.call_count, 2)

    @patch("attendance.punch_security.geodesic")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_check_out_uses_distance_plus_accuracy_boundary(
        self, _remote, verify, distance
    ):
        distance.return_value.meters = 40
        for accuracy in ("9", "10"):
            with self.subTest(accuracy=accuracy):
                evidence = validate_punch_evidence(
                    self.request(accuracy=accuracy), self.employee, "check-out"
                )
                self.assertEqual(evidence["distance_meters"], 40)
        self.assertEqual(verify.call_count, 2)

    @patch("attendance.punch_security.geodesic")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_check_in_rejects_distance_plus_accuracy_over_50m(
        self, _remote, verify, distance
    ):
        distance.return_value.meters = 49
        with self.assertRaisesRegex(PunchEvidenceError, "GPS uncertainty") as failure:
            validate_punch_evidence(
                self.request(accuracy="25"), self.employee, "check-in"
            )
        self.assertEqual(failure.exception.location, {
            "distance_meters": 49, "accuracy_meters": 25, "radius_meters": 50,
        })
        verify.assert_called_once()

    @patch("attendance.punch_security.geodesic")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_check_out_rejects_distance_plus_accuracy_over_50m(
        self, _remote, verify, distance
    ):
        distance.return_value.meters = 49
        with self.assertRaisesRegex(PunchEvidenceError, "GPS uncertainty") as failure:
            validate_punch_evidence(
                self.request(accuracy="25"), self.employee, "check-out"
            )
        self.assertEqual(failure.exception.location, {
            "distance_meters": 49, "accuracy_meters": 25, "radius_meters": 50,
        })
        verify.assert_called_once()

    @patch("attendance.punch_security.verify_employee_face")
    @override_settings(OFFICE_GEOFENCE_RADIUS_METERS=100)
    @patch("attendance.punch_security.geodesic")
    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_configured_radius_applies_to_both_punches(self, _remote, _verify, distance):
        distance.return_value.meters = 90
        for action in ("check-in", "check-out"):
            with self.subTest(action=action):
                validate_punch_evidence(self.request(accuracy="10"), self.employee, action)
                with self.assertRaisesRegex(PunchEvidenceError, "100-metre") as failure:
                    validate_punch_evidence(self.request(accuracy="11"), self.employee, action)
                self.assertEqual(failure.exception.location["radius_meters"], 100)

    @patch("attendance.punch_security.is_remote_workday", return_value=True)
    def test_authorised_wfh_can_punch_outside_radius(self, _remote, _verify):
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

    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_missing_office_fence_blocks_onsite_punches(self, _remote, _verify):
        self.fence.delete()
        with self.assertRaisesRegex(PunchEvidenceError, "missing or disabled"):
            validate_punch_evidence(self.request(), self.employee, "check-in")

    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_disabled_office_fence_blocks_onsite_punches(self, _remote, _verify):
        self.fence.start = False
        self.fence.save(update_fields=["start"])
        with self.assertRaisesRegex(PunchEvidenceError, "missing or disabled"):
            validate_punch_evidence(self.request(), self.employee, "check-out")

    @patch("attendance.punch_security.verify_employee_face")
    @patch("attendance.punch_security.is_remote_workday", return_value=False)
    def test_poor_gps_accuracy_is_rejected(self, _remote, verify):
        with self.assertRaisesRegex(PunchEvidenceError, "GPS accuracy") as failure:
            validate_punch_evidence(
                self.request(accuracy="26"), self.employee, "check-in"
            )
        self.assertEqual(failure.exception.location, {
            "accuracy_meters": 26, "accuracy_limit_meters": 25,
        })
        verify.assert_not_called()

    @patch("attendance.punch_security.verify_employee_face")
    def test_non_finite_gps_accuracy_rejected_for_both_punches(self, verify):
        for action in ("check-in", "check-out"):
            for accuracy in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(action=action, accuracy=accuracy):
                    with self.assertRaisesRegex(PunchEvidenceError, "GPS accuracy"):
                        validate_punch_evidence(
                            self.request(accuracy=accuracy), self.employee, action
                        )
        verify.assert_not_called()

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
        side_effect=FaceVerificationError("Face mismatch. Please try again."),
    )
    def test_face_mismatch_is_rejected_on_check_out(self, _verify, _remote):
        with self.assertRaisesRegex(PunchEvidenceError, "Face mismatch"):
            validate_punch_evidence(self.request(), self.employee, "check-out")

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

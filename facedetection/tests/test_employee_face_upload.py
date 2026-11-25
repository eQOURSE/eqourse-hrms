from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from facedetection.verification import FaceVerificationError
from facedetection.models import EmployeeFaceDetection, FaceDetection
from horilla.testkit import make_company, make_employee, make_user


class EmployeeFaceUploadTests(TestCase):
    def setUp(self):
        self.company = make_company("Face Upload Co")
        self.user = make_user("face-upload")
        self.employee = make_employee(
            company=self.company,
            email="face-upload@test.horilla",
            user=self.user,
        )
        FaceDetection.objects.create(company_id=self.company, start=True)
        self.client.force_login(self.user)

    def upload(self, name="approved.jpg"):
        return SimpleUploadedFile(
            name, b"face image bytes", content_type="image/jpeg"
        )

    @patch("facedetection.views.validate_reference_face_image")
    def test_employee_can_register_and_replace_approved_face_photo(self, validate):
        response = self.client.post(
            reverse("register-own-face"), {"image": self.upload()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EmployeeFaceDetection.objects.filter(
                employee_id=self.employee, image__endswith="approved.jpg"
            ).exists()
        )

        response = self.client.post(
            reverse("register-own-face"), {"image": self.upload("replacement.jpg")}
        )
        self.assertEqual(response.status_code, 200)
        reference = EmployeeFaceDetection.objects.get(employee_id=self.employee)
        self.assertTrue(reference.image.name.endswith("replacement.jpg"))
        self.assertEqual(validate.call_count, 2)

    def test_employee_cannot_register_when_face_detection_is_disabled(self):
        FaceDetection.objects.filter(company_id=self.company).update(start=False)
        response = self.client.post(
            reverse("register-own-face"), {"image": self.upload()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            EmployeeFaceDetection.objects.filter(employee_id=self.employee).exists()
        )

    @patch(
        "facedetection.views.validate_reference_face_image",
        side_effect=FaceVerificationError("The approved face photo must contain exactly one clear face."),
    )
    def test_validator_rejects_invalid_uploaded_photo(self, validate):
        response = self.client.post(
            reverse("register-own-face"), {"image": self.upload()}
        )
        self.assertEqual(response.status_code, 200)
        validate.assert_called_once()

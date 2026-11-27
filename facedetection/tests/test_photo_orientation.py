import io
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from PIL import Image

from facedetection import verification


class FacePhotoOrientationTests(SimpleTestCase):
    @staticmethod
    def photo(orientation=1):
        photo = Image.new("RGB", (80, 40), "red")
        photo.paste("blue", (0, 20, 80, 40))
        exif = photo.getexif()
        exif[274] = orientation
        image = io.BytesIO()
        photo.save(image, format="JPEG", exif=exif)
        image.seek(0)
        return image

    def test_android_orientation_is_applied_before_face_detection(self):
        face_model = Mock()
        verification._face_encodings(face_model, self.photo(6).getvalue())
        pixels = face_model.face_encodings.call_args.args[0]
        self.assertEqual(pixels.shape, (80, 40, 3))
        self.assertGreater(int(pixels[40, 5, 2]), int(pixels[40, 5, 0]))
        self.assertGreater(int(pixels[40, 35, 0]), int(pixels[40, 35, 2]))

    def test_upright_images_keep_their_orientation(self):
        face_model = Mock()
        verification._face_encodings(face_model, self.photo().getvalue())
        pixels = face_model.face_encodings.call_args.args[0]
        self.assertEqual(pixels.shape, (40, 80, 3))

    @patch("facedetection.verification.EmployeeFaceDetection")
    def test_counts_are_distinguished_and_multiple_faces_are_rejected(self, model):
        for faces, message in (
            ([], "No face was detected"),
            ([object(), object()], "More than one face was detected"),
        ):
            with self.subTest(message=message):
                reference = model.objects.filter.return_value.first.return_value
                reference.image.open.return_value = self.photo()
                face_model = Mock()
                face_model.face_encodings.side_effect = [[object()], faces]
                with patch.dict("sys.modules", {"face_recognition": face_model}):
                    with self.assertRaisesRegex(verification.FaceVerificationError, message):
                        verification.verify_employee_face(Mock(), self.photo(6))
                face_model.compare_faces.assert_not_called()

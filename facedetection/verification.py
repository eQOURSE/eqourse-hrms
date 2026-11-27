"""Server-side verification of an employee's live attendance image."""

from __future__ import annotations

import io

import numpy as np
from django.conf import settings
from PIL import Image, ImageOps

from .models import EmployeeFaceDetection


class FaceVerificationError(Exception):
    """A user-actionable reason why a punch image cannot be accepted."""


def _face_encodings(face_model, image_bytes):
    with Image.open(io.BytesIO(image_bytes)) as source:
        # Android camera JPEGs can store landscape pixels with a portrait EXIF
        # orientation. The face detector needs the actual upright pixels.
        pixels = np.array(ImageOps.exif_transpose(source).convert("RGB"))
    return face_model.face_encodings(pixels)


def validate_reference_face_image(uploaded_image) -> None:
    """Validate an employee's approved face photo before storing it."""

    if not uploaded_image:
        raise FaceVerificationError(
            "Please choose a face photo to register."
        )
    try:
        import face_recognition

        image_bytes = uploaded_image.read()
        if not image_bytes:
            raise FaceVerificationError(
                "The selected photo is empty. Please choose another photo."
            )
        faces = _face_encodings(face_recognition, image_bytes)
    except FaceVerificationError:
        raise
    except Exception as exc:
        raise FaceVerificationError(
            "The face photo could not be read. Please upload a clear image."
        ) from exc
    finally:
        if hasattr(uploaded_image, "seek"):
            uploaded_image.seek(0)

    if len(faces) != 1:
        raise FaceVerificationError(
            "The approved face photo must contain exactly one clear face."
        )


def verify_employee_face(employee, uploaded_image) -> None:
    """Compare one live face with the employee's approved reference photo.

    The image is decoded and compared on the server.  No client-supplied match
    flag or face embedding is trusted.  A missing reference, missing face, or
    mismatch raises ``FaceVerificationError`` so callers can leave attendance
    unchanged and return the same clear message to web and native clients.
    """

    if not uploaded_image:
        raise FaceVerificationError(
            "Camera evidence is required. Please allow camera access and try again."
        )

    reference = EmployeeFaceDetection.objects.filter(
        employee_id=employee
    ).first()
    if not reference or not reference.image:
        raise FaceVerificationError(
            "No approved face photo is available for your employee profile."
        )

    try:
        import face_recognition
    except ImportError as exc:  # pragma: no cover - exercised in deployment checks
        raise FaceVerificationError(
            "Face verification is temporarily unavailable. Please contact HR."
        ) from exc

    try:
        live_bytes = uploaded_image.read()
        if not live_bytes:
            raise FaceVerificationError(
                "Camera evidence is empty. Please take a new photo and try again."
            )
        with reference.image.open("rb") as reference_file:
            reference_bytes = reference_file.read()
        reference_faces = _face_encodings(face_recognition, reference_bytes)
        live_faces = _face_encodings(face_recognition, live_bytes)
    except FaceVerificationError:
        raise
    except Exception as exc:
        raise FaceVerificationError(
            "The camera image could not be read. Please take a new photo and try again."
        ) from exc

    if len(reference_faces) != 1:
        raise FaceVerificationError(
            "Your approved face photo must contain exactly one clear face."
        )
    if len(live_faces) == 0:
        raise FaceVerificationError(
            "No face was detected. Hold the phone at eye level, face the camera "
            "in even light, and retake the photo."
        )
    if len(live_faces) > 1:
        raise FaceVerificationError(
            "More than one face was detected. Keep only your face in the frame."
        )

    tolerance = float(getattr(settings, "FACE_MATCH_TOLERANCE", 0.48))
    if not face_recognition.compare_faces(
        [reference_faces[0]], live_faces[0], tolerance=tolerance
    )[0]:
        raise FaceVerificationError(
            "Face mismatch. The camera image does not match your approved photo."
        )

"""Shared evidence and policy checks for employee attendance punches."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone as datetime_timezone

from django.conf import settings
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from geopy.distance import geodesic

from facedetection.verification import FaceVerificationError, verify_employee_face
from geofencing.google_maps import reverse_geocode
from geofencing.models import GeoFencing


class PunchEvidenceError(Exception):
    """A user-actionable reason why a punch must be rejected."""

    def __init__(self, message, *, location=None):
        super().__init__(message)
        self.location = location


def _value(request, key):
    data = getattr(request, "data", None)
    if data is not None and key in data:
        return data.get(key)
    for source_name in ("POST", "GET"):
        source = getattr(request, source_name, None)
        if source is not None and key in source:
            return source.get(key)
    return None


def _uploaded_image(request):
    files = getattr(request, "FILES", None)
    if files:
        return files.get("face_image") or files.get("image")
    data = getattr(request, "data", None)
    if data is not None:
        return data.get("face_image") or data.get("image")
    return None


def _parse_captured_at(value):
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
        # Browser Position.timestamp and most native SDKs use milliseconds.
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, tz=datetime_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime_timezone.utc)
        return parsed.astimezone(datetime_timezone.utc)


def _is_remote_label(value):
    label = str(value or "").strip().lower()
    return any(
        marker in label
        for marker in (
            "wfh",
            "work from home",
            "work-from-home",
            "remote",
            "home based",
            "home-based",
        )
    )


def is_remote_workday(employee, day: date) -> bool:
    """Return whether the employee is authorised to punch outside the office."""

    work_info = getattr(employee, "employee_work_info", None)
    if _is_remote_label(getattr(getattr(work_info, "work_type_id", None), "work_type", "")):
        return True
    if _is_remote_label(getattr(work_info, "location", "")):
        return True

    # Work type requests are the existing approval workflow for a dated WFH
    # assignment.  A permanent approved request has no end date.
    from base.models import RotatingWorkTypeAssign, WorkTypeRequest

    requests = WorkTypeRequest.objects.filter(
        employee_id=employee,
        approved=True,
        canceled=False,
        requested_date__lte=day,
    ).filter(Q(requested_till__gte=day) | Q(requested_till__isnull=True))
    if any(_is_remote_label(req.work_type_id.work_type) for req in requests):
        return True

    rotations = RotatingWorkTypeAssign.objects.filter(
        employee_id=employee,
        is_active=True,
        start_date__lte=day,
    ).select_related("current_work_type")
    return any(
        _is_remote_label(getattr(row.current_work_type, "work_type", ""))
        for row in rotations
    )


def validate_punch_evidence(request, employee, action: str):
    """Validate fresh GPS plus server-side face evidence for one punch."""

    try:
        latitude = float(_value(request, "latitude"))
        longitude = float(_value(request, "longitude"))
    except (TypeError, ValueError):
        raise PunchEvidenceError(
            _("Location evidence is required. Please allow location access and try again.")
        )
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise PunchEvidenceError(_("The location evidence is invalid. Please try again."))

    captured_at = _parse_captured_at(
        _value(request, "location_timestamp") or _value(request, "gps_timestamp")
    )
    if captured_at is None:
        raise PunchEvidenceError(
            _("A fresh GPS reading is required for every check-in and check-out.")
        )
    age = abs((datetime.now(datetime_timezone.utc) - captured_at).total_seconds())
    if age > getattr(settings, "PUNCH_LOCATION_MAX_AGE_SECONDS", 120):
        raise PunchEvidenceError(
            _("Your GPS reading is stale. Please refresh your location and try again.")
        )

    try:
        accuracy = float(_value(request, "accuracy")) if _value(request, "accuracy") else None
    except (TypeError, ValueError):
        accuracy = None
    if accuracy is None:
        raise PunchEvidenceError(
            _(
                "GPS accuracy is required to confirm the office location. "
                "Please refresh your location and try again."
            )
        )
    accuracy_limit = getattr(settings, "PUNCH_LOCATION_MAX_ACCURACY_METERS", 25)
    if not math.isfinite(accuracy) or accuracy < 0 or accuracy > accuracy_limit:
        raise PunchEvidenceError(
            _(
                "Your GPS accuracy is too low to confirm your office location. "
                "Please move to an open area, refresh your location, and try again."
            ),
            location=(
                {"accuracy_meters": accuracy, "accuracy_limit_meters": accuracy_limit}
                if math.isfinite(accuracy) and accuracy >= 0
                else None
            ),
        )

    try:
        verify_employee_face(employee, _uploaded_image(request))
    except FaceVerificationError as exc:
        raise PunchEvidenceError(str(exc)) from exc

    remote_authorized = is_remote_workday(employee, timezone.localdate())
    company = employee.get_company()
    fence = GeoFencing.for_company(company) if company else None
    distance = None
    if not remote_authorized and (fence is None or not fence.start):
        raise PunchEvidenceError(
            _(
                "The office geofence is missing or disabled. Onsite attendance is "
                "blocked until HR enables the approved office fence."
            )
        )
    if fence and fence.start:
        office_latitude = getattr(
            settings, "OFFICE_GEOFENCE_LATITUDE", 25.14402
        )
        office_longitude = getattr(
            settings, "OFFICE_GEOFENCE_LONGITUDE", 75.84506
        )
        office_radius = getattr(
            settings, "OFFICE_GEOFENCE_RADIUS_METERS", 50
        )
        distance = geodesic(
            (office_latitude, office_longitude), (latitude, longitude)
        ).meters
        if not remote_authorized and distance + accuracy > office_radius:
            raise PunchEvidenceError(
                _(
                    "Your office location plus GPS uncertainty is outside the approved "
                    "%(radius)s-metre radius. Please refresh your location and try again. "
                    "Remote or approved WFH staff may punch outside it."
                ) % {"radius": office_radius},
                location={
                    "distance_meters": distance,
                    "accuracy_meters": accuracy,
                    "radius_meters": office_radius,
                },
            )

    location = reverse_geocode(latitude, longitude, required=False)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": accuracy,
        "captured_at": captured_at,
        "distance_meters": distance,
        "remote_authorized": remote_authorized,
        "address": (location or {}).get("formatted_address", ""),
        "google_place_id": (location or {}).get("place_id", ""),
        "action": action,
    }

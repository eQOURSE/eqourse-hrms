"""Open the normal web check-in on the employee's phone."""

import base64
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing

from attendance import phone_handoff
from attendance.models import Attendance, AttendanceGeneralSetting
from attendance.views.clock_in_out import clock_in
from employee.models import Employee
from horilla_auth.google_oidc import enabled as google_sign_in_enabled


def _employee(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return None
    employee = getattr(request.user, "employee_get", None)
    return employee if employee and employee.is_active else None


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _unavailable():
    return _error("This check-in link is unavailable. Sign in with the same account or scan a new code.", 403)


def _already_in(employee_id):
    today = timezone.localdate()
    return Attendance._base_manager.filter(
        employee_id_id=employee_id,
        attendance_date__range=(today - timedelta(days=1), today),
        attendance_clock_out_date__isnull=True,
    ).exists()


@require_POST
@never_cache
def start(request):
    employee = _employee(request)
    if employee is None:
        return _unavailable()
    if _already_in(employee.pk):
        return _error("You are already checked in.", 409)
    token = phone_handoff.issue(request.user.pk)
    url = request.build_absolute_uri(reverse("attendance-phone-check-in")) + "#" + token
    drawing = createBarcodeDrawing("QR", value=url, width=256, height=256)
    image = base64.b64encode(renderSVG.drawToString(drawing).encode()).decode()
    return JsonResponse({"url": url, "image": f"data:image/svg+xml;base64,{image}"})


@require_GET
@never_cache
def landing(request):
    response = render(request, "attendance/phone_check_in.html", {
        "google_sign_in_enabled": google_sign_in_enabled(),
    })
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_POST
@never_cache
def verify(request):
    employee = _employee(request)
    if employee is None or phone_handoff.owner(request.POST.get("handoff")) != request.user.pk:
        return _unavailable()
    if _already_in(employee.pk):
        return _error("You are already checked in.", 409)
    return JsonResponse({"ready": True})


@require_POST
@never_cache
def submit(request):
    employee = _employee(request)
    token = request.POST.get("handoff")
    if employee is None or phone_handoff.owner(token) != request.user.pk:
        return _unavailable()
    with transaction.atomic():
        Employee._base_manager.select_for_update().get(pk=employee.pk)
        if phone_handoff.owner(token) != request.user.pk:
            return _unavailable()
        if _already_in(employee.pk):
            return _error("You are already checked in.", 409)
        selected_company = request.session.get("selected_company")
        company = None if selected_company == "all" else employee.get_company()
        if not AttendanceGeneralSetting._base_manager.filter(
            company_id=company, enable_check_in=True
        ).exists():
            return _error("Web check-in is unavailable for your company.", 403)
        response = clock_in(request)
        if response.status_code >= 400:
            return response
        if not _already_in(employee.pk):
            return _error("Check-in could not be recorded. Check your dashboard or try a new code.")
        phone_handoff.consume(token)
    return JsonResponse({"saved": True})

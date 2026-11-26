"""Open the normal web check-in on the employee's phone."""

import base64
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing

from attendance import laptop_punch, phone_handoff
from attendance.models import Attendance, AttendanceGeneralSetting
from attendance.views.clock_in_out import clock_in, clock_out
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


def _state_error(employee_id, action):
    checked_in = _already_in(employee_id)
    if action == "check-in" and checked_in:
        return _error("You are already checked in.", 409)
    if action == "check-out" and not checked_in:
        return _error("You are already checked out.", 409)
    return None


def _session_key(request):
    return getattr(request.session, "session_key", None)


@require_POST
@never_cache
def start(request):
    employee = _employee(request)
    if employee is None:
        return _unavailable()
    action = request.POST.get("action", "check-in")
    if action not in ("check-in", "check-out"):
        return _error("Unknown attendance action.")
    error = _state_error(employee.pk, action)
    if error is not None:
        return error
    token = phone_handoff.issue(request.user.pk, action, _session_key(request))
    url = request.build_absolute_uri(reverse("attendance-phone-check-in")) + "#" + token
    drawing = createBarcodeDrawing("QR", value=url, width=256, height=256)
    image = base64.b64encode(renderSVG.drawToString(drawing).encode()).decode()
    return JsonResponse({"url": url, "token": token, "image": f"data:image/svg+xml;base64,{image}"})


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
    entry = phone_handoff.pending(request.POST.get("handoff"))
    if employee is None or not entry or entry[0] != request.user.pk:
        return _unavailable()
    error = _state_error(employee.pk, entry[1])
    if error is not None:
        return error
    return JsonResponse({"ready": True, "action": entry[1]})


@require_POST
@never_cache
def status(request):
    employee = _employee(request)
    if employee is None or not _session_key(request):
        return _unavailable()
    token = request.POST.get("handoff")
    done = phone_handoff.completed(token)
    entry = done or phone_handoff.pending(token)
    if not entry or entry[0] != request.user.pk or entry[2] != _session_key(request):
        return _unavailable()
    if not done:
        return JsonResponse({"saved": False})
    if laptop_punch.office_browser(request):
        request.session[laptop_punch.SESSION_KEY] = employee.pk
    controls = render_to_string("attendance/components/in_out_component.html", request=request)
    return JsonResponse({"saved": True, "controls": controls})


@require_POST
@never_cache
def submit(request):
    employee = _employee(request)
    token = request.POST.get("handoff")
    if employee is None:
        return _unavailable()
    with transaction.atomic():
        Employee._base_manager.select_for_update().get(pk=employee.pk)
        entry = phone_handoff.pending(token)
        if not entry or entry[0] != request.user.pk:
            return _unavailable()
        action = entry[1]
        error = _state_error(employee.pk, action)
        if error is not None:
            return error
        selected_company = request.session.get("selected_company")
        company = None if selected_company == "all" else employee.get_company()
        if not AttendanceGeneralSetting._base_manager.filter(
            company_id=company, enable_check_in=True
        ).exists():
            return _error("Web check-in is unavailable for your company.", 403)
        request.phone_attendance_handoff = True
        response = (clock_in if action == "check-in" else clock_out)(request)
        if response.status_code >= 400:
            return response
        if _already_in(employee.pk) != (action == "check-in"):
            return _error("Attendance could not be recorded. Check your dashboard or try a new code.")
        phone_handoff.consume(token)
    phone_handoff.finish(token, entry)
    return JsonResponse({"saved": True, "action": action})

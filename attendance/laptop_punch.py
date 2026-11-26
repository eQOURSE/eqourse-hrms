"""Restrict coarse browser GPS to verified office laptop sessions."""

import re

from django.conf import settings

from horilla.client_ip import client_ip


SESSION_KEY = "office_laptop_employee"
LAPTOP_LIMIT_METERS = 200
DESKTOP = re.compile(r"Windows NT|Macintosh|X11|CrOS", re.I)
MOBILE = re.compile(r"Android|Mobile|iPhone|iPad|iPod", re.I)


def office_browser(request):
    office_ip = getattr(settings, "ATTENDANCE_LAPTOP_OFFICE_IP", "")
    if not office_ip or client_ip(request) != office_ip:
        return False
    agent = request.headers.get("User-Agent", "")
    return (
        request.headers.get("Sec-CH-UA-Mobile") != "?1"
        and DESKTOP.search(agent) is not None
        and MOBILE.search(agent) is None
    )


def approved(request, employee):
    return office_browser(request) and request.session.get(SESSION_KEY) == employee.pk

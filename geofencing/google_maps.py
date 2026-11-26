"""Google Maps geocoding helpers for approved pins and punch review."""

from __future__ import annotations

import requests
from django.conf import settings


class GoogleMapsLocationError(Exception):
    """A user-actionable failure from the Google Maps location service."""


def reverse_geocode(latitude, longitude, *, required=False):
    """Resolve coordinates through Google Maps Geocoding API.

    Coordinates remain the source of truth for the radius decision. Google Maps
    supplies the human-readable address and place id used for authorised review.
    """

    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        if required:
            raise GoogleMapsLocationError(
                "Google Maps location service is not configured."
            )
        return None

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "latlng": f"{latitude},{longitude}",
                "key": api_key,
                "language": "en",
            },
            timeout=getattr(settings, "GOOGLE_MAPS_GEOCODING_TIMEOUT_SECONDS", 5),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        if required:
            raise GoogleMapsLocationError(
                "Google Maps could not identify this location. Please try again."
            ) from exc
        return None

    if payload.get("status") != "OK" or not payload.get("results"):
        if required:
            raise GoogleMapsLocationError(
                "Google Maps could not identify this location. Please try again."
            )
        return None

    result = payload["results"][0]
    location = result.get("geometry", {}).get("location", {})
    return {
        "formatted_address": result.get("formatted_address", ""),
        "place_id": result.get("place_id", ""),
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
    }

# eQOURSE Work attendance punch rollout

This change makes every employee check-in and check-out require two fresh pieces
of evidence: a GPS reading and a live camera image. The server validates both
before writing attendance. Office punches are checked against the active company
geofence; an employee with an approved remote work assignment for the punch date
may be outside that fence. The captured latitude, longitude, accuracy, and
timestamp are stored separately for check-in and check-out on both attendance
records and activity records.

Google Maps Geocoding API resolves the approved office pin and reverse-geocodes
each captured punch coordinate to a reviewable formatted address and place id.
The device-provided coordinates remain the source of truth for radius checks;
the Google response is descriptive metadata, not a substitute for GPS evidence.

## Client contract

The web portal and native app must submit these fields to the existing punch
endpoints:

- `latitude`, `longitude`, `accuracy`
- `location_timestamp` (Unix milliseconds or an ISO-8601 timestamp)
- `face_image` (a live camera capture, not the stored profile photo)

The server rejects missing, malformed, or stale GPS, missing face evidence, a
face mismatch, and an office location outside the active radius. A rejected
punch leaves attendance unchanged and returns an actionable error message.

## Release order

1. Release the native client that captures the fields above and handles denied
   camera/location permissions and the check-out response.
2. Verify the native build against staging with the test matrix below.
3. Deploy this server change and database migration.
4. Enable the production geofence and face policy after both clients have been
   verified. Keep AWS, production deployment credentials, SSO, SMTP, and role
   setup with Bhavesh.

Configure `GOOGLE_MAPS_API_KEY` on the server before enabling location review.
Restrict the key to the Geocoding API and keep it out of source control.

The native app repository was not present in this checkout, so this PR contains
the server contract and web client only. Do not make the server enforcement
mandatory for native users until the companion app release has been reviewed by
Bhavesh and verified against these endpoints.

## Test matrix

- Office check-in and check-out inside the configured radius: accepted.
- Office check-in and check-out outside the configured radius: rejected.
- Approved WFH/remote check-in and check-out outside the radius: accepted, with
  actual locations saved separately.
- Face mismatch or missing face evidence: rejected without changing attendance.
- Denied camera or location permission, stale GPS, and missing GPS: rejected with
  a clear message.

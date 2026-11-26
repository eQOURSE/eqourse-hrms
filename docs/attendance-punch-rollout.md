# eQOURSE Work attendance punch rollout

This change makes every employee check-in and check-out require two fresh pieces
of evidence: a GPS reading and a live camera image. The server validates both
before writing attendance. Office punches are checked against the active company
geofence; an employee with an approved remote work assignment for the punch date
may be outside that fence. The captured latitude, longitude, accuracy, and
timestamp are stored separately for check-in and check-out on both attendance
records and activity records.

The approved eQOURSE Work office pin for this rollout is `25.14402, 75.84506`
with a 100-metre radius. Punch enforcement uses these configured values, while
the enabled company fence record is also required as the HR switch. Google Maps
Geocoding API resolves that approved office pin and reverse-geocodes each
captured punch coordinate to a reviewable formatted address and place id.
The device-provided coordinates remain the source of truth for radius checks;
the Google response is descriptive metadata, not a substitute for GPS evidence.

## Client contract

The web portal and native app must submit these fields to the existing punch
endpoints:

- `latitude`, `longitude`, `accuracy` (reported accuracy must be 25 metres or
  better for the office test; onsite acceptance requires distance from the
  approved pin plus reported accuracy to be no more than 50 metres)
- `location_timestamp` (Unix milliseconds or an ISO-8601 timestamp)
- `face_image` (a live camera capture, not the stored profile photo)

The server rejects missing, malformed, stale, or imprecise GPS, missing face
evidence, a face mismatch, a missing/disabled office fence, and an office
location outside the active 100-metre radius. A rejected punch leaves attendance
unchanged and returns an actionable error message.

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

The employee-facing logo is the official asset sourced from
`https://www.eqourse.com/`. The native app repository was not present in this checkout, so this PR contains
the server contract and web client only. Do not make the server enforcement
mandatory for native users until the companion app release has been reviewed by
Bhavesh and verified against these endpoints.

## Test matrix

- Office check-in and check-out inside the configured radius: accepted.
- Office check-in and check-out outside the configured radius: rejected.
- Office distance plus GPS accuracy boundary: 40 m + 9 m accepted, 40 m +
  10 m accepted exactly at 50 m, and 49 m + 25 m rejected for both actions.
- Missing or disabled office fence: rejected with a clear configuration message.
- GPS accuracy above 25 metres or missing accuracy: rejected with a retry message.
- Approved WFH/remote check-in and check-out outside the radius: accepted, with
  actual locations saved separately.
- Face mismatch or missing face evidence: rejected without changing attendance.
- Manual spoof-resistance check: try a printed approved photo and the same photo
  displayed on another phone for both check-in and check-out. If either spoof is
  accepted, do not use official attendance until a liveness challenge is enabled
  and verified; this PR does not claim liveness from face matching alone.
- Denied camera or location permission, stale GPS, and missing GPS: rejected with
  a clear message.

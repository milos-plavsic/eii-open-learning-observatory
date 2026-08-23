# Incident-response runbook

1. Triage severity and appoint an incident lead and recorder. Treat exposed
   learner content, tokens, signing keys, corrupted evidence, or unauthorized
   activation as high severity.
2. Contain: remove the service from the classroom proxy, rotate bearer tokens,
   revoke compromised keys, and preserve read-only copies of logs, manifests,
   databases, and package hashes.
3. Diagnose using request IDs and bounded audit events. Never expand logging to
   raw learner prompts during the incident.
4. Recover from a verified database backup or use `appliance-recover`/rollback.
   Re-run integrity, schema, conformance, safety, and smoke gates before routing
   traffic. Do not activate an unsigned emergency build.
5. Notify affected operators and the security contact with known scope and safe
   mitigations. Follow applicable contractual and legal notification duties.
6. Publish a blameless review covering timeline, root cause, impact, detection,
   corrective actions, owners, deadlines, and regression tests.

Run a synthetic tabletop twice yearly: lost publisher key, disk exhaustion during
activation, corrupted SQLite database, and accidental audit-log disclosure.

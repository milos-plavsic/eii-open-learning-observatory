"""Ordered, immutable Classroom Weather database migrations."""

WEATHER_MIGRATIONS = (
    """
CREATE TABLE IF NOT EXISTS events (
  occurred_at TEXT NOT NULL, course_key TEXT NOT NULL, activity_key TEXT NOT NULL,
  language TEXT NOT NULL, concept_id TEXT NOT NULL, signal TEXT NOT NULL,
  contributor_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_expiry_idx ON events(occurred_at);
CREATE INDEX IF NOT EXISTS events_aggregate_idx
  ON events(course_key,activity_key,language,concept_id,signal);
""",
    """
CREATE TABLE IF NOT EXISTS privacy_exports (
  id INTEGER PRIMARY KEY CHECK (id = 1), exported_at TEXT NOT NULL,
  payload_hash TEXT NOT NULL
);
""",
    """
CREATE TABLE IF NOT EXISTS privacy_exports_v2 (
  scope TEXT PRIMARY KEY NOT NULL, exported_at TEXT NOT NULL,
  payload_hash TEXT NOT NULL
);
""",
    """
CREATE TABLE IF NOT EXISTS privacy_key_epochs (
  epoch TEXT PRIMARY KEY NOT NULL, key_fingerprint TEXT UNIQUE NOT NULL,
  activated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_export_policy (
  id INTEGER PRIMARY KEY CHECK (id = 1), partition_strategy TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_export_audit (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
  exported_at TEXT NOT NULL, payload_hash TEXT NOT NULL,
  previous_hash TEXT, record_hash TEXT UNIQUE NOT NULL
);
""",
    """
-- Schema 5 deliberately purges pre-epoch events and unauthenticated audit records.
DELETE FROM events;
DELETE FROM privacy_exports_v2;
DELETE FROM privacy_export_audit;
CREATE TRIGGER privacy_export_audit_no_update
BEFORE UPDATE ON privacy_export_audit BEGIN
  SELECT RAISE(ABORT, 'privacy export audit is append-only');
END;
CREATE TRIGGER privacy_export_audit_no_delete
BEFORE DELETE ON privacy_export_audit BEGIN
  SELECT RAISE(ABORT, 'privacy export audit is append-only');
END;
""",
)

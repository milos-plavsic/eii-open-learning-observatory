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
    """
CREATE TABLE IF NOT EXISTS dp_budget (
  id INTEGER PRIMARY KEY CHECK (id = 1), epsilon_limit REAL NOT NULL,
  epsilon_spent REAL NOT NULL CHECK (epsilon_spent >= 0 AND epsilon_spent <= epsilon_limit)
);
CREATE TABLE IF NOT EXISTS dp_releases (
  release_key TEXT PRIMARY KEY NOT NULL, scope TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL, policy_hash TEXT NOT NULL, epsilon REAL NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dp_releases_snapshot_idx
  ON dp_releases(scope,snapshot_hash,policy_hash);
CREATE TRIGGER dp_releases_no_update BEFORE UPDATE ON dp_releases BEGIN
  SELECT RAISE(ABORT, 'differential-privacy releases are immutable');
END;
CREATE TRIGGER dp_releases_no_delete BEFORE DELETE ON dp_releases BEGIN
  SELECT RAISE(ABORT, 'differential-privacy releases are immutable');
END;
CREATE TABLE IF NOT EXISTS privacy_exports_v3 (
  scope TEXT NOT NULL, artifact_kind TEXT NOT NULL, exported_at TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL, artifact_hash TEXT NOT NULL,
  PRIMARY KEY(scope,artifact_kind)
);
CREATE TABLE IF NOT EXISTS privacy_export_audit_v2 (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
  artifact_kind TEXT NOT NULL, exported_at TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL, artifact_hash TEXT NOT NULL,
  previous_hash TEXT, record_hash TEXT UNIQUE NOT NULL
);
CREATE TRIGGER privacy_export_audit_v2_no_update
BEFORE UPDATE ON privacy_export_audit_v2 BEGIN
  SELECT RAISE(ABORT, 'privacy export audit v2 is append-only');
END;
CREATE TRIGGER privacy_export_audit_v2_no_delete
BEFORE DELETE ON privacy_export_audit_v2 BEGIN
  SELECT RAISE(ABORT, 'privacy export audit v2 is append-only');
END;
""",
    """
CREATE TABLE IF NOT EXISTS privacy_ledger_key_binding (
  id INTEGER PRIMARY KEY CHECK (id = 1), key_fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_publication_journal (
  destination TEXT PRIMARY KEY NOT NULL, staged_path TEXT NOT NULL,
  backup_path TEXT, scope TEXT NOT NULL, artifact_kind TEXT NOT NULL,
  exported_at TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
  artifact_hash TEXT NOT NULL, record_mac TEXT NOT NULL
);
""",
    """
ALTER TABLE privacy_publication_journal ADD COLUMN strategy TEXT NOT NULL DEFAULT 'global';
ALTER TABLE privacy_publication_journal ADD COLUMN prior_hash TEXT;
""",
)

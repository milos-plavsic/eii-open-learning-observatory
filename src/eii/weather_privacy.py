"""Persistent privacy-key and export-ledger policy for classroom aggregates."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta


def bind_key_epoch(connection: sqlite3.Connection, *, secret: bytes, epoch: str) -> None:
    fingerprint = hashlib.sha256(secret).hexdigest()
    row = connection.execute(
        "SELECT key_fingerprint FROM privacy_key_epochs WHERE epoch=?", (epoch,)
    ).fetchone()
    if row and row[0] != fingerprint:
        raise ValueError("key epoch is already bound to a different privacy secret")
    reused = connection.execute(
        "SELECT epoch FROM privacy_key_epochs WHERE key_fingerprint=?", (fingerprint,)
    ).fetchone()
    if reused and reused[0] != epoch:
        raise ValueError("privacy secret cannot be reused under a different key epoch")
    epochs = connection.execute("SELECT epoch FROM privacy_key_epochs").fetchall()
    if epochs and row is None:
        raise ValueError("new key epochs require an explicit, audited privacy-key rotation")
    connection.execute(
        "INSERT OR IGNORE INTO privacy_key_epochs VALUES (?,?,?)",
        (epoch, fingerprint, datetime.now(UTC).isoformat()),
    )
    connection.commit()


def rotate_key_epoch(connection: sqlite3.Connection, *, new_secret: bytes, new_epoch: str) -> int:
    """Explicitly rotate unlinkability state and purge data tied to the prior key."""
    fingerprint = hashlib.sha256(new_secret).hexdigest()
    if connection.execute(
        "SELECT 1 FROM privacy_key_epochs WHERE epoch=? OR key_fingerprint=?",
        (new_epoch, fingerprint),
    ).fetchone():
        raise ValueError("privacy key epoch and secret must both be new")
    purged = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    with connection:
        connection.execute("DELETE FROM events")
        connection.execute(
            "INSERT INTO privacy_key_epochs VALUES (?,?,?)",
            (new_epoch, fingerprint, datetime.now(UTC).isoformat()),
        )
    return purged


def verify_export_ledger(connection: sqlite3.Connection, *, ledger_key: bytes) -> str | None:
    """Verify the complete keyed append-only chain and return its current head."""
    previous: str | None = None
    rows = connection.execute(
        "SELECT scope,exported_at,payload_hash,previous_hash,record_hash "
        "FROM privacy_export_audit ORDER BY sequence"
    ).fetchall()
    for scope, exported_at, payload_hash, previous_hash, record_hash in rows:
        if previous_hash != previous:
            raise ValueError("privacy export ledger chain is discontinuous")
        encoded = json.dumps(
            [scope, exported_at, payload_hash, previous], separators=(",", ":")
        ).encode()
        expected = hmac.new(ledger_key, encoded, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(record_hash, expected):
            raise ValueError("privacy export ledger authentication failed")
        previous = record_hash
    return previous


def record_export(
    connection: sqlite3.Connection,
    *,
    scope: str,
    strategy: str,
    exported_at: datetime,
    payload_hash: str,
    minimum_interval: timedelta,
    ledger_key: bytes,
) -> None:
    verify_export_ledger(connection, ledger_key=ledger_key)
    policy = connection.execute(
        "SELECT partition_strategy FROM privacy_export_policy WHERE id=1"
    ).fetchone()
    if policy and policy[0] != strategy:
        raise ValueError("privacy export partition strategy cannot be mixed in one database")
    connection.execute("INSERT OR IGNORE INTO privacy_export_policy VALUES (1,?)", (strategy,))
    previous = connection.execute(
        "SELECT exported_at,payload_hash FROM privacy_exports_v2 WHERE scope=?", (scope,)
    ).fetchone()
    if (
        previous
        and exported_at - datetime.fromisoformat(previous[0]) < minimum_interval
        and previous[1] != payload_hash
    ):
        raise ValueError("privacy export interval blocks a differencing-prone update")
    connection.execute(
        "INSERT OR REPLACE INTO privacy_exports_v2 VALUES (?,?,?)",
        (scope, exported_at.isoformat(), payload_hash),
    )
    previous_audit = connection.execute(
        "SELECT record_hash FROM privacy_export_audit ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    previous_hash = previous_audit[0] if previous_audit else None
    encoded = json.dumps(
        [scope, exported_at.isoformat(), payload_hash, previous_hash], separators=(",", ":")
    ).encode()
    record_hash = hmac.new(ledger_key, encoded, hashlib.sha256).hexdigest()
    connection.execute(
        "INSERT INTO privacy_export_audit(scope,exported_at,payload_hash,previous_hash,record_hash) VALUES (?,?,?,?,?)",
        (scope, exported_at.isoformat(), payload_hash, previous_hash, record_hash),
    )
    connection.commit()

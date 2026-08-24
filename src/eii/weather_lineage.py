"""Database-instance lineage enforcement for privacy-budget stores."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime


def bind_database_lineage(
    connection: sqlite3.Connection,
    expected: str | None,
    *,
    allow_database_fork: bool,
) -> str:
    """Bind a store to an operator identity and reject silent database clones."""
    if expected is not None and (
        len(expected) > 128 or not expected.strip() or any(ord(char) < 33 for char in expected)
    ):
        raise ValueError("database instance id must be bounded printable text without whitespace")
    now = datetime.now(UTC).isoformat()
    row = connection.execute(
        "SELECT instance_id FROM privacy_database_lineage WHERE id=1"
    ).fetchone()
    if row is None:
        instance_id = expected or secrets.token_hex(16)
        connection.execute(
            "INSERT INTO privacy_database_lineage VALUES (1,?,NULL,?)", (instance_id, now)
        )
        connection.execute(
            "INSERT INTO privacy_database_lineage_history(instance_id,parent_instance_id,recorded_at) VALUES (?,NULL,?)",
            (instance_id, now),
        )
        connection.commit()
        return instance_id
    actual = str(row[0])
    if expected is None or expected == actual:
        return actual
    if not allow_database_fork:
        raise ValueError(
            f"database clone detected: expected instance {expected}, database records {actual}"
        )
    connection.execute(
        "UPDATE privacy_database_lineage SET instance_id=?,parent_instance_id=?,updated_at=? WHERE id=1",
        (expected, actual, now),
    )
    connection.execute(
        "INSERT INTO privacy_database_lineage_history(instance_id,parent_instance_id,recorded_at) VALUES (?,?,?)",
        (expected, actual, now),
    )
    connection.commit()
    return expected

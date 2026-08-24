"""Versioned SQLite lifecycle shared by local Observatory stores."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    kind: str
    schema_version: int
    integrity: str


def connect_database(
    path: Path,
    *,
    kind: str,
    migrations: Sequence[str],
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    if not kind.strip() or not migrations:
        raise ValueError("database kind and at least one migration are required")
    connection = sqlite3.connect(path, timeout=5.0, check_same_thread=check_same_thread)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise ValueError(f"database integrity check failed: {integrity}")
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current > len(migrations):
            raise ValueError(
                f"database schema version {current} is newer than supported {len(migrations)}"
            )
        metadata_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_eii_database'"
        ).fetchone()
        if metadata_exists:
            row = connection.execute("SELECT kind FROM _eii_database").fetchone()
            if row is None or row[0] != kind:
                raise ValueError(
                    f"database belongs to {row[0] if row else 'an unknown application'}, not {kind}"
                )
        for version in range(current + 1, len(migrations) + 1):
            connection.executescript("BEGIN IMMEDIATE;\n" + migrations[version - 1])
            connection.execute(f"PRAGMA user_version={version}")
            connection.commit()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS _eii_database(kind TEXT PRIMARY KEY NOT NULL)"
        )
        connection.execute("INSERT OR IGNORE INTO _eii_database(kind) VALUES (?)", (kind,))
        connection.commit()
        return connection
    except Exception:
        connection.close()
        raise


def database_status(connection: sqlite3.Connection, *, kind: str) -> DatabaseStatus:
    row = connection.execute("SELECT kind FROM _eii_database").fetchone()
    if row is None or row[0] != kind:
        raise ValueError("database identity does not match the requested store")
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    return DatabaseStatus(kind, version, integrity)


def backup_database(connection: sqlite3.Connection, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = sqlite3.connect(destination)
    try:
        connection.backup(backup)
        integrity = str(backup.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise ValueError(f"backup integrity check failed: {integrity}")
    finally:
        backup.close()


def open_existing_database(path: Path, *, kind: str) -> sqlite3.Connection:
    """Open an existing store for maintenance without migrations or application secrets."""
    if not path.is_file():
        raise ValueError("database does not exist")
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        row = connection.execute("SELECT kind FROM _eii_database").fetchone()
        if row is None or row[0] != kind:
            raise ValueError("database identity does not match the requested store")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("database integrity check failed")
        return connection
    except Exception:
        connection.close()
        raise

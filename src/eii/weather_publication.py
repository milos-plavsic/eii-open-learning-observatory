"""Crash-recoverable publication bridging SQLite evidence and filesystem artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .weather_privacy import record_export


def publish_artifact(
    connection: sqlite3.Connection,
    destination: Path,
    artifact: bytes,
    *,
    scope: str,
    strategy: str,
    artifact_kind: str,
    exported_at: datetime,
    snapshot_hash: str,
    minimum_interval: timedelta,
    ledger_key: bytes,
) -> None:
    """Atomically replace one artifact with authenticated crash recovery metadata."""
    destination = destination.absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    artifact_hash = hashlib.sha256(artifact).hexdigest()
    descriptor, staged_name = tempfile.mkstemp(
        dir=destination.parent, prefix=".eii-weather-staged-"
    )
    staged = Path(staged_name)
    backup = destination.parent / f".eii-weather-backup-{staged.name.rsplit('-', 1)[-1]}"
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(artifact)
            stream.flush()
            os.fsync(stream.fileno())
        values = _journal_values(
            destination,
            staged,
            backup if destination.exists() else None,
            _file_hash(destination) if destination.is_file() else None,
            scope,
            strategy,
            artifact_kind,
            exported_at,
            snapshot_hash,
            artifact_hash,
        )
        record_mac = _journal_mac(values, ledger_key)
        with connection:
            connection.execute(
                "INSERT INTO privacy_publication_journal "
                "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                "exported_at,snapshot_hash,artifact_hash,record_mac) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*values, record_mac),
            )
        if destination.exists():
            os.replace(destination, backup)
        os.replace(staged, destination)
        _fsync_directory(destination.parent)
        record_export(
            connection,
            scope=scope,
            strategy=strategy,
            artifact_kind=artifact_kind,
            exported_at=exported_at,
            snapshot_hash=snapshot_hash,
            artifact_hash=artifact_hash,
            minimum_interval=minimum_interval,
            ledger_key=ledger_key,
        )
        backup.unlink(missing_ok=True)
        _fsync_directory(destination.parent)
        with connection:
            connection.execute(
                "DELETE FROM privacy_publication_journal WHERE destination=?",
                (str(destination),),
            )
    except BaseException:
        _recover_destination(
            connection,
            str(destination),
            ledger_key=ledger_key,
            complete_installed=False,
        )
        raise


def recover_publications(
    connection: sqlite3.Connection,
    *,
    ledger_key: bytes,
    minimum_interval: timedelta,
) -> int:
    """Complete installed publications or roll back incomplete filesystem changes."""
    rows = connection.execute(
        "SELECT destination FROM privacy_publication_journal ORDER BY destination"
    ).fetchall()
    recovered = 0
    for (destination,) in rows:
        recovered += _recover_destination(
            connection,
            destination,
            ledger_key=ledger_key,
            minimum_interval=minimum_interval,
        )
    return recovered


def _recover_destination(
    connection: sqlite3.Connection,
    destination_value: str,
    *,
    ledger_key: bytes,
    minimum_interval: timedelta = timedelta(0),
    complete_installed: bool = True,
) -> int:
    row = connection.execute(
        "SELECT destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,exported_at,"
        "snapshot_hash,artifact_hash,record_mac FROM privacy_publication_journal "
        "WHERE destination=?",
        (destination_value,),
    ).fetchone()
    if row is None:
        return 0
    values, supplied_mac = tuple(row[:-1]), row[-1]
    if not hmac.compare_digest(_journal_mac(values, ledger_key), supplied_mac):
        raise ValueError("weather publication recovery record authentication failed")
    destination, staged, backup = Path(row[0]), Path(row[1]), Path(row[2]) if row[2] else None
    _validate_recovery_paths(destination, staged, backup)
    artifact_hash = row[9]
    prior_hash = row[3]
    destination_matches = destination.is_file() and _file_hash(destination) == artifact_hash
    if destination_matches:
        indexed = connection.execute(
            "SELECT artifact_hash FROM privacy_exports_v3 WHERE scope=? AND artifact_kind=?",
            (row[4], row[6]),
        ).fetchone()
        if (not indexed or indexed[0] != artifact_hash) and complete_installed:
            record_export(
                connection,
                scope=row[4],
                strategy=row[5],
                artifact_kind=row[6],
                exported_at=datetime.fromisoformat(row[7]),
                snapshot_hash=row[8],
                artifact_hash=artifact_hash,
                minimum_interval=minimum_interval,
                ledger_key=ledger_key,
            )
        elif not indexed or indexed[0] != artifact_hash:
            destination.unlink()
            if backup and backup.exists():
                os.replace(backup, destination)
    elif destination.is_file() and prior_hash and _file_hash(destination) == prior_hash:
        # The crash preceded the first filesystem rename; the prior artifact is intact.
        pass
    else:
        if destination.exists() and backup is None:
            raise ValueError("weather publication recovery found an unrelated destination")
        destination.unlink(missing_ok=True)
        if backup and backup.exists():
            os.replace(backup, destination)
    staged.unlink(missing_ok=True)
    if backup:
        backup.unlink(missing_ok=True)
    with connection:
        connection.execute(
            "DELETE FROM privacy_publication_journal WHERE destination=?", (str(destination),)
        )
    _fsync_directory(destination.parent)
    return 1


def _journal_values(
    destination: Path,
    staged: Path,
    backup: Path | None,
    prior_hash: str | None,
    scope: str,
    strategy: str,
    artifact_kind: str,
    exported_at: datetime,
    snapshot_hash: str,
    artifact_hash: str,
) -> tuple[str, str, str | None, str | None, str, str, str, str, str, str]:
    return (
        str(destination),
        str(staged),
        str(backup) if backup else None,
        prior_hash,
        scope,
        strategy,
        artifact_kind,
        exported_at.isoformat(),
        snapshot_hash,
        artifact_hash,
    )


def _journal_mac(values: tuple[object, ...], ledger_key: bytes) -> str:
    encoded = json.dumps(values, separators=(",", ":")).encode()
    return hmac.new(ledger_key, encoded, hashlib.sha256).hexdigest()


def _validate_recovery_paths(destination: Path, staged: Path, backup: Path | None) -> None:
    if (
        not destination.is_absolute()
        or staged.parent != destination.parent
        or not staged.name.startswith(".eii-weather-staged-")
        or (
            backup is not None
            and (
                backup.parent != destination.parent
                or not backup.name.startswith(".eii-weather-backup-")
            )
        )
    ):
        raise ValueError("weather publication recovery paths are unsafe")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(directory: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

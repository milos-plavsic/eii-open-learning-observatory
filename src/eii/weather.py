"""Privacy-preserving, local-first aggregate classroom signals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from html import escape
from pathlib import Path

from .persistence import DatabaseStatus, backup_database, connect_database, database_status
from .weather_migrations import WEATHER_MIGRATIONS
from .weather_privacy import bind_key_epoch, record_export, rotate_key_epoch, verify_export_ledger


class Signal(StrEnum):
    MISCONCEPTION = "misconception"
    REPEATED_QUESTION = "repeated_question"
    COMPLETE_ANSWER_REQUEST = "complete_answer_request"
    FRUSTRATION = "frustration"
    ABANDONMENT = "abandonment"
    RETRIEVAL_FAILURE = "retrieval_failure"
    UNSUPPORTED_QUESTION = "unsupported_question"


@dataclass(frozen=True, slots=True)
class MinimizedEvent:
    occurred_at: str
    course_key: str
    activity_key: str
    language: str
    concept_id: str
    signal: Signal
    contribution_token: str

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("course_key", self.course_key, 200),
            ("activity_key", self.activity_key, 200),
            ("language", self.language, 35),
            ("concept_id", self.concept_id, 200),
        ):
            if not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
                raise ValueError(f"{label} must be non-empty, bounded text without controls")
        if (
            "@" in self.contribution_token
            or len(self.contribution_token) > 128
            or any(char.isspace() or ord(char) < 33 for char in self.contribution_token)
        ):
            raise ValueError("contribution token must be pseudonymous and bounded")
        if not self.contribution_token.strip():
            raise ValueError("contribution token cannot be empty")
        occurred = datetime.fromisoformat(self.occurred_at)
        if occurred.tzinfo is None:
            raise ValueError("event timestamp must include a timezone")


@dataclass(frozen=True, slots=True)
class WeatherCell:
    course_key: str
    activity_key: str
    language: str
    concept_id: str
    signal: Signal
    event_count: int
    contributor_count: int
    explanation: str
    recommendation: str


_RECOMMENDATIONS = {
    Signal.MISCONCEPTION: "Add a contrasting example and a diagnostic question.",
    Signal.REPEATED_QUESTION: "Add or expand the explanation addressing this concept.",
    Signal.COMPLETE_ANSWER_REQUEST: "Review hint progression and task difficulty.",
    Signal.FRUSTRATION: "Review language complexity and add a worked example.",
    Signal.ABANDONMENT: "Ask a teacher to inspect this activity's prerequisite load.",
    Signal.RETRIEVAL_FAILURE: "Improve chunking, metadata, or concept alignment.",
    Signal.UNSUPPORTED_QUESTION: "Review whether the course should cover this emerging question.",
}


class WeatherStore:
    """SQLite store containing no conversation text or direct identifiers."""

    def __init__(
        self,
        path: Path,
        *,
        secret: bytes,
        minimum_group_size: int = 5,
        retention_days: int = 30,
        max_events_per_contributor_per_cell: int = 3,
        count_granularity: int = 2,
        minimum_export_interval_hours: int = 24,
        key_epoch: str = "v1",
        ledger_key: bytes | None = None,
    ):
        if len(secret) < 32:
            raise ValueError("weather secret must contain at least 32 bytes")
        if minimum_group_size < 2:
            raise ValueError("minimum group size must be at least 2")
        if retention_days < 1:
            raise ValueError("retention must be positive")
        if max_events_per_contributor_per_cell < 1:
            raise ValueError("contribution bound must be positive")
        if count_granularity < 1 or minimum_export_interval_hours < 1:
            raise ValueError("count granularity and export interval must be positive")
        if (
            not key_epoch.strip()
            or len(key_epoch) > 64
            or any(ord(char) < 33 for char in key_epoch)
        ):
            raise ValueError("key epoch must be bounded printable text without whitespace")
        self.path, self.secret = path, secret
        self.ledger_key = ledger_key or secret
        if len(self.ledger_key) < 32:
            raise ValueError("weather ledger key must contain at least 32 bytes")
        self.minimum_group_size, self.retention_days = minimum_group_size, retention_days
        self.max_events_per_contributor_per_cell = max_events_per_contributor_per_cell
        self.count_granularity = count_granularity
        self.minimum_export_interval_hours = minimum_export_interval_hours
        self.key_epoch = key_epoch
        self.connection = connect_database(path, kind="weather", migrations=WEATHER_MIGRATIONS)
        try:
            bind_key_epoch(self.connection, secret=self.secret, epoch=self.key_epoch)
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def status(self) -> DatabaseStatus:
        return database_status(self.connection, kind="weather")

    def backup(self, destination: Path) -> None:
        backup_database(self.connection, destination)

    def rotate_privacy_key(self, *, new_secret: bytes, new_epoch: str) -> int:
        if len(new_secret) < 32:
            raise ValueError("weather secret must contain at least 32 bytes")
        purged = rotate_key_epoch(self.connection, new_secret=new_secret, new_epoch=new_epoch)
        self.secret, self.key_epoch = new_secret, new_epoch
        return purged

    def verify_export_ledger(self) -> str | None:
        return verify_export_ledger(self.connection, ledger_key=self.ledger_key)

    def __enter__(self) -> WeatherStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def ingest(self, event: MinimizedEvent) -> None:
        # Tokens are keyed and hashed immediately; the input value is never persisted.
        occurred_day = datetime.fromisoformat(event.occurred_at).astimezone(UTC).date().isoformat()
        linkage_scope = "\x1f".join(
            (
                self.key_epoch,
                occurred_day,
                event.course_key,
                event.activity_key,
                event.language,
                event.concept_id,
                event.signal.value,
                event.contribution_token,
            )
        )
        contributor_hash = hashlib.blake2b(
            linkage_scope.encode(), key=self.secret, digest_size=16
        ).hexdigest()
        existing = self.connection.execute(
            """SELECT COUNT(*) FROM events WHERE contributor_hash = ?
          AND occurred_at = ? AND course_key = ? AND activity_key = ? AND language = ?
          AND concept_id = ? AND signal = ?""",
            (
                contributor_hash,
                occurred_day,
                event.course_key,
                event.activity_key,
                event.language,
                event.concept_id,
                event.signal.value,
            ),
        ).fetchone()[0]
        if existing >= self.max_events_per_contributor_per_cell:
            return
        self.connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
            (
                occurred_day,
                event.course_key,
                event.activity_key,
                event.language,
                event.concept_id,
                event.signal.value,
                contributor_hash,
            ),
        )
        self.connection.commit()

    def purge_expired(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        cursor = self.connection.execute("DELETE FROM events WHERE occurred_at < ?", (cutoff,))
        self.connection.commit()
        return cursor.rowcount

    def aggregate(self, *, course_key: str | None = None) -> tuple[WeatherCell, ...]:
        if course_key:
            rows = self.connection.execute(
                """SELECT course_key, activity_key, language, concept_id,
                signal, COUNT(*), COUNT(DISTINCT contributor_hash) FROM events
                WHERE course_key = ?
                GROUP BY course_key, activity_key, language, concept_id, signal
                HAVING COUNT(DISTINCT contributor_hash) >= ? ORDER BY COUNT(*) DESC""",
                (course_key, self.minimum_group_size),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT course_key, activity_key, language, concept_id,
                signal, COUNT(*), COUNT(DISTINCT contributor_hash) FROM events
                GROUP BY course_key, activity_key, language, concept_id, signal
                HAVING COUNT(DISTINCT contributor_hash) >= ? ORDER BY COUNT(*) DESC""",
                (self.minimum_group_size,),
            ).fetchall()
        return tuple(
            WeatherCell(
                row[0],
                row[1],
                row[2],
                row[3],
                Signal(row[4]),
                row[5],
                row[6],
                f"{row[5]} minimized events from at least {row[6]} pseudonymous contributors.",
                _RECOMMENDATIONS[Signal(row[4])],
            )
            for row in rows
        )

    def export(
        self,
        destination: Path,
        *,
        course_key: str | None = None,
        now: datetime | None = None,
    ) -> None:
        cells = self._privacy_cells(course_key=course_key, now=now)
        payload = {
            "schema_version": "2.0",
            "privacy": {
                "minimum_group_size": self.minimum_group_size,
                "retention_days": self.retention_days,
                "max_events_per_contributor_per_cell_per_day": self.max_events_per_contributor_per_cell,
                "timestamp_precision": "utc-day",
                "raw_conversations_stored": False,
                "direct_identifiers_stored": False,
                "count_granularity": self.count_granularity,
                "minimum_export_interval_hours": self.minimum_export_interval_hours,
                "key_epoch": self.key_epoch,
                "contribution_linkage": "within-cell-day-only-pseudonymous",
            },
            "cells": [asdict(cell) for cell in cells],
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized, "utf-8")

    def _privacy_cells(
        self, *, course_key: str | None, now: datetime | None = None
    ) -> tuple[WeatherCell, ...]:
        cells = tuple(self._coarsen(cell) for cell in self.aggregate(course_key=course_key))
        payload_hash = hashlib.sha256(
            json.dumps([asdict(cell) for cell in cells], sort_keys=True, default=str).encode()
        ).hexdigest()
        exported_at = now or datetime.now(UTC)
        scope = course_key or "*"
        strategy = "global" if course_key is None else "course-partitioned"
        record_export(
            self.connection,
            scope=scope,
            strategy=strategy,
            exported_at=exported_at,
            payload_hash=payload_hash,
            minimum_interval=timedelta(hours=self.minimum_export_interval_hours),
            ledger_key=self.ledger_key,
        )
        return cells

    def _coarsen(self, cell: WeatherCell) -> WeatherCell:
        contributors = max(
            self.minimum_group_size,
            cell.contributor_count // self.count_granularity * self.count_granularity,
        )
        events = max(
            contributors, cell.event_count // self.count_granularity * self.count_granularity
        )
        return WeatherCell(
            cell.course_key,
            cell.activity_key,
            cell.language,
            cell.concept_id,
            cell.signal,
            events,
            contributors,
            f"At least {events} minimized events from at least {contributors} pseudonymous contributors.",
            cell.recommendation,
        )

    def export_html(self, destination: Path, *, course_key: str | None = None) -> None:
        cells = self._privacy_cells(course_key=course_key)
        rows = "".join(
            f"<tr><td>{escape(cell.activity_key)}</td><td>{escape(cell.language)}</td>"
            f"<td>{escape(cell.concept_id)}</td><td>{escape(cell.signal.value)}</td>"
            f"<td>{cell.event_count}</td><td>{cell.contributor_count}+</td>"
            f"<td>{escape(cell.recommendation)}</td></tr>"
            for cell in cells
        )
        if not rows:
            rows = '<tr><td colspan="7">No groups meet the privacy threshold.</td></tr>'
        html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Classroom Weather Map</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:auto;padding:2rem}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccd;padding:.55rem;text-align:left}}th{{background:#eef}}.privacy{{background:#eaf7ef;padding:1rem}}</style>
<main><h1>Classroom Weather Map</h1><div class="privacy"><b>Privacy boundary:</b> only groups with at least
{self.minimum_group_size} pseudonymous contributors are shown. Events expire after {self.retention_days} days.
No conversation text, direct identity, token, or contributor hash is present in this report.
Contributor linkage is pseudonymous and restricted to one cell and UTC day.</div>
<table><caption>Aggregated learning-difficulty signals</caption><thead><tr><th scope="col">Activity</th><th scope="col">Language</th><th scope="col">Concept</th><th scope="col">Signal</th>
<th scope="col">Events</th><th scope="col">Contributors</th><th scope="col">Suggested intervention</th></tr></thead><tbody>{rows}</tbody></table></main></html>"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(html, "utf-8")


def load_events(path: Path) -> tuple[MinimizedEvent, ...]:
    data = json.loads(path.read_text("utf-8"))
    allowed = {
        "occurred_at",
        "course_key",
        "activity_key",
        "language",
        "concept_id",
        "signal",
        "contribution_token",
    }
    events = []
    for index, item in enumerate(data["events"]):
        unexpected = set(item) - allowed
        if unexpected:
            raise ValueError(
                f"event {index} contains prohibited/unrecognized fields: {sorted(unexpected)}"
            )
        events.append(
            MinimizedEvent(
                signal=Signal(item["signal"]), **{k: v for k, v in item.items() if k != "signal"}
            )
        )
    return tuple(events)

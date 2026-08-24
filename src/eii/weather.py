"""Privacy-preserving, local-first aggregate classroom signals."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .persistence import DatabaseStatus, backup_database, connect_database, database_status
from .weather_dp import DifferentialPrivacyReceipt, release_counts, validate_policy
from .weather_lineage import bind_database_lineage
from .weather_lock import synchronized as _synchronized
from .weather_migrations import WEATHER_MIGRATIONS
from .weather_privacy import (
    authorize_export,
    bind_key_epoch,
    bind_ledger_key,
    rotate_key_epoch,
    verify_export_ledger,
)
from .weather_publication import publish_artifact, recover_publications
from .weather_rendering import html_artifact, json_artifact, privacy_metadata
from .weather_types import MinimizedEvent, Signal, WeatherCell
from .weather_types import load_events as load_events
from .weather_universe import (
    PublicCell,
    aggregate_public_universe,
    aggregate_thresholded,
)
from .weather_universe import load_public_cell_universe as load_public_cell_universe

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
        dp_epsilon: float = 1.0,
        dp_total_epsilon: float = 10.0,
        public_cell_universe: frozenset[PublicCell] | None = None,
        max_cells_per_contributor_per_day: int = 3,
        database_instance_id: str | None = None,
        allow_database_fork: bool = False,
    ):
        if len(secret) < 32:
            raise ValueError("weather secret must contain at least 32 bytes")
        if minimum_group_size < 2:
            raise ValueError("minimum group size must be at least 2")
        if retention_days < 1:
            raise ValueError("retention must be positive")
        if max_events_per_contributor_per_cell < 1:
            raise ValueError("contribution bound must be positive")
        if max_cells_per_contributor_per_day < 1:
            raise ValueError("contributor cell bound must be positive")
        if public_cell_universe is not None and not public_cell_universe:
            raise ValueError("public cell universe cannot be empty")
        if count_granularity < 1 or minimum_export_interval_hours < 1:
            raise ValueError("count granularity and export interval must be positive")
        validate_policy(dp_epsilon, dp_total_epsilon)
        if (
            not key_epoch.strip()
            or len(key_epoch) > 64
            or any(ord(char) < 33 for char in key_epoch)
        ):
            raise ValueError("key epoch must be bounded printable text without whitespace")
        self.path, self.secret = path, secret
        self._implicit_ledger_key = ledger_key is None
        self.ledger_key = ledger_key or secret
        if len(self.ledger_key) < 32:
            raise ValueError("weather ledger key must contain at least 32 bytes")
        self.minimum_group_size, self.retention_days = minimum_group_size, retention_days
        self.max_events_per_contributor_per_cell = max_events_per_contributor_per_cell
        self.public_cell_universe = public_cell_universe
        self.max_cells_per_contributor_per_day = max_cells_per_contributor_per_day
        self.count_granularity = count_granularity
        self.minimum_export_interval_hours = minimum_export_interval_hours
        self.key_epoch = key_epoch
        self.dp_epsilon, self.dp_total_epsilon = dp_epsilon, dp_total_epsilon
        self._lock = threading.RLock()
        self.connection = connect_database(
            path, kind="weather", migrations=WEATHER_MIGRATIONS, check_same_thread=False
        )
        try:
            configured_budget = self.connection.execute(
                "SELECT epsilon_limit FROM dp_budget WHERE id=1"
            ).fetchone()
            if configured_budget and configured_budget[0] != self.dp_total_epsilon:
                raise ValueError("differential-privacy budget limit is immutable for this database")
            self.database_instance_id = bind_database_lineage(
                self.connection, database_instance_id, allow_database_fork=allow_database_fork
            )
            bind_key_epoch(self.connection, secret=self.secret, epoch=self.key_epoch)
            bind_ledger_key(self.connection, ledger_key=self.ledger_key)
            verify_export_ledger(self.connection, ledger_key=self.ledger_key)
            recover_publications(
                self.connection,
                ledger_key=self.ledger_key,
                minimum_interval=timedelta(hours=self.minimum_export_interval_hours),
            )
        except Exception:
            self.connection.close()
            raise

    @_synchronized
    def close(self) -> None:
        self.connection.close()

    @_synchronized
    def status(self) -> DatabaseStatus:
        return database_status(self.connection, kind="weather")

    @_synchronized
    def backup(self, destination: Path) -> None:
        backup_database(self.connection, destination)

    @_synchronized
    def rotate_privacy_key(self, *, new_secret: bytes, new_epoch: str) -> int:
        if len(new_secret) < 32:
            raise ValueError("weather secret must contain at least 32 bytes")
        if self._implicit_ledger_key:
            raise ValueError(
                "privacy-key rotation requires an independently supplied persistent ledger key"
            )
        purged = rotate_key_epoch(self.connection, new_secret=new_secret, new_epoch=new_epoch)
        self.secret, self.key_epoch = new_secret, new_epoch
        return purged

    @_synchronized
    def verify_export_ledger(self) -> str | None:
        return verify_export_ledger(self.connection, ledger_key=self.ledger_key)

    @_synchronized
    def verify_export_artifact(
        self, artifact: Path, *, artifact_kind: str, course_key: str | None = None
    ) -> None:
        self.verify_export_ledger()
        row = self.connection.execute(
            "SELECT artifact_hash FROM privacy_export_audit_v2 "
            "WHERE scope=? AND artifact_kind=? ORDER BY sequence DESC LIMIT 1",
            (course_key or "*", artifact_kind),
        ).fetchone()
        if row is None or hashlib.sha256(artifact.read_bytes()).hexdigest() != row[0]:
            raise ValueError(
                "weather artifact is absent from or inconsistent with the export ledger"
            )

    def __enter__(self) -> WeatherStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @_synchronized
    def ingest(self, event: MinimizedEvent) -> None:
        # Tokens are keyed and hashed immediately; the input value is never persisted.
        occurred_day = datetime.fromisoformat(event.occurred_at).astimezone(UTC).date().isoformat()
        cell = (
            event.course_key,
            event.activity_key,
            event.language,
            event.concept_id,
            event.signal,
        )
        if self.public_cell_universe is not None and cell not in self.public_cell_universe:
            raise ValueError("event cell is outside the declared public universe")
        linkage_parts = [self.key_epoch, occurred_day, event.course_key]
        if self.public_cell_universe is None:
            linkage_parts.extend(
                (event.activity_key, event.language, event.concept_id, event.signal.value)
            )
        linkage_parts.append(event.contribution_token)
        linkage_scope = "\x1f".join(linkage_parts)
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
        if self.public_cell_universe is not None:
            cells = self.connection.execute(
                """SELECT COUNT(*) FROM (SELECT DISTINCT activity_key,language,concept_id,signal
                FROM events WHERE contributor_hash=? AND occurred_at=? AND course_key=?)""",
                (contributor_hash, occurred_day, event.course_key),
            ).fetchone()[0]
            current_exists = existing > 0
            if not current_exists and cells >= self.max_cells_per_contributor_per_day:
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

    @_synchronized
    def purge_expired(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        cursor = self.connection.execute("DELETE FROM events WHERE occurred_at < ?", (cutoff,))
        self.connection.commit()
        return cursor.rowcount

    @_synchronized
    def aggregate(self, *, course_key: str | None = None) -> tuple[WeatherCell, ...]:
        if self.public_cell_universe is not None:
            return self._aggregate_public_universe(course_key)
        return aggregate_thresholded(
            self.connection,
            _RECOMMENDATIONS,
            course_key=course_key,
            minimum_group_size=self.minimum_group_size,
        )

    def _aggregate_public_universe(self, course_key: str | None) -> tuple[WeatherCell, ...]:
        assert self.public_cell_universe is not None
        return aggregate_public_universe(
            self.connection, self.public_cell_universe, _RECOMMENDATIONS, course_key
        )

    @_synchronized
    def export(
        self,
        destination: Path,
        *,
        course_key: str | None = None,
        now: datetime | None = None,
    ) -> None:
        cells, receipt, snapshot_hash, exported_at = self._privacy_cells(
            course_key=course_key, now=now
        )
        fixed_universe = self.public_cell_universe is not None
        privacy = privacy_metadata(
            receipt,
            minimum_group_size=self.minimum_group_size,
            retention_days=self.retention_days,
            per_cell_event_bound=self.max_events_per_contributor_per_cell,
            maximum_cells=self.max_cells_per_contributor_per_day if fixed_universe else 1,
            count_granularity=self.count_granularity,
            minimum_export_interval_hours=self.minimum_export_interval_hours,
            key_epoch=self.key_epoch,
            fixed_public_universe=fixed_universe,
        )
        self._publish_artifact(
            destination,
            json_artifact(cells, receipt, privacy),
            artifact_kind="json",
            course_key=course_key,
            snapshot_hash=snapshot_hash,
            exported_at=exported_at,
        )

    def _privacy_cells(
        self, *, course_key: str | None, now: datetime | None = None
    ) -> tuple[tuple[WeatherCell, ...], DifferentialPrivacyReceipt, str, datetime]:
        # Noise is applied to the raw bounded counts. Any output rounding happens
        # afterwards as privacy-preserving post-processing.
        cells = self.aggregate(course_key=course_key)
        snapshot_hash = hashlib.sha256(
            json.dumps([asdict(cell) for cell in cells], sort_keys=True, default=str).encode()
        ).hexdigest()
        exported_at = now or datetime.now(UTC)
        scope = course_key or "*"
        strategy = "global" if course_key is None else "course-partitioned"
        authorize_export(
            self.connection,
            scope=scope,
            strategy=strategy,
            snapshot_hash=snapshot_hash,
            exported_at=exported_at,
            minimum_interval=timedelta(hours=self.minimum_export_interval_hours),
        )
        released, receipt = release_counts(
            self.connection,
            scope=course_key or "*",
            snapshot_hash=snapshot_hash,
            cells=[asdict(cell) for cell in cells],
            epsilon=self.dp_epsilon,
            epsilon_limit=self.dp_total_epsilon,
            event_sensitivity=(
                self.max_events_per_contributor_per_cell * self.max_cells_per_contributor_per_day
                if self.public_cell_universe is not None
                else self.max_events_per_contributor_per_cell
            ),
            contributor_sensitivity=(
                self.max_cells_per_contributor_per_day
                if self.public_cell_universe is not None
                else 1
            ),
        )
        private_cells = tuple(
            self._round_private_cell(WeatherCell(**{**cell, "signal": Signal(cell["signal"])}))
            for cell in released
        )
        return private_cells, receipt, snapshot_hash, exported_at

    def _publish_artifact(
        self,
        destination: Path,
        artifact: bytes,
        *,
        artifact_kind: str,
        course_key: str | None,
        snapshot_hash: str,
        exported_at: datetime,
    ) -> None:
        publish_artifact(
            self.connection,
            destination,
            artifact,
            scope=course_key or "*",
            strategy="global" if course_key is None else "course-partitioned",
            artifact_kind=artifact_kind,
            exported_at=exported_at,
            snapshot_hash=snapshot_hash,
            minimum_interval=timedelta(hours=self.minimum_export_interval_hours),
            ledger_key=self.ledger_key,
        )

    def _round_private_cell(self, cell: WeatherCell) -> WeatherCell:
        """Round already-private estimates without consulting sensitive data."""
        granularity = self.count_granularity
        contributors = max(0, round(cell.contributor_count / granularity) * granularity)
        events = max(contributors, round(cell.event_count / granularity) * granularity)
        return WeatherCell(
            cell.course_key,
            cell.activity_key,
            cell.language,
            cell.concept_id,
            cell.signal,
            events,
            contributors,
            cell.explanation,
            cell.recommendation,
        )

    @_synchronized
    def export_html(self, destination: Path, *, course_key: str | None = None) -> None:
        cells, receipt, snapshot_hash, exported_at = self._privacy_cells(course_key=course_key)
        self._publish_artifact(
            destination,
            html_artifact(
                cells,
                receipt,
                minimum_group_size=self.minimum_group_size,
                retention_days=self.retention_days,
                fixed_public_universe=self.public_cell_universe is not None,
            ),
            artifact_kind="html",
            course_key=course_key,
            snapshot_hash=snapshot_hash,
            exported_at=exported_at,
        )

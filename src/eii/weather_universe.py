"""Declared, data-independent Classroom Weather publication cells."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .weather_types import Signal, WeatherCell

PublicCell = tuple[str, str, str, str, Signal]


def aggregate_thresholded(
    connection: sqlite3.Connection,
    recommendations: dict[Signal, str],
    *,
    course_key: str | None,
    minimum_group_size: int,
) -> tuple[WeatherCell, ...]:
    """Aggregate compatibility-mode cells after exact contributor suppression."""
    if course_key:
        rows = connection.execute(
            """SELECT course_key, activity_key, language, concept_id, signal, COUNT(*),
            COUNT(DISTINCT contributor_hash) FROM events WHERE course_key = ?
            GROUP BY course_key, activity_key, language, concept_id, signal
            HAVING COUNT(DISTINCT contributor_hash) >= ? ORDER BY COUNT(*) DESC""",
            (course_key, minimum_group_size),
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT course_key, activity_key, language, concept_id, signal, COUNT(*),
            COUNT(DISTINCT contributor_hash) FROM events
            GROUP BY course_key, activity_key, language, concept_id, signal
            HAVING COUNT(DISTINCT contributor_hash) >= ? ORDER BY COUNT(*) DESC""",
            (minimum_group_size,),
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
            recommendations[Signal(row[4])],
        )
        for row in rows
    )


def load_public_cell_universe(path: Path) -> frozenset[PublicCell]:
    """Load a declared, non-data-dependent set of publishable Weather cells."""
    document = json.loads(path.read_text("utf-8"))
    if not isinstance(document, dict) or set(document) != {"schema_version", "cells"}:
        raise ValueError("public cell universe fields do not match schema")
    if document["schema_version"] != "1.0" or not isinstance(document["cells"], list):
        raise ValueError("unsupported public cell universe")
    result: set[PublicCell] = set()
    required = {"course_key", "activity_key", "language", "concept_id", "signal"}
    for item in document["cells"]:
        if (
            not isinstance(item, dict)
            or set(item) != required
            or not all(isinstance(item[key], str) and item[key] for key in required)
        ):
            raise ValueError("invalid public cell universe entry")
        result.add(
            (
                item["course_key"],
                item["activity_key"],
                item["language"],
                item["concept_id"],
                Signal(item["signal"]),
            )
        )
    if not result:
        raise ValueError("public cell universe cannot be empty")
    return frozenset(result)


def aggregate_public_universe(
    connection: sqlite3.Connection,
    universe: frozenset[PublicCell],
    recommendations: dict[Signal, str],
    course_key: str | None,
) -> tuple[WeatherCell, ...]:
    """Return every declared cell, including zero-count cells."""
    rows = connection.execute(
        """SELECT course_key,activity_key,language,concept_id,signal,COUNT(*),
        COUNT(DISTINCT contributor_hash) FROM events
        GROUP BY course_key,activity_key,language,concept_id,signal"""
    ).fetchall()
    counts = {(row[0], row[1], row[2], row[3], Signal(row[4])): (row[5], row[6]) for row in rows}
    cells = sorted(
        (cell for cell in universe if course_key is None or cell[0] == course_key),
        key=lambda cell: tuple(str(value) for value in cell),
    )
    return tuple(
        WeatherCell(
            *cell,
            counts.get(cell, (0, 0))[0],
            counts.get(cell, (0, 0))[1],
            "Differentially private estimates over a fixed public cell universe.",
            recommendations[cell[4]],
        )
        for cell in cells
    )

"""Serialization and presentation for privacy-reviewed Weather releases."""

from __future__ import annotations

import json
from dataclasses import asdict
from html import escape
from typing import Any

from .weather_dp import DifferentialPrivacyReceipt
from .weather_types import WeatherCell


def json_artifact(
    cells: tuple[WeatherCell, ...],
    receipt: DifferentialPrivacyReceipt,
    privacy: dict[str, Any],
) -> bytes:
    """Serialize the stable public Weather JSON schema."""
    payload = {"schema_version": "3.0", "privacy": privacy, "cells": [asdict(c) for c in cells]}
    return (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode()


def privacy_metadata(
    receipt: DifferentialPrivacyReceipt,
    *,
    minimum_group_size: int,
    retention_days: int,
    per_cell_event_bound: int,
    maximum_cells: int,
    count_granularity: int,
    minimum_export_interval_hours: int,
    key_epoch: str,
    fixed_public_universe: bool,
) -> dict[str, Any]:
    """Describe the exact mechanism and bounded adjacency used for a release."""
    return {
        "minimum_group_size": minimum_group_size,
        "retention_days": retention_days,
        "max_events_per_contributor_per_cell_per_day": per_cell_event_bound,
        "timestamp_precision": "utc-day",
        "raw_conversations_stored": False,
        "direct_identifiers_stored": False,
        "count_granularity": count_granularity,
        "minimum_export_interval_hours": minimum_export_interval_hours,
        "key_epoch": key_epoch,
        "contribution_linkage": (
            "within-course-day-bounded-pseudonymous"
            if fixed_public_universe
            else "within-cell-day-only-pseudonymous"
        ),
        "mechanism": "central-laplace-differential-privacy",
        "protected_unit": (
            "bounded-contributor-course-utc-day"
            if fixed_public_universe
            else "bounded-contributor-cell-utc-day"
        ),
        "epsilon_per_release": receipt.epsilon_per_release,
        "epsilon_spent": receipt.epsilon_spent,
        "epsilon_limit": receipt.epsilon_limit,
        "composition": "basic-sequential",
        "release_memoization": "scope-snapshot-policy-bound",
        "event_count_sensitivity": per_cell_event_bound * maximum_cells,
        "contributor_count_sensitivity": maximum_cells,
        "artifact_ledger_binding": "sha256-exact-serialized-bytes",
        "cell_selection_privacy": (
            "fixed-public-universe-end-to-end-central-dp"
            if fixed_public_universe
            else "exact-k-threshold-not-end-to-end-dp"
        ),
    }


def html_artifact(
    cells: tuple[WeatherCell, ...],
    receipt: DifferentialPrivacyReceipt,
    *,
    minimum_group_size: int,
    retention_days: int,
    fixed_public_universe: bool,
) -> bytes:
    """Render a self-contained, escaped teacher report."""
    rows = "".join(
        f"<tr><td>{escape(cell.activity_key)}</td><td>{escape(cell.language)}</td>"
        f"<td>{escape(cell.concept_id)}</td><td>{escape(cell.signal.value)}</td>"
        f"<td>{cell.event_count}</td><td>{cell.contributor_count}</td>"
        f"<td>{escape(cell.recommendation)}</td></tr>"
        for cell in cells
    )
    if not rows:
        rows = '<tr><td colspan="7">No groups meet the privacy threshold.</td></tr>'
    selection = (
        "Cells come from a fixed public universe; zero-count cells are retained."
        if fixed_public_universe
        else f"Only groups with at least {minimum_group_size} pseudonymous contributors are shown."
    )
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Classroom Weather Map</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:auto;padding:2rem}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccd;padding:.55rem;text-align:left}}th{{background:#eef}}.privacy{{background:#eaf7ef;padding:1rem}}</style>
<main><h1>Classroom Weather Map</h1><div class="privacy"><b>Privacy boundary:</b> {selection}
Events expire after {retention_days} days. No conversation text, direct identity, token, or contributor hash is present.</div>
<p>Differentially private Laplace estimates are shown (ε={receipt.epsilon_per_release:g} for this
memoized release; cumulative ε={receipt.epsilon_spent:g}/{receipt.epsilon_limit:g}). Counts may be zero
or differ from exact internal aggregates.</p>
<table><caption>Aggregated learning-difficulty signals</caption><thead><tr><th scope="col">Activity</th><th scope="col">Language</th><th scope="col">Concept</th><th scope="col">Signal</th>
<th scope="col">Events</th><th scope="col">Contributors</th><th scope="col">Suggested intervention</th></tr></thead><tbody>{rows}</tbody></table></main></html>"""
    return html.encode()

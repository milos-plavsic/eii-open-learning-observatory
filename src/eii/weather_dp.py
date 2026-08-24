"""Persistent, memoized differential privacy for Weather Map releases."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DifferentialPrivacyReceipt:
    epsilon_per_release: float
    epsilon_spent: float
    epsilon_limit: float
    reused_release: bool


def validate_policy(epsilon: float, epsilon_limit: float) -> None:
    if (
        not math.isfinite(epsilon)
        or not math.isfinite(epsilon_limit)
        or epsilon <= 0
        or epsilon_limit <= 0
        or epsilon > epsilon_limit
    ):
        raise ValueError(
            "differential-privacy epsilon values must be finite, positive, and within budget"
        )


def laplace_noise(*, sensitivity: float, epsilon: float) -> float:
    """Draw Laplace noise using a cryptographically secure uniform source."""
    if not math.isfinite(sensitivity) or sensitivity <= 0:
        raise ValueError("sensitivity must be finite and positive")
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be finite and positive")
    # Map the 53-bit integer lattice into the open interval symmetrically. The
    # denominator makes complementary draws exact floating-point opposites.
    uniform = ((secrets.randbits(53) + 1) / (2**53 + 1)) - 0.5
    return -(sensitivity / epsilon) * math.copysign(1.0, uniform) * math.log1p(-2 * abs(uniform))


def release_counts(
    connection: sqlite3.Connection,
    *,
    scope: str,
    snapshot_hash: str,
    cells: list[dict[str, Any]],
    epsilon: float,
    epsilon_limit: float,
    event_sensitivity: int,
) -> tuple[list[dict[str, Any]], DifferentialPrivacyReceipt]:
    """Return one memoized DP release and atomically account for its privacy cost."""
    validate_policy(epsilon, epsilon_limit)
    if event_sensitivity < 1:
        raise ValueError("event sensitivity must be positive")
    policy_hash = hashlib.sha256(
        json.dumps(
            {
                "mechanism": "laplace",
                "epsilon": epsilon,
                "event_sensitivity": event_sensitivity,
                "contributor_sensitivity": 1,
                "allocation": "equal-split",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    key = hashlib.sha256(f"{scope}\0{snapshot_hash}\0{policy_hash}".encode()).hexdigest()

    connection.execute("BEGIN IMMEDIATE")
    try:
        configured = connection.execute("SELECT epsilon_limit FROM dp_budget WHERE id=1").fetchone()
        if configured and not math.isclose(configured[0], epsilon_limit, rel_tol=0, abs_tol=1e-12):
            raise ValueError("differential-privacy budget limit is immutable for this database")
        connection.execute(
            "INSERT OR IGNORE INTO dp_budget(id,epsilon_limit,epsilon_spent) VALUES (1,?,0)",
            (epsilon_limit,),
        )
        cached = connection.execute(
            "SELECT payload_json FROM dp_releases WHERE release_key=?", (key,)
        ).fetchone()
        spent, limit = connection.execute(
            "SELECT epsilon_spent,epsilon_limit FROM dp_budget WHERE id=1"
        ).fetchone()
        if not cells:
            connection.commit()
            return [], DifferentialPrivacyReceipt(0.0, spent, limit, True)
        if cached:
            connection.commit()
            return json.loads(cached[0]), DifferentialPrivacyReceipt(epsilon, spent, limit, True)
        if spent + epsilon > limit + 1e-12:
            raise ValueError("differential-privacy budget exhausted")

        # Each released vector contains two count queries. Sequential composition
        # allocates half of the release epsilon to each query.
        count_epsilon = epsilon / 2
        released: list[dict[str, Any]] = []
        for cell in cells:
            item = dict(cell)
            item["event_count"] = max(
                0,
                round(
                    int(item["event_count"])
                    + laplace_noise(sensitivity=event_sensitivity, epsilon=count_epsilon)
                ),
            )
            item["contributor_count"] = max(
                0,
                round(
                    int(item["contributor_count"])
                    + laplace_noise(sensitivity=1, epsilon=count_epsilon)
                ),
            )
            item["explanation"] = (
                "Differentially private estimates derived from a thresholded contributor group."
            )
            released.append(item)
        payload_json = json.dumps(released, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "INSERT INTO dp_releases VALUES (?,?,?,?,?,?)",
            (key, scope, snapshot_hash, policy_hash, epsilon, payload_json),
        )
        connection.execute(
            "UPDATE dp_budget SET epsilon_spent=epsilon_spent+? WHERE id=1", (epsilon,)
        )
        connection.commit()
        return released, DifferentialPrivacyReceipt(epsilon, spent + epsilon, limit, False)
    except Exception:
        connection.rollback()
        raise

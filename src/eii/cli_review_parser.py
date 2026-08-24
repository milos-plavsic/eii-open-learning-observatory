"""Argument definitions for human-review and blinded-study commands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path


def add_review_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_audit_log_arguments: Callable[[argparse.ArgumentParser], None],
) -> None:
    review = commands.add_parser("review", help="append a human decision for an evidence finding")
    review.add_argument("finding_id")
    review.add_argument(
        "decision",
        choices=(
            "confirmed",
            "rejected",
            "resolved",
            "intentional_localization",
            "partially_correct",
            "cannot_determine",
        ),
    )
    review.add_argument("--reviewer", required=True)
    review.add_argument("--rationale", required=True)
    review.add_argument("--reviews", type=Path, required=True)
    review.add_argument(
        "--evidence-quality", choices=("sufficient", "incomplete", "wrong", "absent")
    )
    review.add_argument(
        "--severity-assessment", choices=("info", "low", "medium", "high", "critical")
    )
    review.add_argument("--usefulness", type=int, choices=range(1, 6))
    review.add_argument("--actionability", choices=("usable", "needs_revision", "unusable"))
    review.add_argument("--seconds-spent", type=int)
    review.add_argument("--review-round")

    regression = commands.add_parser(
        "regression-check", help="verify whether recorded course gaps persist"
    )
    regression.add_argument("cases", type=Path)
    regression.add_argument("evidence", type=Path)
    regression.add_argument("--output", type=Path, default=Path("regression-results.json"))
    regression.add_argument("--fail-if-present", action="store_true")

    study_init = commands.add_parser(
        "review-study-init", help="freeze blinded randomized review assignments"
    )
    study_init.add_argument("evidence", type=Path)
    study_init.add_argument("--database", type=Path, required=True)
    study_init.add_argument("--study-id", required=True)
    study_init.add_argument("--reviewers", required=True)
    study_init.add_argument("--seed-file", type=Path, required=True)
    study_init.add_argument(
        "--credentials-output",
        type=Path,
        help="write one-time reviewer bearer tokens; protect and delete after distribution",
    )
    study_next = commands.add_parser("review-study-next", help="open the next blinded assignment")
    study_next.add_argument("--database", type=Path, required=True)
    study_next.add_argument("--study-id", required=True)
    study_next.add_argument("--reviewer", required=True)
    study_next.add_argument("--output", type=Path, required=True)
    study_record = commands.add_parser(
        "review-study-record", help="record a completed blinded assignment"
    )
    study_record.add_argument("record", type=Path)
    study_record.add_argument("--database", type=Path, required=True)
    study_record.add_argument("--study-id", required=True)
    study_record.add_argument("--reviewer", required=True)
    study_export = commands.add_parser(
        "review-study-export", help="export versioned review decisions"
    )
    study_export.add_argument("--database", type=Path, required=True)
    study_export.add_argument("--study-id", required=True)
    study_export.add_argument("--output", type=Path, required=True)
    study_serve = commands.add_parser(
        "review-study-serve", help="serve the authenticated blinded review UI"
    )
    study_serve.add_argument("--database", type=Path, required=True)
    study_serve.add_argument("--study-id", required=True)
    study_serve.add_argument("--host", default="127.0.0.1")
    study_serve.add_argument("--port", type=int, default=8090)
    add_audit_log_arguments(study_serve)

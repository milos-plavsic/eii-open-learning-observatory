"""Human review, regression, and blinded-study CLI command group."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TextIO, cast

from .audit_log import ManagedAuditLog
from .domain import FindingStatus, ReviewDecision
from .fixture_export import verify_finding_regressions
from .reviews import append_review
from .secureio import write_private_text
from .study import ReviewStudy, serve_study


def handle_review_command(
    args: argparse.Namespace,
    command_parser: argparse.ArgumentParser,
    secret_text: Callable[[Any, str, argparse.ArgumentParser], str],
) -> int | None:
    if args.command == "review":
        decision = ReviewDecision(
            args.finding_id,
            FindingStatus(args.decision),
            args.reviewer,
            args.rationale,
            datetime.now(UTC).isoformat(),
            args.evidence_quality,
            args.severity_assessment,
            args.usefulness,
            args.actionability,
            args.seconds_spent,
            args.review_round,
        )
        append_review(args.reviews, decision)
        print(f"Recorded {args.decision} for {args.finding_id}")
        return 0
    if args.command == "regression-check":
        regression_result = verify_finding_regressions(args.cases, args.evidence)
        args.output.write_text(
            json.dumps(regression_result, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        print(
            f"Regression cases: {regression_result['still_present']} still present, {regression_result['resolved']} resolved"
        )
        return 2 if args.fail_if_present and regression_result["still_present"] else 0
    if args.command == "review-study-init":
        with ReviewStudy(args.database) as study:
            credentials = study.initialize(
                args.evidence,
                study_id=args.study_id,
                reviewers=tuple(
                    value.strip() for value in args.reviewers.split(",") if value.strip()
                ),
                seed=secret_text(args.seed_file, "review study seed", command_parser),
            )
        if args.credentials_output:
            write_private_text(args.credentials_output, json.dumps(credentials, indent=2) + "\n")
        print(f"Initialized blinded review study {args.study_id}")
        return 0
    if args.command == "review-study-next":
        with ReviewStudy(args.database) as study:
            assignment = study.next_assignment(args.study_id, args.reviewer)
        args.output.write_text(json.dumps(assignment, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(
            "Review study complete"
            if assignment is None
            else f"Opened assignment {assignment['sequence']}"
        )
        return 0
    if args.command == "review-study-record":
        record = json.loads(args.record.read_text("utf-8"))
        finding_id = str(record.pop("finding_id"))
        with ReviewStudy(args.database) as study:
            study.record(args.study_id, args.reviewer, finding_id, **record)
        print(f"Recorded blinded review for {finding_id}")
        return 0
    if args.command == "review-study-export":
        with ReviewStudy(args.database) as study:
            study.export(args.study_id, args.output)
        print(f"Exported review study {args.study_id}: {args.output}")
        return 0
    if args.command == "review-study-serve":
        if args.audit_log:
            with ManagedAuditLog(
                args.audit_log,
                max_bytes=args.audit_log_max_bytes,
                retention_days=args.audit_log_retention_days,
            ) as audit_stream:
                serve_study(
                    args.database,
                    args.study_id,
                    host=args.host,
                    port=args.port,
                    audit_stream=cast(TextIO, audit_stream),
                )
        else:
            serve_study(args.database, args.study_id, host=args.host, port=args.port)
        return 0
    return None

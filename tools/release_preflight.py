#!/usr/bin/env python3
"""Validate a built release candidate without publishing it."""

from argparse import ArgumentParser
from pathlib import Path

from eii.release_preflight import (
    require_clean_source_tree,
    validate_release_candidate,
    write_approval_evidence,
)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--approval-output", type=Path)
    parser.add_argument("--candidate-run-id")
    parser.add_argument("--approval-run-id")
    parser.add_argument("--github-repository")
    parser.add_argument("--actor")
    parser.add_argument("--environment")
    parser.add_argument("--run-url")
    parser.add_argument(
        "--receipt",
        action="append",
        default=[],
        metavar="CHECK=PATH",
        help="verified check output to hash into approval evidence",
    )
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    validate_release_candidate(tuple(args.artifacts), expected_version=args.version, tag=args.tag)
    if args.repository is not None:
        revision = require_clean_source_tree(args.repository, revision=args.revision)
    else:
        revision = args.revision
    if args.approval_output is not None:
        metadata = (
            args.candidate_run_id,
            args.approval_run_id,
            args.github_repository,
            args.actor,
            args.environment,
            args.run_url,
        )
        if revision is None or any(item is None for item in metadata):
            parser.error("approval output requires repository/revision and all approval metadata")
        try:
            receipts = dict(item.split("=", 1) for item in args.receipt)
        except ValueError:
            parser.error("each --receipt must be CHECK=PATH")
        if len(receipts) != len(args.receipt):
            parser.error("approval receipt names must be unique")
        write_approval_evidence(
            args.approval_output,
            tuple(args.artifacts),
            version=args.version,
            revision=revision,
            candidate_run_id=args.candidate_run_id,
            approval_run_id=args.approval_run_id,
            repository=args.github_repository,
            actor=args.actor,
            environment=args.environment,
            run_url=args.run_url,
            receipts={name: Path(path) for name, path in receipts.items()},
        )
    print(f"Release candidate version binding verified: {args.version}")


if __name__ == "__main__":
    main()

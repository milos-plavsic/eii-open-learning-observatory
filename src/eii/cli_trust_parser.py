"""Arguments for cryptographic review and classroom privacy-key operations."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_trust_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    initialize = commands.add_parser(
        "safety-review-init", help="bind an unsigned human review to an exact safety-case result"
    )
    initialize.add_argument("case", type=Path)
    initialize.add_argument("--fixture-id", required=True)
    initialize.add_argument("--reviewer", required=True)
    initialize.add_argument("--decision", choices=("approve", "reject"), required=True)
    initialize.add_argument("--rationale", required=True)
    initialize.add_argument("--output", type=Path, required=True)

    review = commands.add_parser(
        "safety-review-sign", help="sign one human safety-review JSON record"
    )
    review.add_argument("review", type=Path)
    review.add_argument("--private-key-file", type=Path, required=True)
    review.add_argument("--public-key-file", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)

    generate = commands.add_parser(
        "weather-key-generate", help="generate a private 256-bit classroom privacy secret"
    )
    generate.add_argument("--output", type=Path, required=True)

    rotate = commands.add_parser(
        "weather-key-rotate", help="backup, purge linked events, and activate a new key epoch"
    )
    rotate.add_argument("--database", type=Path, required=True)
    rotate.add_argument("--current-secret-file", type=Path, required=True)
    rotate.add_argument("--new-secret-file", type=Path, required=True)
    rotate.add_argument("--ledger-key-file", type=Path, required=True)
    rotate.add_argument("--current-epoch", required=True)
    rotate.add_argument("--new-epoch", required=True)
    rotate.add_argument("--backup", type=Path, required=True)

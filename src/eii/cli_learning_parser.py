"""Argument definitions for curriculum and tutor-safety commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli_audit import add_semantic_arguments


def add_learning_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    audit = commands.add_parser("audit", help="audit one or more course releases")
    audit.add_argument("source", type=Path, nargs="+")
    audit.add_argument("--languages", help="comma-separated BCP-47 language tags")
    audit.add_argument("--output", type=Path, default=Path("eii-report"))
    audit.add_argument("--glossary", type=Path)
    audit.add_argument("--model-base-url")
    audit.add_argument("--model")
    audit.add_argument("--provider", default="openai-compatible")
    audit.add_argument("--api-key-env", default="EII_MODEL_API_KEY")
    add_semantic_arguments(audit)
    audit.add_argument("--reviews", type=Path, help="append-only JSONL human review log")

    mri = commands.add_parser("mri", help="run an evidence-backed curriculum audit")
    mri.add_argument("source", type=Path)
    mri.add_argument("--language")
    mri.add_argument("--spec", type=Path, required=True)
    mri.add_argument("--output", type=Path, default=Path("eii-mri-report"))
    mri.add_argument("--model-base-url")
    mri.add_argument("--model")
    mri.add_argument("--provider", default="openai-compatible")
    mri.add_argument("--api-key-env", default="EII_MODEL_API_KEY")
    mri.add_argument("--generated-question-count", type=int, default=5)

    safety = commands.add_parser(
        "safety-case", help="evaluate a replayed educational assistant release"
    )
    safety.add_argument("source", type=Path)
    safety.add_argument("--suite", type=Path, required=True)
    safety.add_argument("--responses", type=Path)
    safety.add_argument("--prompt-version", required=True)
    safety.add_argument("--language")
    safety.add_argument("--output", type=Path, default=Path("eii-safety-case.json"))
    safety.add_argument("--model-base-url")
    safety.add_argument("--model")
    safety.add_argument("--provider", default="openai-compatible")
    safety.add_argument("--api-key-env", default="EII_MODEL_API_KEY")
    safety.add_argument("--human-reviews", type=Path)

    suite_init = commands.add_parser(
        "safety-suite-init", help="write built-in educational AI risk fixtures"
    )
    suite_init.add_argument("--languages", default="en")
    suite_init.add_argument("--output", type=Path, required=True)

    safety_sign = commands.add_parser(
        "safety-sign", help="sign a verified safety case with an evaluator key"
    )
    safety_sign.add_argument("case", type=Path)
    safety_sign.add_argument("--private-key-file", type=Path, required=True)
    safety_sign.add_argument("--course", type=Path, required=True)
    safety_sign.add_argument("--language")

    safety_verify = commands.add_parser(
        "safety-verify", help="verify safety-case integrity and evaluator signature"
    )
    safety_verify.add_argument("case", type=Path)
    safety_verify.add_argument("--public-key-file", type=Path, required=True)
    safety_verify.add_argument("--course", type=Path, required=True)
    safety_verify.add_argument("--language")
    safety_verify.add_argument("--trusted-reviewer-fingerprint", action="append", default=[])
    safety_verify.add_argument(
        "--require-passing-gates",
        action="store_true",
        help="also apply the built-in release-authorization policy",
    )

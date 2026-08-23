"""Argument schema for the EII command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .cli_audit import add_semantic_arguments
from .cli_trust_parser import add_trust_commands


def _add_audit_log_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--audit-log", type=Path, help="append privacy-bounded request metadata as JSONL"
    )
    command.add_argument("--audit-log-max-bytes", type=int, default=10 * 1024 * 1024)
    command.add_argument("--audit-log-retention-days", type=int, default=30)


def _add_appliance_server_arguments(server: argparse.ArgumentParser) -> None:
    server.add_argument("--root", type=Path, required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    server.add_argument("--max-request-workers", type=int, default=64)
    server.add_argument("--max-concurrent-queries", type=int, default=4)
    server.add_argument("--max-queries-per-minute", type=int, default=30)
    server.add_argument("--max-rate-limit-clients", type=int, default=4096)
    server.add_argument("--shutdown-grace-seconds", type=float, default=30.0)
    server.add_argument(
        "--query-token-file",
        type=Path,
        help="optional shared classroom bearer token; file must not be packaged with content",
    )
    _add_audit_log_arguments(server)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="eii", description="EII Open Learning Observatory")
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    add_trust_commands(commands)

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

    weather = commands.add_parser(
        "weather", help="ingest minimized events and export private aggregates"
    )
    weather.add_argument("events", type=Path)
    weather.add_argument("--database", type=Path, required=True)
    weather.add_argument("--secret-file", type=Path, required=True)
    weather.add_argument("--ledger-key-file", type=Path)
    weather.add_argument("--minimum-group-size", type=int, default=5)
    weather.add_argument("--retention-days", type=int, default=30)
    weather.add_argument("--count-granularity", type=int, default=2)
    weather.add_argument("--minimum-export-interval-hours", type=int, default=24)
    weather.add_argument("--key-epoch", default="v1")
    weather.add_argument("--course-key")
    weather.add_argument("--output", type=Path, default=Path("weather-map.json"))
    weather.add_argument("--html-output", type=Path)

    check = commands.add_parser("appliance-check", help="assess hardware for offline model serving")
    check.add_argument("--path", type=Path, default=Path("."))

    package = commands.add_parser(
        "appliance-package", help="create an integrity-protected offline package"
    )
    package.add_argument("input", type=Path, nargs="+")
    package.add_argument("--version", required=True)
    package.add_argument("--private-key-file", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--model-base-url")
    package.add_argument("--model")
    package.add_argument("--course-path", help="package-relative path, e.g. content/course.json")
    package.add_argument("--language")
    package.add_argument("--safety-case", type=Path)
    package.add_argument("--trusted-reviewer-fingerprint", action="append", default=[])

    install = commands.add_parser(
        "appliance-install", help="verify, stage and activate an offline package"
    )
    install.add_argument("package", type=Path)
    install.add_argument("--root", type=Path, required=True)
    install.add_argument("--public-key-file", type=Path)
    install.add_argument("--use-trust-store", action="store_true")
    install.add_argument(
        "--safety-public-key-file", type=Path, help="independent evaluator key required for updates"
    )
    install.add_argument("--trusted-reviewer-fingerprint", action="append", default=[])

    server = commands.add_parser(
        "appliance-serve", help="serve the active release on the school LAN"
    )
    _add_appliance_server_arguments(server)

    appliance_config = commands.add_parser(
        "appliance-configure", help="select classroom courses and tutor behavior"
    )
    appliance_config.add_argument("--root", type=Path, required=True)
    appliance_config.add_argument("--courses", required=True)
    appliance_config.add_argument("--languages", required=True)
    appliance_config.add_argument(
        "--assistant-behavior", choices=("hint-first", "socratic", "direct"), default="hint-first"
    )

    appliance_rollback = commands.add_parser(
        "appliance-rollback", help="atomically reactivate the previous release"
    )
    appliance_rollback.add_argument("--root", type=Path, required=True)

    appliance_recover = commands.add_parser(
        "appliance-recover", help="recover activation state from local history"
    )
    appliance_recover.add_argument("--root", type=Path, required=True)

    onboarding = commands.add_parser(
        "appliance-onboarding", help="create an offline QR connection page"
    )
    onboarding.add_argument("--url", required=True)
    onboarding.add_argument("--output", type=Path, required=True)

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
    _add_audit_log_arguments(study_serve)

    trust_init = commands.add_parser(
        "appliance-trust-init", help="initialize the publisher trust store"
    )
    trust_init.add_argument("--root", type=Path, required=True)
    trust_init.add_argument("--public-key-file", type=Path, required=True)

    rotation_create = commands.add_parser(
        "appliance-trust-rotation-create", help="authorize a new publisher key"
    )
    rotation_create.add_argument("--current-private-key", type=Path, required=True)
    rotation_create.add_argument("--current-public-key", type=Path, required=True)
    rotation_create.add_argument("--new-public-key", type=Path, required=True)
    rotation_create.add_argument("--revoke-old", action="store_true")
    rotation_create.add_argument("--output", type=Path, required=True)

    rotation_apply = commands.add_parser(
        "appliance-trust-rotation-apply", help="verify and apply key rotation"
    )
    rotation_apply.add_argument("authorization", type=Path)
    rotation_apply.add_argument("--root", type=Path, required=True)

    compare = commands.add_parser("compare", help="compare evidence between course releases")
    compare.add_argument("previous", type=Path)
    compare.add_argument("current", type=Path)
    compare.add_argument("--output", type=Path, default=Path("eii-comparison.json"))
    compare.add_argument("--fail-on-regression", action="store_true")

    validate = commands.add_parser(
        "validate", help="validate an evidence bundle or complete audit directory"
    )
    validate.add_argument("bundle", type=Path)

    audit_sign = commands.add_parser("audit-sign", help="sign a complete validated audit directory")
    audit_sign.add_argument("directory", type=Path)
    audit_sign.add_argument("--private-key-file", type=Path, required=True)
    audit_sign.add_argument("--public-key-file", type=Path, required=True)
    audit_sign.add_argument("--signer-id", required=True)
    audit_sign.add_argument("--purpose", default="course-quality-audit")
    audit_verify = commands.add_parser("audit-verify", help="authenticate a signed audit directory")
    audit_verify.add_argument("directory", type=Path)
    audit_verify.add_argument("--public-key-file", type=Path, required=True)
    audit_verify.add_argument("--authorization-policy", type=Path)
    audit_verify.add_argument("--expected-purpose")

    database_status = commands.add_parser(
        "database-status", help="verify a managed SQLite database"
    )
    database_status.add_argument("database", type=Path)
    database_status.add_argument("--kind", choices=("weather", "review-study"), required=True)

    database_backup = commands.add_parser(
        "database-backup", help="create and verify an online SQLite backup"
    )
    database_backup.add_argument("database", type=Path)
    database_backup.add_argument("--kind", choices=("weather", "review-study"), required=True)
    database_backup.add_argument("--output", type=Path, required=True)

    plct_conformance = commands.add_parser(
        "plct-conformance", help="validate the proposed PLCT adapter boundary"
    )
    plct_conformance.add_argument("export", type=Path)
    plct_conformance.add_argument("--previous", type=Path)
    plct_conformance.add_argument("--output", type=Path, required=True)
    plct_attest = commands.add_parser(
        "plct-attest", help="sign Petlja's review of a conformance report"
    )
    plct_attest.add_argument("report", type=Path)
    plct_attest.add_argument("--maintainer", required=True)
    plct_attest.add_argument("--repository-revision", required=True)
    plct_attest.add_argument("--private-key-file", type=Path, required=True)
    plct_attest.add_argument("--public-key-file", type=Path, required=True)
    plct_attest.add_argument("--output", type=Path, required=True)
    plct_verify = commands.add_parser(
        "plct-attestation-verify", help="verify Petlja conformance attestation"
    )
    plct_verify.add_argument("attestation", type=Path)
    plct_verify.add_argument("--report", type=Path, required=True)
    plct_verify.add_argument("--public-key-file", type=Path, required=True)
    release_sign = commands.add_parser("release-sign", help="sign release checksums with Ed25519")
    release_sign.add_argument("evidence", type=Path)
    release_sign.add_argument("--private-key-file", type=Path, required=True)
    release_sign.add_argument("--public-key-file", type=Path, required=True)
    release_verify = commands.add_parser(
        "release-verify", help="verify signed release evidence and artifacts"
    )
    release_verify.add_argument("evidence", type=Path)
    release_verify.add_argument("--artifacts", type=Path, required=True)
    release_verify.add_argument("--public-key-file", type=Path, required=True)
    external_sign = commands.add_parser(
        "external-record-sign", help="sign independently produced gate evidence"
    )
    external_sign.add_argument("statement", type=Path)
    external_sign.add_argument("--private-key-file", type=Path, required=True)
    external_sign.add_argument("--public-key-file", type=Path, required=True)
    external_sign.add_argument("--output", type=Path, required=True)
    external_verify = commands.add_parser(
        "external-record-verify", help="verify independently produced gate evidence"
    )
    external_verify.add_argument("record", type=Path)
    external_verify.add_argument("--public-key-file", type=Path, required=True)
    envelope = commands.add_parser(
        "federation-envelope", help="create a signed Sentinel evidence envelope"
    )
    envelope.add_argument("bundle", type=Path)
    envelope.add_argument("--private-key-file", type=Path, required=True)
    envelope.add_argument("--public-key-file", type=Path, required=True)
    envelope.add_argument("--provider-id")
    envelope.add_argument("--audit-run-id")
    envelope.add_argument("--output", type=Path, required=True)
    envelope_verify = commands.add_parser("federation-verify", help="verify an envelope")
    envelope_verify.add_argument("envelope", type=Path)
    envelope_verify.add_argument("--public-key-file", type=Path, required=True)
    envelope_submit = commands.add_parser(
        "federation-submit", help="submit a signed envelope to Sentinel"
    )
    envelope_submit.add_argument("envelope", type=Path)
    envelope_submit.add_argument("--endpoint", required=True)
    envelope_submit.add_argument("--token-file", type=Path, required=True)
    envelope_submit.add_argument("--timeout", type=float, default=30)
    envelope_submit.add_argument("--institution-id", required=True)
    envelope_submit.add_argument("--provider-id")
    envelope_submit.add_argument("--allow-http-loopback", action="store_true")
    return result

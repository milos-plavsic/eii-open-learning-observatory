"""Argument definitions for evidence, federation, and release operations."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_operations_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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

"""Evidence, conformance, federation, database, and release CLI commands."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from .audit_package import sign_audit_directory, verify_signed_audit
from .compare import compare_files
from .domain import to_dict
from .evidence import load_audit_directory, load_bundle
from .external_validation import sign_external_record, verify_external_record
from .federation import create_envelope, submit_envelope, verify_envelope
from .persistence import backup_database, database_status, open_existing_database
from .plct_conformance import (
    compare_plct_exports,
    create_conformance_attestation,
    evaluate_plct_export,
    verify_conformance_attestation,
    write_conformance_report,
)
from .supply_chain import sign_release_evidence, verify_signed_release


def _database_command(args: argparse.Namespace) -> int:
    connection = open_existing_database(args.database, kind=args.kind)
    try:
        status = database_status(connection, kind=args.kind)
        if args.command == "database-backup":
            backup_database(connection, args.output)
            print(
                f"Backed up {status.kind} schema {status.schema_version} database to {args.output}"
            )
        else:
            print(json.dumps(to_dict(status), ensure_ascii=False, sort_keys=True))
    finally:
        connection.close()
    return 0


def handle_operations_command(
    args: argparse.Namespace,
    command_parser: argparse.ArgumentParser,
    secret_text: Callable[[Any, str, argparse.ArgumentParser], str],
) -> int:
    if args.command == "compare":
        comparison = compare_files(args.previous, args.current, args.output)
        print(
            f"Comparison: {len(comparison['added'])} added, {len(comparison['resolved'])} resolved"
        )
        return 2 if args.fail_on_regression and comparison["regression"] else 0
    if args.command in {"database-status", "database-backup"}:
        return _database_command(args)
    if args.command == "plct-conformance":
        plct_report = evaluate_plct_export(args.export)
        write_conformance_report(plct_report, args.output)
        if args.previous:
            plct_comparison = compare_plct_exports(args.previous, args.export)
            args.output.with_name(args.output.stem + "-compatibility.json").write_text(
                json.dumps(plct_comparison, ensure_ascii=False, indent=2) + "\n", "utf-8"
            )
        print(
            f"PLCT export {'compatible' if plct_report.compatible else 'incompatible'}: {args.output}"
        )
        return 0 if plct_report.compatible else 2
    if args.command == "plct-attest":
        create_conformance_attestation(
            args.report,
            args.output,
            maintainer=args.maintainer,
            repository_revision=args.repository_revision,
            private_key=args.private_key_file,
            public_key=args.public_key_file,
        )
        print(f"Signed PLCT conformance attestation: {args.output}")
        return 0
    if args.command == "plct-attestation-verify":
        verify_conformance_attestation(args.attestation, args.report, args.public_key_file)
        print(f"Verified PLCT conformance attestation: {args.attestation}")
        return 0
    if args.command == "release-sign":
        destination = sign_release_evidence(
            args.evidence, args.private_key_file, args.public_key_file
        )
        print(f"Signed release checksums: {destination}")
        return 0
    if args.command == "release-verify":
        verify_signed_release(args.evidence, args.artifacts, args.public_key_file)
        print(f"Verified signed release: {args.evidence}")
        return 0
    if args.command == "external-record-sign":
        sign_external_record(
            args.statement,
            args.output,
            private_key=args.private_key_file,
            public_key=args.public_key_file,
        )
        print(f"Signed external validation record: {args.output}")
        return 0
    if args.command == "external-record-verify":
        verify_external_record(args.record, args.public_key_file)
        print(f"Verified external validation record: {args.record}")
        return 0
    if args.command == "federation-envelope":
        create_envelope(
            args.bundle,
            args.output,
            private_key=args.private_key_file,
            public_key=args.public_key_file,
            provider_id=args.provider_id,
            audit_run_id=args.audit_run_id,
        )
        print(f"Wrote signed federation envelope: {args.output}")
        return 0
    if args.command == "federation-verify":
        verify_envelope(args.envelope, args.public_key_file)
        print(f"Verified federation envelope: {args.envelope}")
        return 0
    if args.command == "federation-submit":
        response_status, response = submit_envelope(
            args.envelope,
            args.endpoint,
            token=secret_text(args.token_file, "federation token", command_parser),
            institution_id=args.institution_id,
            provider_id=args.provider_id,
            timeout=args.timeout,
            allow_http_loopback=args.allow_http_loopback,
        )
        print(json.dumps({"status": response_status, "response": response}, ensure_ascii=False))
        return 0
    if args.command == "audit-sign":
        destination = sign_audit_directory(
            args.directory,
            args.private_key_file,
            args.public_key_file,
            signer_id=args.signer_id,
            purpose=args.purpose,
        )
        print(f"Signed audit directory: {destination}")
        return 0
    if args.command == "audit-verify":
        fingerprint = verify_signed_audit(
            args.directory,
            args.public_key_file,
            authorization_policy=args.authorization_policy,
            expected_purpose=args.expected_purpose,
        )
        state = "Authorized" if args.authorization_policy else "Authenticated"
        print(f"{state} audit directory with key {fingerprint}")
        return 0
    try:
        bundle = (
            load_audit_directory(args.bundle) if args.bundle.is_dir() else load_bundle(args.bundle)
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        command_parser.error(str(error))
    print(f"Valid evidence bundle {bundle.id} (schema {bundle.schema_version})")
    return 0

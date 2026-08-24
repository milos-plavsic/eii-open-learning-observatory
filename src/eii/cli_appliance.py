"""Offline-appliance CLI command group."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any, TextIO, cast

from . import safety_verification as safety_trust
from .appliance import (
    apply_trust_rotation,
    capability_check,
    configure,
    create_package,
    create_trust_rotation,
    initialize_trust,
    install_package,
    install_trusted_package,
    recover_active_release,
    rollback,
    serve,
    write_onboarding_page,
)
from .appliance_types import ApplianceConfig
from .audit_log import ManagedAuditLog
from .domain import to_dict


def _serve_command(
    args: argparse.Namespace,
    command_parser: argparse.ArgumentParser,
    secret_text: Callable[[Any, str, argparse.ArgumentParser], str],
) -> int:
    print(f"Serving offline appliance on http://{args.host}:{args.port}")
    token = (
        secret_text(args.query_token_file, "query token", command_parser)
        if args.query_token_file
        else None
    )
    options = {
        "host": args.host,
        "port": args.port,
        "query_token": token,
        "max_request_workers": args.max_request_workers,
        "max_concurrent_queries": args.max_concurrent_queries,
        "max_queries_per_minute": args.max_queries_per_minute,
        "max_rate_limit_clients": args.max_rate_limit_clients,
        "shutdown_grace_seconds": args.shutdown_grace_seconds,
    }
    if args.audit_log:
        with ManagedAuditLog(
            args.audit_log,
            max_bytes=args.audit_log_max_bytes,
            retention_days=args.audit_log_retention_days,
        ) as audit_stream:
            serve(args.root, audit_stream=cast(TextIO, audit_stream), **options)
    else:
        serve(args.root, **options)
    return 0


def handle_appliance_command(
    args: argparse.Namespace,
    command_parser: argparse.ArgumentParser,
    secret_text: Callable[[Any, str, argparse.ArgumentParser], str],
) -> int | None:
    if args.command == "appliance-check":
        report = capability_check(args.path)
        print(json.dumps(to_dict(report), indent=2))
        return 0 if report.suitable else 2
    if args.command == "appliance-package":
        model_values = (args.model_base_url, args.model, args.course_path)
        if any(model_values) and not all(model_values):
            command_parser.error(
                "--model-base-url, --model, and --course-path must be provided together"
            )
        metadata = (
            {
                "model_base_url": args.model_base_url,
                "model": args.model,
                "course_path": args.course_path,
                "language": args.language,
                "prompt_version": "grounded-tutor-v1",
            }
            if all(model_values)
            else {}
        )
        inputs = list(args.input)
        if args.safety_case:
            safety_document = json.loads(args.safety_case.read_text("utf-8"))
            safety_trust.validate_safety_case_document(safety_document)
            safety_trust.authorize_safety_case(
                safety_document,
                trusted_reviewer_fingerprints=frozenset(args.trusted_reviewer_fingerprint),
            )
            if not all(model_values):
                command_parser.error(
                    "safety-gated packages require --model-base-url, --model, and --course-path"
                )
            inputs.append(args.safety_case)
            metadata["safety_case_path"] = f"content/{args.safety_case.name}"
            metadata["safety_case_id"] = safety_document["id"]
        manifest = create_package(
            tuple(inputs),
            args.output,
            version=args.version,
            private_key=args.private_key_file,
            metadata=metadata,
        )
        print(f"Created package {manifest.package_id} version {manifest.version}: {args.output}")
        return 0
    if args.command == "appliance-install":
        modes = sum(bool(x) for x in (args.public_key_file, args.use_trust_store))
        if modes != 1:
            command_parser.error("provide exactly one of --public-key-file or --use-trust-store")
        manifest = (
            install_trusted_package(
                args.package,
                args.root,
                safety_public_key=args.safety_public_key_file,
                trusted_reviewer_fingerprints=frozenset(args.trusted_reviewer_fingerprint),
            )
            if args.use_trust_store
            else install_package(
                args.package,
                args.root,
                public_key=args.public_key_file,
                safety_public_key=args.safety_public_key_file,
                trusted_reviewer_fingerprints=frozenset(args.trusted_reviewer_fingerprint),
            )
        )
        print(f"Activated package {manifest.package_id} version {manifest.version}")
        return 0
    if args.command == "appliance-serve":
        return _serve_command(args, command_parser, secret_text)
    if args.command == "appliance-configure":
        config = ApplianceConfig(
            tuple(x.strip() for x in args.courses.split(",") if x.strip()),
            tuple(x.strip() for x in args.languages.split(",") if x.strip()),
            args.assistant_behavior,
        )
        configure(args.root, config)
        print(
            f"Configured {len(config.selected_courses)} courses and {len(config.allowed_languages)} languages"
        )
        return 0
    if args.command == "appliance-rollback":
        target = rollback(args.root)
        print(f"Rolled back to package {target['package_id']} version {target['version']}")
        return 0
    if args.command == "appliance-recover":
        target = recover_active_release(args.root)
        print(f"Recovered package {target['package_id']} version {target['version']}")
        return 0
    if args.command == "appliance-onboarding":
        write_onboarding_page(args.output, args.url)
        print(f"Wrote QR onboarding page: {args.output}")
        return 0
    if args.command == "appliance-trust-init":
        fingerprint = initialize_trust(args.root, args.public_key_file)
        print(f"Trusted publisher key {fingerprint}")
        return 0
    if args.command == "appliance-trust-rotation-create":
        create_trust_rotation(
            args.current_private_key,
            args.current_public_key,
            args.new_public_key,
            args.output,
            revoke_old=args.revoke_old,
        )
        print(f"Wrote signed trust rotation: {args.output}")
        return 0
    if args.command == "appliance-trust-rotation-apply":
        fingerprint = apply_trust_rotation(args.root, args.authorization)
        print(f"Trusted rotated publisher key {fingerprint}")
        return 0
    return None

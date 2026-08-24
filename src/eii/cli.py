from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, cast

from . import safety_verification as safety_trust
from .adapters import adapter_for
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
from .audit_package import sign_audit_directory, verify_signed_audit
from .cli_audit import handle_audit
from .cli_model import model_client as _model_client
from .cli_parser import parser as parser
from .cli_trust import handle_trust_command
from .compare import compare_files
from .curriculum import CurriculumMRI, CurriculumSpec
from .domain import EvidenceBundle, FindingStatus, ReviewDecision, Severity, to_dict
from .editorial import LLMEditorialAuditor
from .evidence import load_audit_directory, load_bundle, write_bundle
from .external_validation import sign_external_record, verify_external_record
from .federation import create_envelope, submit_envelope, verify_envelope
from .fixture_export import (
    export_finding_regressions,
    export_findings_as_suite,
    verify_finding_regressions,
)
from .models import OpenAICompatibleClient
from .persistence import backup_database, database_status, open_existing_database
from .plct_conformance import (
    compare_plct_exports,
    create_conformance_attestation,
    evaluate_plct_export,
    verify_conformance_attestation,
    write_conformance_report,
)
from .report import write_html
from .reviews import append_review
from .safety import (
    SafetyCaseRunner,
    builtin_suite,
    load_human_evaluations,
    load_replay,
    load_suite,
    write_safety_case,
    write_suite,
)
from .safety_types import AssistantUnderTest
from .secureio import read_secret_bytes, write_private_text
from .study import ReviewStudy, serve_study
from .supply_chain import sign_release_evidence, verify_signed_release
from .tutor import GroundedTutor
from .weather import WeatherStore, load_events


def main(argv: list[str] | None = None) -> int:
    command_parser = parser()
    args = command_parser.parse_args(argv)
    if (trust_result := handle_trust_command(args, command_parser, _secret_bytes)) is not None:
        return trust_result
    if args.command == "audit":
        return handle_audit(args, command_parser, _model_client(args, command_parser))
    if args.command == "mri":
        adapter = adapter_for(args.source)
        if adapter is None:
            command_parser.error(f"no compatible adapter for {args.source}")
        release = adapter.load(args.source, language=args.language)
        findings = CurriculumMRI().analyze(release, CurriculumSpec.load(args.spec))
        client = _model_client(args, command_parser)
        if client:
            auditor = LLMEditorialAuditor(client)
            findings += auditor.analyze(release)
            findings += auditor.generate_support_tests(release, count=args.generated_question_count)
        bundle = EvidenceBundle.create((release,), findings)
        args.output.mkdir(parents=True, exist_ok=True)
        write_bundle(bundle, args.output / "evidence.json")
        write_html(bundle, (), args.output / "index.html")
        backlog = sorted(
            findings, key=lambda f: (list(Severity).index(f.severity), f.confidence), reverse=True
        )
        (args.output / "backlog.json").write_text(
            json.dumps([to_dict(item) for item in backlog], ensure_ascii=False, indent=2) + "\n",
            "utf-8",
        )
        export_findings_as_suite(
            findings, args.output / "regression-suite.json", version=release.version
        )
        export_finding_regressions(
            findings, args.output / "regression-cases.json", version=release.version
        )
        print(f"Wrote {len(findings)} curriculum findings to {args.output}")
        return 0
    if args.command == "safety-case":
        adapter = adapter_for(args.source)
        if adapter is None:
            command_parser.error(f"no compatible adapter for {args.source}")
        release = adapter.load(args.source, language=args.language)
        version, fixtures, gates = load_suite(args.suite)
        client = _model_client(args, command_parser)
        if bool(args.responses) == bool(client):
            command_parser.error("provide exactly one of --responses or --model-base-url/--model")
        if args.responses:
            assistant: AssistantUnderTest = load_replay(args.responses)
        else:
            assistant = GroundedTutor(
                cast(OpenAICompatibleClient, client), prompt_version=args.prompt_version
            )
        human = load_human_evaluations(args.human_reviews) if args.human_reviews else ()
        case = SafetyCaseRunner().run_with_human(
            release,
            assistant,
            fixtures,
            gates,
            dataset_version=version,
            prompt_version=args.prompt_version,
            human_evaluations=human,
        )
        write_safety_case(case, args.output)
        print(f"Safety case {case.release_decision}: {args.output}")
        return 0 if case.release_decision == "configured_gates_passed" else 2
    if args.command == "safety-suite-init":
        version, fixtures, gates = builtin_suite(
            tuple(x.strip() for x in args.languages.split(",") if x.strip())
        )
        write_suite(version, fixtures, gates, args.output)
        print(f"Wrote {len(fixtures)} built-in safety fixtures to {args.output}")
        return 0
    if args.command == "safety-sign":
        adapter = adapter_for(args.course)
        if adapter is None:
            command_parser.error(f"no compatible adapter for {args.course}")
        course = adapter.load(args.course, language=args.language)
        safety_trust.sign_safety_case(args.case, args.private_key_file, course=course)
        print(f"Signed safety case: {args.case}")
        return 0
    if args.command == "weather":
        secret = _secret_bytes(args.secret_file, "weather secret", 32, command_parser)
        ledger = _secret_bytes(args.ledger_key_file, "weather ledger key", 32, command_parser)
        with WeatherStore(
            args.database,
            secret=secret,
            minimum_group_size=args.minimum_group_size,
            dp_epsilon=args.dp_epsilon,
            dp_total_epsilon=args.dp_total_epsilon,
            retention_days=args.retention_days,
            count_granularity=args.count_granularity,
            minimum_export_interval_hours=args.minimum_export_interval_hours,
            key_epoch=args.key_epoch,
            ledger_key=ledger,
        ) as store:
            purged = store.purge_expired()
            events = load_events(args.events)
            for event in events:
                store.ingest(event)
            store.export(args.output, course_key=args.course_key)
            html_output = args.html_output or args.output.with_suffix(".html")
            store.export_html(html_output, course_key=args.course_key)
            visible = len(store.aggregate(course_key=args.course_key))
        print(
            f"Ingested {len(events)} minimized events, purged {purged}, exported {visible} safe cells"
        )
        return 0
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
        print(f"Serving offline appliance on http://{args.host}:{args.port}")
        token = (
            _secret_text(args.query_token_file, "query token", command_parser)
            if args.query_token_file
            else None
        )
        if args.audit_log:
            with ManagedAuditLog(
                args.audit_log,
                max_bytes=args.audit_log_max_bytes,
                retention_days=args.audit_log_retention_days,
            ) as audit_stream:
                serve(
                    args.root,
                    host=args.host,
                    port=args.port,
                    query_token=token,
                    audit_stream=cast(TextIO, audit_stream),
                    max_request_workers=args.max_request_workers,
                    max_concurrent_queries=args.max_concurrent_queries,
                    max_queries_per_minute=args.max_queries_per_minute,
                    max_rate_limit_clients=args.max_rate_limit_clients,
                    shutdown_grace_seconds=args.shutdown_grace_seconds,
                )
        else:
            serve(
                args.root,
                host=args.host,
                port=args.port,
                query_token=token,
                max_request_workers=args.max_request_workers,
                max_concurrent_queries=args.max_concurrent_queries,
                max_queries_per_minute=args.max_queries_per_minute,
                max_rate_limit_clients=args.max_rate_limit_clients,
                shutdown_grace_seconds=args.shutdown_grace_seconds,
            )
        return 0
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
                seed=_secret_text(args.seed_file, "review study seed", command_parser),
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
    if args.command == "compare":
        comparison = compare_files(args.previous, args.current, args.output)
        print(
            f"Comparison: {len(comparison['added'])} added, {len(comparison['resolved'])} resolved"
        )
        return 2 if args.fail_on_regression and comparison["regression"] else 0
    if args.command in {"database-status", "database-backup"}:
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
            token=_secret_text(args.token_file, "federation token", command_parser),
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


def _secret_bytes(
    path: Path, label: str, minimum: int, command_parser: argparse.ArgumentParser
) -> bytes:
    try:
        return read_secret_bytes(path, label=label, minimum_bytes=minimum)
    except ValueError as error:
        command_parser.error(str(error))


def _secret_text(path: Path, label: str, command_parser: argparse.ArgumentParser) -> str:
    value = _secret_bytes(path, label, 1, command_parser)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        command_parser.error(f"{label} must be UTF-8 text: {error}")

"""Curriculum, tutor-safety, and Weather Map CLI command group."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any, cast

from . import safety_verification as safety_trust
from .adapters import adapter_for
from .cli_model import model_client
from .curriculum import CurriculumMRI, CurriculumSpec
from .domain import EvidenceBundle, Severity, to_dict
from .editorial import LLMEditorialAuditor
from .evidence import write_bundle
from .fixture_export import export_finding_regressions, export_findings_as_suite
from .models import OpenAICompatibleClient
from .report import write_html
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
from .tutor import GroundedTutor
from .weather import WeatherStore, load_events, load_public_cell_universe


def handle_learning_command(
    args: argparse.Namespace,
    command_parser: argparse.ArgumentParser,
    secret_bytes: Callable[[Any, str, int, argparse.ArgumentParser], bytes],
) -> int | None:
    if args.command == "mri":
        adapter = adapter_for(args.source)
        if adapter is None:
            command_parser.error(f"no compatible adapter for {args.source}")
        release = adapter.load(args.source, language=args.language)
        findings = CurriculumMRI().analyze(release, CurriculumSpec.load(args.spec))
        client = model_client(args, command_parser)
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
        client = model_client(args, command_parser)
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
        secret = secret_bytes(args.secret_file, "weather secret", 32, command_parser)
        ledger = secret_bytes(args.ledger_key_file, "weather ledger key", 32, command_parser)
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
            public_cell_universe=(
                load_public_cell_universe(args.public_cell_universe)
                if args.public_cell_universe
                else None
            ),
            max_cells_per_contributor_per_day=args.max_cells_per_contributor_per_day,
            database_instance_id=args.database_instance_id,
            allow_database_fork=args.allow_database_fork,
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
    return None

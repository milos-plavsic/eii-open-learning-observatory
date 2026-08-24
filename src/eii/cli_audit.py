"""Audit-specific CLI policy construction."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .adapters import adapter_for
from .alignment_relationships import translation_status
from .babelbridge import BabelBridge
from .domain import EvidenceBundle, content_hash, seal_bundle, to_dict
from .evidence import write_bundle
from .glossary import Glossary
from .models import OpenAICompatibleClient
from .report import write_html
from .reviews import read_reviews
from .semantic_policy import SemanticPolicy, load_semantic_policy


def add_semantic_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--semantic-evaluator-config",
        type=Path,
        help="versioned JSON policy for an odd panel of distinct evaluator configurations",
    )
    parser.add_argument("--semantic-threshold", type=float, default=0.7)
    parser.add_argument("--semantic-minimum-agreement", type=float, default=0.5)
    parser.add_argument("--semantic-maximum-minority-confidence", type=float)
    parser.add_argument("--semantic-require-unanimity", action="store_true")
    parser.add_argument("--semantic-maximum-failed-members", type=int, default=0)
    parser.add_argument("--max-semantic-comparisons", type=int, default=100)


def semantic_policy_from_args(
    args: argparse.Namespace,
    client: OpenAICompatibleClient | None,
    command_parser: argparse.ArgumentParser,
) -> SemanticPolicy:
    try:
        return load_semantic_policy(
            threshold=args.semantic_threshold,
            config_path=args.semantic_evaluator_config,
            single_client=client,
            minimum_agreement_ratio=getattr(args, "semantic_minimum_agreement", 0.5),
            maximum_minority_confidence=getattr(args, "semantic_maximum_minority_confidence", None),
            require_unanimity=getattr(args, "semantic_require_unanimity", False),
            maximum_failed_members=getattr(args, "semantic_maximum_failed_members", 0),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        command_parser.error(str(error))


def handle_audit(
    args: argparse.Namespace,
    command_parser: argparse.ArgumentParser,
    client: OpenAICompatibleClient | None,
) -> int:
    languages = args.languages.split(",") if args.languages else [None] * len(args.source)
    if len(languages) not in (1, len(args.source)):
        command_parser.error("--languages must contain one language per source")
    if len(languages) == 1 and len(args.source) > 1:
        languages *= len(args.source)
    releases = []
    for source, language in zip(args.source, languages, strict=True):
        adapter = adapter_for(source)
        if adapter is None:
            command_parser.error(f"no compatible adapter for {source}")
        releases.append(adapter.load(source, language=language))
    glossary = Glossary.load(args.glossary) if args.glossary else None
    policy = semantic_policy_from_args(args, client, command_parser)
    result = BabelBridge(
        semantic_decision_threshold=policy.threshold,
        semantic_minimum_agreement=policy.minimum_agreement_ratio,
        semantic_maximum_minority_confidence=policy.maximum_minority_confidence,
        semantic_require_unanimity=policy.require_unanimity,
        semantic_maximum_failed_members=policy.maximum_failed_members,
        max_semantic_comparisons=args.max_semantic_comparisons,
    ).analyze(tuple(releases), glossary=glossary, comparator=policy.comparator)
    alignment_data = to_dict(result.alignments)
    status_data = to_dict(translation_status(result, tuple(releases)))
    artifacts = {
        "alignments": _artifact(alignment_data),
        "translation_status": _artifact(status_data),
    }
    bundle = replace(
        EvidenceBundle.create(tuple(releases), result.findings),
        model_runs=result.model_runs,
        reviews=read_reviews(args.reviews) if args.reviews else (),
        metadata={
            "semantic_policy": policy.evidence,
            "max_semantic_comparisons": args.max_semantic_comparisons,
            "semantic_evaluations_schema_version": "2.0",
            "semantic_evaluations": to_dict(result.semantic_evaluations),
            "semantic_evaluation_plan": to_dict(result.semantic_evaluation_plan),
            "audit_artifacts": artifacts,
        },
    )
    bundle = seal_bundle(bundle)
    args.output.mkdir(parents=True, exist_ok=True)
    write_bundle(bundle, args.output / "evidence.json")
    _write_json(alignment_data, args.output / "alignments.json")
    _write_json(status_data, args.output / "translation-status.json")
    write_html(bundle, result.alignments, args.output / "index.html")
    print(
        f"Wrote {len(result.alignments)} alignments and {len(result.findings)} findings to {args.output}"
    )
    return 0


def _artifact(records: object) -> dict[str, object]:
    return {"schema_version": "1.0", "content_hash": content_hash(records), "records": records}


def _write_json(value: object, path: Path) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

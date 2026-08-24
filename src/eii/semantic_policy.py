"""Validated, provenance-bound semantic evaluator policy loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import content_hash
from .models import OpenAICompatibleClient
from .semantics import ConsensusSemanticComparator, LLMSemanticComparator, SemanticComparator


@dataclass(frozen=True, slots=True)
class SemanticPolicy:
    comparator: SemanticComparator | None
    threshold: float
    minimum_agreement_ratio: float
    maximum_minority_confidence: float | None
    require_unanimity: bool
    maximum_failed_members: int
    evidence: dict[str, Any]


def _required_api_key(name: str | None, index: int) -> str | None:
    value = os.environ.get(name) if name else None
    if name and not value:
        raise ValueError(
            f"semantic evaluator {index} requires non-empty environment variable {name}"
        )
    return value


def _policy_controls(
    document: dict[str, Any], public_config: list[dict[str, Any]], comparator_count: int
) -> tuple[int, float, float | None, int | None, int, int, int, int]:
    quorum = document.get("quorum", comparator_count // 2 + 1)
    timeout = document.get("overall_timeout_seconds", 180.0)
    cost = document.get("max_total_cost")
    tokens = document.get("max_total_tokens")
    panels = document.get("max_outstanding_panels", 1)
    operators = document.get("minimum_declared_operators", 0)
    families = document.get("minimum_declared_model_families", 0)
    failed_members = document.get("maximum_failed_members", 0)
    if not isinstance(quorum, int) or isinstance(quorum, bool):
        raise ValueError("semantic evaluator quorum must be an integer")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("semantic evaluator timeout must be numeric")
    if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool)):
        raise ValueError("semantic evaluator cost budget must be numeric")
    if tokens is not None and (not isinstance(tokens, int) or isinstance(tokens, bool)):
        raise ValueError("semantic evaluator token budget must be an integer")
    integers = (operators, families, panels, failed_members)
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in integers
    ):
        raise ValueError("semantic evaluator diversity and capacity settings must be integers")
    declared_operators = {item.get("operator") for item in public_config if item.get("operator")}
    declared_families = {
        item.get("model_family") for item in public_config if item.get("model_family")
    }
    if len(declared_operators) < operators or len(declared_families) < families:
        raise ValueError("semantic evaluator panel does not meet declared diversity requirements")
    if failed_members >= comparator_count:
        raise ValueError("maximum failed semantic members must be smaller than the panel")
    return (
        quorum,
        float(timeout),
        float(cost) if cost is not None else None,
        tokens,
        panels,
        operators,
        families,
        failed_members,
    )


def _decision_policy(
    document: dict[str, Any],
    agreement_default: float,
    minority_default: float | None,
    unanimity_default: bool,
) -> tuple[float, float | None, bool]:
    agreement = document.get("minimum_agreement_ratio", agreement_default)
    minority = document.get("maximum_minority_confidence", minority_default)
    unanimity = document.get("require_unanimity", unanimity_default)
    valid_minority = minority is None or (
        isinstance(minority, (int, float)) and not isinstance(minority, bool) and 0 <= minority <= 1
    )
    if (
        not isinstance(agreement, (int, float))
        or isinstance(agreement, bool)
        or not 0.5 <= agreement <= 1
        or not valid_minority
        or not isinstance(unanimity, bool)
    ):
        raise ValueError("semantic consensus decision-signal policy is invalid")
    return float(agreement), float(minority) if minority is not None else None, unanimity


def _build_comparators(
    evaluators: list[object],
) -> tuple[list[LLMSemanticComparator], list[dict[str, Any]]]:
    allowed = {
        "base_url",
        "model",
        "provider",
        "api_key_env",
        "prompt_version",
        "model_revision",
        "operator",
        "model_family",
    }
    comparators, public_config = [], []
    identities: set[str] = set()
    for index, item in enumerate(evaluators):
        if (
            not isinstance(item, dict)
            or set(item) - allowed
            or not {"base_url", "model"} <= set(item)
        ):
            raise ValueError(f"semantic evaluator {index} has invalid fields")
        if not all(isinstance(item[key], str) and item[key].strip() for key in item):
            raise ValueError(f"semantic evaluator {index} fields must be non-empty strings")
        client = OpenAICompatibleClient(
            item["base_url"],
            item["model"],
            provider=item.get("provider", "openai-compatible"),
            api_key=_required_api_key(item.get("api_key_env"), index),
            model_revision=item.get("model_revision"),
        )
        public_item = {key: value for key, value in item.items() if key != "api_key_env"}
        identity = content_hash(
            {
                "base_url": item["base_url"].rstrip("/"),
                "model": item["model"],
                "provider": item.get("provider", "openai-compatible"),
                "prompt_version": item.get("prompt_version", "babel-semantic-v1"),
                "model_revision": item.get("model_revision"),
            }
        )
        if identity in identities:
            raise ValueError("semantic evaluator configurations must have distinct identities")
        identities.add(identity)
        comparators.append(
            LLMSemanticComparator(
                client, prompt_version=item.get("prompt_version", "babel-semantic-v1")
            )
        )
        public_config.append(public_item)
    return comparators, public_config


def load_semantic_policy(
    *,
    threshold: float,
    config_path: Path | None = None,
    single_client: OpenAICompatibleClient | None = None,
    minimum_agreement_ratio: float = 0.5,
    maximum_minority_confidence: float | None = None,
    require_unanimity: bool = False,
    maximum_failed_members: int = 0,
) -> SemanticPolicy:
    if not 0 <= threshold <= 1:
        raise ValueError("semantic threshold must be between zero and one")
    if not 0.5 <= minimum_agreement_ratio <= 1:
        raise ValueError("minimum semantic agreement must be between one half and one")
    if maximum_minority_confidence is not None and not 0 <= maximum_minority_confidence <= 1:
        raise ValueError("maximum minority confidence must be between zero and one")
    if isinstance(maximum_failed_members, bool) or maximum_failed_members < 0:
        raise ValueError("maximum failed semantic members must be a non-negative integer")
    if config_path and single_client:
        raise ValueError("semantic evaluator config cannot be combined with single-model options")
    if not config_path:
        comparator = LLMSemanticComparator(single_client) if single_client else None
        mode = "single" if comparator else "deterministic-only"
        return SemanticPolicy(
            comparator,
            threshold,
            minimum_agreement_ratio,
            maximum_minority_confidence,
            require_unanimity,
            maximum_failed_members,
            {
                "mode": mode,
                "decision_threshold": threshold,
                "minimum_agreement_ratio": minimum_agreement_ratio,
                "maximum_minority_confidence": maximum_minority_confidence,
                "require_unanimity": require_unanimity,
                "maximum_failed_members": maximum_failed_members,
            },
        )
    document = json.loads(config_path.read_text("utf-8"))
    if not isinstance(document, dict) or set(document) - {
        "schema_version",
        "evaluators",
        "quorum",
        "overall_timeout_seconds",
        "max_total_cost",
        "max_total_tokens",
        "max_outstanding_panels",
        "minimum_declared_operators",
        "minimum_declared_model_families",
        "minimum_agreement_ratio",
        "maximum_minority_confidence",
        "require_unanimity",
        "maximum_failed_members",
    }:
        raise ValueError("semantic evaluator config contains unsupported fields")
    if document.get("schema_version") != "1.0":
        raise ValueError("semantic evaluator config requires schema_version 1.0")
    if "evaluators" not in document:
        raise ValueError("semantic evaluator config requires evaluators")
    evaluators = document["evaluators"]
    if not isinstance(evaluators, list) or len(evaluators) < 3 or len(evaluators) % 2 == 0:
        raise ValueError("semantic evaluator config requires an odd panel of at least three")
    comparators, public_config = _build_comparators(evaluators)
    (
        quorum,
        timeout,
        max_total_cost,
        max_total_tokens,
        max_outstanding_panels,
        minimum_operators,
        minimum_families,
        configured_failed_members,
    ) = _policy_controls(document, public_config, len(comparators))
    consensus = ConsensusSemanticComparator(
        comparators,
        quorum=quorum,
        overall_timeout_seconds=timeout,
        max_total_cost=max_total_cost,
        max_total_tokens=max_total_tokens,
        max_outstanding_panels=max_outstanding_panels,
        max_failed_members=configured_failed_members,
    )
    configured_agreement, configured_minority, configured_unanimity = _decision_policy(
        document, minimum_agreement_ratio, maximum_minority_confidence, require_unanimity
    )
    evidence = {
        "mode": "distinct-config-consensus",
        "policy_schema_version": "1.0",
        "decision_threshold": threshold,
        "evaluator_count": len(comparators),
        "quorum": quorum,
        "overall_timeout_seconds": timeout,
        "max_total_cost": max_total_cost,
        "max_total_tokens": max_total_tokens,
        "max_outstanding_panels": max_outstanding_panels,
        "minimum_declared_operators": minimum_operators,
        "minimum_declared_model_families": minimum_families,
        "public_config": public_config,
        "public_config_hash": content_hash(public_config),
        "independence_claim": "distinct-configurations-only",
        "minimum_agreement_ratio": configured_agreement,
        "maximum_minority_confidence": configured_minority,
        "require_unanimity": configured_unanimity,
        "maximum_failed_members": configured_failed_members,
    }
    return SemanticPolicy(
        consensus,
        threshold,
        configured_agreement,
        configured_minority,
        configured_unanimity,
        configured_failed_members,
        evidence,
    )

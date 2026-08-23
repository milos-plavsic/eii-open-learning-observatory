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
) -> tuple[int, float, float | None, int | None, int, int, int]:
    quorum = document.get("quorum", comparator_count // 2 + 1)
    timeout = document.get("overall_timeout_seconds", 180.0)
    cost = document.get("max_total_cost")
    tokens = document.get("max_total_tokens")
    panels = document.get("max_outstanding_panels", 1)
    operators = document.get("minimum_declared_operators", 0)
    families = document.get("minimum_declared_model_families", 0)
    if not isinstance(quorum, int) or isinstance(quorum, bool):
        raise ValueError("semantic evaluator quorum must be an integer")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("semantic evaluator timeout must be numeric")
    if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool)):
        raise ValueError("semantic evaluator cost budget must be numeric")
    if tokens is not None and (not isinstance(tokens, int) or isinstance(tokens, bool)):
        raise ValueError("semantic evaluator token budget must be an integer")
    integers = (operators, families, panels)
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
    return (
        quorum,
        float(timeout),
        float(cost) if cost is not None else None,
        tokens,
        panels,
        operators,
        families,
    )


def load_semantic_policy(
    *,
    threshold: float,
    config_path: Path | None = None,
    single_client: OpenAICompatibleClient | None = None,
) -> SemanticPolicy:
    if not 0 <= threshold <= 1:
        raise ValueError("semantic threshold must be between zero and one")
    if config_path and single_client:
        raise ValueError("semantic evaluator config cannot be combined with single-model options")
    if not config_path:
        comparator = LLMSemanticComparator(single_client) if single_client else None
        mode = "single" if comparator else "deterministic-only"
        return SemanticPolicy(
            comparator, threshold, {"mode": mode, "decision_threshold": threshold}
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
    }:
        raise ValueError("semantic evaluator config contains unsupported fields")
    if document.get("schema_version") != "1.0":
        raise ValueError("semantic evaluator config requires schema_version 1.0")
    if "evaluators" not in document:
        raise ValueError("semantic evaluator config requires evaluators")
    evaluators = document["evaluators"]
    if not isinstance(evaluators, list) or len(evaluators) < 3 or len(evaluators) % 2 == 0:
        raise ValueError("semantic evaluator config requires an odd panel of at least three")
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
    comparators = []
    public_config = []
    configured_identities: set[str] = set()
    for index, item in enumerate(evaluators):
        if (
            not isinstance(item, dict)
            or set(item) - allowed
            or not {"base_url", "model"} <= set(item)
        ):
            raise ValueError(f"semantic evaluator {index} has invalid fields")
        if not all(isinstance(item[key], str) and item[key].strip() for key in item):
            raise ValueError(f"semantic evaluator {index} fields must be non-empty strings")
        api_key_env = item.get("api_key_env")
        api_key = _required_api_key(api_key_env, index)
        client = OpenAICompatibleClient(
            item["base_url"],
            item["model"],
            provider=item.get("provider", "openai-compatible"),
            api_key=api_key,
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
        if identity in configured_identities:
            raise ValueError("semantic evaluator configurations must have distinct identities")
        configured_identities.add(identity)
        comparators.append(
            LLMSemanticComparator(
                client, prompt_version=item.get("prompt_version", "babel-semantic-v1")
            )
        )
        public_config.append(public_item)
    (
        quorum,
        timeout,
        max_total_cost,
        max_total_tokens,
        max_outstanding_panels,
        minimum_operators,
        minimum_families,
    ) = _policy_controls(document, public_config, len(comparators))
    consensus = ConsensusSemanticComparator(
        comparators,
        quorum=quorum,
        overall_timeout_seconds=timeout,
        max_total_cost=max_total_cost,
        max_total_tokens=max_total_tokens,
        max_outstanding_panels=max_outstanding_panels,
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
    }
    return SemanticPolicy(consensus, threshold, evidence)

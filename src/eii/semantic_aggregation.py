"""Strict-majority semantic-panel aggregation with complete provenance."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .domain import ModelRun, content_hash, to_dict
from .semantic_types import SemanticJudgment
from .semantic_usage import aggregate_usage


def _majority(values: list[bool], quorum: int) -> bool | None:
    if sum(values) >= quorum:
        return True
    if sum(not value for value in values) >= quorum:
        return False
    return None


def _validate_members(judgments: tuple[SemanticJudgment, ...]) -> list[str]:
    for judgment in judgments:
        if judgment.abstained:
            raise ValueError("abstaining semantic members cannot participate in a vote")
        if not 0 <= judgment.confidence <= 1 or not math.isfinite(judgment.confidence):
            raise ValueError(
                "semantic comparator confidence must be finite and between zero and one"
            )
    identities = [
        content_hash(
            {
                "provider": item.model_run.provider,
                "model": item.model_run.model,
                "prompt_version": item.model_run.prompt_version,
                "endpoint_hash": item.model_run.configuration.get("endpoint_hash"),
                "model_revision": item.model_run.configuration.get("effective_model_revision"),
            }
        )
        for item in judgments
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("semantic consensus members must have distinct evaluator identities")
    return identities


def aggregate_consensus(
    judgments: tuple[SemanticJudgment, ...],
    failures: list[Mapping[str, object]],
    *,
    panel_size: int,
    quorum: int,
    max_total_cost: float | None,
    max_total_tokens: int | None,
) -> SemanticJudgment:
    identities = _validate_members(judgments)
    property_sets = {frozenset(item.properties) for item in judgments}
    if len(property_sets) != 1 or not next(iter(property_sets)):
        raise ValueError("semantic consensus members must report the same non-empty properties")
    property_names = sorted(next(iter(property_sets)))
    property_votes = {
        name: _majority([item.properties[name] for item in judgments], quorum)
        for name in property_names
    }
    properties = {name: value is True for name, value in property_votes.items()}
    whole_vote = _majority([item.equivalent for item in judgments], quorum)
    property_vote = all(properties.values())
    inconclusive = whole_vote is None or any(value is None for value in property_votes.values())
    contradictory = not inconclusive and whole_vote != property_vote
    equivalent = whole_vote is True and property_vote and not inconclusive
    agreement = (
        0.0
        if whole_vote is None
        else sum(item.equivalent == whole_vote for item in judgments) / len(judgments)
    )
    confidence = agreement * sum(item.confidence for item in judgments) / len(judgments)
    total_cost, total_tokens = aggregate_usage([item.model_run for item in judgments])
    budget_exceeded = (
        max_total_cost is not None
        and (bool(failures) or total_cost is None or total_cost > max_total_cost)
    ) or (
        max_total_tokens is not None
        and (bool(failures) or total_tokens is None or total_tokens > max_total_tokens)
    )
    members = [
        {
            "equivalent": item.equivalent,
            "confidence": item.confidence,
            "properties": dict(item.properties),
            "explanation": item.explanation,
            "model_run": to_dict(item.model_run),
        }
        for item in judgments
    ]
    decision = {
        "equivalent": equivalent,
        "confidence": confidence,
        "properties": properties,
        "member_output_hashes": [item.model_run.output_hash for item in judgments],
        "whole_judgment_vote": whole_vote,
        "property_conjunction_vote": property_vote,
        "abstained": contradictory or inconclusive,
        "failures": failures,
        "budget_exceeded": budget_exceeded,
    }
    run = ModelRun(
        "consensus",
        "+".join(item.model_run.model for item in judgments),
        "semantic-consensus-v2",
        {
            "member_judgments": members,
            "member_count": len(judgments),
            "panel_size": panel_size,
            "quorum": quorum,
            "decision_majority_denominator": "configured_panel",
            "failures": failures,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "cost_metering_complete": not failures and total_cost is not None,
            "token_metering_complete": not failures and total_tokens is not None,
            "max_total_cost": max_total_cost,
            "max_total_tokens": max_total_tokens,
            "budget_semantics": "post_run_release_gate_not_pre_spend_enforcement",
            "member_identity_hashes": identities,
            "score_semantics": "agreement_ratio_times_mean_member_score_uncalibrated",
        },
        content_hash([item.model_run.input_hash for item in judgments]),
        content_hash(decision),
    )
    explanation = "Consensus of distinct configured evaluators: " + " | ".join(
        item.explanation for item in judgments
    )
    if inconclusive:
        explanation = (
            "Panel abstained because no strict-majority outcome was reached. " + explanation
        )
    elif contradictory:
        explanation = (
            "Panel abstained because whole-judgment and property votes conflict. " + explanation
        )
    if budget_exceeded:
        explanation = (
            "Panel abstained because its configured evaluation budget was exceeded. " + explanation
        )
    abstained = contradictory or inconclusive or budget_exceeded
    return SemanticJudgment(
        equivalent,
        confidence if not abstained else 0.0,
        explanation[:2000],
        properties,
        run,
        abstained,
        tuple(members) + tuple(failures),
    )

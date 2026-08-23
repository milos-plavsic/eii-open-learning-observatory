"""Fail-closed model usage aggregation for semantic release gates."""

import math
from collections.abc import Mapping, Sequence

from .domain import ModelRun


def effective_timeout(configured: float, override: float | None) -> float:
    if override is not None and (not math.isfinite(override) or override <= 0):
        raise ValueError("semantic comparison timeout must be finite and positive")
    return min(configured, override) if override is not None else configured


def usage_total(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    total = value.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    prompt, completion = value.get("prompt_tokens"), value.get("completion_tokens")
    if (
        isinstance(prompt, int)
        and not isinstance(prompt, bool)
        and prompt >= 0
        and isinstance(completion, int)
        and not isinstance(completion, bool)
        and completion >= 0
    ):
        return prompt + completion
    return None


def aggregate_usage(runs: Sequence[ModelRun]) -> tuple[float | None, int | None]:
    costs = [run.cost for run in runs]
    tokens = [usage_total(run.configuration.get("usage")) for run in runs]
    total_cost = (
        sum(value for value in costs if value is not None)
        if all(value is not None for value in costs)
        else None
    )
    total_tokens = (
        sum(value for value in tokens if value is not None)
        if all(value is not None for value in tokens)
        else None
    )
    return total_cost, total_tokens

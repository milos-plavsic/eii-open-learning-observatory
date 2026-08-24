"""Cardinality-aware multilingual alignment relationships."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .domain import CourseRelease, content_hash, freeze_json

ALIGNMENT_SCORE_VERSION = "alignment-score-v2"
ALIGNMENT_METHODS = frozenset(
    {
        "explicit-translation-id",
        "partial-translation-id",
        "explicit-concept",
        "title-or-order-heuristic",
    }
)
CARDINALITIES = frozenset({"one-to-one", "one-to-many", "many-to-one", "many-to-many"})


@dataclass(frozen=True, slots=True)
class Alignment:
    concept_id: str
    members: tuple[tuple[str, str], ...]
    confidence: float | None
    method: str
    cardinality: str = "one-to-one"
    alignment_score: float = 1.0
    score_components: Mapping[str, float] | None = None
    score_version: str = ALIGNMENT_SCORE_VERSION

    def __post_init__(self) -> None:
        if (
            not self.concept_id
            or not self.members
            or len(set(self.members)) != len(self.members)
            or self.method not in ALIGNMENT_METHODS
            or self.cardinality not in CARDINALITIES
            or not 0 <= self.alignment_score <= 1
            or self.score_version != ALIGNMENT_SCORE_VERSION
        ):
            raise ValueError("alignment invariants are invalid")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("legacy alignment confidence must be null or between zero and one")
        components = freeze_json(self.score_components or {})
        if any(
            not isinstance(value, (int, float)) or not 0 <= value <= 1
            for value in components.values()
        ):
            raise ValueError("alignment score components must be between zero and one")
        object.__setattr__(self, "score_components", components)


def relationship_id(concept_id: str, members: tuple[tuple[str, str], ...]) -> str:
    """Derive an unambiguous relationship identity even when concepts repeat."""
    return (
        "alignment:" + content_hash({"concept_id": concept_id, "members": members}).split(":", 1)[1]
    )


def consolidate_alignments(
    alignments: tuple[Alignment, ...], releases: tuple[CourseRelease, ...]
) -> tuple[Alignment, ...]:
    """Represent declared split/merge relationships once, without duplicate membership."""
    release_order = {release.id: index for index, release in enumerate(releases)}
    grouped: dict[tuple[str, str], list[Alignment]] = {}
    for alignment in alignments:
        discriminator = (
            alignment.method
            if alignment.method in {"explicit-translation-id", "partial-translation-id"}
            else alignment.members[0][1]
        )
        grouped.setdefault((alignment.concept_id, discriminator), []).append(alignment)
    consolidated = []
    for items in grouped.values():
        members = tuple(
            sorted(
                {member for item in items for member in item.members},
                key=lambda member: (release_order[member[0]], member[1]),
            )
        )
        counts = [sum(member[0] == release.id for member in members) for release in releases]
        populated = [count for count in counts if count]
        if not populated or max(populated) == 1:
            cardinality = "one-to-one"
        elif counts[0] == 1 and any(count > 1 for count in counts[1:]):
            cardinality = "one-to-many"
        elif counts[0] > 1 and all(count == 1 for count in counts[1:] if count):
            cardinality = "many-to-one"
        else:
            cardinality = "many-to-many"
        first = items[0]
        weights = [max(1, len(item.members) - 1) for item in items]
        total_weight = sum(weights)
        component_names = sorted({name for item in items for name in (item.score_components or {})})
        components = {
            name: round(
                sum(
                    float((item.score_components or {}).get(name, 0)) * weight
                    for item, weight in zip(items, weights, strict=True)
                )
                / total_weight,
                8,
            )
            for name in component_names
        }
        consolidated.append(
            Alignment(
                first.concept_id,
                members,
                first.confidence,
                first.method,
                cardinality,
                round(
                    sum(
                        item.alignment_score * weight
                        for item, weight in zip(items, weights, strict=True)
                    )
                    / total_weight,
                    8,
                ),
                components,
                first.score_version,
            )
        )
    return tuple(consolidated)

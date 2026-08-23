"""Cardinality-aware multilingual alignment relationships."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import CourseRelease, content_hash


@dataclass(frozen=True, slots=True)
class Alignment:
    concept_id: str
    members: tuple[tuple[str, str], ...]
    confidence: float
    method: str
    cardinality: str = "one-to-one"


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
            if alignment.method == "explicit-translation-id"
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
        consolidated.append(
            Alignment(first.concept_id, members, first.confidence, first.method, cardinality)
        )
    return tuple(consolidated)

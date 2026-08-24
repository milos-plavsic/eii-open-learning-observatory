"""Relationship-level multilingual composition and status projections."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .alignment import ALIGNMENT_SCORE_VERSION, Alignment, relationship_id
from .domain import ContentBlock, CourseRelease, Finding, content_hash

CourseBlock = tuple[CourseRelease, ContentBlock]


@dataclass(frozen=True, slots=True)
class PairScore:
    raw_score: float
    normalized_score: float
    eligible: bool
    hard_reason: str | None
    components: Mapping[str, float]


class AlignmentResult(Protocol):
    @property
    def alignments(self) -> tuple[Alignment, ...]: ...

    @property
    def findings(self) -> tuple[Finding, ...]: ...


@dataclass(frozen=True, slots=True)
class TranslationUnitStatus:
    concept_id: str
    languages_present: tuple[str, ...]
    languages_missing: tuple[str, ...]
    state: str
    members: tuple[tuple[str, str], ...]


def _valid_score(value: object, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def _valid_components(value: object) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(name, str) and name and _valid_score(score) for name, score in value.items()
    )


def validate_translation_ids(release: CourseRelease) -> None:
    occurrences: dict[str, list[tuple[int, ContentBlock]]] = {}
    for index, block in enumerate(release.blocks):
        if identity := translation_key(block):
            occurrences.setdefault(identity, []).append((index, block))
    for identity, members in occurrences.items():
        if len(members) < 2:
            continue
        parents = {item[1].parent_id for item in members}
        explicitly_scoped = all(item[1].metadata.get("translation_scope") for item in members)
        if not explicitly_scoped and len(parents) != 1:
            raise ValueError(
                f"translation identity {identity!r} spans parents without translation_scope"
            )


def translation_key(block: ContentBlock) -> str | None:
    identity = block.metadata.get("translation_id")
    if not identity:
        return None
    scope = block.metadata.get("translation_scope")
    return f"{scope}::{identity}" if scope else str(identity)


def pair_score(
    left: ContentBlock,
    right: ContentBlock,
    left_index: int,
    right_index: int,
    left_count: int,
    right_count: int,
    title_similarity: Callable[[str, str], float],
) -> float:
    return score_pair(
        left,
        right,
        left_index,
        right_index,
        left_count,
        right_count,
        title_similarity,
    ).raw_score


def score_pair(
    left: ContentBlock,
    right: ContentBlock,
    left_index: int,
    right_index: int,
    left_count: int,
    right_count: int,
    title_similarity: Callable[[str, str], float],
) -> PairScore:
    left_translation, right_translation = translation_key(left), translation_key(right)
    if left_translation and left_translation == right_translation:
        return PairScore(
            12.0,
            1.0,
            True,
            "matching-translation-id",
            _score_components(left, right, 1.0, 0.0, 0.0, 0.0, title_similarity),
        )
    if left_translation and right_translation:
        return PairScore(
            -12.0,
            0.0,
            False,
            "missing-or-conflicting-translation-id",
            _score_components(left, right, 0.0, 1.0, 0.0, 0.0, title_similarity),
        )
    score = 0.0
    shared = set(left.concepts) & set(right.concepts)
    if shared:
        score += 7.0 + min(1.0, len(shared) / max(len(set(left.concepts) | set(right.concepts)), 1))
    if left.id == right.id:
        score += 6.0
    if left.locator.path == right.locator.path:
        score += 1.5
    if left.kind == right.kind:
        score += 0.75
    if (
        left.metadata.get("heading_level") is not None
        and right.metadata.get("heading_level") is not None
        and left.metadata["heading_level"] == right.metadata["heading_level"]
    ):
        score += 0.5
    similarity = title_similarity(left.title, right.title)
    if similarity >= 0.72:
        score += 3.0 * similarity
    position = 0.0
    if left_count > 1 and right_count > 1:
        left_position = left_index / (left_count - 1)
        right_position = right_index / (right_count - 1)
        position = max(0.0, 1.0 - abs(left_position - right_position) * 2)
        score += position
    translation_missing = float(bool(left_translation) != bool(right_translation))
    if translation_missing:
        score -= 2.0
    components = _score_components(
        left, right, 0.0, 0.0, translation_missing, position, title_similarity
    )
    return PairScore(
        score,
        round(max(0.0, min(1.0, score / 20.75)), 8),
        score >= (6.0 if translation_missing else 2.5),
        "one-sided-translation-id" if translation_missing else None,
        components,
    )


def _score_components(
    left: ContentBlock,
    right: ContentBlock,
    translation_match: float,
    translation_conflict: float,
    translation_missing: float,
    position: float,
    title_similarity: Callable[[str, str], float],
) -> dict[str, float]:
    union = set(left.concepts) | set(right.concepts)
    similarity = title_similarity(left.title, right.title)
    return {
        "translation_id_match": translation_match,
        "translation_id_conflict": translation_conflict,
        "translation_id_missing": translation_missing,
        "concept_jaccard": len(set(left.concepts) & set(right.concepts)) / len(union)
        if union
        else 0.0,
        "block_id_match": float(left.id == right.id),
        "path_match": float(left.locator.path == right.locator.path),
        "kind_match": float(left.kind == right.kind),
        "heading_level_match": float(
            left.metadata.get("heading_level") is not None
            and right.metadata.get("heading_level") is not None
            and left.metadata["heading_level"] == right.metadata["heading_level"]
        ),
        "title_similarity": similarity,
        "title_threshold_met": float(similarity >= 0.72),
        "relative_position_similarity": position,
    }


def pair_score_components(
    left: ContentBlock,
    right: ContentBlock,
    title_similarity: Callable[[str, str], float],
) -> tuple[float, dict[str, float]]:
    """Return the bounded ranking score and auditable components used for selection."""
    result = score_pair(left, right, 0, 0, 1, 1, title_similarity)
    return result.normalized_score, dict(result.components)


def group_score_components(
    group: Sequence[CourseBlock], title_similarity: Callable[[str, str], float]
) -> tuple[float, dict[str, float]]:
    """Aggregate transparent pair-ranking signals for a multilingual group."""
    first_block = group[0][1]
    first_release = group[0][0]
    first_index = first_release.blocks.index(first_block)
    comparisons = []
    for release, block in group[1:]:
        result = score_pair(
            first_block,
            block,
            first_index,
            release.blocks.index(block),
            len(first_release.blocks),
            len(release.blocks),
            title_similarity,
        )
        comparisons.append((result.normalized_score, result.components))
    if not comparisons:
        return 1.0, {}
    names = sorted({name for _, components in comparisons for name in components})
    components = {
        name: round(sum(values.get(name, 0.0) for _, values in comparisons) / len(comparisons), 8)
        for name in names
    }
    return round(sum(item[0] for item in comparisons) / len(comparisons), 8), components


def alignment_identity(group: Sequence[CourseBlock]) -> tuple[str, str]:
    """Derive a stable concept identity and disclose the method that produced it."""
    declared = {translation_key(block) for _, block in group if translation_key(block)}
    explicit = set(group[0][1].concepts)
    for _, block in group[1:]:
        explicit &= set(block.concepts)
    if len(declared) == 1:
        method = (
            "explicit-translation-id"
            if all(translation_key(block) for _, block in group)
            else "partial-translation-id"
        )
        return "translation:" + str(next(iter(declared))), method
    if explicit:
        return sorted(explicit)[0], "explicit-concept"
    seed = [(release.canonical_course_id, block.order) for release, block in group]
    return "derived:" + content_hash(seed).split(":", 1)[1][:20], "title-or-order-heuristic"


def semantic_group(
    group: Sequence[CourseBlock], releases: tuple[CourseRelease, ...]
) -> list[CourseBlock] | None:
    by_release: dict[str, list[ContentBlock]] = {}
    for release, block in group:
        by_release.setdefault(release.id, []).append(block)
    if any(release.id not in by_release for release in releases):
        return None
    return [
        (release, _combine(sorted(by_release[release.id], key=lambda item: item.order)))
        for release in releases
    ]


def _combine(blocks: list[ContentBlock]) -> ContentBlock:
    if len(blocks) == 1:
        return blocks[0]
    first = blocks[0]
    return ContentBlock(
        "relationship:" + content_hash([item.hash for item in blocks]).split(":", 1)[1][:24],
        first.kind,
        " / ".join(item.title for item in blocks),
        "\n\n".join(item.text for item in blocks),
        first.order,
        first.locator,
        parent_id=first.parent_id,
        concepts=tuple(sorted({value for item in blocks for value in item.concepts})),
        learning_objectives=tuple(
            sorted({value for item in blocks for value in item.learning_objectives})
        ),
        metadata={"constituent_block_ids": [item.id for item in blocks]},
    )


def translation_status(
    result: AlignmentResult, releases: tuple[CourseRelease, ...]
) -> tuple[TranslationUnitStatus, ...]:
    language_by_release = {release.id: release.language for release in releases}
    all_languages = {release.language for release in releases}
    review_blocks = {
        (evidence.course_release_id, evidence.block_id)
        for finding in result.findings
        for evidence in finding.evidence
    }
    statuses = []
    aligned_members: set[tuple[str, str]] = set()
    for alignment in result.alignments:
        aligned_members.update(alignment.members)
        present = {language_by_release[release_id] for release_id, _ in alignment.members}
        state = (
            "review-needed"
            if any(member in review_blocks for member in alignment.members)
            else "aligned"
        )
        if present != all_languages:
            state = "missing-translation"
        statuses.append(
            TranslationUnitStatus(
                alignment.concept_id,
                tuple(sorted(present)),
                tuple(sorted(all_languages - present)),
                state,
                alignment.members,
            )
        )
    for release in releases:
        for block in release.blocks:
            if (release.id, block.id) not in aligned_members:
                statuses.append(
                    TranslationUnitStatus(
                        "unaligned:" + block.id,
                        (release.language,),
                        tuple(sorted(all_languages - {release.language})),
                        "unaligned",
                        ((release.id, block.id),),
                    )
                )
    return tuple(statuses)


def parse_sealed_relationships(
    records: object, release_blocks: Mapping[tuple[str, str], ContentBlock]
) -> dict[str, set[tuple[str, str]]]:
    """Validate sealed alignment projections used by semantic evidence."""
    if not isinstance(records, (list, tuple)):
        raise ValueError("semantic evaluations require sealed alignment records")
    relationships: dict[str, set[tuple[str, str]]] = {}
    for alignment in records:
        legacy_fields = {"concept_id", "members", "confidence", "method", "cardinality"}
        current_fields = legacy_fields | {
            "alignment_score",
            "score_components",
            "score_version",
        }
        legacy = isinstance(alignment, Mapping) and set(alignment) == legacy_fields
        if (
            not isinstance(alignment, Mapping)
            or frozenset(alignment)
            not in {
                frozenset(legacy_fields),
                frozenset(current_fields),
            }
            or not isinstance(alignment["concept_id"], str)
            or not alignment["concept_id"].strip()
            or not isinstance(alignment["members"], (list, tuple))
            or len(alignment["members"]) < 2
            or not _valid_score(alignment["confidence"], nullable=True)
            or (
                not legacy
                and (
                    not _valid_score(alignment["alignment_score"])
                    or not _valid_components(alignment["score_components"])
                    or alignment["score_version"] != ALIGNMENT_SCORE_VERSION
                )
            )
            or alignment["method"]
            not in {
                "explicit-translation-id",
                "partial-translation-id",
                "explicit-concept",
                "title-or-order-heuristic",
            }
            or alignment["cardinality"]
            not in {"one-to-one", "one-to-many", "many-to-one", "many-to-many"}
        ):
            raise ValueError("semantic evaluation alignment record is invalid")
        members = tuple(
            (member[0], member[1])
            for member in alignment["members"]
            if isinstance(member, (list, tuple))
            and len(member) == 2
            and all(isinstance(item, str) and item for item in member)
        )
        if (
            len(members) != len(alignment["members"])
            or len(set(members)) != len(members)
            or any(member not in release_blocks for member in members)
        ):
            raise ValueError("semantic evaluation alignment member is invalid")
        identity = relationship_id(alignment["concept_id"], members)
        if identity in relationships:
            raise ValueError("semantic alignment relationship identifiers must be unique")
        relationships[identity] = set(members)
    return relationships

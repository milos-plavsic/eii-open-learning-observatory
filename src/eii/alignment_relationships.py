"""Relationship-level multilingual composition and status projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .alignment import Alignment, relationship_id
from .domain import ContentBlock, CourseRelease, Finding, content_hash

CourseBlock = tuple[CourseRelease, ContentBlock]


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
    left_translation, right_translation = translation_key(left), translation_key(right)
    if left_translation and left_translation == right_translation:
        return 12.0
    if left_translation or right_translation:
        return -12.0
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
    if left.metadata.get("heading_level") == right.metadata.get("heading_level"):
        score += 0.5
    similarity = title_similarity(left.title, right.title)
    if similarity >= 0.72:
        score += 3.0 * similarity
    if left_count > 1 and right_count > 1:
        left_position = left_index / (left_count - 1)
        right_position = right_index / (right_count - 1)
        score += max(0.0, 1.0 - abs(left_position - right_position) * 2)
    return score


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
        if (
            not isinstance(alignment, Mapping)
            or set(alignment) != {"concept_id", "members", "confidence", "method", "cardinality"}
            or not isinstance(alignment["concept_id"], str)
            or not alignment["concept_id"].strip()
            or not isinstance(alignment["members"], (list, tuple))
            or len(alignment["members"]) < 2
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

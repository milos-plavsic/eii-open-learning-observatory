"""Multilingual course alignment and deterministic semantic-drift signals."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from .alignment import Alignment, consolidate_alignments, relationship_id
from .alignment_relationships import (
    TranslationUnitStatus as TranslationUnitStatus,
)
from .alignment_relationships import (
    alignment_identity,
    group_score_components,
    pair_score,
    semantic_group,
    translation_key,
    validate_translation_ids,
)
from .alignment_relationships import (
    translation_status as translation_status,
)
from .babel_semantic import SemanticReleasePolicy, evidence_refs, semantic_findings
from .domain import (
    ContentBlock,
    CourseRelease,
    Finding,
    ModelRun,
    Severity,
    content_hash,
)
from .glossary import Glossary
from .literal_patterns import NUMBER_PATTERN
from .semantic_records import SemanticEvaluationRecord
from .semantics import SemanticComparator

_CODE, _LINK = (
    re.compile(r"`([^`]+)`|```(?:\w+)?\s*(.*?)```", re.DOTALL),
    re.compile(r"!?\[[^]]*]\(([^)]+)\)"),
)
CourseBlock = tuple[CourseRelease, ContentBlock]


@dataclass(frozen=True, slots=True)
class BabelResult:
    alignments: tuple[Alignment, ...]
    findings: tuple[Finding, ...]
    model_runs: tuple[ModelRun, ...] = ()
    semantic_evaluations: tuple[SemanticEvaluationRecord, ...] = ()
    semantic_evaluation_plan: tuple[Mapping[str, str], ...] = ()


def _normalized_title(title: str) -> str:
    return " ".join(re.findall(r"\w+", title.casefold(), re.UNICODE))


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized_title(left), _normalized_title(right)).ratio()


def _contains_term(text: str, term: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)"
    return bool(re.search(pattern, text.casefold(), re.UNICODE))


class BabelBridge:
    """Align releases and flag deterministic or model-assisted drift evidence."""

    def __init__(
        self,
        *,
        semantic_decision_threshold: float = 0.7,
        semantic_minimum_agreement: float = 0.5,
        semantic_maximum_minority_confidence: float | None = None,
        semantic_require_unanimity: bool = False,
        semantic_maximum_failed_members: int = 0,
        max_semantic_comparisons: int = 100,
    ):
        self.semantic_policy = SemanticReleasePolicy(
            semantic_decision_threshold,
            semantic_minimum_agreement,
            semantic_maximum_minority_confidence,
            semantic_require_unanimity,
            semantic_maximum_failed_members,
        )
        if max_semantic_comparisons < 1:
            raise ValueError("maximum semantic comparisons must be positive")
        self.max_semantic_comparisons = max_semantic_comparisons

    def analyze(
        self,
        releases: tuple[CourseRelease, ...],
        *,
        glossary: Glossary | None = None,
        comparator: SemanticComparator | None = None,
    ) -> BabelResult:
        if len(releases) < 2:
            raise ValueError("BabelBridge requires at least two language releases")
        canonical_ids = {r.canonical_course_id for r in releases}
        if len(canonical_ids) != 1:
            raise ValueError("releases must share one canonical_course_id")
        for release in releases:
            validate_translation_ids(release)

        base = releases[0]
        groups: list[list[tuple[CourseRelease, ContentBlock]]] = [
            [(base, block)] for block in base.blocks
        ]
        unmatched: list[tuple[CourseRelease, ContentBlock]] = []
        for release in releases[1:]:
            matches, available = self._align_release(base, release)
            for base_index, candidates in matches.items():
                groups[base_index].extend((release, release.blocks[index]) for index in candidates)
            unmatched.extend((release, release.blocks[i]) for i in available)

        alignments = consolidate_alignments(
            tuple(self._alignment(group) for group in groups if len(group) > 1), releases
        )
        member_index = {
            (release.id, block.id): (release, block)
            for release in releases
            for block in release.blocks
        }
        relationship_groups = [
            [member_index[member] for member in alignment.members] for alignment in alignments
        ]
        requested_comparisons = sum(
            len(releases) - 1
            for group in relationship_groups
            if all(any(item[0].id == release.id for item in group) for release in releases)
        )
        if comparator and requested_comparisons > self.max_semantic_comparisons:
            raise ValueError(
                f"semantic audit requires {requested_comparisons} comparisons, exceeding configured maximum {self.max_semantic_comparisons}"
            )
        findings: list[Finding] = []
        model_runs: list[ModelRun] = []
        semantic_evaluations: list[SemanticEvaluationRecord] = []
        semantic_evaluation_plan: list[Mapping[str, str]] = []
        for alignment, group in zip(alignments, relationship_groups, strict=True):
            findings.extend(self._group_findings(group, releases))
            if glossary:
                findings.extend(self._glossary_findings(group, glossary))
            composed_group = semantic_group(group, releases)
            if comparator and composed_group is not None:
                relation = relationship_id(alignment.concept_id, alignment.members)
                for release, _block in composed_group[1:]:
                    semantic_evaluation_plan.append(
                        {
                            "relationship_id": relation,
                            "left_release_id": composed_group[0][0].id,
                            "right_release_id": release.id,
                        }
                    )
                semantic, runs, evaluations = semantic_findings(
                    composed_group,
                    group,
                    relation,
                    comparator,
                    self.semantic_policy.confidence,
                    self.semantic_policy.agreement,
                    self.semantic_policy.maximum_minority_confidence,
                    self.semantic_policy.require_unanimity,
                    self.semantic_policy.maximum_failed_members,
                    self._finding,
                )
                findings.extend(semantic)
                model_runs.extend(runs)
                semantic_evaluations.extend(evaluations)
        for release, block in unmatched:
            findings.append(
                self._finding(
                    "translation.extra_unit",
                    f"Unaligned unit in {release.language}: {block.title}",
                    "This unit has no confident counterpart in the canonical language release.",
                    Severity.MEDIUM,
                    0.75,
                    ((release, block),),
                    (release.language,),
                    "Confirm whether this is intentional localization or missing source content.",
                )
            )
        return BabelResult(
            alignments,
            tuple(findings),
            tuple(model_runs),
            tuple(semantic_evaluations),
            tuple(semantic_evaluation_plan),
        )

    def _glossary_findings(self, group: Sequence[CourseBlock], glossary: Glossary) -> list[Finding]:
        findings = []
        concepts = set().union(*(set(block.concepts) for _, block in group))
        for term in glossary.terms:
            if term.concept_id not in concepts:
                continue
            for release, block in group:
                text = f"{block.title}\n{block.text}".casefold()
                forbidden = [
                    word
                    for word in term.forbidden.get(release.language, ())
                    if _contains_term(text, word)
                ]
                approved = term.translations.get(release.language, ())
                if forbidden or (
                    approved and not any(_contains_term(text, word) for word in approved)
                ):
                    findings.append(
                        self._finding(
                            "translation.terminology",
                            f"Terminology review needed in {release.language}",
                            f"Concept {term.concept_id} does not follow glossary {glossary.id}@{glossary.version}.",
                            Severity.MEDIUM,
                            0.95,
                            ((release, block),),
                            (release.language,),
                            "Use an approved term or record a justified glossary exception.",
                        )
                    )
        return findings

    @classmethod
    def _align_release(
        cls, base: CourseRelease, target: CourseRelease
    ) -> tuple[dict[int, list[int]], list[int]]:
        """Globally align hierarchies while preserving explicit many-to-one identities."""
        matches: dict[int, list[int]] = {}
        used_base: set[int] = set()
        used_target: set[int] = set()
        base_declared: dict[str, list[int]] = {}
        target_declared: dict[str, list[int]] = {}
        for index, block in enumerate(base.blocks):
            if identity := translation_key(block):
                base_declared.setdefault(identity, []).append(index)
        for index, block in enumerate(target.blocks):
            if identity := translation_key(block):
                target_declared.setdefault(identity, []).append(index)
        for identity in sorted(base_declared.keys() & target_declared.keys()):
            left, right = base_declared[identity], target_declared[identity]
            if len(left) == 1:
                matches[left[0]] = list(right)
                used_base.update(left)
                used_target.update(right)
            elif len(right) == 1:
                # A translated unit may intentionally merge several canonical units.
                # Retain the target in every canonical evidence group so no source
                # unit is falsely reported missing and every relationship is visible.
                for base_index in left:
                    matches[base_index] = list(right)
                used_base.update(left)
                used_target.update(right)
            else:
                # A repeated identity denotes one explicit many-to-many
                # relationship, not an instruction to guess pairings by order.
                for base_index in left:
                    matches[base_index] = list(right)
                used_base.update(left)
                used_target.update(right)

        left = [i for i in range(len(base.blocks)) if i not in used_base]
        right = [i for i in range(len(target.blocks)) if i not in used_target]
        n, m, gap = len(left), len(right), -2.0
        scores = [[0.0] * (m + 1) for _ in range(n + 1)]
        paths = [[""] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            scores[i][0], paths[i][0] = i * gap, "up"
        for j in range(1, m + 1):
            scores[0][j], paths[0][j] = j * gap, "left"
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                pair = cls._pair_score(
                    base.blocks[left[i - 1]], target.blocks[right[j - 1]], i - 1, j - 1, n, m
                )
                options = (
                    (scores[i - 1][j - 1] + pair, "diag"),
                    (scores[i - 1][j] + gap, "up"),
                    (scores[i][j - 1] + gap, "left"),
                )
                scores[i][j], paths[i][j] = max(options, key=lambda item: item[0])
        i, j = n, m
        while i or j:
            direction = paths[i][j]
            if direction == "diag":
                base_index, target_index = left[i - 1], right[j - 1]
                if (
                    cls._pair_score(
                        base.blocks[base_index], target.blocks[target_index], i - 1, j - 1, n, m
                    )
                    >= 2.5
                ):
                    matches.setdefault(base_index, []).append(target_index)
                    used_target.add(target_index)
                i -= 1
                j -= 1
            elif direction == "up":
                i -= 1
            else:
                j -= 1
        return matches, [index for index in range(len(target.blocks)) if index not in used_target]

    @staticmethod
    def _pair_score(
        left: ContentBlock,
        right: ContentBlock,
        left_index: int,
        right_index: int,
        left_count: int,
        right_count: int,
    ) -> float:
        return pair_score(
            left, right, left_index, right_index, left_count, right_count, _similarity
        )

    @staticmethod
    def _alignment(group: Sequence[CourseBlock]) -> Alignment:
        concept_id, method = alignment_identity(group)
        alignment_score, components = group_score_components(group, _similarity)
        return Alignment(
            concept_id,
            tuple((r.id, b.id) for r, b in group),
            None,
            method,
            alignment_score=alignment_score,
            score_components=components,
        )

    def _group_findings(
        self, group: Sequence[CourseBlock], releases: tuple[CourseRelease, ...]
    ) -> list[Finding]:
        present = {r.id for r, _ in group}
        if len(present) != len(releases):
            missing = tuple(r.language for r in releases if r.id not in present)
            return [
                self._finding(
                    "translation.missing_unit",
                    f"Unit missing in {', '.join(missing)}",
                    f"The aligned unit '{group[0][1].title}' is absent from one or more releases.",
                    Severity.HIGH,
                    0.9,
                    tuple(group),
                    missing,
                    "Add the corresponding unit or record an intentional-localization review decision.",
                )
            ]

        findings = []
        by_release: dict[str, list[ContentBlock]] = {}
        for release, block in group:
            by_release.setdefault(release.id, []).append(block)
        for label, pattern, severity in (
            ("code", _CODE, Severity.HIGH),
            ("number_or_unit", NUMBER_PATTERN, Severity.HIGH),
            ("link_or_asset", _LINK, Severity.MEDIUM),
        ):
            values = []
            for release in releases:
                blocks = sorted(by_release[release.id], key=lambda item: item.order)
                values.append(
                    tuple(
                        self._literal(label, match)
                        for block in blocks
                        for match in pattern.finditer(block.text)
                    )
                )
            if not any(value != values[0] for value in values[1:]):
                continue
            same_multiset = all(Counter(value) == Counter(values[0]) for value in values[1:])
            order_only = label in {"number_or_unit", "link_or_asset"} and same_multiset
            findings.append(
                self._finding(
                    f"translation.{label}_{'order_' if order_only else ''}drift",
                    (
                        f"Reordered {label.replace('_', ' ')} across languages"
                        if order_only
                        else f"Changed {label.replace('_', ' ')} across languages"
                    ),
                    f"Aligned passages contain different {label.replace('_', ' ')} literals: {values!r}.",
                    Severity.LOW if order_only else severity,
                    0.95,
                    tuple(group),
                    tuple(r.language for r, _ in group),
                    (
                        "Confirm that reordering preserves instructional and assessment meaning."
                        if order_only
                        else "Verify the literals are equivalent and preserve assessment validity."
                    ),
                )
            )
        return findings

    @staticmethod
    def _literal(label: str, match: re.Match[str]) -> str:
        if label == "code":
            return (match.group(1) or match.group(2) or "").strip()
        if label == "link_or_asset":
            return match.group(1).strip()
        value = match.group(0).strip().casefold().replace("−", "-")  # noqa: RUF001
        value = re.sub(r"(?<=\d),(?=\d)", ".", value)
        return re.sub(r"\s+", "", value)

    @staticmethod
    def _finding(
        kind: str,
        title: str,
        explanation: str,
        severity: Severity,
        confidence: float,
        group: Sequence[CourseBlock],
        languages: tuple[str, ...],
        action: str,
    ) -> Finding:
        refs = evidence_refs(group)
        finding_id = (
            "babel:"
            + content_hash(
                {"kind": kind, "refs": [(r.course_release_id, r.block_id) for r in refs]}
            ).split(":", 1)[1][:24]
        )
        return Finding(
            finding_id,
            kind,
            title,
            explanation,
            severity,
            confidence,
            refs,
            tuple(languages),
            action,
        )

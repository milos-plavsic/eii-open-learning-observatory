"""Curriculum MRI: evidence-backed structural and editorial course analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .domain import ContentBlock, CourseRelease, EvidenceRef, Finding, Severity, content_hash


@dataclass(frozen=True, slots=True)
class Objective:
    id: str
    description: str
    concepts: tuple[str, ...]
    prerequisites: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Assessment:
    id: str
    block_id: str
    objective_ids: tuple[str, ...]
    expected_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CurriculumSpec:
    id: str
    version: str
    objectives: tuple[Objective, ...]
    assessments: tuple[Assessment, ...]

    @classmethod
    def load(cls, path: Path) -> CurriculumSpec:
        data = json.loads(path.read_text("utf-8"))
        return cls(
            data["id"],
            str(data["version"]),
            tuple(
                Objective(
                    x["id"],
                    x["description"],
                    tuple(x.get("concepts", ())),
                    tuple(x.get("prerequisites", ())),
                )
                for x in data["objectives"]
            ),
            tuple(
                Assessment(
                    x["id"],
                    x["block_id"],
                    tuple(x.get("objective_ids", ())),
                    tuple(x.get("expected_evidence", ())),
                )
                for x in data["assessments"]
            ),
        )


class CurriculumMRI:
    def analyze(self, release: CourseRelease, spec: CurriculumSpec) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        blocks = {b.id: b for b in release.blocks}
        assessed = {oid for assessment in spec.assessments for oid in assessment.objective_ids}
        objective_map = {o.id: o for o in spec.objectives}

        for objective in spec.objectives:
            supporting = [b for b in release.blocks if set(objective.concepts) & set(b.concepts)]
            if objective.id not in assessed:
                findings.append(
                    self._finding(
                        release,
                        "curriculum.unassessed_objective",
                        f"Objective is taught but never assessed: {objective.description}",
                        "No assessment maps to this learning objective.",
                        Severity.HIGH,
                        supporting,
                    )
                )
            if not supporting:
                findings.append(
                    self._finding(
                        release,
                        "curriculum.unsupported_objective",
                        f"No course evidence for objective: {objective.description}",
                        "No content block declares a supporting concept.",
                        Severity.HIGH,
                        [],
                    )
                )
            if supporting:
                first_order = min(b.order for b in supporting)
                for prerequisite in objective.prerequisites:
                    prereq = objective_map.get(prerequisite)
                    prereq_blocks = [
                        b
                        for b in release.blocks
                        if prereq and set(prereq.concepts) & set(b.concepts)
                    ]
                    if not prereq_blocks or min(b.order for b in prereq_blocks) >= first_order:
                        findings.append(
                            self._finding(
                                release,
                                "curriculum.prerequisite_jump",
                                f"Prerequisite jump before {objective.description}",
                                f"Prerequisite '{prerequisite}' is absent or first appears too late.",
                                Severity.HIGH,
                                supporting + prereq_blocks,
                            )
                        )

        for assessment in spec.assessments:
            block = blocks.get(assessment.block_id)
            if not block:
                findings.append(
                    self._finding(
                        release,
                        "curriculum.missing_assessment",
                        f"Assessment source is missing: {assessment.id}",
                        f"Expected block {assessment.block_id} does not exist.",
                        Severity.CRITICAL,
                        [],
                    )
                )
                continue
            course_text = " ".join(
                b.text.casefold() for b in release.blocks if b.order <= block.order
            )
            missing = [
                phrase
                for phrase in assessment.expected_evidence
                if phrase.casefold() not in course_text
            ]
            if missing:
                findings.append(
                    self._finding(
                        release,
                        "curriculum.unsupported_question",
                        f"Course may not support assessment {assessment.id}",
                        f"Expected evidence is absent before the assessment: {missing!r}.",
                        Severity.HIGH,
                        [block],
                    )
                )

        for block in release.blocks:
            words = re.findall(r"\w+", block.text, re.UNICODE)
            sentences = max(1, len(re.findall(r"[.!?]+", block.text)))
            if len(words) >= 80 and len(words) / sentences > 28:
                findings.append(
                    self._finding(
                        release,
                        "accessibility.sentence_complexity",
                        f"Dense passage: {block.title}",
                        f"Average sentence length is {len(words) / sentences:.1f} words.",
                        Severity.MEDIUM,
                        [block],
                    )
                )
            images = re.findall(r"!\[([^]]*)]\([^)]+\)", block.text)
            if any(not alt.strip() for alt in images):
                findings.append(
                    self._finding(
                        release,
                        "accessibility.missing_alt_text",
                        f"Image lacks alternative text: {block.title}",
                        "At least one Markdown image has empty alternative text.",
                        Severity.HIGH,
                        [block],
                    )
                )
        return tuple(findings)

    @staticmethod
    def _finding(
        release: CourseRelease,
        kind: str,
        title: str,
        explanation: str,
        severity: Severity,
        blocks: list[ContentBlock],
    ) -> Finding:
        refs = tuple(EvidenceRef(release.id, b.id, b.hash, b.text[:240] or None) for b in blocks)
        key = {
            "release": release.hash,
            "kind": kind,
            "title": title,
            "blocks": [b.id for b in blocks],
        }
        return Finding(
            "mri:" + content_hash(key).split(":", 1)[1][:24],
            kind,
            title,
            explanation,
            severity,
            1.0 if kind.startswith("accessibility") else 0.9,
            refs,
            (release.language,),
            "Review the cited source and add or revise course evidence.",
        )

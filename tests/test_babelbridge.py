import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from eii.adapters import RepositoryAdapter
from eii.alignment_relationships import group_score_components, pair_score_components
from eii.babelbridge import Alignment, BabelBridge, BabelResult, _similarity, translation_status
from eii.cli import main
from eii.domain import (
    ContentBlock,
    CourseRelease,
    EvidenceBundle,
    EvidenceRef,
    Finding,
    ModelRun,
    Severity,
    SourceLocator,
    UnitKind,
)
from eii.evidence import load_audit_directory, load_bundle, write_bundle
from eii.glossary import Glossary
from eii.semantics import SemanticJudgment

FIXTURES = Path(__file__).parent / "fixtures"


class BabelBridgeTests(unittest.TestCase):
    def setUp(self):
        adapter = RepositoryAdapter()
        self.en = adapter.load(FIXTURES / "course_en")
        self.sr = adapter.load(FIXTURES / "course_sr")

    def test_semantic_comparison_capacity_validation(self):
        class Equivalent:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(
                    True,
                    1,
                    "same",
                    {"meaning": True},
                    ModelRun("p", "m", "v", {}, "input", "output"),
                )

        with self.assertRaisesRegex(ValueError, "maximum semantic comparisons"):
            BabelBridge(max_semantic_comparisons=0)
        with self.assertRaisesRegex(ValueError, "exceeding configured maximum"):
            BabelBridge(max_semantic_comparisons=1).analyze(
                (self.en, self.sr), comparator=Equivalent()
            )

    def test_repeated_concept_has_distinct_semantic_relationship_identity(self):
        base = self._release(
            "en",
            (
                ("a", "A", "A", "shared.concept", {}),
                ("b", "B", "B", "shared.concept", {}),
            ),
        )
        target = self._release(
            "sr",
            (
                ("a", "A", "A", "shared.concept", {}),
                ("b", "B", "B", "shared.concept", {}),
            ),
        )

        class Equivalent:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(
                    True,
                    1,
                    "same",
                    {"meaning": True},
                    ModelRun("p", "m", "v", {}, "input", "output"),
                )

        result = BabelBridge().analyze((base, target), comparator=Equivalent())
        self.assertEqual(len({item.relationship_id for item in result.semantic_evaluations}), 2)

    def test_aligns_by_order_and_reports_literal_drift(self):
        result = BabelBridge().analyze((self.en, self.sr))
        self.assertEqual(len(result.alignments), 2)
        kinds = {finding.finding_type for finding in result.findings}
        self.assertIn("translation.code_drift", kinds)
        self.assertIn("translation.number_or_unit_drift", kinds)
        self.assertTrue(all(finding.evidence for finding in result.findings))
        statuses = translation_status(result, (self.en, self.sr))
        self.assertIn("review-needed", {item.state for item in statuses})

    def test_translation_review_status_uses_release_and_block_identity(self):
        left = self._release(
            "en",
            (("shared", "A", "A", "a", {}), ("other", "B", "B", "b", {})),
        )
        right = self._release(
            "sr",
            (("other", "A", "A", "a", {}), ("shared", "B", "B", "b", {})),
        )
        left = replace(
            left,
            blocks=(
                replace(left.blocks[0], id="shared", hash=""),
                replace(left.blocks[1], id="other", hash=""),
            ),
            hash="",
        )
        right = replace(
            right,
            blocks=(
                replace(right.blocks[0], id="other", hash=""),
                replace(right.blocks[1], id="shared", hash=""),
            ),
            hash="",
        )
        evidence = left.blocks[0]
        finding = Finding(
            "f",
            "translation.test",
            "T",
            "E",
            Severity.MEDIUM,
            1,
            (EvidenceRef(left.id, evidence.id, evidence.hash, evidence.text),),
        )
        result = BabelResult(
            (
                Alignment(
                    "a",
                    ((left.id, left.blocks[0].id), (right.id, right.blocks[0].id)),
                    1,
                    "explicit-concept",
                ),
                Alignment(
                    "b",
                    ((left.id, left.blocks[1].id), (right.id, right.blocks[1].id)),
                    1,
                    "explicit-concept",
                ),
            ),
            (finding,),
        )
        states = {item.concept_id: item.state for item in translation_status(result, (left, right))}
        self.assertEqual(states, {"a": "review-needed", "b": "aligned"})

    def test_translated_nouns_are_not_units_but_allowlisted_units_are_compared(self):
        prose_en = self._release(
            "en", (("count", "Count", "5 apples on the table and 3 dogs", "count", {}),)
        )
        prose_sr = self._release(
            "sr", (("count", "Brojanje", "5 jabuka na stolu i 3 psa", "count", {}),)
        )
        prose = BabelBridge().analyze((prose_en, prose_sr))
        self.assertNotIn(
            "translation.number_or_unit_drift", {item.finding_type for item in prose.findings}
        )

        metric = self._release("en", (("mass", "Mass", "The package is 10 kg.", "mass", {}),))
        imperial = self._release("sr", (("mass", "Masa", "Paket ima 10 lbs.", "mass", {}),))
        drift = BabelBridge().analyze((metric, imperial))
        self.assertIn(
            "translation.number_or_unit_drift", {item.finding_type for item in drift.findings}
        )

    def test_cli_writes_reproducible_evidence_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report"
            code = main(
                [
                    "audit",
                    str(FIXTURES / "course_en"),
                    str(FIXTURES / "course_sr"),
                    "--output",
                    str(output),
                    "--semantic-threshold",
                    "0.8",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((output / "evidence.json").exists())
            self.assertTrue((output / "alignments.json").exists())
            self.assertTrue((output / "index.html").exists())
            html = (output / "index.html").read_text()
            self.assertNotIn("onclick=", html)
            self.assertIn("data-decision=", html)
            evidence = json.loads((output / "evidence.json").read_text())
            self.assertEqual(evidence["metadata"]["semantic_policy"]["decision_threshold"], 0.8)
            self.assertEqual(
                evidence["metadata"]["audit_artifacts"]["alignments"]["records"],
                json.loads((output / "alignments.json").read_text()),
            )
            embedded = html.split('<script type="application/json" id="eii-data">', 1)[1].split(
                "</script>", 1
            )[0]
            self.assertEqual(json.loads(embedded)["bundle"]["id"], evidence["id"])
            self.assertTrue((output / "translation-status.json").exists())
            self.assertEqual(load_audit_directory(output).id, evidence["id"])
            self.assertEqual(main(["validate", str(output)]), 0)
            alignments_path = output / "alignments.json"
            original = alignments_path.read_text()
            alignments_path.write_text("[]")
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_audit_directory(output)
            alignments_path.write_text(original)
            report_path = output / "index.html"
            original_report = report_path.read_text()
            report_path.write_text("<html></html>")
            with self.assertRaisesRegex(ValueError, "embedded evidence"):
                load_audit_directory(output)
            report_path.write_text(original_report)

            bundle = load_bundle(output / "evidence.json")
            original_evidence = (output / "evidence.json").read_text()
            write_bundle(
                replace(
                    bundle,
                    metadata={
                        "semantic_evaluations_schema_version": "2.0",
                        "semantic_evaluations": [],
                    },
                ),
                output / "evidence.json",
            )
            with self.assertRaisesRegex(ValueError, "sealed alignment records"):
                load_audit_directory(output)
            (output / "evidence.json").write_text(original_evidence)

            metadata = json.loads(json.dumps(bundle.metadata))
            metadata["audit_artifacts"]["alignments"] = {}
            write_bundle(replace(bundle, metadata=metadata), output / "evidence.json")
            with self.assertRaisesRegex(ValueError, "sealed alignment records"):
                load_audit_directory(output)
            metadata = json.loads(json.dumps(bundle.metadata))
            metadata["audit_artifacts"]["alignments"]["content_hash"] = "sha256:" + "0" * 64
            write_bundle(replace(bundle, metadata=metadata), output / "evidence.json")
            with self.assertRaisesRegex(ValueError, "hash does not match"):
                load_audit_directory(output)
            (output / "evidence.json").write_text(original_evidence)

            report_path.write_text('<script type="application/json" id="eii-data">{}')
            with self.assertRaisesRegex(ValueError, "embedded evidence"):
                load_audit_directory(output)
            report_path.write_text('<script type="application/json" id="eii-data">[]</script>')
            with self.assertRaisesRegex(ValueError, "bundle does not match"):
                load_audit_directory(output)
            embedded_payload = json.loads(embedded)
            embedded_payload["alignments"] = []
            report_path.write_text(
                '<script type="application/json" id="eii-data">'
                + json.dumps(embedded_payload)
                + "</script>"
            )
            with self.assertRaisesRegex(ValueError, "report alignments"):
                load_audit_directory(output)
            report_path.write_text(original_report)

    def test_glossary_flags_forbidden_term(self):
        glossary = Glossary.load(FIXTURES / "glossary.json")
        block = self.sr.blocks[0]
        changed = ContentBlock(
            block.id,
            block.kind,
            block.title,
            "Omča ponavlja naredbe.",
            block.order,
            block.locator,
            concepts=("programming.loop",),
        )
        release = CourseRelease(
            self.sr.id,
            self.sr.course_key,
            self.sr.language,
            self.sr.version,
            self.sr.title,
            (changed, *self.sr.blocks[1:]),
            self.sr.source,
            canonical_course_id=self.sr.canonical_course_id,
        )
        en_block = self.en.blocks[0]
        en_changed = ContentBlock(
            en_block.id,
            en_block.kind,
            en_block.title,
            en_block.text,
            en_block.order,
            en_block.locator,
            concepts=("programming.loop",),
        )
        en = CourseRelease(
            self.en.id,
            self.en.course_key,
            self.en.language,
            self.en.version,
            self.en.title,
            (en_changed, *self.en.blocks[1:]),
            self.en.source,
            canonical_course_id=self.en.canonical_course_id,
        )
        result = BabelBridge().analyze((en, release), glossary=glossary)
        self.assertIn("translation.terminology", {f.finding_type for f in result.findings})

    @staticmethod
    def _release(language, specifications):
        locator = SourceLocator("fixture", language, "lesson.md")
        blocks = tuple(
            ContentBlock(
                f"{language}:{name}",
                UnitKind.SECTION,
                title,
                text,
                index,
                locator,
                concepts=(concept,) if concept else (),
                metadata=metadata,
            )
            for index, (name, title, text, concept, metadata) in enumerate(specifications, 1)
        )
        return CourseRelease(
            f"course:{language}:1",
            "course",
            language,
            "1",
            "Course",
            blocks,
            locator,
            canonical_course_id="course",
        )

    def test_insertion_does_not_cascade_subsequent_alignments(self):
        base = self._release(
            "en",
            (
                ("a", "Variables", "Variables", "concept.a", {}),
                ("b", "Loops", "Loops", "concept.b", {}),
                ("c", "Functions", "Functions", "concept.c", {}),
            ),
        )
        target = self._release(
            "sr",
            (
                ("a", "Promenljive", "Promenljive", "concept.a", {}),
                ("extra", "Napomena", "Dodatak", "concept.extra", {}),
                ("b", "Petlje", "Petlje", "concept.b", {}),
                ("c", "Funkcije", "Funkcije", "concept.c", {}),
            ),
        )
        result = BabelBridge().analyze((base, target))
        members = {alignment.concept_id: alignment.members for alignment in result.alignments}
        self.assertEqual({member[1] for member in members["concept.b"]}, {"en:b", "sr:b"})
        self.assertEqual({member[1] for member in members["concept.c"]}, {"en:c", "sr:c"})
        extras = [
            finding
            for finding in result.findings
            if finding.finding_type == "translation.extra_unit"
        ]
        self.assertEqual([finding.evidence[0].block_id for finding in extras], ["sr:extra"])

    def test_explicit_translation_identity_supports_split_target_unit(self):
        base = self._release(
            "en", (("loops", "Loops", "Combined lesson", None, {"translation_id": "loops"}),)
        )
        target = self._release(
            "sr",
            (
                ("loops-1", "Petlje I", "Prvi deo", None, {"translation_id": "loops"}),
                ("loops-2", "Petlje II", "Drugi deo", None, {"translation_id": "loops"}),
            ),
        )
        result = BabelBridge().analyze((base, target))
        self.assertEqual(len(result.alignments), 1)
        self.assertEqual(len(result.alignments[0].members), 3)
        self.assertEqual(result.alignments[0].method, "explicit-translation-id")
        self.assertEqual(result.alignments[0].cardinality, "one-to-many")

    def test_explicit_translation_identity_supports_merged_target_unit(self):
        base = self._release(
            "en",
            (
                ("loops-1", "Loops I", "First part", None, {"translation_id": "loops"}),
                ("loops-2", "Loops II", "Second part", None, {"translation_id": "loops"}),
            ),
        )
        target = self._release(
            "sr", (("loops", "Petlje", "Spojena lekcija", None, {"translation_id": "loops"}),)
        )
        result = BabelBridge().analyze((base, target))
        self.assertEqual(len(result.alignments), 1)
        self.assertEqual(len(result.alignments[0].members), 3)
        self.assertEqual(result.alignments[0].cardinality, "many-to-one")
        self.assertNotIn(
            "translation.missing_unit", {finding.finding_type for finding in result.findings}
        )

    def test_merged_semantic_drift_uses_only_canonical_constituent_evidence(self):
        base = self._release(
            "en",
            (
                ("a", "A", "First", None, {"translation_id": "shared"}),
                ("b", "B", "Second", None, {"translation_id": "shared"}),
            ),
        )
        target = self._release(
            "sr", (("merged", "AB", "Changed", None, {"translation_id": "shared"}),)
        )
        run = ModelRun("p", "m", "v", {}, "input", "output")

        class Drift:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(False, 0.9, "meaning changed", {"meaning": False}, run)

        result = BabelBridge().analyze((base, target), comparator=Drift())
        finding = next(
            item for item in result.findings if item.finding_type == "translation.semantic_drift"
        )
        self.assertEqual(
            {item.block_id for item in finding.evidence}, {"en:a", "en:b", "sr:merged"}
        )
        self.assertFalse(
            any(item.block_id.startswith("relationship:") for item in finding.evidence)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            write_bundle(
                replace(
                    EvidenceBundle.create((base, target), result.findings),
                    model_runs=result.model_runs,
                ),
                path,
            )
            self.assertEqual(len(load_bundle(path).findings), len(result.findings))

    def test_scopes_reused_translation_identifiers(self):
        base = self._release(
            "en",
            (
                ("a", "A", "A", None, {"translation_id": "generic", "translation_scope": "a"}),
                ("b", "B", "B", None, {"translation_id": "generic", "translation_scope": "b"}),
            ),
        )
        target = self._release(
            "sr",
            (
                ("a", "A", "A", None, {"translation_id": "generic", "translation_scope": "a"}),
                ("b", "B", "B", None, {"translation_id": "generic", "translation_scope": "b"}),
            ),
        )
        result = BabelBridge().analyze((base, target))
        self.assertEqual(
            {item.concept_id for item in result.alignments},
            {"translation:a::generic", "translation:b::generic"},
        )
        mismatched = self._release(
            "hr",
            (("a", "A", "A", None, {"translation_id": "generic", "translation_scope": "other"}),),
        )
        self.assertFalse(
            BabelBridge()
            .analyze(
                (
                    self._release(
                        "en",
                        (
                            (
                                "a",
                                "A",
                                "A",
                                None,
                                {"translation_id": "generic", "translation_scope": "a"},
                            ),
                        ),
                    ),
                    mismatched,
                )
            )
            .alignments
        )
        invalid_base = self._release(
            "en",
            (
                ("a", "A", "A", None, {"translation_id": "generic"}),
                ("b", "B", "B", None, {"translation_id": "generic"}),
            ),
        )
        invalid = replace(
            invalid_base,
            blocks=(
                replace(invalid_base.blocks[0], parent_id="parent-a", hash=""),
                replace(invalid_base.blocks[1], parent_id="parent-b", hash=""),
            ),
            hash="",
        )
        with self.assertRaisesRegex(ValueError, "spans parents"):
            BabelBridge().analyze((invalid, target))

    def test_semantic_comparator_abstains_below_configured_threshold(self):
        run = ModelRun("p", "m", "v", {}, "i", "o")

        class Comparator:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(
                    False, 0.4, "Evaluator is uncertain", {"same_meaning": False}, run
                )

        result = BabelBridge(semantic_decision_threshold=0.7).analyze(
            (self.en, self.sr), comparator=Comparator()
        )
        semantic = [
            item for item in result.findings if item.finding_type.startswith("translation.semantic")
        ]
        self.assertEqual(
            {item.finding_type for item in semantic}, {"translation.semantic_uncertain"}
        )
        signals = result.semantic_evaluations[0].decision_signals
        self.assertIsNone(signals["completion_ratio"])
        self.assertEqual(signals["failed_member_count"], 0)
        self.assertTrue(
            all(
                value["majority_mean_confidence"] is None
                for value in signals["property_signals"].values()
            )
        )
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            BabelBridge(semantic_decision_threshold=1.1)

    def test_input_validation_semantic_drift_and_unaligned_status(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            BabelBridge().analyze((self.en,))
        other = CourseRelease(
            self.sr.id,
            self.sr.course_key,
            self.sr.language,
            self.sr.version,
            self.sr.title,
            self.sr.blocks,
            self.sr.source,
            canonical_course_id="other",
        )
        with self.assertRaisesRegex(ValueError, "canonical"):
            BabelBridge().analyze((self.en, other))
        run = ModelRun("p", "m", "v", {}, "i", "o")

        class Comparator:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(False, 0.8, "Meaning changed", {}, run)

        result = BabelBridge().analyze((self.en, self.sr), comparator=Comparator())
        drift = [f for f in result.findings if f.finding_type == "translation.semantic_drift"]
        self.assertEqual(drift[0].model_run, run)

        class EquivalentComparator:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(True, 1, "Equivalent", {}, run)

        self.assertFalse(
            any(
                f.finding_type == "translation.semantic_drift"
                for f in BabelBridge()
                .analyze((self.en, self.sr), comparator=EquivalentComparator())
                .findings
            )
        )
        passed = BabelBridge().analyze((self.en, self.sr), comparator=EquivalentComparator())
        self.assertGreater(len(passed.model_runs), 0)
        self.assertTrue(all(item.outcome == "equivalent" for item in passed.semantic_evaluations))

        class UncertainComparator:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(True, 0.1, "Needs review", {}, run)

        uncertain = BabelBridge().analyze((self.en, self.sr), comparator=UncertainComparator())
        self.assertIn(
            "review-needed",
            {item.state for item in translation_status(uncertain, (self.en, self.sr))},
        )

        class SplitPanelComparator:
            def compare(self, *args, **kwargs):
                return SemanticJudgment(
                    True,
                    0.95,
                    "Bare majority",
                    {},
                    run,
                    agreement_ratio=0.6,
                    majority_mean_confidence=0.95,
                    minority_mean_confidence=0.99,
                )

        policy_rejected = BabelBridge(
            semantic_minimum_agreement=0.8,
            semantic_maximum_minority_confidence=0.8,
        ).analyze((self.en, self.sr), comparator=SplitPanelComparator())
        self.assertTrue(
            all(item.outcome == "abstained" for item in policy_rejected.semantic_evaluations)
        )
        lone = BabelResult((), ())
        statuses = translation_status(lone, (self.en, self.sr))
        self.assertTrue(all(item.state == "unaligned" for item in statuses))

    def test_many_canonical_to_one_target_and_pair_score_edges(self):
        base = self._release(
            "en",
            (
                ("a", "A", "same", None, {"translation_id": "shared"}),
                ("b", "B", "same", None, {"translation_id": "shared"}),
            ),
        )
        target = self._release("sr", (("x", "X", "same", None, {"translation_id": "shared"}),))
        matches, _ = BabelBridge._align_release(base, target)
        self.assertEqual(matches, {0: [0], 1: [0]})
        split = self._release(
            "hr",
            (
                ("x", "X", "x", None, {"translation_id": "shared"}),
                ("y", "Y", "y", None, {"translation_id": "shared"}),
            ),
        )
        BabelBridge._align_release(base, split)
        matches, _ = BabelBridge._align_release(base, split)
        self.assertEqual(matches, {0: [0, 1], 1: [0, 1]})
        self.assertEqual(BabelBridge._pair_score(base.blocks[0], target.blocks[0], 0, 0, 1, 1), 12)
        identical = ContentBlock(
            base.blocks[0].id,
            UnitKind.SECTION,
            "A",
            "x",
            1,
            SourceLocator("fixture", "x", "lesson.md"),
            metadata={},
        )
        score = BabelBridge._pair_score(base.blocks[0], identical, 0, 0, 2, 2)
        self.assertGreater(score, 6)
        explicit_score, components = pair_score_components(
            base.blocks[0], target.blocks[0], _similarity
        )
        self.assertEqual(explicit_score, 1)
        self.assertEqual(components["translation_id_match"], 1)
        partial_score, partial_components = pair_score_components(
            base.blocks[0], identical, _similarity
        )
        self.assertGreater(partial_score, 0)
        self.assertEqual(partial_components["translation_id_missing"], 1)
        conflicting = replace(target.blocks[0], metadata={"translation_id": "different"}, hash="")
        conflict_score, conflict_components = pair_score_components(
            base.blocks[0], conflicting, _similarity
        )
        self.assertEqual(conflict_score, 0)
        self.assertEqual(conflict_components["translation_id_conflict"], 1)
        self.assertEqual(BabelBridge._pair_score(base.blocks[0], conflicting, 0, 0, 1, 1), -12)
        self.assertEqual(group_score_components(((base, base.blocks[0]),), _similarity), (1.0, {}))
        plain_left = replace(base.blocks[0], metadata={}, hash="")
        same_identity = replace(plain_left, hash="")
        self.assertGreater(BabelBridge._pair_score(plain_left, same_identity, 0, 0, 2, 2), 6)
        weak_pair = replace(
            plain_left,
            id="different",
            title="unrelated",
            locator=SourceLocator("fixture", "other", "different.md"),
            hash="",
        )
        weak_base = replace(base, blocks=(plain_left,), hash="")
        weak_target_release = replace(target, blocks=(weak_pair,), hash="")
        self.assertEqual(BabelBridge._align_release(weak_base, weak_target_release)[0], {})
        weak_locator = SourceLocator("fixture", "pt", "other.md")
        weak_block = ContentBlock(
            "pt:z",
            UnitKind.ASSESSMENT,
            "Entirely unrelated",
            "x",
            1,
            weak_locator,
            metadata={"heading_level": 9},
        )
        weak = CourseRelease(
            "course:pt:1",
            "course",
            "pt",
            "1",
            "Course",
            (weak_block,),
            weak_locator,
            canonical_course_id="course",
        )
        matches, available = BabelBridge._align_release(base, weak)
        self.assertEqual(matches, {})
        self.assertEqual(available, [0])

    def test_link_literal_and_missing_translation_status(self):
        self.assertEqual(
            BabelBridge._literal(
                "link_or_asset", __import__("re").search(r"!\[[^]]*]\(([^)]+)\)", "![x]( a.png )")
            ),
            "a.png",
        )
        alignment = Alignment("c", ((self.en.id, self.en.blocks[0].id),), 0.9, "explicit-concept")
        result = BabelResult(
            (alignment,),
            (Finding("f", "translation.code_drift", "t", "e", Severity.HIGH, 0.9, ()),),
        )
        status = translation_status(result, (self.en, self.sr))[0]
        self.assertEqual(status.state, "missing-translation")


if __name__ == "__main__":
    unittest.main()

import copy
import math
import unittest

from eii.domain import (
    ContentBlock,
    CourseRelease,
    EvidenceBundle,
    Finding,
    ModelRun,
    Severity,
    SourceLocator,
    UnitKind,
    canonical_json,
    content_hash,
    freeze_json,
    to_dict,
)


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.locator = SourceLocator("fixture", "course", "lesson.md", "intro")
        self.block = ContentBlock(
            "lesson:intro", UnitKind.SECTION, "Loops", "Use a loop.", 1, self.locator
        )

    def test_hash_is_deterministic(self):
        self.assertEqual(content_hash({"b": 2, "a": 1}), content_hash({"a": 1, "b": 2}))
        self.assertEqual(canonical_json({"numbers": [-0.0, 1e30]}), '{"numbers":[0,1e+30]}')
        for value in (math.nan, math.inf, 2**60, {1: "non-string key"}, object()):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                content_hash(value)

    def test_hashed_metadata_is_recursively_immutable(self):
        metadata = {"nested": {"values": [1, 2]}}
        block = ContentBlock(
            "b", UnitKind.SECTION, "Title", "Text", 0, self.locator, metadata=metadata
        )
        metadata["nested"]["values"].append(3)
        self.assertEqual(block.metadata["nested"]["values"], (1, 2))
        with self.assertRaises(TypeError):
            block.metadata["new"] = True
        self.assertIs(copy.deepcopy(block.metadata), block.metadata)
        mutations = (
            lambda: block.metadata.__delitem__("nested"),
            block.metadata.clear,
            lambda: block.metadata.pop("nested"),
            block.metadata.popitem,
            lambda: block.metadata.setdefault("new", True),
            lambda: block.metadata.update({"new": True}),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(TypeError):
                mutation()
        self.assertEqual(canonical_json(Severity.HIGH), '"high"')
        self.assertIsNone(freeze_json(None))
        self.assertEqual(freeze_json(Severity.HIGH), "high")
        with self.assertRaisesRegex(TypeError, "keys"):
            freeze_json({1: "value"})
        with self.assertRaisesRegex(TypeError, "not representable"):
            freeze_json(object())

    def test_block_hash_changes_with_content(self):
        changed = ContentBlock(
            "lesson:intro", UnitKind.SECTION, "Loops", "Use a for loop.", 1, self.locator
        )
        self.assertNotEqual(self.block.hash, changed.hash)

    def test_model_run_rejects_invalid_identity_latency_and_cost(self):
        for arguments, message in (
            (("", "m", "p", {}, "i", "o"), "identity"),
            (("p", "m", "p", {}, "i", "o", True), "latency"),
            (("p", "m", "p", {}, "i", "o", -1), "latency"),
            (("p", "m", "p", {}, "i", "o", None, True), "cost"),
            (("p", "m", "p", {}, "i", "o", None, math.inf), "cost"),
            (("p", "m", "p", {}, "i", "o", None, -1), "cost"),
        ):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, message):
                ModelRun(*arguments)

    def test_block_hash_binds_identity_structure_provenance_and_semantics(self):
        variants = (
            ContentBlock("lesson:other", UnitKind.SECTION, "Loops", "Use a loop.", 1, self.locator),
            ContentBlock(
                "lesson:intro", UnitKind.EXERCISE, "Loops", "Use a loop.", 1, self.locator
            ),
            ContentBlock("lesson:intro", UnitKind.SECTION, "Loops", "Use a loop.", 2, self.locator),
            ContentBlock(
                "lesson:intro",
                UnitKind.SECTION,
                "Loops",
                "Use a loop.",
                1,
                SourceLocator("fixture", "other", "lesson.md", "intro"),
            ),
            ContentBlock(
                "lesson:intro",
                UnitKind.SECTION,
                "Loops",
                "Use a loop.",
                1,
                self.locator,
                concepts=("programming.loop",),
            ),
            ContentBlock(
                "lesson:intro",
                UnitKind.SECTION,
                "Loops",
                "Use a loop.",
                1,
                self.locator,
                learning_objectives=("objective.loop",),
            ),
        )
        self.assertTrue(all(item.hash != self.block.hash for item in variants))

    def test_supplied_hash_must_match_canonical_payload(self):
        with self.assertRaisesRegex(ValueError, "block hash"):
            ContentBlock(
                "lesson:intro",
                UnitKind.SECTION,
                "Loops",
                "Use a loop.",
                1,
                self.locator,
                hash="sha256:" + "0" * 64,
            )

    def test_release_rejects_duplicate_ids(self):
        with self.assertRaises(ValueError):
            CourseRelease(
                "r", "course", "en", "1", "Course", (self.block, self.block), self.locator
            )

    def test_release_hash_binds_version_language_license_and_course_identity(self):
        release = CourseRelease(
            "r",
            "course",
            "en",
            "1",
            "Course",
            (self.block,),
            self.locator,
            "CC-BY-4.0",
            "canonical",
        )
        variants = (
            CourseRelease(
                "r",
                "course",
                "sr",
                "1",
                "Course",
                (self.block,),
                self.locator,
                "CC-BY-4.0",
                "canonical",
            ),
            CourseRelease(
                "r",
                "course",
                "en",
                "2",
                "Course",
                (self.block,),
                self.locator,
                "CC-BY-4.0",
                "canonical",
            ),
            CourseRelease(
                "r", "course", "en", "1", "Course", (self.block,), self.locator, "MIT", "canonical"
            ),
            CourseRelease(
                "r",
                "course",
                "en",
                "1",
                "Course",
                (self.block,),
                self.locator,
                "CC-BY-4.0",
                "other",
            ),
        )
        self.assertTrue(all(item.hash != release.hash for item in variants))

    def test_bundle_id_binds_complete_finding_not_only_finding_id(self):
        release = CourseRelease("r", "course", "en", "1", "Course", (self.block,), self.locator)
        first = Finding("f", "coverage", "Gap", "Missing", Severity.HIGH, 0.8, ())
        second = Finding("f", "coverage", "Gap", "Changed explanation", Severity.HIGH, 0.8, ())
        self.assertNotEqual(
            EvidenceBundle.create((release,), (first,)).id,
            EvidenceBundle.create((release,), (second,)).id,
        )

    def test_bundle_is_json_safe(self):
        release = CourseRelease("r", "course", "en", "1", "Course", (self.block,), self.locator)
        finding = Finding("f", "coverage", "Gap", "Missing evidence", Severity.HIGH, 0.8, ())
        value = to_dict(EvidenceBundle.create((release,), (finding,)))
        self.assertEqual(value["findings"][0]["severity"], "high")
        self.assertEqual(value["schema_version"], "2.0")


if __name__ == "__main__":
    unittest.main()

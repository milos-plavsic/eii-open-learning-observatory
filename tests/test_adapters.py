import json
import tempfile
import unittest
from pathlib import Path

from eii.adapters import PlctExportAdapter, RepositoryAdapter

FIXTURES = Path(__file__).parent / "fixtures"


class RepositoryAdapterTests(unittest.TestCase):
    def test_loads_markdown_sections_with_provenance(self):
        release = RepositoryAdapter().load(FIXTURES / "course_en")
        self.assertEqual(release.language, "en")
        self.assertEqual(len(release.blocks), 2)
        self.assertEqual(release.blocks[1].locator.anchor, "range")
        self.assertEqual(release.content_license, "CC-BY-4.0")

    def test_preserves_nested_heading_hierarchy_and_declared_unit_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lesson.md").write_text("# Course\nIntro\n## Lesson\nText\n### Quiz\nQuestion")
            (root / "course.json").write_text(
                json.dumps(
                    {
                        "course_key": "nested",
                        "language": "en",
                        "version": "1",
                        "unit_kinds": {"lesson.md#quiz": "assessment"},
                        "translation_ids": {"lesson.md#lesson": "lesson-1"},
                    }
                )
            )
            release = RepositoryAdapter().load(root)
        self.assertEqual(release.blocks[1].parent_id, release.blocks[0].id)
        self.assertEqual(release.blocks[2].parent_id, release.blocks[1].id)
        self.assertEqual(release.blocks[2].kind.value, "assessment")
        self.assertEqual(release.blocks[1].metadata["translation_id"], "lesson-1")


class PlctAdapterTests(unittest.TestCase):
    def test_loads_export_without_plct_runtime_dependency(self):
        adapter = PlctExportAdapter()
        source = FIXTURES / "plct.json"
        self.assertTrue(adapter.can_load(source))
        release = adapter.load(source)
        self.assertIn("programming.loop", release.blocks[0].concepts)
        self.assertEqual(release.blocks[0].locator.path, "a1")

    def test_rejects_wrong_format_and_duplicate_activity_keys(self):
        source = json.loads((FIXTURES / "plct.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            source["format"] = "unknown"
            path.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, "format"):
                PlctExportAdapter().load(path)
            source["format"] = "plct-course-export-v1"
            source["activities"].append(dict(source["activities"][0]))
            path.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, "unique"):
                PlctExportAdapter().load(path)

    def test_preserves_explicit_translation_identity(self):
        source = json.loads((FIXTURES / "plct.json").read_text())
        source["activities"][0]["translation_id"] = "loop-introduction"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps(source))
            release = PlctExportAdapter().load(path)
        self.assertEqual(release.blocks[0].metadata["translation_id"], "loop-introduction")

    def test_loads_lesson_level_plct_chunks_with_stable_parentage(self):
        source = json.loads((FIXTURES / "plct.json").read_text())
        source["activities"][0]["chunks"] = [
            {
                "chunk_key": "range-example",
                "kind": "exercise",
                "title": "Range",
                "text": "Use range(3).",
                "concepts": ["programming.range"],
                "learning_objectives": ["use-range"],
                "translation_id": "range-example",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps(source))
            release = PlctExportAdapter().load(path)
        chunk = release.blocks[1]
        self.assertEqual(chunk.id, "plct:loops:a1:range-example")
        self.assertEqual(chunk.parent_id, release.blocks[0].id)
        self.assertEqual(chunk.kind.value, "exercise")
        self.assertEqual(chunk.locator.anchor, "range-example")


if __name__ == "__main__":
    unittest.main()

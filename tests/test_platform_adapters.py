import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from eii.adapters import (
    H5PAdapter,
    KolibriChannelAdapter,
    LearningGraphAdapter,
    MediaWikiRevisionAdapter,
    MoodleBackupAdapter,
    OpenEdxOlxAdapter,
    adapter_for,
)
from eii.adapters.common import safe_zip_members


class PlatformAdapterTests(unittest.TestCase):
    def test_h5p_maps_nested_text_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "lesson.h5p"
            with ZipFile(source, "w") as archive:
                archive.writestr(
                    "h5p.json",
                    json.dumps(
                        {
                            "title": "Loops",
                            "language": "en",
                            "mainLibrary": "H5P.MultiChoice",
                            "license": "CC BY 4.0",
                            "preloadedDependencies": [],
                        }
                    ),
                )
                archive.writestr(
                    "content/content.json",
                    json.dumps(
                        {
                            "question": "What repeats?",
                            "answers": [{"text": "A loop"}, {"text": "A variable"}],
                        }
                    ),
                )
            release = H5PAdapter().load(source)
            self.assertEqual(release.language, "en")
            self.assertEqual(release.content_license, "CC BY 4.0")
            self.assertEqual(
                [block.text for block in release.blocks], ["A loop", "A variable", "What repeats?"]
            )
            self.assertIs(adapter_for(source).__class__, H5PAdapter)

    def test_h5p_rejects_missing_content_and_unsafe_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.h5p"
            with ZipFile(source, "w") as archive:
                archive.writestr("h5p.json", "{}")
            with self.assertRaisesRegex(ValueError, "requires"):
                H5PAdapter().load(source)
            unsafe = Path(directory) / "unsafe.zip"
            with ZipFile(unsafe, "w") as archive:
                archive.writestr("../escape", "x")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                safe_zip_members(unsafe)

    def test_open_edx_directory_and_archive(self):
        xml = b'<course org="eii" course="loops" display_name="Loops" language="en"><chapter url_name="one" display_name="Start"><vertical url_name="unit"><problem url_name="quiz">Question?</problem></vertical></chapter></course>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "olx"
            root.mkdir()
            (root / "course.xml").write_bytes(xml)
            release = OpenEdxOlxAdapter().load(root)
            self.assertEqual(release.course_key, "eii:loops")
            self.assertTrue(any(block.kind.value == "assessment" for block in release.blocks))
            archive = Path(directory) / "course.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("export/course.xml")
                info.size = len(xml)
                output.addfile(info, io.BytesIO(xml))
            self.assertEqual(OpenEdxOlxAdapter().load(archive).title, "Loops")

    def test_kolibri_preserves_tree_and_assessments(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "channel.json"
            source.write_text(
                json.dumps(
                    {
                        "format": "kolibri-channel-v1",
                        "channel_id": "ch",
                        "language": "sr",
                        "title": "Programiranje",
                        "nodes": [
                            {"id": "t", "kind": "topic", "title": "Petlje"},
                            {
                                "id": "q",
                                "parent_id": "t",
                                "kind": "exercise",
                                "title": "Provera",
                                "text": "Pitanje",
                            },
                        ],
                    }
                )
            )
            release = KolibriChannelAdapter().load(source)
            self.assertEqual(release.blocks[1].parent_id, "kolibri:t")
            self.assertEqual(release.blocks[1].kind.value, "assessment")

    def test_mediawiki_uses_immutable_revision_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "wiki.json"
            source.write_text(
                json.dumps(
                    {
                        "format": "mediawiki-revisions-v1",
                        "language": "es",
                        "wiki": "Wikilibros",
                        "pages": [
                            {
                                "pageid": 10,
                                "revid": 22,
                                "title": "Bucles",
                                "content": "Inicio\n== For ==\nTexto",
                            }
                        ],
                    }
                )
            )
            release = MediaWikiRevisionAdapter().load(source)
            self.assertEqual(release.version, "22")
            self.assertEqual([block.title for block in release.blocks], ["Bucles", "For"])

    def test_moodle_backup_maps_quiz_as_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "course.mbz"
            manifest = "<moodle_backup><information><backup_id>b1</backup_id><original_course_id>7</original_course_id><original_course_fullname>Loops</original_course_fullname><original_course_language>en</original_course_language><backup_date>10</backup_date></information></moodle_backup>"
            quiz = '<activity id="9"><quiz><name>Loop quiz</name><intro>Choose an answer</intro><questiontext>What repeats?</questiontext></quiz></activity>'
            with ZipFile(source, "w") as archive:
                archive.writestr("moodle_backup.xml", manifest)
                archive.writestr("activities/quiz_9/quiz.xml", quiz)
            release = MoodleBackupAdapter().load(source)
            self.assertEqual(release.title, "Loops")
            self.assertEqual(release.blocks[0].kind.value, "assessment")
            self.assertIn("What repeats?", release.blocks[0].text)

    def test_learning_graph_validates_edges_and_preserves_transitions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "graph.json"
            source.write_text(
                json.dumps(
                    {
                        "format": "eii-learning-graph-v1",
                        "course_key": "oppia",
                        "language": "pt",
                        "initial_state": "intro",
                        "states": [
                            {"id": "intro", "content": "Olá"},
                            {
                                "id": "question",
                                "content": "Escolha",
                                "interactions": [{"type": "choice"}],
                            },
                        ],
                        "edges": [{"from": "intro", "to": "question", "answer": "continue"}],
                    }
                )
            )
            release = LearningGraphAdapter().load(source)
            self.assertTrue(release.blocks[0].metadata["start"])
            self.assertEqual(release.blocks[1].kind.value, "assessment")
            data = json.loads(source.read_text())
            data["edges"][0]["to"] = "missing"
            source.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unknown state"):
                LearningGraphAdapter().load(source)

    def test_capabilities_are_explicit(self):
        self.assertTrue(H5PAdapter().capabilities().assessments)
        self.assertTrue(OpenEdxOlxAdapter().capabilities().parallel_languages)
        self.assertFalse(MediaWikiRevisionAdapter().capabilities().retrieval_context)
        self.assertEqual(
            LearningGraphAdapter().capabilities().metadata["topology"], "directed-graph"
        )


if __name__ == "__main__":
    unittest.main()

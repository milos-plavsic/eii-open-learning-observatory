import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from eii.adapters import (
    H5PAdapter,
    KolibriChannelAdapter,
    LearningGraphAdapter,
    MediaWikiRevisionAdapter,
    MoodleBackupAdapter,
    OpenEdxOlxAdapter,
    PlctExportAdapter,
    RepositoryAdapter,
    common,
)
from eii.adapters.h5p import _strings


class _Zip:
    def __init__(self, infos):
        self.infos = infos

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def infolist(self):
        return self.infos

    def read(self, _):
        return b"x"


class DefensiveAdapterTests(unittest.TestCase):
    def test_common_archive_limits_encoding_and_language(self):
        info = ZipInfo("x")
        info.file_size = 2
        with (
            patch.object(common, "ZipFile", return_value=_Zip([info, info])),
            patch.object(common, "MAX_ARCHIVE_FILES", 1),
        ):
            with self.assertRaisesRegex(ValueError, "too many"):
                common.safe_zip_members(Path("x"))
        with (
            patch.object(common, "ZipFile", return_value=_Zip([info])),
            patch.object(common, "MAX_MEMBER_BYTES", 1),
            self.assertRaisesRegex(ValueError, "member"),
        ):
            common.safe_zip_members(Path("x"))
        with (
            patch.object(common, "ZipFile", return_value=_Zip([info, info])),
            patch.object(common, "MAX_ARCHIVE_BYTES", 3),
        ):
            with self.assertRaisesRegex(ValueError, "uncompressed"):
                common.safe_zip_members(Path("x"))
        directory = ZipInfo("folder/")
        with patch.object(common, "ZipFile", return_value=_Zip([directory])):
            self.assertEqual(common.safe_zip_members(Path("x")), ())
        with tempfile.TemporaryDirectory() as directory_name:
            invalid = Path(directory_name) / "bad.zip"
            invalid.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "valid ZIP"):
                common.safe_zip_members(invalid)
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            common.decoded_text(b"\xff", label="x")
        with self.assertRaisesRegex(ValueError, "language"):
            common.normalized_language(None, None)

    def test_format_detection_handles_missing_and_malformed_sources(self):
        adapters = [LearningGraphAdapter(), KolibriChannelAdapter(), MediaWikiRevisionAdapter()]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "bad.json"
            malformed.write_text("{")
            for adapter in adapters:
                self.assertFalse(adapter.can_load(root / "missing.json"))
                self.assertFalse(adapter.can_load(malformed))
            self.assertFalse(H5PAdapter().can_load(root))
            self.assertFalse(MoodleBackupAdapter().can_load(root))
            self.assertFalse(OpenEdxOlxAdapter().can_load(root))
            self.assertTrue(KolibriChannelAdapter().capabilities().assessments)
            self.assertTrue(MoodleBackupAdapter().capabilities().assessments)
            self.assertTrue(PlctExportAdapter().capabilities().retrieval_context)
            self.assertTrue(RepositoryAdapter().capabilities().patch_proposals)
            self.assertEqual(_strings(1), [])

    def test_tar_adapter_limits_and_unsafe_paths(self):
        class Member:
            def __init__(self, name="x", size=1, file=True):
                self.name = name
                self.size = size
                self.file = file

            def isfile(self):
                return self.file

        class Archive:
            def __init__(self, members):
                self.members = members

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def getmembers(self):
                return self.members

            def extractfile(self, _):
                return io.BytesIO(b"x")

        with (
            patch("eii.adapters.moodle.is_zipfile", return_value=False),
            patch(
                "eii.adapters.moodle.tarfile.open",
                return_value=Archive([Member(size=1_000_000_001)]),
            ),
            self.assertRaisesRegex(ValueError, "safety limits"),
        ):
            MoodleBackupAdapter()._files(Path("x"))
        with (
            patch("eii.adapters.moodle.is_zipfile", return_value=False),
            patch(
                "eii.adapters.moodle.tarfile.open",
                return_value=Archive([Member(file=False), Member("../x")]),
            ),
            self.assertRaisesRegex(ValueError, "unsafe"),
        ):
            MoodleBackupAdapter()._files(Path("x"))
        with (
            patch(
                "eii.adapters.olx.tarfile.open", return_value=Archive([Member(size=1_000_000_001)])
            ),
            self.assertRaisesRegex(ValueError, "safety limits"),
        ):
            OpenEdxOlxAdapter()._files(Path("x"))
        with (
            patch(
                "eii.adapters.olx.tarfile.open",
                return_value=Archive([Member(file=False), Member("/x")]),
            ),
            self.assertRaisesRegex(ValueError, "unsafe"),
        ):
            OpenEdxOlxAdapter()._files(Path("x"))
        no_stream = Archive([Member("x")])
        no_stream.extractfile = lambda _: None
        with (
            patch("eii.adapters.moodle.is_zipfile", return_value=False),
            patch("eii.adapters.moodle.tarfile.open", return_value=no_stream),
        ):
            self.assertEqual(MoodleBackupAdapter()._files(Path("x")), {})
        with patch("eii.adapters.olx.tarfile.open", return_value=no_stream):
            self.assertEqual(OpenEdxOlxAdapter()._files(Path("x")), {})

    def test_h5p_rejects_wrong_shapes_library_empty_text_and_encoding(self):
        cases = [
            ([], {}, "objects or arrays"),
            ({"mainLibrary": "X", "language": "en"}, {}, "no auditable"),
            ({"language": "en"}, {"x": "text"}, "mainLibrary"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (package, content, message) in enumerate(cases):
                source = Path(directory) / f"{index}.h5p"
                with ZipFile(source, "w") as archive:
                    archive.writestr("h5p.json", json.dumps(package))
                    archive.writestr("content/content.json", json.dumps(content))
                with self.assertRaisesRegex(ValueError, message):
                    H5PAdapter().load(source)
            bad = Path(directory) / "encoding.h5p"
            with ZipFile(bad, "w") as archive:
                archive.writestr("h5p.json", b"\xff")
                archive.writestr("content/content.json", "{}")
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                H5PAdapter().load(bad)

    def test_json_adapters_reject_structural_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "graph.json"
            for data, message in [
                ({"states": []}, "requires states"),
                ({"states": [{"id": "x"}], "edges": {}}, "edges"),
                ({"states": [{"id": "x"}, {"id": "x"}]}, "unique"),
                ({"states": ["x"]}, "unique"),
                ({"states": [{"id": "x"}], "edges": ["bad"]}, "unknown state"),
            ]:
                graph.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, message):
                    LearningGraphAdapter().load(graph, language="en")
            kolibri = root / "kolibri.json"
            for data, message in [
                ({"nodes": []}, "requires nodes"),
                ({"nodes": ["x"], "language": "en"}, "stable id"),
                ({"nodes": [{"id": "x"}, {"id": "x"}], "language": "en"}, "unique"),
            ]:
                kolibri.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, message):
                    KolibriChannelAdapter().load(kolibri)
            wiki = root / "wiki.json"
            wiki.write_text(json.dumps({"pages": []}))
            with self.assertRaisesRegex(ValueError, "requires pages"):
                MediaWikiRevisionAdapter().load(wiki, language="en")
            wiki.write_text(json.dumps({"pages": [{"title": "x"}]}))
            with self.assertRaisesRegex(ValueError, "pageid"):
                MediaWikiRevisionAdapter().load(wiki, language="en")

    def test_moodle_tar_paths_parse_errors_and_empty_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.mbz"
            invalid.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "invalid Moodle"):
                MoodleBackupAdapter().load(invalid)
            missing = root / "missing.mbz"
            with tarfile.open(missing, "w:gz") as archive:
                pass
            with self.assertRaisesRegex(ValueError, "requires moodle"):
                MoodleBackupAdapter().load(missing)
            bad_manifest = root / "manifest.mbz"
            with tarfile.open(bad_manifest, "w:gz") as archive:
                payload = b"<"
                info = tarfile.TarInfo("moodle_backup.xml")
                info.size = 1
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(ValueError, "manifest"):
                MoodleBackupAdapter().load(bad_manifest)
            empty = root / "empty.mbz"
            with ZipFile(empty, "w") as archive:
                archive.writestr(
                    "moodle_backup.xml",
                    "<information><original_course_language>en</original_course_language></information>",
                )
            with self.assertRaisesRegex(ValueError, "no auditable"):
                MoodleBackupAdapter().load(empty)
            broken = root / "broken.mbz"
            with ZipFile(broken, "w") as archive:
                archive.writestr(
                    "moodle_backup.xml",
                    "<information><original_course_language>en</original_course_language></information>",
                )
                archive.writestr("activities/page_1/page.xml", "<")
            with self.assertRaisesRegex(ValueError, "invalid Moodle XML"):
                MoodleBackupAdapter().load(broken)
            skipped = root / "skip.mbz"
            with ZipFile(skipped, "w") as archive:
                archive.writestr(
                    "moodle_backup.xml",
                    "<information><original_course_language>en</original_course_language></information>",
                )
                archive.writestr("activities/page_1/module.xml", '<module id="1"/>')
            with self.assertRaisesRegex(ValueError, "no auditable"):
                MoodleBackupAdapter().load(skipped)

    def test_olx_invalid_archives_paths_xml_root_external_encoding_and_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "bad.tgz"
            invalid.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "invalid OLX"):
                OpenEdxOlxAdapter().load(invalid)
            missing = root / "missing"
            missing.mkdir()
            with self.assertRaisesRegex(ValueError, "course.xml"):
                OpenEdxOlxAdapter().load(missing)
            (missing / "course.xml").write_text("<")
            with self.assertRaisesRegex(ValueError, "invalid OLX course"):
                OpenEdxOlxAdapter().load(missing)
            (missing / "course.xml").write_text('<chapter language="en"/>')
            with self.assertRaisesRegex(ValueError, "root element"):
                OpenEdxOlxAdapter().load(missing)
            (missing / "course.xml").write_text('<course language="en"><custom/></course>')
            self.assertEqual(len(OpenEdxOlxAdapter().load(missing).blocks), 1)
            (missing / "course.xml").write_text(
                '<course language="en"><html url_name="x"/></course>'
            )
            (missing / "html").mkdir()
            (missing / "html" / "x.html").write_bytes(b"\xff")
            with self.assertRaisesRegex(ValueError, "not UTF-8"):
                OpenEdxOlxAdapter().load(missing)


if __name__ == "__main__":
    unittest.main()

import io
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from eii import __version__
from eii.release_preflight import (
    artifact_version,
    require_clean_source_tree,
    validate_release_candidate,
)


class ReleasePreflightTests(unittest.TestCase):
    def test_source_tree_must_be_clean_and_match_revision(self):
        clean = subprocess.CompletedProcess([], 0, stdout="abc\n", stderr="")
        status = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("subprocess.run", side_effect=(clean, status)):
            self.assertEqual(require_clean_source_tree(Path("."), revision="abc"), "abc")
        dirty = subprocess.CompletedProcess([], 0, stdout=" M source.py\n", stderr="")
        with (
            patch("subprocess.run", side_effect=(clean, dirty)),
            self.assertRaisesRegex(ValueError, "dirty"),
        ):
            require_clean_source_tree(Path("."))
        with (
            patch("subprocess.run", side_effect=(clean, status)),
            self.assertRaisesRegex(ValueError, "does not match"),
        ):
            require_clean_source_tree(Path("."), revision="def")
        with (
            patch("subprocess.run", side_effect=OSError("git missing")),
            self.assertRaisesRegex(ValueError, "Git worktree"),
        ):
            require_clean_source_tree(Path("."))

    def artifacts(self, root: Path, version: str = __version__) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        metadata = f"Metadata-Version: 2.4\nName: eii-observatory\nVersion: {version}\n\n".encode()
        wheel = root / f"eii_observatory-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(f"eii_observatory-{version}.dist-info/METADATA", metadata)
        sdist = root / f"eii_observatory-{version}.tar.gz"
        with tarfile.open(sdist, "w:gz") as archive:
            member = tarfile.TarInfo(f"eii_observatory-{version}/PKG-INFO")
            member.size = len(metadata)
            archive.addfile(member, io.BytesIO(metadata))
        return wheel, sdist

    def test_accepts_bound_wheel_sdist_and_optional_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel, sdist = self.artifacts(Path(directory))
            self.assertEqual(artifact_version(wheel), __version__)
            self.assertEqual(artifact_version(sdist), __version__)
            validate_release_candidate(
                (wheel, sdist), expected_version=__version__, tag=f"v{__version__}"
            )
            validate_release_candidate((wheel, sdist), expected_version=__version__)

    def test_rejects_version_tag_count_kind_and_artifact_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel, sdist = self.artifacts(root)
            with self.assertRaisesRegex(ValueError, "expected version"):
                validate_release_candidate((wheel, sdist), expected_version="9.9.9")
            with self.assertRaisesRegex(ValueError, "tag"):
                validate_release_candidate(
                    (wheel, sdist), expected_version=__version__, tag="v9.9.9"
                )
            with self.assertRaisesRegex(ValueError, "exactly one wheel"):
                validate_release_candidate((wheel,), expected_version=__version__)
            with self.assertRaisesRegex(ValueError, "exactly one wheel"):
                validate_release_candidate((wheel, wheel), expected_version=__version__)
            wrong = root / "wrong.whl"
            with zipfile.ZipFile(wrong, "w") as archive:
                archive.writestr("wrong.dist-info/METADATA", "Version: 9.9.9\n")
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_release_candidate((wrong, sdist), expected_version=__version__)
            wrong_name = root / f"eii_observatory-{__version__}-bad.whl"
            with zipfile.ZipFile(wrong_name, "w") as archive:
                archive.writestr(
                    "wrong.dist-info/METADATA",
                    f"Name: another-project\nVersion: {__version__}\n",
                )
            with self.assertRaisesRegex(ValueError, "project name"):
                validate_release_candidate((wrong_name, sdist), expected_version=__version__)
            renamed_wheel = root / "renamed.whl"
            wheel.rename(renamed_wheel)
            with self.assertRaisesRegex(ValueError, "wheel filename"):
                validate_release_candidate((renamed_wheel, sdist), expected_version=__version__)
            wheel, renamed_sdist = self.artifacts(root / "renamed")
            bad_sdist_name = renamed_sdist.with_name("renamed.tar.gz")
            renamed_sdist.rename(bad_sdist_name)
            with self.assertRaisesRegex(ValueError, "sdist filename"):
                validate_release_candidate((wheel, bad_sdist_name), expected_version=__version__)

    def test_rejects_invalid_or_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "artifact.txt"
            text.write_text("not a package")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                artifact_version(text)
            wheel = root / "bad.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("one.dist-info/METADATA", "Version: 1\n")
                archive.writestr("two.dist-info/METADATA", "Version: 1\n")
            with self.assertRaisesRegex(ValueError, "exactly one METADATA"):
                artifact_version(wheel)
            wheel = root / "missing-version.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("one.dist-info/METADATA", "Name: p\n")
            with self.assertRaisesRegex(ValueError, "no Version"):
                artifact_version(wheel)
            with self.assertRaisesRegex(ValueError, "no Version"):
                validate_release_candidate(
                    (wheel, self.artifacts(root / "valid")[1]), expected_version=__version__
                )
            sdist = root / "bad.tar.gz"
            with tarfile.open(sdist, "w:gz") as archive:
                for name in ("one/PKG-INFO", "two/PKG-INFO"):
                    metadata = b"Version: 1\n"
                    member = tarfile.TarInfo(name)
                    member.size = len(metadata)
                    archive.addfile(member, io.BytesIO(metadata))
            with self.assertRaisesRegex(ValueError, "exactly one PKG-INFO"):
                artifact_version(sdist)
            with (
                patch("tarfile.TarFile.extractfile", return_value=None),
                self.assertRaisesRegex(ValueError, "unreadable"),
            ):
                artifact_version(self.artifacts(root / "nested")[1])


if __name__ == "__main__":
    unittest.main()

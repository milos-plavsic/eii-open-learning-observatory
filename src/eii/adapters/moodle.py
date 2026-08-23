"""Read-only Moodle backup adapter; never connects to a live LMS database."""

from __future__ import annotations

import tarfile
from pathlib import Path
from zipfile import is_zipfile

from defusedxml import ElementTree

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind, content_hash

from .base import SourceCapabilities
from .common import normalized_language, safe_zip_members


class MoodleBackupAdapter:
    name = "moodle-backup"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities("moodle2-backup", assessments=True, parallel_languages=True)

    def can_load(self, source: Path) -> bool:
        return source.is_file() and source.suffix.casefold() == ".mbz"

    def _files(self, source: Path) -> dict[str, bytes]:
        if is_zipfile(source):
            return {info.filename: data for info, data in safe_zip_members(source)}
        files: dict[str, bytes] = {}
        try:
            with tarfile.open(source, "r:*") as archive:
                members = archive.getmembers()
                if len(members) > 20_000 or sum(item.size for item in members) > 1_000_000_000:
                    raise ValueError("Moodle backup exceeds safety limits")
                for member in members:
                    if not member.isfile():
                        continue
                    if member.name.startswith("/") or ".." in Path(member.name).parts:
                        raise ValueError("Moodle backup contains an unsafe path")
                    stream = archive.extractfile(member)
                    if stream:
                        files[member.name] = stream.read()
        except tarfile.TarError as error:
            raise ValueError("invalid Moodle backup") from error
        return files

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        files = self._files(source)
        if "moodle_backup.xml" not in files:
            raise ValueError("Moodle backup requires moodle_backup.xml")
        try:
            manifest = ElementTree.fromstring(files["moodle_backup.xml"])
        except ElementTree.ParseError as error:
            raise ValueError("invalid Moodle backup manifest") from error
        information = manifest.find(".//information")
        if information is None:
            information = manifest
        key = (
            information.findtext("original_course_id")
            or information.findtext("backup_id")
            or source.stem
        )
        title = (
            information.findtext("original_course_fullname")
            or information.findtext("original_course_shortname")
            or key
        )
        version = information.findtext("backup_date") or content_hash(sorted(files))[7:23]
        lang = normalized_language(language, information.findtext("original_course_language"))
        blocks: list[ContentBlock] = []
        order = 0
        candidates = sorted(
            name
            for name in files
            if name.endswith(".xml") and (name.startswith(("sections/", "activities/")))
        )
        for name in candidates:
            try:
                root = ElementTree.fromstring(files[name])
            except ElementTree.ParseError as error:
                raise ValueError(f"invalid Moodle XML: {name}") from error
            module = (
                name.split("/")[1] if name.startswith("activities/") and "/" in name else "section"
            )
            stable = root.attrib.get("id") or root.findtext(".//id") or name
            display = (
                root.findtext(".//name")
                or root.findtext(".//title")
                or root.findtext(".//number")
                or module
            )
            text_parts: list[str] = []
            for tag in (
                "name",
                "title",
                "intro",
                "content",
                "questiontext",
                "generalfeedback",
                "summary",
            ):
                text_parts.extend(
                    item.text.strip() for item in root.iter(tag) if item.text and item.text.strip()
                )
            text = "\n".join(dict.fromkeys(text_parts))
            if not text and name.endswith("module.xml"):
                continue
            activity_type = module.split("_", 1)[0]
            kind = (
                UnitKind.ASSESSMENT
                if activity_type in {"quiz", "assign", "lesson", "workshop", "choice"}
                else (UnitKind.SECTION if name.startswith("sections/") else UnitKind.ACTIVITY)
            )
            blocks.append(
                ContentBlock(
                    f"moodle:{key}:{stable}:{order}",
                    kind,
                    display,
                    text,
                    order,
                    SourceLocator(self.name, source.name, name, str(stable)),
                    metadata={"moodle_component": activity_type},
                )
            )
            order += 1
        if not blocks:
            raise ValueError("Moodle backup contains no auditable course content")
        return CourseRelease(
            f"moodle:{key}:{lang}:{version}",
            str(key),
            lang,
            str(version),
            str(title),
            tuple(blocks),
            SourceLocator(self.name, source.name, "moodle_backup.xml"),
            canonical_course_id=str(key),
            metadata={"moodle_backup_format": information.findtext("moodle_version")},
        )

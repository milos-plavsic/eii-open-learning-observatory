"""Open edX OLX directory/archive adapter."""

from __future__ import annotations

import tarfile
from hashlib import sha256
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind

from .base import SourceCapabilities
from .common import normalized_language

_KINDS = {
    "course": UnitKind.COURSE,
    "chapter": UnitKind.SECTION,
    "sequential": UnitKind.SECTION,
    "vertical": UnitKind.ACTIVITY,
    "problem": UnitKind.ASSESSMENT,
}


class OpenEdxOlxAdapter:
    name = "openedx-olx"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities("openedx-olx", assessments=True, parallel_languages=True)

    def can_load(self, source: Path) -> bool:
        return (source.is_dir() and (source / "course.xml").exists()) or (
            source.is_file() and source.name.casefold().endswith((".tar.gz", ".tgz"))
        )

    def _files(self, source: Path) -> dict[str, bytes]:
        if source.is_dir():
            return {
                item.relative_to(source).as_posix(): item.read_bytes()
                for item in source.rglob("*")
                if item.is_file()
            }
        files: dict[str, bytes] = {}
        try:
            with tarfile.open(source, "r:gz") as archive:
                members = archive.getmembers()
                if len(members) > 20_000 or sum(item.size for item in members) > 1_000_000_000:
                    raise ValueError("OLX archive exceeds safety limits")
                for item in members:
                    if item.isfile():
                        if item.name.startswith("/") or ".." in Path(item.name).parts:
                            raise ValueError("OLX archive contains an unsafe path")
                        stream = archive.extractfile(item)
                        if stream:
                            files[item.name] = stream.read()
        except tarfile.TarError as error:
            raise ValueError("invalid OLX archive") from error
        return files

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        files = self._files(source)
        course_name = next((name for name in files if name.endswith("course.xml")), None)
        if course_name is None:
            raise ValueError("OLX source does not contain course.xml")
        try:
            root = ElementTree.fromstring(files[course_name])
        except ElementTree.ParseError as error:
            raise ValueError("invalid OLX course XML") from error
        if root.tag != "course":
            raise ValueError("OLX root element must be course")
        lang = normalized_language(language, root.attrib.get("language"))
        blocks: list[ContentBlock] = []
        order = 0

        def visit(node: Element, parent: str | None, path: str) -> None:
            nonlocal order
            tag = node.tag.rsplit("}", 1)[-1]
            url_name = node.attrib.get("url_name") or f"{tag}-{order}"
            block_id = f"olx:{path}/{url_name}"
            text = " ".join(part.strip() for part in node.itertext() if part.strip())
            component_names = {f"{tag}/{url_name}.html", f"{tag}/{url_name}.xml"}
            external = next(
                (
                    name
                    for name in files
                    if name in component_names
                    or any(name.endswith(f"/{candidate}") for candidate in component_names)
                ),
                None,
            )
            if external and external != course_name:
                try:
                    text = files[external].decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(f"OLX component {external} is not UTF-8") from error
            current = block_id if tag in _KINDS or text else parent
            if tag in _KINDS or text:
                blocks.append(
                    ContentBlock(
                        id=block_id,
                        kind=_KINDS.get(tag, UnitKind.ACTIVITY),
                        title=node.attrib.get("display_name", url_name),
                        text=text,
                        order=order,
                        locator=SourceLocator(
                            self.name, source.name, external or course_name, url_name
                        ),
                        parent_id=parent,
                        metadata={"xblock_type": tag, "attributes": dict(node.attrib)},
                    )
                )
                order += 1
            for child in node:
                visit(child, current, f"{path}/{url_name}")

        visit(root, None, "course")
        digest = sha256(b"".join(files[key] for key in sorted(files))).hexdigest()[:16]
        key = f"{root.attrib.get('org', 'org')}:{root.attrib.get('course', root.attrib.get('url_name', source.stem))}"
        return CourseRelease(
            id=f"olx:{key}:{lang}:{digest}",
            course_key=key,
            language=lang,
            version=digest,
            title=root.attrib.get("display_name", key),
            blocks=tuple(blocks),
            source=SourceLocator(self.name, source.name, course_name),
            canonical_course_id=key,
            metadata={"olx_attributes": dict(root.attrib)},
        )

"""Portable H5P package adapter using the published package contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind, content_hash

from .base import SourceCapabilities
from .common import decoded_text, normalized_language, safe_zip_members


def _strings(value: Any, path: str = "content") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str) and value.strip():
        found.append((path, value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_strings(item, f"{path}/{index}"))
    elif isinstance(value, dict):
        for key in sorted(value):
            found.extend(_strings(value[key], f"{path}/{key}"))
    return found


class H5PAdapter:
    name = "h5p"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities("h5p", assessments=True, parallel_languages=True)

    def can_load(self, source: Path) -> bool:
        return source.is_file() and source.suffix.casefold() == ".h5p"

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        members = {info.filename: data for info, data in safe_zip_members(source)}
        if "h5p.json" not in members or "content/content.json" not in members:
            raise ValueError("H5P package requires h5p.json and content/content.json")
        package = json.loads(decoded_text(members["h5p.json"], label="h5p.json"))
        content = json.loads(decoded_text(members["content/content.json"], label="content.json"))
        if not isinstance(package, dict) or not isinstance(content, (dict, list)):
            raise ValueError("H5P metadata and content must be JSON objects or arrays")
        main_library = str(package.get("mainLibrary", "")).strip()
        if not main_library:
            raise ValueError("H5P package does not declare mainLibrary")
        lang = normalized_language(language, package.get("language"))
        strings = _strings(content)
        if not strings:
            raise ValueError("H5P content has no auditable textual values")
        blocks = tuple(
            ContentBlock(
                id=f"h5p:{content_hash(path)[7:23]}",
                kind=UnitKind.EXERCISE,
                title=path.rsplit("/", 1)[-1],
                text=text,
                order=index,
                locator=SourceLocator(self.name, source.name, "content/content.json", path),
                metadata={"json_pointer": path, "main_library": main_library},
            )
            for index, (path, text) in enumerate(strings)
        )
        version = content_hash({"package": package, "content": content})[7:23]
        title = str(package.get("title") or source.stem)
        return CourseRelease(
            id=f"h5p:{source.stem}:{lang}:{version}",
            course_key=source.stem,
            language=lang,
            version=version,
            title=title,
            blocks=blocks,
            source=SourceLocator(self.name, source.name, "h5p.json"),
            content_license=package.get("license"),
            canonical_course_id=source.stem,
            metadata={
                "main_library": main_library,
                "dependencies": package.get("preloadedDependencies", []),
            },
        )

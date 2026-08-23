"""Adapter for portable course repositories containing Markdown documents."""

from __future__ import annotations

import json
import re
from pathlib import Path

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind, content_hash

from .base import SourceCapabilities

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _slug(value: str) -> str:
    value = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-")
    return value or "section"


class RepositoryAdapter:
    """Load Markdown, retaining exact file/heading provenance.

    An optional ``course.json`` can declare course_key, language, version,
    title, license and canonical_course_id. Command-line language overrides it.
    """

    name = "repository"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            "markdown-repository", parallel_languages=True, patch_proposals=True
        )

    def can_load(self, source: Path) -> bool:
        return source.is_dir() and any(source.rglob("*.md"))

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        source = source.resolve()
        manifest_path = source / "course.json"
        manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
        lang = language or manifest.get("language")
        if not lang:
            raise ValueError(f"language is required for repository {source}")

        repository = manifest.get("repository", source.name)
        blocks: list[ContentBlock] = []
        order = 0
        for document in sorted(source.rglob("*.md")):
            if any(part.startswith(".") for part in document.relative_to(source).parts):
                continue
            relative = document.relative_to(source).as_posix()
            sections = self._sections(document.read_text("utf-8"), document.stem)
            parents: dict[int, str] = {}
            for level, heading, body, occurrence in sections:
                order += 1
                anchor = f"{_slug(heading)}-{occurrence}" if occurrence > 1 else _slug(heading)
                block_id = f"repo:{relative}#{anchor}"
                declared_concepts = manifest.get("concepts", {}).get(f"{relative}#{anchor}", ())
                declared_objectives = manifest.get("learning_objectives", {}).get(
                    f"{relative}#{anchor}", ()
                )
                declared_kind = manifest.get("unit_kinds", {}).get(f"{relative}#{anchor}")
                kind = (
                    UnitKind(declared_kind)
                    if declared_kind
                    else (UnitKind.ACTIVITY if level == 1 else UnitKind.SECTION)
                )
                parent_id = next(
                    (
                        parents[candidate]
                        for candidate in range(level - 1, 0, -1)
                        if candidate in parents
                    ),
                    None,
                )
                translation_id = manifest.get("translation_ids", {}).get(f"{relative}#{anchor}")
                blocks.append(
                    ContentBlock(
                        id=block_id,
                        kind=kind,
                        title=heading,
                        text=body.strip(),
                        order=order,
                        locator=SourceLocator(self.name, repository, relative, anchor),
                        parent_id=parent_id,
                        concepts=tuple(declared_concepts),
                        learning_objectives=tuple(declared_objectives),
                        metadata={
                            "heading_level": level,
                            **(
                                {"translation_id": str(translation_id)}
                                if translation_id is not None
                                else {}
                            ),
                        },
                    )
                )
                parents[level] = block_id
                for deeper in [candidate for candidate in parents if candidate > level]:
                    del parents[deeper]
        if not blocks:
            raise ValueError(f"no Markdown course content found in {source}")

        course_key = manifest.get("course_key", source.name)
        version = str(manifest.get("version", "working-tree"))
        release_id = manifest.get("id", f"repo:{course_key}:{lang}:{version}")
        return CourseRelease(
            id=release_id,
            course_key=course_key,
            language=lang,
            version=version,
            title=manifest.get("title", course_key),
            blocks=tuple(blocks),
            source=SourceLocator(self.name, repository, "."),
            content_license=manifest.get("license"),
            canonical_course_id=manifest.get("canonical_course_id", course_key),
            metadata={"manifest_hash": content_hash(manifest)},
        )

    @staticmethod
    def _sections(text: str, fallback_title: str) -> list[tuple[int, str, str, int]]:
        sections: list[tuple[int, str, list[str]]] = []
        current: tuple[int, str, list[str]] | None = None
        preamble: list[str] = []
        for line in text.splitlines():
            match = _HEADING.match(line)
            if match:
                if current:
                    sections.append(current)
                elif preamble and any(part.strip() for part in preamble):
                    sections.append((1, fallback_title, preamble))
                current = (len(match.group(1)), match.group(2).strip(), [])
            elif current:
                current[2].append(line)
            else:
                preamble.append(line)
        if current:
            sections.append(current)
        elif preamble:
            sections.append((1, fallback_title, preamble))

        occurrences: dict[str, int] = {}
        result = []
        for level, heading, lines in sections:
            key = _slug(heading)
            occurrences[key] = occurrences.get(key, 0) + 1
            result.append((level, heading, "\n".join(lines), occurrences[key]))
        return result

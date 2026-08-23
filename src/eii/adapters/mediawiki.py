"""Adapter for immutable MediaWiki revision snapshots."""

from __future__ import annotations

import json
import re
from pathlib import Path

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind

from .base import SourceCapabilities
from .common import normalized_language

_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.MULTILINE)


class MediaWikiRevisionAdapter:
    name = "mediawiki-revision"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities("mediawiki-revision", parallel_languages=True)

    def can_load(self, source: Path) -> bool:
        if not source.is_file() or source.suffix.casefold() != ".json":
            return False
        try:
            return bool(
                json.loads(source.read_text("utf-8")).get("format") == "mediawiki-revisions-v1"
            )
        except (OSError, ValueError, AttributeError):
            return False

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        data = json.loads(source.read_text("utf-8"))
        pages = data.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("MediaWiki snapshot requires pages")
        lang = normalized_language(language, data.get("language"))
        blocks = []
        order = 0
        for page in pages:
            if not isinstance(page, dict) or not page.get("pageid") or not page.get("revid"):
                raise ValueError("MediaWiki page requires pageid and revid")
            content = str(page.get("content", ""))
            matches = list(_HEADING.finditer(content))
            spans = [
                (
                    str(page.get("title") or page["pageid"]),
                    0,
                    matches[0].start() if matches else len(content),
                )
            ]
            spans += [
                (
                    m.group(2),
                    m.end(),
                    matches[i + 1].start() if i + 1 < len(matches) else len(content),
                )
                for i, m in enumerate(matches)
            ]
            parent = f"mediawiki:{page['pageid']}:{page['revid']}"
            for index, (title, start, end) in enumerate(spans):
                blocks.append(
                    ContentBlock(
                        f"{parent}:{index}",
                        UnitKind.SECTION,
                        title,
                        content[start:end].strip(),
                        order,
                        SourceLocator(
                            self.name,
                            str(data.get("wiki") or source.name),
                            str(page["pageid"]),
                            str(page["revid"]),
                            page.get("url"),
                        ),
                        None if index == 0 else f"{parent}:0",
                        metadata={"page_id": page["pageid"], "revision_id": page["revid"]},
                    )
                )
                order += 1
        version = str(max(int(page["revid"]) for page in pages))
        key = str(data.get("course_key") or source.stem)
        return CourseRelease(
            f"mediawiki:{key}:{lang}:{version}",
            key,
            lang,
            version,
            str(data.get("title") or key),
            tuple(blocks),
            SourceLocator(self.name, str(data.get("wiki") or source.name), source.name),
            data.get("license"),
            str(data.get("canonical_course_id") or key),
            {},
        )

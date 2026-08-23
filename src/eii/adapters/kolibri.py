"""Adapter for a provider-neutral Kolibri channel JSON snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind, content_hash

from .base import SourceCapabilities
from .common import normalized_language


class KolibriChannelAdapter:
    name = "kolibri-channel"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities("kolibri-channel", assessments=True, parallel_languages=True)

    def can_load(self, source: Path) -> bool:
        if not source.is_file() or source.suffix.casefold() != ".json":
            return False
        try:
            return bool(json.loads(source.read_text("utf-8")).get("format") == "kolibri-channel-v1")
        except (OSError, ValueError, AttributeError):
            return False

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        data = json.loads(source.read_text("utf-8"))
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("Kolibri channel requires nodes")
        lang = normalized_language(language, data.get("language"))
        seen: set[str] = set()
        blocks = []
        kind_map = {
            "topic": UnitKind.SECTION,
            "exercise": UnitKind.ASSESSMENT,
            "quiz": UnitKind.ASSESSMENT,
        }
        for order, node in enumerate(nodes):
            if not isinstance(node, dict) or not str(node.get("id", "")).strip():
                raise ValueError("Kolibri node requires a stable id")
            node_id = str(node["id"])
            if node_id in seen:
                raise ValueError("Kolibri node ids must be unique")
            seen.add(node_id)
            blocks.append(
                ContentBlock(
                    id=f"kolibri:{node_id}",
                    kind=kind_map.get(str(node.get("kind")), UnitKind.ACTIVITY),
                    title=str(node.get("title") or node_id),
                    text=str(node.get("text") or node.get("description") or ""),
                    order=order,
                    locator=SourceLocator(
                        self.name, source.name, node_id, source_url=node.get("url")
                    ),
                    parent_id=f"kolibri:{node['parent_id']}" if node.get("parent_id") else None,
                    concepts=tuple(node.get("concepts", ())),
                    learning_objectives=tuple(node.get("learning_objectives", ())),
                    metadata={
                        key: value
                        for key, value in node.items()
                        if key not in {"id", "title", "text", "description"}
                    },
                )
            )
        version = str(data.get("version") or content_hash(data)[7:23])
        key = str(data.get("channel_id") or source.stem)
        return CourseRelease(
            f"kolibri:{key}:{lang}:{version}",
            key,
            lang,
            version,
            str(data.get("title") or key),
            tuple(blocks),
            SourceLocator(self.name, source.name, source.name),
            data.get("license"),
            str(data.get("canonical_course_id") or key),
            {"channel_token": data.get("channel_token")},
        )

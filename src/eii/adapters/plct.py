"""Thin adapter for a stable PLCT JSON export boundary.

PLCT integrations should export this small shape rather than importing PLCT's
internal Python classes. This keeps the Observatory replaceable and testable.
"""

from __future__ import annotations

import json
from pathlib import Path

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind

from .base import SourceCapabilities


class PlctExportAdapter:
    name = "plct-export"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            "plct-course-export-v1",
            assessments=True,
            parallel_languages=True,
            retrieval_context=True,
        )

    def can_load(self, source: Path) -> bool:
        if not source.is_file() or source.suffix.lower() != ".json":
            return False
        try:
            return bool(
                json.loads(source.read_text("utf-8")).get("format") == "plct-course-export-v1"
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            return False

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        data = json.loads(source.read_text("utf-8"))
        if data.get("format") != "plct-course-export-v1":
            raise ValueError("unsupported PLCT export format")
        required = ("course_key", "language", "version", "activities")
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"PLCT export missing: {', '.join(missing)}")
        if not isinstance(data["activities"], list) or not data["activities"]:
            raise ValueError("PLCT export activities must be a non-empty array")
        if not all(
            isinstance(data[key], (str, int)) and str(data[key]).strip()
            for key in ("course_key", "language", "version")
        ):
            raise ValueError(
                "PLCT course key, language, and version must be non-empty scalar values"
            )
        lang = language or str(data["language"])
        repository = data.get("repository", source.name)
        blocks = []
        activity_keys: set[str] = set()
        block_ids: set[str] = set()
        order_counter = -1
        for index, activity in enumerate(data["activities"]):
            if not isinstance(activity, dict) or "activity_key" not in activity:
                raise ValueError(f"PLCT activity {index} must be an object with activity_key")
            activity_key = str(activity["activity_key"])
            if not activity_key.strip() or activity_key in activity_keys:
                raise ValueError("PLCT activity keys must be non-empty and unique")
            activity_keys.add(activity_key)
            if not isinstance(activity.get("metadata", {}), dict):
                raise ValueError(f"PLCT activity {activity_key} metadata must be an object")
            activity_id = f"plct:{data['course_key']}:{activity_key}"
            order_counter += 1
            blocks.append(
                ContentBlock(
                    id=activity_id,
                    kind=UnitKind(activity.get("kind", "activity")),
                    title=activity.get("title", activity_key),
                    text=activity.get("text", ""),
                    order=order_counter,
                    locator=SourceLocator(
                        self.name, repository, activity_key, source_url=activity.get("url")
                    ),
                    concepts=tuple(activity.get("concepts", ())),
                    learning_objectives=tuple(activity.get("learning_objectives", ())),
                    metadata={
                        **activity.get("metadata", {}),
                        **(
                            {"translation_id": str(activity["translation_id"])}
                            if activity.get("translation_id") is not None
                            else {}
                        ),
                    },
                )
            )
            block_ids.add(activity_id)
            chunks = activity.get("chunks", [])
            if not isinstance(chunks, list):
                raise ValueError(f"PLCT activity {activity_key} chunks must be an array")
            chunk_keys: set[str] = set()
            for chunk_index, chunk in enumerate(chunks):
                if not isinstance(chunk, dict) or "chunk_key" not in chunk:
                    raise ValueError(f"PLCT chunk {activity_key}:{chunk_index} requires chunk_key")
                chunk_key = str(chunk["chunk_key"])
                if not chunk_key.strip() or chunk_key in chunk_keys:
                    raise ValueError(
                        f"PLCT chunk keys must be non-empty and unique within {activity_key}"
                    )
                chunk_keys.add(chunk_key)
                chunk_id = f"{activity_id}:{chunk_key}"
                block_ids.add(chunk_id)
                order_counter += 1
                chunk_metadata = chunk.get("metadata", {})
                if not isinstance(chunk_metadata, dict):
                    raise ValueError(
                        f"PLCT chunk {activity_key}:{chunk_key} metadata must be an object"
                    )
                blocks.append(
                    ContentBlock(
                        id=chunk_id,
                        kind=UnitKind(chunk.get("kind", "section")),
                        title=str(chunk.get("title", chunk_key)),
                        text=str(chunk.get("text", "")),
                        order=order_counter,
                        locator=SourceLocator(
                            self.name,
                            repository,
                            activity_key,
                            chunk_key,
                            source_url=chunk.get("url") or activity.get("url"),
                        ),
                        parent_id=activity_id,
                        concepts=tuple(chunk.get("concepts", ())),
                        learning_objectives=tuple(chunk.get("learning_objectives", ())),
                        metadata={
                            **chunk_metadata,
                            **(
                                {"translation_id": str(chunk["translation_id"])}
                                if chunk.get("translation_id") is not None
                                else {}
                            ),
                        },
                    )
                )
        return CourseRelease(
            id=f"plct:{data['course_key']}:{lang}:{data['version']}",
            course_key=data["course_key"],
            language=lang,
            version=str(data["version"]),
            title=data.get("title", data["course_key"]),
            blocks=tuple(blocks),
            source=SourceLocator(self.name, repository, source.name),
            content_license=data.get("license"),
            canonical_course_id=data.get("canonical_course_id", data["course_key"]),
            metadata=data.get("metadata", {}),
        )

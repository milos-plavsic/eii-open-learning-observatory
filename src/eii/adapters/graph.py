"""Graph-course adapter for branching platforms such as Oppia."""

from __future__ import annotations

import json
from pathlib import Path

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind, content_hash

from .base import SourceCapabilities
from .common import normalized_language


class LearningGraphAdapter:
    name = "learning-graph"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            "eii-learning-graph-v1",
            assessments=True,
            parallel_languages=True,
            metadata={"topology": "directed-graph"},
        )

    def can_load(self, source: Path) -> bool:
        if not source.is_file() or source.suffix.casefold() != ".json":
            return False
        try:
            return bool(
                json.loads(source.read_text("utf-8")).get("format") == "eii-learning-graph-v1"
            )
        except (OSError, ValueError, AttributeError):
            return False

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease:
        data = json.loads(source.read_text("utf-8"))
        states = data.get("states")
        edges = data.get("edges", [])
        if not isinstance(states, list) or not states:
            raise ValueError("learning graph requires states")
        if not isinstance(edges, list):
            raise ValueError("learning graph edges must be an array")
        state_ids = {
            str(state.get("id")) for state in states if isinstance(state, dict) and state.get("id")
        }
        if len(state_ids) != len(states):
            raise ValueError("learning graph state ids must be present and unique")
        outgoing: dict[str, list[dict[str, object]]] = {state_id: [] for state_id in state_ids}
        for edge in edges:
            if (
                not isinstance(edge, dict)
                or str(edge.get("from")) not in state_ids
                or str(edge.get("to")) not in state_ids
            ):
                raise ValueError("learning graph edge references an unknown state")
            outgoing[str(edge["from"])].append(edge)
        blocks = []
        for order, state in enumerate(states):
            state_id = str(state["id"])
            interactions = state.get("interactions", [])
            kind = UnitKind.ASSESSMENT if interactions else UnitKind.ACTIVITY
            blocks.append(
                ContentBlock(
                    f"graph:{state_id}",
                    kind,
                    str(state.get("title") or state_id),
                    str(state.get("content") or ""),
                    order,
                    SourceLocator(self.name, source.name, state_id),
                    concepts=tuple(state.get("concepts", ())),
                    learning_objectives=tuple(state.get("learning_objectives", ())),
                    metadata={
                        "interactions": interactions,
                        "transitions": outgoing[state_id],
                        "terminal": not outgoing[state_id],
                        "start": state_id == str(data.get("initial_state")),
                    },
                )
            )
        lang = normalized_language(language, data.get("language"))
        key = str(data.get("course_key") or source.stem)
        version = str(data.get("version") or content_hash(data)[7:23])
        return CourseRelease(
            f"graph:{key}:{lang}:{version}",
            key,
            lang,
            version,
            str(data.get("title") or key),
            tuple(blocks),
            SourceLocator(self.name, source.name, source.name),
            data.get("license"),
            str(data.get("canonical_course_id") or key),
            {"initial_state": data.get("initial_state"), "edge_count": len(edges)},
        )

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Term:
    concept_id: str
    translations: Mapping[str, tuple[str, ...]]
    forbidden: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class Glossary:
    id: str
    version: str
    terms: tuple[Term, ...]

    @classmethod
    def load(cls, path: Path) -> Glossary:
        data = json.loads(path.read_text("utf-8"))
        terms = tuple(
            Term(
                item["concept_id"],
                {k: tuple(v) for k, v in item.get("translations", {}).items()},
                {k: tuple(v) for k, v in item.get("forbidden", {}).items()},
            )
            for item in data["terms"]
        )
        return cls(data["id"], str(data["version"]), terms)

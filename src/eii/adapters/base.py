"""Provider-neutral adapter contracts and capability discovery."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from eii.domain import CourseRelease


@dataclass(frozen=True, slots=True)
class SourceCapabilities:
    """Features an adapter can prove rather than features callers assume."""

    format: str
    versions: bool = True
    stable_ids: bool = True
    assessments: bool = False
    parallel_languages: bool = False
    retrieval_context: bool = False
    learner_events: bool = False
    patch_proposals: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class CourseAdapter(Protocol):
    name: str

    def can_load(self, source: Path) -> bool: ...

    def load(self, source: Path, *, language: str | None = None) -> CourseRelease: ...

    def capabilities(self) -> SourceCapabilities: ...

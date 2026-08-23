"""Stable public value types for offline appliance operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    architecture: str
    cpu_count: int
    memory_bytes: int | None
    free_disk_bytes: int
    model_profile: str
    suitable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackageManifest:
    schema_version: str
    package_id: str
    version: str
    created_at: str
    files: dict[str, str]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class ApplianceConfig:
    selected_courses: tuple[str, ...]
    allowed_languages: tuple[str, ...]
    assistant_behavior: str = "hint-first"

    def __post_init__(self) -> None:
        if self.assistant_behavior not in {"hint-first", "socratic", "direct"}:
            raise ValueError("assistant behavior must be hint-first, socratic, or direct")
        if not self.selected_courses or not self.allowed_languages:
            raise ValueError("at least one course and language must be selected")

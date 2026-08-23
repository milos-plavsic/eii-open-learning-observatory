"""Default adapter registry used by CLI and integrations."""

from pathlib import Path

from .base import CourseAdapter
from .graph import LearningGraphAdapter
from .h5p import H5PAdapter
from .kolibri import KolibriChannelAdapter
from .mediawiki import MediaWikiRevisionAdapter
from .moodle import MoodleBackupAdapter
from .olx import OpenEdxOlxAdapter
from .plct import PlctExportAdapter
from .repository import RepositoryAdapter

DEFAULT_ADAPTERS: tuple[CourseAdapter, ...] = (
    PlctExportAdapter(),
    H5PAdapter(),
    OpenEdxOlxAdapter(),
    MoodleBackupAdapter(),
    KolibriChannelAdapter(),
    MediaWikiRevisionAdapter(),
    LearningGraphAdapter(),
    RepositoryAdapter(),
)


def adapter_for(source: Path) -> CourseAdapter | None:
    return next((adapter for adapter in DEFAULT_ADAPTERS if adapter.can_load(source)), None)

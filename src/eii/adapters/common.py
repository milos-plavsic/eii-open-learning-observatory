"""Shared safe parsing helpers for archive-backed course adapters."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_MEMBER_BYTES = 100_000_000


def safe_zip_members(source: Path) -> tuple[tuple[ZipInfo, bytes], ...]:
    """Read a bounded ZIP without extracting paths onto the filesystem."""
    try:
        with ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise ValueError("archive contains too many files")
            total = 0
            result = []
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts or "\x00" in info.filename:
                    raise ValueError("archive contains an unsafe path")
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ValueError("archive member exceeds size limit")
                total += info.file_size
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("archive exceeds uncompressed size limit")
                if not info.is_dir():
                    result.append((info, archive.read(info)))
            return tuple(result)
    except BadZipFile as error:
        raise ValueError("source is not a valid ZIP archive") from error


def decoded_text(data: bytes, *, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} is not valid UTF-8") from error


def normalized_language(language: str | None, fallback: str | None) -> str:
    value = (language or fallback or "").strip()
    if not value:
        raise ValueError("course language is required")
    return value

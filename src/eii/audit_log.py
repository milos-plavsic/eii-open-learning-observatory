"""Size-bounded, retention-managed local JSONL audit streams."""

from __future__ import annotations

import os
import stat
import time
import uuid
from io import TextIOBase
from pathlib import Path
from threading import RLock
from typing import TextIO


class ManagedAuditLog(TextIOBase):
    def __init__(self, path: Path, *, max_bytes: int = 10 * 1024 * 1024, retention_days: int = 30):
        super().__init__()
        self._stream: TextIO | None = None
        self._lock_descriptor: int | None = None
        self._lock = RLock()
        self._next_purge_at = 0.0
        if max_bytes < 1024 or retention_days < 1:
            raise ValueError("audit log limits require at least 1024 bytes and one retention day")
        self.path, self.max_bytes, self.retention_days = path, max_bytes, retention_days
        path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_writer_lock()
        self._purge()
        self._stream = self._open_stream()
        path.chmod(0o600)

    def _acquire_writer_lock(self) -> None:
        lock_path = self.path.with_name(f".{self.path.name}.writer.lock")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):  # pragma: no branch - absent on Windows
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("audit writer lock must be a regular file")
            try:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:  # pragma: no cover - Windows exercises this in native CI
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except (OSError, ValueError) as error:
            os.close(descriptor)
            raise ValueError("audit log already has a writer or an unsafe lock") from error
        self._lock_descriptor = descriptor

    def _open_stream(self) -> TextIO:
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):  # pragma: no branch - absent on Windows
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("audit log must be a regular non-symbolic file")
        return os.fdopen(descriptor, "a", encoding="utf-8")

    def _purge(self) -> None:
        now = time.time()
        cutoff = now - self.retention_days * 86_400
        for archived in self.path.parent.glob(f"{self.path.name}.*.jsonl"):
            if (
                archived.is_file()
                and not archived.is_symlink()
                and archived.stat().st_mtime < cutoff
            ):
                archived.unlink()
        self._next_purge_at = now + min(3600, self.retention_days * 86_400)

    def write(self, value: str) -> int:
        if self.closed or self._stream is None:
            raise ValueError("I/O operation on closed audit log")
        encoded_size = len(value.encode("utf-8"))
        if encoded_size > self.max_bytes:
            raise ValueError("one audit record exceeds the configured log size limit")
        with self._lock:
            if time.time() >= self._next_purge_at:
                self._purge()
            self._stream.flush()
            if self.path.stat().st_size + encoded_size > self.max_bytes:
                self._stream.close()
                suffix = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "." + uuid.uuid4().hex
                os.replace(self.path, self.path.with_name(f"{self.path.name}.{suffix}.jsonl"))
                self._stream = self._open_stream()
                self.path.chmod(0o600)
                self._purge()
            return int(self._stream.write(value))

    def flush(self) -> None:
        stream = getattr(self, "_stream", None)
        if stream is not None and not stream.closed:
            with self._lock:
                stream.flush()

    def close(self) -> None:
        if self.closed:
            return
        stream = getattr(self, "_stream", None)
        super().close()
        if stream is not None and not stream.closed:
            stream.close()
        descriptor = getattr(self, "_lock_descriptor", None)
        if descriptor is not None:
            os.close(descriptor)
            self._lock_descriptor = None

    def __enter__(self) -> ManagedAuditLog:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

"""Health, readiness, and metrics routes for the offline appliance."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .appliance_handler_support import send_json
from .appliance_state import active_release
from .service import ObservableHandler


def metrics_handler(handler: ObservableHandler) -> None:
    handler.send_metrics()


def readiness_handler(
    root: Path, draining: threading.Event | None
) -> Callable[[ObservableHandler], None]:
    def ready(handler: ObservableHandler) -> None:
        if draining and draining.is_set():
            send_json(handler, {"status": "draining"}, 503)
            return
        try:
            release = active_release(root)
            send_json(handler, {"status": "ready", "release": release.name}, 200)
        except Exception as error:
            send_json(handler, {"status": "not-ready", "detail": str(error)}, 503)

    return ready


def health_handler(root: Path) -> Callable[[ObservableHandler], None]:
    def health(handler: ObservableHandler) -> None:
        try:
            release = active_release(root)
            send_json(handler, {"status": "ok", "release": release.name, "offline": True}, 200)
        except Exception as error:
            send_json(handler, {"status": "error", "detail": str(error)}, 503)

    return health

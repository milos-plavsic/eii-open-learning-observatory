"""Read-only evidence and static-content HTTP route group."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .appliance_content_handlers import content_handler
from .appliance_handler_support import send_json
from .appliance_router import ApplianceRouter
from .appliance_state import active_release
from .service import ObservableHandler

__all__ = ["content_handler", "evidence_handler", "register_evidence_routes"]


def evidence_handler(root: Path) -> Callable[[ObservableHandler], None]:
    """Serve a bounded evidence bundle only when it is packaged with the release."""

    def serve(handler: ObservableHandler) -> None:
        try:
            path = active_release(root) / "content" / "evidence.json"
        except (FileNotFoundError, ValueError):
            handler.send_error(404)
            return
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            handler.send_error(404)
            return
        try:
            document = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            send_json(handler, {"error": f"packaged evidence is invalid: {error}"}, 503)
            return
        if not isinstance(document, dict) or "schema_version" not in document:
            send_json(handler, {"error": "packaged evidence is invalid"}, 503)
            return
        send_json(handler, document, 200)

    return serve


def register_evidence_routes(router: ApplianceRouter, root: Path) -> None:
    router.add("GET", "/api/evidence", evidence_handler(root))
    router.fallback("GET", content_handler(root))

"""Read-only Classroom Weather HTTP route group."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .appliance_handler_support import send_json
from .appliance_router import ApplianceRouter
from .appliance_state import active_release
from .service import ObservableHandler


def weather_handler(root: Path) -> Callable[[ObservableHandler], None]:
    """Serve a previously privacy-released map; never accept learner events."""

    def serve(handler: ObservableHandler) -> None:
        try:
            path = active_release(root) / "content" / "weather-map.json"
        except (FileNotFoundError, ValueError):
            handler.send_error(404)
            return
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            handler.send_error(404)
            return
        try:
            document = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            send_json(handler, {"error": f"packaged weather map is invalid: {error}"}, 503)
            return
        privacy = document.get("privacy") if isinstance(document, dict) else None
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "3.0"
            or not isinstance(privacy, dict)
            or privacy.get("raw_conversations_stored") is not False
            or privacy.get("direct_identifiers_stored") is not False
            or not isinstance(document.get("cells"), list)
        ):
            send_json(handler, {"error": "packaged weather map violates the public schema"}, 503)
            return
        send_json(handler, document, 200)

    return serve


def register_weather_routes(router: ApplianceRouter, root: Path) -> None:
    router.add("GET", "/api/weather", weather_handler(root))

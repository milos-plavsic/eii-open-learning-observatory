"""Response helpers shared by appliance HTTP handler groups."""

from __future__ import annotations

import json
from typing import Any

from .service import ObservableHandler


def send_json(handler: ObservableHandler, payload: dict[str, Any], status: int) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

"""Static-content routes for the offline appliance."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import unquote, urlparse

from .appliance_state import active_release
from .service import ObservableHandler
from .service_limits import nonce_html


def content_handler(root: Path) -> Callable[[ObservableHandler], None]:
    def serve_content(handler: ObservableHandler) -> None:
        relative = unquote(urlparse(handler.path).path).lstrip("/") or "index.html"
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            handler.send_error(400)
            return
        content_root = active_release(root) / "content"
        target = content_root.joinpath(*pure.parts)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file() or not target.resolve().is_relative_to(content_root.resolve()):
            handler.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if content_type == "text/html":
            body, nonce = nonce_html(body)
            cast(Any, handler)._content_nonce = nonce
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    return serve_content

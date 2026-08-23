"""Bounded in-process request limiting and nonce-safe HTML transformation."""

from __future__ import annotations

import re
import secrets
import threading
import time


class BoundedRateLimiter:
    def __init__(self, requests_per_minute: int, client_capacity: int):
        self.requests_per_minute = requests_per_minute
        self.client_capacity = client_capacity
        self.state: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def limited(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for key in [
                key for key, values in self.state.items() if not values or now - values[-1] >= 60
            ]:
                self.state.pop(key, None)
            if client not in self.state and len(self.state) >= self.client_capacity:
                # Fail closed instead of allowing rotating identifiers to evict
                # existing counters and bypass the limiter.
                return True
            recent = [value for value in self.state.get(client, []) if now - value < 60]
            if len(recent) >= self.requests_per_minute:
                self.state[client] = recent
                return True
            recent.append(now)
            self.state[client] = recent
            return False


def nonce_html(body: bytes) -> tuple[bytes, str]:
    nonce = secrets.token_urlsafe(24)
    text = body.decode("utf-8")
    text = re.sub(r"<(script|style)(?![^>]*\bnonce=)", rf'<\1 nonce="{nonce}"', text)
    return text.encode("utf-8"), nonce

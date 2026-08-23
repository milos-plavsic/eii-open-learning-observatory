"""Dependency-free HTTP observability without learner-content logging."""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
from typing import Any, TextIO, cast
from urllib.parse import urlparse

AuditSink = Callable[[Mapping[str, object]], None]
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class HardenedThreadingHTTPServer(_ThreadingHTTPServer):
    """Bound active requests and drain accepted work during orderly shutdown."""

    daemon_threads = True
    block_on_close = False
    request_queue_size = 64
    allow_reuse_address = False

    def __init__(
        self,
        server_address: Any,
        handler: Any,
        bind_and_activate: bool = True,
        *,
        max_request_workers: int = 64,
    ) -> None:
        if max_request_workers < 1:
            raise ValueError("maximum request workers must be positive")
        self.max_request_workers = max_request_workers
        self.capacity_rejections = 0
        self.metrics_registry = getattr(handler, "metrics_registry", ServiceMetrics())
        self._capacity = threading.BoundedSemaphore(max_request_workers)
        self._active_condition = threading.Condition()
        self._active_sockets: set[socket.socket] = set()
        super().__init__(server_address, handler, bind_and_activate)

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> None:
        stream = cast(socket.socket, request)
        if not self._capacity.acquire(blocking=False):
            self.capacity_rejections += 1
            request_id = str(uuid.uuid4())
            self.metrics_registry.reject_capacity()
            body = b'{"error":"service overloaded"}'
            try:
                stream.settimeout(0.25)
                stream.sendall(
                    (
                        "HTTP/1.1 503 Service Unavailable\r\n"
                        "Connection: close\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\nRetry-After: 1\r\n"
                        f"X-Request-ID: {request_id}\r\n"
                        "X-Content-Type-Options: nosniff\r\nCache-Control: no-store\r\n\r\n"
                    ).encode("ascii")
                    + body
                )
            except OSError:
                pass
            self.shutdown_request(request)
            emitter = getattr(self.RequestHandlerClass, "audit_emitter", None)
            if emitter:
                try:
                    emitter(
                        audit_event(
                            request_id, "UNKNOWN", "/", 503, 0.0, event="capacity_rejection"
                        )
                    )
                except (OSError, ValueError):
                    self.metrics_registry.audit_failed()
            return
        try:
            with self._active_condition:
                self._active_sockets.add(stream)
            super().process_request(request, client_address)
        except BaseException:
            with self._active_condition:
                self._active_sockets.discard(stream)
                self._active_condition.notify_all()
            self._capacity.release()
            raise

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: Any
    ) -> None:
        stream = cast(socket.socket, request)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._active_condition:
                self._active_sockets.discard(stream)
                self._active_condition.notify_all()
            self._capacity.release()

    def drain(self, timeout: float) -> bool:
        """Wait for accepted requests, then interrupt sockets at the finite deadline."""
        if timeout < 0:
            raise ValueError("drain timeout cannot be negative")
        deadline = time.monotonic() + timeout
        with self._active_condition:
            clean = self._active_condition.wait_for(
                lambda: not self._active_sockets, timeout=max(0.0, deadline - time.monotonic())
            )
            sockets = tuple(self._active_sockets) if not clean else ()
        for active in sockets:
            with suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)
        return clean


def route_label(path: str) -> str:
    if path in {"/healthz", "/readyz", "/metrics", "/api/query", "/api/next", "/api/decision", "/"}:
        return path
    return "/static"


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    requests: Mapping[tuple[str, str, int], int]
    latency_seconds: Mapping[tuple[str, str], float]
    latency_buckets: Mapping[tuple[str, str, float], int]
    latency_counts: Mapping[tuple[str, str], int]
    in_flight: int
    capacity_rejections: int
    audit_log_failures: int


class ServiceMetrics:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._requests: dict[tuple[str, str, int], int] = {}
        self._latency: dict[tuple[str, str], float] = {}
        self._latency_buckets: dict[tuple[str, str, float], int] = {}
        self._latency_counts: dict[tuple[str, str], int] = {}
        self._in_flight = 0
        self._capacity_rejections = 0
        self._audit_log_failures = 0

    def begin(self) -> None:
        with self._condition:
            self._in_flight += 1

    def finish(self, method: str, path: str, status: int, seconds: float) -> None:
        route = route_label(path)
        with self._condition:
            self._in_flight = max(0, self._in_flight - 1)
            request_key = (method, route, status)
            latency_key = (method, route)
            self._requests[request_key] = self._requests.get(request_key, 0) + 1
            self._latency[latency_key] = self._latency.get(latency_key, 0.0) + max(0.0, seconds)
            self._latency_counts[latency_key] = self._latency_counts.get(latency_key, 0) + 1
            for upper_bound in LATENCY_BUCKETS:
                if seconds <= upper_bound:
                    bucket_key = (method, route, upper_bound)
                    self._latency_buckets[bucket_key] = self._latency_buckets.get(bucket_key, 0) + 1
            self._condition.notify_all()

    def snapshot(self) -> MetricsSnapshot:
        with self._condition:
            return MetricsSnapshot(
                dict(self._requests),
                dict(self._latency),
                dict(self._latency_buckets),
                dict(self._latency_counts),
                self._in_flight,
                self._capacity_rejections,
                self._audit_log_failures,
            )

    def reject_capacity(self) -> None:
        with self._condition:
            self._capacity_rejections += 1
            key = ("UNKNOWN", "/static", 503)
            self._requests[key] = self._requests.get(key, 0) + 1
            self._condition.notify_all()

    def audit_failed(self) -> None:
        with self._condition:
            self._audit_log_failures += 1

    def wait_for_requests(
        self, method: str, path: str, status: int, expected: int, *, timeout: float
    ) -> bool:
        """Wait boundedly until the requested completed-request count is observable."""
        key = (method, route_label(path), status)
        with self._condition:
            return self._condition.wait_for(
                lambda: self._requests.get(key, 0) >= expected, timeout=timeout
            )

    def prometheus(self) -> bytes:
        snapshot = self.snapshot()
        lines = ["# TYPE eii_http_requests_total counter"]
        for (method, route, status), count in sorted(snapshot.requests.items()):
            lines.append(
                f'eii_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}'
            )
        lines.append("# TYPE eii_http_request_latency_seconds_total counter")
        for (method, route), seconds in sorted(snapshot.latency_seconds.items()):
            lines.append(
                f'eii_http_request_latency_seconds_total{{method="{method}",route="{route}"}} {seconds:.6f}'
            )
        lines.append("# TYPE eii_http_request_duration_seconds histogram")
        for method, route in sorted(snapshot.latency_counts):
            for upper_bound in LATENCY_BUCKETS:
                count = snapshot.latency_buckets.get((method, route, upper_bound), 0)
                lines.append(
                    f'eii_http_request_duration_seconds_bucket{{method="{method}",route="{route}",le="{upper_bound:g}"}} {count}'
                )
            count = snapshot.latency_counts[(method, route)]
            total = snapshot.latency_seconds.get((method, route), 0.0)
            labels = f'method="{method}",route="{route}"'
            lines.append(f'eii_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}')
            lines.append(f"eii_http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
            lines.append(f"eii_http_request_duration_seconds_count{{{labels}}} {count}")
        lines.extend(
            (
                "# TYPE eii_http_in_flight gauge",
                f"eii_http_in_flight {snapshot.in_flight}",
                "# TYPE eii_http_capacity_rejections_total counter",
                f"eii_http_capacity_rejections_total {snapshot.capacity_rejections}",
                "# TYPE eii_audit_log_failures_total counter",
                f"eii_audit_log_failures_total {snapshot.audit_log_failures}",
            )
        )
        return ("\n".join(lines) + "\n").encode("ascii")


def request_started() -> tuple[str, float]:
    return str(uuid.uuid4()), time.monotonic()


def audit_event(
    request_id: str,
    method: str,
    path: str,
    status: int,
    seconds: float,
    *,
    event: str = "http_request",
) -> Mapping[str, object]:
    return {
        "event": event,
        "request_id": request_id,
        "method": method,
        "route": route_label(path),
        "status": status,
        "duration_ms": round(max(0.0, seconds) * 1000),
    }


def json_audit_sink(stream: TextIO) -> AuditSink:
    lock = threading.Lock()

    def emit(event: Mapping[str, object]) -> None:
        with lock:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()

    return emit


class ObservableHandler(BaseHTTPRequestHandler):
    """HTTP handler base that records bounded metadata, never bodies or query text."""

    metrics_registry = ServiceMetrics()
    audit_emitter: AuditSink | None = None
    request_timeout_seconds = 30.0

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.request_timeout_seconds)

    def handle_one_request(self) -> None:
        self._request_id, started = request_started()
        self._response_status = 500
        self.metrics_registry.begin()
        try:
            super().handle_one_request()
        finally:
            elapsed = time.monotonic() - started
            method = getattr(self, "command", "UNKNOWN") or "UNKNOWN"
            path = urlparse(getattr(self, "path", "")).path
            self.metrics_registry.finish(method, path, self._response_status, elapsed)
            if self.audit_emitter:
                try:
                    self.audit_emitter(
                        audit_event(self._request_id, method, path, self._response_status, elapsed)
                    )
                except (OSError, ValueError):
                    self.metrics_registry.audit_failed()

    def send_response(self, code: int, message: str | None = None) -> None:
        self._response_status = code
        super().send_response(code, message)

    def end_headers(self) -> None:
        self.send_header("X-Request-ID", self._request_id)
        super().end_headers()

    def send_metrics(self) -> None:
        body = self.metrics_registry.prometheus()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

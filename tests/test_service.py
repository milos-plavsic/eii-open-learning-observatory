import io
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from unittest.mock import MagicMock, patch

from eii.service import (
    HardenedThreadingHTTPServer,
    ObservableHandler,
    ServiceMetrics,
    audit_event,
    json_audit_sink,
    request_started,
    route_label,
)


class ServiceTests(unittest.TestCase):
    def test_server_has_bounded_thread_and_queue_policy(self):
        self.assertTrue(HardenedThreadingHTTPServer.daemon_threads)
        self.assertFalse(HardenedThreadingHTTPServer.block_on_close)
        self.assertEqual(HardenedThreadingHTTPServer.request_queue_size, 64)
        self.assertFalse(HardenedThreadingHTTPServer.allow_reuse_address)

    def test_server_rejects_over_capacity_and_validates_worker_limit(self):
        class Handler(BaseHTTPRequestHandler):
            audit_emitter = MagicMock()

            def log_message(self, format, *args):
                pass

        with self.assertRaisesRegex(ValueError, "positive"):
            HardenedThreadingHTTPServer(("127.0.0.1", 0), Handler, max_request_workers=0)
        with HardenedThreadingHTTPServer(
            ("127.0.0.1", 0), Handler, max_request_workers=1
        ) as server:
            self.assertTrue(server._capacity.acquire(blocking=False))
            client, accepted = socket.socketpair()
            try:
                server.process_request(accepted, ("local", 1))
                response = client.recv(1024)
                self.assertIn(b"503 Service Unavailable", response)
                headers, body = response.split(b"\r\n\r\n", 1)
                declared = int(
                    next(
                        line.split(b":", 1)[1]
                        for line in headers.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                )
                self.assertEqual(declared, len(body))
                self.assertEqual(json.loads(body), {"error": "service overloaded"})
                self.assertEqual(server.capacity_rejections, 1)
                self.assertEqual(server.metrics_registry.snapshot().capacity_rejections, 1)
                metrics = server.metrics_registry.prometheus().decode()
                self.assertNotIn(
                    'eii_http_request_duration_seconds_bucket{method="UNKNOWN"', metrics
                )
                Handler.audit_emitter.assert_called_once()
            finally:
                client.close()
                server._capacity.release()

            self.assertTrue(server._capacity.acquire(blocking=False))
            Handler.audit_emitter = None
            broken = MagicMock()
            broken.sendall.side_effect = OSError("closed")
            server.process_request(broken, ("local", 2))
            self.assertEqual(server.capacity_rejections, 2)
            server._capacity.release()

            self.assertTrue(server._capacity.acquire(blocking=False))
            Handler.audit_emitter = MagicMock(side_effect=ValueError("disk full"))
            client, accepted = socket.socketpair()
            try:
                server.process_request(accepted, ("local", 4))
                client.recv(1024)
                self.assertEqual(server.metrics_registry.snapshot().audit_log_failures, 1)
            finally:
                client.close()
                server._capacity.release()

            client, accepted = socket.socketpair()
            try:
                with (
                    patch(
                        "http.server.ThreadingHTTPServer.process_request",
                        side_effect=RuntimeError("thread start failed"),
                    ),
                    self.assertRaisesRegex(RuntimeError, "thread start failed"),
                ):
                    server.process_request(accepted, ("local", 3))
                self.assertTrue(server._capacity.acquire(blocking=False))
                server._capacity.release()
            finally:
                client.close()
                accepted.close()

    def test_server_close_is_finite_while_explicit_drain_tracks_request(self):
        entered, release = threading.Event(), threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                entered.set()
                release.wait(2)

            def log_message(self, format, *args):
                pass

        server = HardenedThreadingHTTPServer(("127.0.0.1", 0), Handler, max_request_workers=1)
        runner = threading.Thread(target=server.handle_request)
        runner.start()
        with socket.create_connection(server.server_address) as connection:
            connection.sendall(b"GET / HTTP/1.0\r\n\r\n")
            self.assertTrue(entered.wait(1))
            closed = threading.Event()

            def close():
                server.server_close()
                closed.set()

            closer = threading.Thread(target=close)
            closer.start()
            self.assertTrue(closed.wait(0.2))
            release.set()
            closer.join()
        runner.join()

    def test_finite_drain_validation_clean_and_forced_socket_close(self):
        class Handler(BaseHTTPRequestHandler):
            pass

        with HardenedThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            with self.assertRaisesRegex(ValueError, "cannot be negative"):
                server.drain(-1)
            self.assertTrue(server.drain(0))
            active = MagicMock()
            with server._active_condition:
                server._active_sockets.add(active)
            self.assertFalse(server.drain(0))
            active.shutdown.assert_called_once()
            with server._active_condition:
                server._active_sockets.clear()
            broken = MagicMock()
            broken.shutdown.side_effect = OSError("closed")
            with server._active_condition:
                server._active_sockets.add(broken)
            self.assertFalse(server.drain(0))
            with server._active_condition:
                server._active_sockets.clear()

    def test_route_labels_metrics_and_prometheus_output(self):
        self.assertEqual(route_label("/healthz"), "/healthz")
        self.assertEqual(route_label("/course/file"), "/static")
        metrics = ServiceMetrics()
        metrics.begin()
        self.assertFalse(metrics.wait_for_requests("GET", "/healthz", 200, 1, timeout=0.001))
        metrics.finish("GET", "/healthz", 200, 0.25)
        self.assertTrue(metrics.wait_for_requests("GET", "/healthz", 200, 1, timeout=0.001))
        metrics.finish("GET", "/healthz", 200, -1)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.requests[("GET", "/healthz", 200)], 2)
        self.assertEqual(snapshot.in_flight, 0)
        output = metrics.prometheus().decode()
        self.assertIn('route="/healthz"', output)
        self.assertIn("eii_http_in_flight 0", output)
        self.assertIn("eii_http_request_duration_seconds_bucket", output)
        self.assertIn('le="+Inf"', output)
        self.assertIn("eii_http_request_duration_seconds_count", output)
        metrics.audit_failed()
        self.assertEqual(metrics.snapshot().audit_log_failures, 1)

    def test_request_identity_bounded_audit_and_json_sink(self):
        request_id, started = request_started()
        self.assertEqual(len(request_id), 36)
        self.assertGreater(started, 0)
        event = audit_event(request_id, "POST", "/learner/private/path", 400, -1)
        self.assertEqual(event["route"], "/static")
        self.assertNotIn("learner", json.dumps(event))
        stream = io.StringIO()
        sink = json_audit_sink(stream)
        sink(event)
        self.assertEqual(json.loads(stream.getvalue())["request_id"], request_id)

    def test_request_survives_audit_sink_failure(self):
        class Handler(ObservableHandler):
            metrics_registry = ServiceMetrics()
            audit_emitter = MagicMock(side_effect=OSError("disk full"))

            def do_GET(self):
                self.send_response(204)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        with HardenedThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection(server.server_address) as client:
                client.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
                self.assertIn(b"204", client.recv(1024))
            thread.join()
            self.assertTrue(
                Handler.metrics_registry.wait_for_requests("GET", "/healthz", 204, 1, timeout=1)
            )
            self.assertEqual(Handler.metrics_registry.snapshot().audit_log_failures, 1)


if __name__ == "__main__":
    unittest.main()

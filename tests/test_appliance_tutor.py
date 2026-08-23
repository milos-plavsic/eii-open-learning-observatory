import json
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY
from test_appliance import signed_safety_case

from eii.adapters import PlctExportAdapter
from eii.appliance import configured_tutor, create_package, install_package, make_handler, serve
from eii.domain import ModelRun
from eii.safety_types import AssistantResponse
from eii.service import ServiceMetrics

FIXTURES = Path(__file__).parent / "fixtures"


class ApplianceTutorTests(unittest.TestCase):
    def test_model_query_capacity_rejects_overload(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingTutor:
            def answer(self, *args, **kwargs):
                entered.set()
                release.wait(2)
                return AssistantResponse("ok", (), (), ModelRun("p", "m", "v", {}, "i", "o"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "site"
            content.mkdir()
            (content / "index.html").write_text(
                "<style>body{color:black}</style><script>window.loaded=true</script>classroom"
            )
            (content / "data.json").write_text('{"ok":true}')
            package, box = root / "box.eii", root / "box"
            create_package((content,), package, version="1", private_key=TEST_PRIVATE_KEY)
            install_package(package, box, public_key=TEST_PUBLIC_KEY)
            course = PlctExportAdapter().load(FIXTURES / "plct.json")
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(box, tutor=BlockingTutor(), course=course, max_concurrent_queries=1),
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/query",
                b'{"question":"q"}',
                {"Content-Type": "application/json"},
            )
            first = threading.Thread(target=lambda: urlopen(request).read())
            first.start()
            self.assertTrue(entered.wait(1))
            with self.assertRaises(HTTPError) as overloaded:
                urlopen(request)
            self.assertEqual(overloaded.exception.code, 503)
            overloaded.exception.close()
            release.set()
            first.join()
            server.shutdown()
            server.server_close()
            server_thread.join()

    def test_configures_loopback_vllm_tutor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "box.eii"
            safety, evaluator_public, case = signed_safety_case(
                root, FIXTURES / "plct.json", model="local"
            )
            metadata = {
                "model_base_url": "http://127.0.0.1:8000/v1",
                "model": "local",
                "course_path": "content/plct.json",
                "prompt_version": "p1",
                "safety_case_path": "content/safety.json",
                "safety_case_id": case.id,
            }
            create_package(
                (FIXTURES / "plct.json", safety),
                package,
                version="1",
                private_key=TEST_PRIVATE_KEY,
                metadata=metadata,
            )
            install_package(
                package,
                root / "box",
                public_key=TEST_PUBLIC_KEY,
                safety_public_key=evaluator_public,
            )
            tutor, course = configured_tutor(root / "box")
            self.assertEqual(tutor.client.provider, "local-vllm")
            self.assertEqual(course.course_key, "loops")

    def test_rejects_nonlocal_model_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "box.eii"
            safety, evaluator_public, case = signed_safety_case(
                root, FIXTURES / "plct.json", model="remote"
            )
            metadata = {
                "model_base_url": "https://example.com/v1",
                "model": "remote",
                "course_path": "content/plct.json",
                "prompt_version": "p1",
                "safety_case_path": "content/safety.json",
                "safety_case_id": case.id,
            }
            create_package(
                (FIXTURES / "plct.json", safety),
                package,
                version="1",
                private_key=TEST_PRIVATE_KEY,
                metadata=metadata,
            )
            install_package(
                package,
                root / "box",
                public_key=TEST_PUBLIC_KEY,
                safety_public_key=evaluator_public,
            )
            with self.assertRaisesRegex(ValueError, "loopback"):
                configured_tutor(root / "box")

    def test_http_security_headers_and_optional_query_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "site"
            content.mkdir()
            (content / "index.html").write_text(
                "<style>body{color:black}</style><script>window.loaded=true</script>classroom"
            )
            (content / "data.json").write_text('{"ok":true}')
            package = root / "box.eii"
            box = root / "box"
            create_package((content,), package, version="1", private_key=TEST_PRIVATE_KEY)
            install_package(package, box, public_key=TEST_PUBLIC_KEY)
            course = PlctExportAdapter().load(FIXTURES / "plct.json")
            events = []
            metrics = ServiceMetrics()
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    box,
                    tutor=object(),
                    course=course,
                    query_token="class-token",
                    metrics=metrics,
                    audit_sink=events.append,
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                response = urlopen(base + "/site/index.html")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertNotIn("unsafe-inline", response.headers["Content-Security-Policy"])
                policy = response.headers["Content-Security-Policy"]
                nonce = re.search(r"script-src 'self' 'nonce-([^']+)'", policy).group(1)
                self.assertIn(f'nonce="{nonce}"', response.read().decode())
                data_response = urlopen(base + "/site/data.json")
                self.assertEqual(data_response.headers["Content-Type"], "application/json")
                self.assertEqual(json.loads(data_response.read()), {"ok": True})
                self.assertTrue(response.headers["X-Request-ID"])
                ready = json.loads(urlopen(base + "/readyz").read())
                self.assertEqual(ready["status"], "ready")
                self.assertIn(b"eii_http_requests_total", urlopen(base + "/metrics").read())
                request = Request(base + "/api/query", b"{}", {"Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as rejected:
                    urlopen(request)
                self.assertEqual(rejected.exception.code, 401)
                rejected.exception.close()
                self.assertTrue(events)
                self.assertEqual(events[0]["event"], "http_request")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_draining_readiness_and_bounded_rate_limit_client_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "site"
            content.mkdir()
            (content / "index.html").write_text("classroom")
            package, box = root / "box.eii", root / "box"
            create_package((content,), package, version="1", private_key=TEST_PRIVATE_KEY)
            install_package(package, box, public_key=TEST_PUBLIC_KEY)
            draining = threading.Event()
            handler = make_handler(box, draining=draining, max_rate_limit_clients=1)
            instance = object.__new__(handler)
            instance.client_address = ("first", 1)
            with patch("eii.service_limits.time.monotonic", return_value=100):
                self.assertFalse(instance._rate_limited())
            instance.client_address = ("second", 1)
            with patch("eii.service_limits.time.monotonic", return_value=101):
                self.assertTrue(instance._rate_limited())
            self.assertEqual(set(handler.rate_limit_state), {"first"})
            with patch("eii.service_limits.time.monotonic", return_value=200):
                self.assertFalse(instance._rate_limited())
            self.assertEqual(set(handler.rate_limit_state), {"second"})

            draining.set()
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as response:
                    urlopen(f"http://127.0.0.1:{server.server_port}/readyz")
                self.assertEqual(response.exception.code, 503)
                self.assertEqual(json.loads(response.exception.read())["status"], "draining")
                response.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_rejects_invalid_rate_limit_client_capacity(self):
        with self.assertRaisesRegex(ValueError, "client capacity"):
            make_handler(Path("."), max_rate_limit_clients=0)

    def test_serve_installs_signal_handlers_and_drains(self):
        server = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = server
        handlers = {}

        def install(name, handler):
            if callable(handler):
                handlers[name] = handler

        def run():
            handlers[__import__("signal").SIGTERM](15, None)

        server.serve_forever.side_effect = run
        with (
            patch("eii.appliance.configured_tutor", return_value=(None, None)),
            patch("eii.appliance.read_config", return_value=None),
            patch("eii.appliance.HardenedThreadingHTTPServer", return_value=context),
            patch("eii.appliance.signal.getsignal", return_value=object()),
            patch("eii.appliance.signal.signal", side_effect=install),
        ):
            serve(Path("."), shutdown_grace_seconds=0.25)
        server.drain.assert_called_once_with(0.25)

        server.reset_mock()
        context.__enter__.return_value = server
        server.serve_forever.side_effect = None
        with (
            patch("eii.appliance.configured_tutor", return_value=(None, None)),
            patch("eii.appliance.read_config", return_value=None),
            patch("eii.appliance.HardenedThreadingHTTPServer", return_value=context),
            patch("eii.appliance.threading.current_thread", return_value=object()),
            patch("eii.appliance.threading.main_thread", return_value=object()),
            patch("eii.appliance.signal.signal") as install_signal,
        ):
            serve(Path("."), shutdown_grace_seconds=0)
        install_signal.assert_not_called()

    def test_serve_rejects_negative_shutdown_grace(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            serve(Path("."), shutdown_grace_seconds=-1)


if __name__ == "__main__":
    unittest.main()

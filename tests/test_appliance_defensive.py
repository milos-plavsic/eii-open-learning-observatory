import json
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from eii.adapters import PlctExportAdapter
from eii.appliance import (
    ApplianceConfig,
    active_release,
    capability_check,
    configured_tutor,
    create_package,
    install_package,
    make_handler,
    read_config,
    recover_active_release,
    rollback,
    verify_package,
    write_onboarding_page,
)
from eii.appliance_router import ApplianceRouter, patterns_intersect
from eii.domain import ModelRun, content_hash
from eii.safety import AssistantResponse

FIXTURES = Path(__file__).parent / "fixtures"
KEY = b"0123456789abcdef0123456789abcdef"


class Tutor:
    def answer(self, question, **kwargs):
        return AssistantResponse(
            question, (), (), ModelRun("p", "m", "v", {}, "i", content_hash(question))
        )


class ApplianceDefensiveTests(unittest.TestCase):
    def test_pattern_intersection_is_complete_for_supported_tokens(self):
        self.assertTrue(patterns_intersect(("{segment}", "foo"), ("bar", "{segment}")))
        self.assertFalse(patterns_intersect(("{segment}", "foo"), ("bar", "baz")))
        self.assertFalse(patterns_intersect(("",), ("{segment}",)))
        self.assertFalse(patterns_intersect(("one",), ("one", "two")))
        self.assertTrue(patterns_intersect(("one",), ("one",)))
        self.assertTrue(patterns_intersect(("one", "{path}"), ("one",)))
        self.assertFalse(patterns_intersect(("one", "{path}"), ()))
        self.assertTrue(patterns_intersect(("one",), ("one", "{path}")))
        self.assertFalse(patterns_intersect((), ("one", "{path}")))
        self.assertTrue(patterns_intersect(("{path}",), ("one", "{path}")))

    def test_router_rejects_ambiguous_patterns_dispatches_params_and_404(self):
        calls = []
        router = ApplianceRouter()

        def handler(request):
            calls.append(dict(request.route_params))

        router.add("get", "/exact", handler)
        with self.assertRaisesRegex(ValueError, "duplicate appliance route"):
            router.add("GET", "/exact", handler)
        router.add_pattern("GET", "/course/{course_id}", handler)
        router.add("GET", "/{content_path:path}", handler)
        with self.assertRaisesRegex(ValueError, "overlap"):
            router.add_pattern("GET", "/course/{other_name}", handler)
        with self.assertRaisesRegex(ValueError, "overlap"):
            router.add_pattern("GET", "/{first}/loops", handler)
        router.add_pattern("POST", "/{first}/loops", handler)
        router.add_pattern("GET", "/lesson/{name}/extra", handler)
        router.add_pattern("GET", "/asset/{name}", handler)
        specific_first = ApplianceRouter()
        general_first = ApplianceRouter()
        specific_first.add_pattern("GET", "/course/{tail:path}", handler)
        specific_first.add_pattern("GET", "/{tail:path}", handler)
        general_first.add_pattern("GET", "/{tail:path}", handler)
        general_first.add_pattern("GET", "/course/{tail:path}", handler)
        self.assertEqual(
            [route.template for route in specific_first.patterns],
            [route.template for route in general_first.patterns],
        )
        for pattern, message in (
            ("relative/{name}", "absolute"),
            ("/course/{name}?x", "absolute"),
            ("/course/{name}/{name}", "duplicate"),
            ("/course/{tail:path}/extra", "final"),
            ("/course/{invalid-name}", "invalid"),
        ):
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, message):
                router.add_pattern("GET", pattern, handler)
        for path in ("relative", "/query?x", "/fragment#x"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "absolute"):
                router.add("GET", path, handler)
        request = Mock()
        router.dispatch(request, "get", "/exact")
        router.dispatch(request, "get", "/course/loops")
        router.dispatch(request, "get", "/assets/images/loop.svg")
        router.dispatch(request, "get", "/")
        router.dispatch(request, "post", "/absent")
        self.assertEqual(
            calls,
            [
                {},
                {"course_id": "loops"},
                {"content_path": "assets/images/loop.svg"},
                {"content_path": ""},
            ],
        )
        request.send_error.assert_called_once_with(404)

    def test_configuration_capability_and_package_preconditions(self):
        for courses, languages, behavior in (
            ((), ("en",), "direct"),
            (("c",), (), "direct"),
            (("c",), ("en",), "bad"),
        ):
            with self.assertRaises(ValueError):
                ApplianceConfig(courses, languages, behavior)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(read_config(root))
            with (
                patch("eii.appliance.Path.exists", return_value=False),
                patch("eii.appliance.shutil.disk_usage") as disk,
                patch("eii.appliance.os.cpu_count", return_value=None),
            ):
                disk.return_value.free = 1
                report = capability_check(root, minimum_disk_bytes=2)
                self.assertFalse(report.suitable)
                self.assertIsNone(report.memory_bytes)
            with self.assertRaises(TypeError):
                create_package((root / "missing",), root / "x", version="1")
            with self.assertRaises(TypeError):
                create_package(
                    (root / "missing",),
                    root / "x",
                    version="1",
                    private_key=root / "x",
                    signing_key=KEY,
                )
            empty = root / "empty"
            empty.mkdir()
            with self.assertRaisesRegex(ValueError, "at least one"):
                create_package((empty,), root / "x", version="1", private_key=TEST_PRIVATE_KEY)
            with self.assertRaises(FileNotFoundError):
                verify_package(root / "missing", public_key=TEST_PUBLIC_KEY)

    def test_corrupt_archive_paths_hashes_duplicates_and_missing_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x"
            source.write_text("x")
            package = root / "p.eii"
            create_package((source,), package, version="1", private_key=TEST_PRIVATE_KEY)
            tampered = root / "tampered.eii"
            with zipfile.ZipFile(package) as old, zipfile.ZipFile(tampered, "w") as new:
                for name in old.namelist():
                    new.writestr(name, b"changed" if name == "content/x" else old.read(name))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_package(tampered, public_key=TEST_PUBLIC_KEY)
            unsafe = root / "unsafe.eii"
            with zipfile.ZipFile(package) as old, zipfile.ZipFile(unsafe, "w") as new:
                for name in old.namelist():
                    new.writestr(name, old.read(name))
                new.writestr("../escape", "x")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                verify_package(unsafe, public_key=TEST_PUBLIC_KEY)
            duplicate_box = root / "duplicate"
            manifest = verify_package(package, public_key=TEST_PUBLIC_KEY)
            (duplicate_box / "releases" / manifest.package_id).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "already installed"):
                install_package(package, duplicate_box, public_key=TEST_PUBLIC_KEY)
            box = root / "box"
            manifest = install_package(package, box, public_key=TEST_PUBLIC_KEY)
            (box / "releases" / manifest.package_id).rename(root / "gone")
            with self.assertRaisesRegex(ValueError, "active release"):
                active_release(box)

    def test_rollback_recovery_and_onboarding_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "activation-history.jsonl").write_text("")
            with self.assertRaisesRegex(ValueError, "no previous"):
                rollback(root)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                recover_active_release(root / "none")
            (root / "activation-history.jsonl").write_text(
                '{"current":{"package_id":"gone","version":"1"}}\n'
            )
            with self.assertRaisesRegex(ValueError, "no intact"):
                recover_active_release(root)
            for url in ("https://local", "relative"):
                with self.assertRaises(ValueError):
                    write_onboarding_page(root / "x", url)
            write_onboarding_page(root / "nested" / "index.html", "http://127.0.0.1:8080")
            self.assertIn("<svg", (root / "nested/index.html").read_text())

    def test_http_health_static_query_validation_success_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            (site / "index.html").write_text("ok")
            evidence_file = root / "evidence.json"
            evidence_file.write_text('{"schema_version":"2.0","id":"demo"}')
            weather_file = root / "weather-map.json"
            weather_file.write_text(
                '{"schema_version":"3.0","privacy":{"raw_conversations_stored":false,'
                '"direct_identifiers_stored":false},"cells":[]}'
            )
            package = root / "p.eii"
            box = root / "box"
            create_package(
                (site, evidence_file, weather_file),
                package,
                version="1",
                private_key=TEST_PRIVATE_KEY,
            )
            install_package(package, box, public_key=TEST_PUBLIC_KEY)
            course = PlctExportAdapter().load(FIXTURES / "plct.json")
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(
                    box,
                    tutor=Tutor(),
                    course=course,
                    config=ApplianceConfig(("c",), ("sr",)),
                    max_queries_per_minute=8,
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                self.assertEqual(json.loads(urlopen(base + "/healthz").read())["status"], "ok")
                self.assertEqual(urlopen(base + "/site/").read(), b"ok")
                self.assertEqual(json.loads(urlopen(base + "/api/evidence").read())["id"], "demo")
                self.assertEqual(json.loads(urlopen(base + "/api/weather").read())["cells"], [])
                for path, code in (("/missing", 404), ("/%2e%2e/x", 400)):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(base + path)
                    self.assertEqual(error.exception.code, code)
                    error.exception.close()
                values = [
                    (b"{}", {}, 400),
                    (b"{}", {"Content-Type": "text/plain"}, 400),
                    (b'{"question":""}', {"Content-Type": "application/json"}, 400),
                    (b'{"question":"q","extra":1}', {"Content-Type": "application/json"}, 400),
                    (
                        b'{"question":"q","language":1}',
                        {"Content-Type": "application/json"},
                        400,
                    ),
                    (
                        b'{"question":"q","language":"en"}',
                        {"Content-Type": "application/json"},
                        400,
                    ),
                ]
                for body, headers, code in values:
                    request = Request(base + "/api/query", body, headers)
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request)
                    self.assertEqual(error.exception.code, code)
                    error.exception.close()
                response = urlopen(
                    Request(
                        base + "/api/query",
                        b'{"question":"q"}',
                        {"Content-Type": "application/json"},
                    )
                )
                self.assertIn("hint-first", json.loads(response.read())["answer"])
                for _ in range(2):
                    try:
                        urlopen(
                            Request(
                                base + "/api/query",
                                b'{"question":"q"}',
                                {"Content-Type": "application/json"},
                            )
                        )
                    except HTTPError as error:
                        error.close()
                with self.assertRaises(HTTPError) as limited:
                    urlopen(
                        Request(
                            base + "/api/query",
                            b'{"question":"q"}',
                            {"Content-Type": "application/json"},
                        )
                    )
                self.assertEqual(limited.exception.code, 429)
                limited.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_configured_tutor_missing_metadata_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x"
            source.write_text("x")
            for index, metadata in enumerate(
                (
                    {},
                    {"model_base_url": "http://localhost", "model": "m", "course_path": "../x"},
                    {
                        "model_base_url": "http://localhost",
                        "model": "m",
                        "course_path": "content/x",
                    },
                )
            ):
                box = root / f"box{index}"
                package = root / f"p{index}.eii"
                create_package(
                    (source,), package, version="1", private_key=TEST_PRIVATE_KEY, metadata=metadata
                )
                if not metadata:
                    install_package(package, box, public_key=TEST_PUBLIC_KEY)
                    self.assertEqual(configured_tutor(box), (None, None))
                else:
                    with self.assertRaisesRegex(ValueError, "approved offline safety case"):
                        install_package(package, box, public_key=TEST_PUBLIC_KEY)

    def test_http_unhealthy_disabled_endpoint_auth_origin_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            course = PlctExportAdapter().load(FIXTURES / "plct.json")
            for index, handler in enumerate(
                (
                    make_handler(root),
                    make_handler(
                        root,
                        tutor=Tutor(),
                        course=course,
                        query_token="token",
                        max_queries_per_minute=20,
                    ),
                )
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = f"http://127.0.0.1:{server.server_port}"
                    with self.assertRaises(HTTPError) as health:
                        urlopen(base + "/healthz")
                    self.assertEqual(health.exception.code, 503)
                    health.exception.close()
                    with self.assertRaises(HTTPError) as ready:
                        urlopen(base + "/readyz")
                    self.assertEqual(ready.exception.code, 503)
                    ready.exception.close()
                    request = Request(
                        base + "/api/query",
                        b'{"question":"q"}',
                        {"Content-Type": "application/json"},
                    )
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(request)
                    self.assertIn(rejected.exception.code, (401, 404))
                    rejected.exception.close()
                    if index:
                        cross = Request(
                            base + "/api/query",
                            b'{"question":"q"}',
                            {
                                "Content-Type": "application/json",
                                "Authorization": "Bearer token",
                                "Origin": "http://evil",
                            },
                        )
                        with self.assertRaises(HTTPError) as error:
                            urlopen(cross)
                        self.assertIn(error.exception.code, (400, 404))
                        error.exception.close()
                        oversized = Request(
                            base + "/api/query",
                            b"x" * 32769,
                            {"Content-Type": "application/json", "Authorization": "Bearer token"},
                        )
                        with self.assertRaises(HTTPError) as error:
                            urlopen(oversized)
                        self.assertIn(error.exception.code, (400, 404))
                        error.exception.close()
                        valid = Request(
                            base + "/api/query",
                            b'{"question":"q"}',
                            {"Content-Type": "application/json", "Authorization": "Bearer token"},
                        )
                        self.assertEqual(urlopen(valid).status, 200)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from eii.service import ServiceMetrics
from eii.study import ReviewStudy, make_study_handler, serve_study


def evidence(path):
    path.write_text(
        json.dumps(
            {
                "id": "bundle",
                "findings": [
                    {
                        "id": "f",
                        "finding_type": "x",
                        "title": "T",
                        "explanation": "E",
                        "evidence": [],
                        "affected_languages": ["en"],
                        "suggested_action": "A",
                        "severity": "high",
                        "confidence": 0.9,
                    }
                ],
            }
        )
    )


class StudyDefensiveTests(unittest.TestCase):
    def test_serve_study_enters_server_and_serves(self):
        server = MagicMock()
        server.__enter__.return_value = server
        with (
            tempfile.TemporaryFile("w+") as audit_stream,
            patch("eii.study.service.HardenedThreadingHTTPServer", return_value=server),
        ):
            serve_study(Path("db"), "s", port=1, audit_stream=audit_stream)
        server.serve_forever.assert_called_once()

    def test_initialization_auth_opening_record_and_export_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "e.json"
            evidence(source)
            db = root / "s.db"
            with ReviewStudy(db) as study:
                for study_id, reviewers, seed in (
                    ("", ("r",), "s"),
                    ("x", (), "s"),
                    ("x", ("",), "s"),
                    ("x", ("r",), ""),
                ):
                    with self.assertRaises(ValueError):
                        study.initialize(source, study_id=study_id, reviewers=reviewers, seed=seed)
                with self.assertRaisesRegex(ValueError, "unique"):
                    study.initialize(source, study_id="dup", reviewers=("r", "r"), seed="s")
                empty = root / "empty.json"
                empty.write_text('{"id":"e","findings":[]}')
                with self.assertRaisesRegex(ValueError, "no findings"):
                    study.initialize(empty, study_id="empty", reviewers=("r",), seed="s")
                token = study.initialize(source, study_id="ok", reviewers=("r",), seed="s")["r"]
                self.assertIsNone(study.authenticate("ok", ""))
                self.assertIsNone(study.authenticate("ok", "bad"))
                self.assertEqual(study.authenticate("ok", token), "r")
                first = study.next_assignment("ok", "r")
                second = study.next_assignment("ok", "r")
                self.assertEqual(first["opened_at"], second["opened_at"])
                for values in (
                    ("bad", "sufficient", "high", 5, "usable", 0),
                    ("confirmed", "bad", "high", 5, "usable", 0),
                    ("confirmed", "sufficient", "bad", 5, "usable", 0),
                    ("confirmed", "sufficient", "high", 0, "usable", 0),
                    ("confirmed", "sufficient", "high", 5, "bad", 0),
                    ("confirmed", "sufficient", "high", 5, "usable", -1),
                ):
                    with self.assertRaises(ValueError):
                        study.record(
                            "ok",
                            "r",
                            "f",
                            decision=values[0],
                            rationale="why",
                            evidence_quality=values[1],
                            severity_assessment=values[2],
                            usefulness=values[3],
                            actionability=values[4],
                            seconds_spent=values[5],
                        )
                with self.assertRaisesRegex(ValueError, "opened"):
                    study.record(
                        "ok",
                        "r",
                        "missing",
                        decision="confirmed",
                        rationale="why",
                        evidence_quality="sufficient",
                        severity_assessment="high",
                        usefulness=5,
                        actionability="usable",
                        seconds_spent=0,
                    )
                study.record(
                    "ok",
                    "r",
                    "f",
                    decision="confirmed",
                    rationale="why",
                    evidence_quality="sufficient",
                    severity_assessment="high",
                    usefulness=5,
                    actionability="usable",
                    seconds_spent=0,
                )
                self.assertIsNone(study.next_assignment("ok", "r"))
                self.assertEqual(
                    study.progress("ok", "r"), {"completed": 1, "total": 1, "remaining": 0}
                )
                with self.assertRaisesRegex(ValueError, "unknown"):
                    study.export("missing", root / "x")
                study.export("ok", root / "export.json")
                self.assertEqual(
                    json.loads((root / "export.json").read_text())["decisions"][0]["finding_id"],
                    "f",
                )

    def test_http_success_and_all_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "e.json"
            evidence(source)
            db = root / "s.db"
            with ReviewStudy(db) as study:
                token = study.initialize(source, study_id="ok", reviewers=("r",), seed="s")["r"]
            events = []
            metrics = ServiceMetrics()
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_study_handler(db, "ok", metrics=metrics, audit_sink=events.append),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                page = urlopen(base + "/")
                page_body = page.read()
                self.assertIn(b"Blinded", page_body)
                csp = page.headers["Content-Security-Policy"]
                self.assertNotIn("unsafe-inline", csp)
                self.assertIn("nonce-", csp)
                self.assertIn(b'<script nonce="', page_body)
                self.assertTrue(page.headers["X-Request-ID"])
                self.assertEqual(json.loads(urlopen(base + "/readyz").read())["status"], "ready")
                self.assertIn(b"eii_http_requests_total", urlopen(base + "/metrics").read())
                for request, code in (
                    (Request(base + "/missing"), 404),
                    (Request(base + "/api/next"), 401),
                    (Request(base + "/missing", b"x"), 404),
                    (Request(base + "/api/decision", b"{}"), 401),
                ):
                    with self.subTest(code=code), self.assertRaises(HTTPError) as error:
                        urlopen(request)
                    self.assertEqual(error.exception.code, code)
                    error.exception.close()
                headers = {"Authorization": "Bearer " + token}
                unopened = {
                    "finding_id": "f",
                    "decision": "confirmed",
                    "rationale": "why",
                    "evidence_quality": "sufficient",
                    "severity_assessment": "high",
                    "usefulness": 5,
                    "actionability": "usable",
                }
                with self.assertRaises(HTTPError) as error:
                    urlopen(
                        Request(
                            base + "/api/decision",
                            json.dumps(unopened).encode(),
                            {**headers, "Content-Type": "application/json"},
                        )
                    )
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
                assignment = json.loads(
                    urlopen(Request(base + "/api/next", headers=headers)).read()
                )["assignment"]
                missing = dict(unopened)
                missing["finding_id"] = "missing"
                with self.assertRaises(HTTPError) as error:
                    urlopen(
                        Request(
                            base + "/api/decision",
                            json.dumps(missing).encode(),
                            {**headers, "Content-Type": "application/json"},
                        )
                    )
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
                bad_requests = (
                    (Request(base + "/api/decision", b"{}", headers), 415),
                    (
                        Request(
                            base + "/api/decision",
                            b"{}",
                            {
                                **headers,
                                "Content-Type": "application/json",
                                "Origin": "http://evil",
                            },
                        ),
                        403,
                    ),
                    (
                        Request(
                            base + "/api/decision",
                            b"{",
                            {**headers, "Content-Type": "application/json"},
                        ),
                        400,
                    ),
                    (
                        Request(
                            base + "/api/decision",
                            b"",
                            {**headers, "Content-Type": "application/json"},
                        ),
                        400,
                    ),
                )
                for request, code in bad_requests:
                    with self.subTest(code=code), self.assertRaises(HTTPError) as error:
                        urlopen(request)
                    self.assertEqual(error.exception.code, code)
                    error.exception.close()
                record = {
                    "finding_id": assignment["finding_id"],
                    "decision": "confirmed",
                    "rationale": "why",
                    "evidence_quality": "sufficient",
                    "severity_assessment": "high",
                    "usefulness": 5,
                    "actionability": "usable",
                }
                response = urlopen(
                    Request(
                        base + "/api/decision",
                        json.dumps(record).encode(),
                        {**headers, "Content-Type": "application/json", "Origin": base},
                    )
                )
                self.assertEqual(response.status, 201)
                self.assertTrue(events)
                self.assertEqual(events[0]["route"], "/")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_http_readiness_reports_database_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            database_directory = Path(directory)
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_study_handler(database_directory, "s")
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(f"http://127.0.0.1:{server.server_port}/readyz")
                self.assertEqual(error.exception.code, 503)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()

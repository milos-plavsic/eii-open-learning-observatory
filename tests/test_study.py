import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from eii.cli import main
from eii.study import ReviewStudy, make_study_handler, serve_study


class ReviewStudyTests(unittest.TestCase):
    def evidence(self, root):
        path = root / "evidence.json"
        path.write_text(
            json.dumps(
                {
                    "id": "sha256:bundle",
                    "findings": [
                        {
                            "id": f"f{i}",
                            "finding_type": "translation.test",
                            "title": f"Finding {i}",
                            "explanation": "Review me",
                            "severity": "high",
                            "confidence": 0.99,
                            "evidence": [],
                            "model_run": {"provider": "hidden"},
                        }
                        for i in range(5)
                    ],
                }
            )
        )
        return path

    def test_assignments_are_deterministic_blinded_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "study.sqlite"
            evidence = self.evidence(root)
            with ReviewStudy(database) as study:
                tokens = study.initialize(
                    evidence, study_id="pilot", reviewers=("r1", "r2"), seed="secret"
                )
                self.assertEqual(study.authenticate("pilot", tokens["r1"]), "r1")
                self.assertIsNone(study.authenticate("pilot", "wrong"))
                first = study.next_assignment("pilot", "r1")
                self.assertNotIn("confidence", first["finding"])
                self.assertNotIn("severity", first["finding"])
                self.assertNotIn("model_run", first["finding"])
                study.record(
                    "pilot",
                    "r1",
                    first["finding_id"],
                    decision="confirmed",
                    rationale="Verified",
                    evidence_quality="sufficient",
                    severity_assessment="high",
                    usefulness=5,
                    actionability="usable",
                    seconds_spent=42,
                )
                self.assertEqual(
                    study.progress("pilot", "r1"), {"completed": 1, "total": 5, "remaining": 4}
                )
                self.assertNotEqual(
                    study.next_assignment("pilot", "r1")["finding_id"], first["finding_id"]
                )
                output = root / "export.json"
                study.export("pilot", output)
                self.assertEqual(
                    json.loads(output.read_text())["decisions"][0]["seconds_spent"], 42
                )

    def test_rejects_duplicate_or_unopened_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ReviewStudy(root / "study.sqlite") as study:
                study.initialize(
                    self.evidence(root), study_id="pilot", reviewers=("r1",), seed="secret"
                )
                with self.assertRaisesRegex(ValueError, "opened"):
                    study.record(
                        "pilot",
                        "r1",
                        "f0",
                        decision="confirmed",
                        rationale="yes",
                        evidence_quality="sufficient",
                        severity_assessment="high",
                        usefulness=5,
                        actionability="usable",
                        seconds_spent=1,
                    )

    def test_cli_study_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.evidence(root)
            database = root / "study.sqlite"
            seed = root / "seed"
            seed.write_text("private-random-seed")
            seed.chmod(0o600)
            self.assertEqual(
                main(
                    [
                        "review-study-init",
                        str(evidence),
                        "--database",
                        str(database),
                        "--study-id",
                        "pilot",
                        "--reviewers",
                        "r1,r2",
                        "--seed-file",
                        str(seed),
                    ]
                ),
                0,
            )
            assignment = root / "assignment.json"
            self.assertEqual(
                main(
                    [
                        "review-study-next",
                        "--database",
                        str(database),
                        "--study-id",
                        "pilot",
                        "--reviewer",
                        "r1",
                        "--output",
                        str(assignment),
                    ]
                ),
                0,
            )
            item = json.loads(assignment.read_text())
            record = root / "record.json"
            record.write_text(
                json.dumps(
                    {
                        "finding_id": item["finding_id"],
                        "decision": "confirmed",
                        "rationale": "Checked",
                        "evidence_quality": "sufficient",
                        "severity_assessment": "high",
                        "usefulness": 5,
                        "actionability": "usable",
                        "seconds_spent": 20,
                    }
                )
            )
            self.assertEqual(
                main(
                    [
                        "review-study-record",
                        str(record),
                        "--database",
                        str(database),
                        "--study-id",
                        "pilot",
                        "--reviewer",
                        "r1",
                    ]
                ),
                0,
            )
            output = root / "export.json"
            self.assertEqual(
                main(
                    [
                        "review-study-export",
                        "--database",
                        str(database),
                        "--study-id",
                        "pilot",
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertEqual(len(json.loads(output.read_text())["decisions"]), 1)

    def test_authenticated_web_review_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "study.sqlite"
            with ReviewStudy(database) as study:
                tokens = study.initialize(
                    self.evidence(root), study_id="pilot", reviewers=("r1",), seed="secret"
                )
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_study_handler(database, "pilot"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                headers = {"Authorization": "Bearer " + tokens["r1"]}
                assignment = json.loads(
                    urlopen(Request(base + "/api/next", headers=headers)).read()
                )
                record = {
                    "finding_id": assignment["assignment"]["finding_id"],
                    "decision": "confirmed",
                    "rationale": "Verified",
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
                progress = json.loads(urlopen(Request(base + "/api/next", headers=headers)).read())[
                    "progress"
                ]
                self.assertEqual(progress["completed"], 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_remote_study_bind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            serve_study(Path("unused.sqlite"), "pilot", host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()

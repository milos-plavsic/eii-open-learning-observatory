import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from eii.appliance import CapabilityReport
from eii.cli import _model_client, main, parser
from eii.study import ReviewStudy
from eii.weather import WeatherStore


class CliDefensiveTests(unittest.TestCase):
    def test_model_client_pair_validation_none_and_environment_key(self):
        command_parser = parser()
        with self.assertRaises(SystemExit):
            _model_client(SimpleNamespace(model_base_url="http://x", model=None), command_parser)
        self.assertIsNone(
            _model_client(SimpleNamespace(model_base_url=None, model=None), command_parser)
        )
        args = SimpleNamespace(
            model_base_url="http://localhost", model="m", provider="p", api_key_env="TEST_EII_KEY"
        )
        with patch.dict(os.environ, {"TEST_EII_KEY": "secret"}):
            self.assertEqual(_model_client(args, command_parser).api_key, "secret")

    def test_simple_appliance_commands_and_serve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "token"
            token.write_text("secret")
            token.chmod(0o600)
            good = CapabilityReport("x", 4, 1, 1, "small", True, ())
            bad = CapabilityReport("x", 1, 1, 1, "small", False, ("cpu",))
            with patch("eii.cli_appliance.capability_check", return_value=good):
                self.assertEqual(main(["appliance-check", "--path", str(root)]), 0)
            with patch("eii.cli_appliance.capability_check", return_value=bad):
                self.assertEqual(main(["appliance-check"]), 2)
            self.assertEqual(
                main(
                    [
                        "appliance-configure",
                        "--root",
                        str(root),
                        "--courses",
                        "a,b",
                        "--languages",
                        "en,sr",
                        "--assistant-behavior",
                        "direct",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "appliance-onboarding",
                        "--url",
                        "http://localhost:1",
                        "--output",
                        str(root / "onboard.html"),
                    ]
                ),
                0,
            )
            with patch(
                "eii.cli_appliance.rollback", return_value={"package_id": "p", "version": "1"}
            ):
                self.assertEqual(main(["appliance-rollback", "--root", str(root)]), 0)
            with patch(
                "eii.cli_appliance.recover_active_release",
                return_value={"package_id": "p", "version": "1"},
            ):
                self.assertEqual(main(["appliance-recover", "--root", str(root)]), 0)
            with patch("eii.cli_appliance.serve") as serve:
                self.assertEqual(
                    main(
                        [
                            "appliance-serve",
                            "--root",
                            str(root),
                            "--host",
                            "127.0.0.1",
                            "--port",
                            "1",
                            "--query-token-file",
                            str(token),
                        ]
                    ),
                    0,
                )
            serve.assert_called_once_with(
                root,
                host="127.0.0.1",
                port=1,
                query_token="secret",
                max_request_workers=64,
                max_concurrent_queries=4,
                max_queries_per_minute=30,
                max_rate_limit_clients=4096,
                shutdown_grace_seconds=30.0,
            )
            audit = root / "logs" / "appliance.jsonl"
            with patch("eii.cli_appliance.serve") as serve:
                self.assertEqual(
                    main(
                        [
                            "appliance-serve",
                            "--root",
                            str(root),
                            "--port",
                            "1",
                            "--audit-log",
                            str(audit),
                        ]
                    ),
                    0,
                )
                self.assertIs(serve.call_args.kwargs["audit_stream"].closed, True)
            token.write_text("")
            with self.assertRaises(SystemExit):
                main(["appliance-serve", "--root", str(root), "--query-token-file", str(token)])
            token.write_bytes(b"\xff")
            token.chmod(0o600)
            with self.assertRaises(SystemExit):
                main(["appliance-serve", "--root", str(root), "--query-token-file", str(token)])

    def test_compare_validate_regression_and_parser_error_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old"
            new = root / "new"
            output = root / "out"
            old.write_text('{"id":"a","findings":[]}')
            new.write_text('{"id":"b","findings":[{"finding_type":"x","evidence":[]}]}')
            self.assertEqual(
                main(
                    ["compare", str(old), str(new), "--output", str(output), "--fail-on-regression"]
                ),
                2,
            )
            from eii.adapters import PlctExportAdapter
            from eii.domain import EvidenceBundle
            from eii.evidence import write_bundle

            valid = root / "valid"
            write_bundle(
                EvidenceBundle.create(
                    (PlctExportAdapter().load(Path(__file__).parent / "fixtures/plct.json"),), ()
                ),
                valid,
            )
            self.assertEqual(main(["validate", str(valid)]), 0)
            invalid = root / "invalid"
            invalid.write_text("{}")
            with self.assertRaises(SystemExit):
                main(["validate", str(invalid)])
            with patch(
                "eii.cli_review.verify_finding_regressions",
                return_value={"still_present": 1, "resolved": 0},
            ):
                self.assertEqual(
                    main(
                        [
                            "regression-check",
                            str(old),
                            str(new),
                            "--output",
                            str(output),
                            "--fail-if-present",
                        ]
                    ),
                    2,
                )
            with self.assertRaises(SystemExit):
                main(["audit", str(root / "missing")])
            with self.assertRaises(SystemExit):
                main(["audit", str(old), str(new), "--languages", "en,sr,pt"])
            with self.assertRaises(SystemExit):
                main(["mri", str(root / "missing"), "--spec", str(old)])
            with self.assertRaises(SystemExit):
                main(
                    [
                        "safety-case",
                        str(root / "missing"),
                        "--suite",
                        str(old),
                        "--prompt-version",
                        "p",
                    ]
                )

    def test_mocked_trust_and_study_serve_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key"
            key.write_text("k")
            auth = root / "auth"
            auth.write_text("{}")
            with patch("eii.cli_appliance.initialize_trust", return_value="fingerprint"):
                self.assertEqual(
                    main(
                        ["appliance-trust-init", "--root", str(root), "--public-key-file", str(key)]
                    ),
                    0,
                )
            with patch("eii.cli_appliance.create_trust_rotation"):
                self.assertEqual(
                    main(
                        [
                            "appliance-trust-rotation-create",
                            "--current-private-key",
                            str(key),
                            "--current-public-key",
                            str(key),
                            "--new-public-key",
                            str(key),
                            "--revoke-old",
                            "--output",
                            str(auth),
                        ]
                    ),
                    0,
                )
            with patch("eii.cli_appliance.apply_trust_rotation", return_value="new"):
                self.assertEqual(
                    main(["appliance-trust-rotation-apply", str(auth), "--root", str(root)]), 0
                )
            with patch("eii.cli_review.serve_study"):
                self.assertEqual(
                    main(
                        [
                            "review-study-serve",
                            "--database",
                            str(root / "db"),
                            "--study-id",
                            "s",
                            "--port",
                            "1",
                        ]
                    ),
                    0,
                )
            audit = root / "logs" / "study.jsonl"
            with patch("eii.cli_review.serve_study") as serve_study:
                self.assertEqual(
                    main(
                        [
                            "review-study-serve",
                            "--database",
                            str(root / "db"),
                            "--study-id",
                            "s",
                            "--port",
                            "1",
                            "--audit-log",
                            str(audit),
                        ]
                    ),
                    0,
                )
                self.assertIs(serve_study.call_args.kwargs["audit_stream"].closed, True)
            with patch("eii.cli_operations.sign_release_evidence", return_value=root / "signature"):
                self.assertEqual(
                    main(
                        [
                            "release-sign",
                            str(root),
                            "--private-key-file",
                            str(key),
                            "--public-key-file",
                            str(key),
                        ]
                    ),
                    0,
                )
            with patch("eii.cli_operations.verify_signed_release"):
                self.assertEqual(
                    main(
                        [
                            "release-verify",
                            str(root),
                            "--artifacts",
                            str(root),
                            "--public-key-file",
                            str(key),
                        ]
                    ),
                    0,
                )

    def test_remaining_validation_and_optional_cli_paths(self):
        fixtures = Path(__file__).parent / "fixtures"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviews = root / "reviews"
            reviews.write_text("")
            self.assertEqual(
                main(
                    [
                        "audit",
                        str(fixtures / "course_en"),
                        str(fixtures / "course_sr"),
                        "--languages",
                        "en",
                        "--reviews",
                        str(reviews),
                        "--output",
                        str(root / "audit"),
                    ]
                ),
                0,
            )
            short = root / "short"
            short.write_text("x")
            short.chmod(0o600)
            events = root / "events"
            events.write_text('{"events":[]}')
            with self.assertRaises(SystemExit):
                main(
                    [
                        "weather",
                        str(events),
                        "--database",
                        str(root / "db"),
                        "--secret-file",
                        str(short),
                        "--ledger-key-file",
                        str(short),
                        "--database-instance-id",
                        "test-primary",
                    ]
                )
            source = root / "source"
            source.write_text("x")
            key = root / "key"
            key.write_text("0123456789abcdef0123456789abcdef")
            key.chmod(0o600)
            with self.assertRaises(SystemExit):
                main(
                    [
                        "appliance-package",
                        str(source),
                        "--version",
                        "1",
                        "--output",
                        str(root / "p"),
                        "--signing-key-file",
                        str(key),
                        "--model",
                        "m",
                    ]
                )
            with self.assertRaises(SystemExit):
                main(
                    [
                        "appliance-package",
                        str(source),
                        "--version",
                        "1",
                        "--output",
                        str(root / "p"),
                    ]
                )
            with self.assertRaises(SystemExit):
                main(["appliance-install", str(root / "p"), "--root", str(root)])
            evidence = root / "evidence"
            evidence.write_text(
                json.dumps(
                    {
                        "id": "b",
                        "findings": [
                            {
                                "id": "f",
                                "finding_type": "x",
                                "title": "t",
                                "explanation": "e",
                                "evidence": [],
                            }
                        ],
                    }
                )
            )
            seed = root / "seed"
            seed.write_text("secret")
            seed.chmod(0o600)
            credentials = root / "credentials"
            self.assertEqual(
                main(
                    [
                        "review-study-init",
                        str(evidence),
                        "--database",
                        str(root / "study.db"),
                        "--study-id",
                        "s",
                        "--reviewers",
                        "r",
                        "--seed-file",
                        str(seed),
                        "--credentials-output",
                        str(credentials),
                    ]
                ),
                0,
            )
            self.assertIn("r", json.loads(credentials.read_text()))

    def test_model_assisted_mri_safety_and_safety_package_dispatch(self):
        fixtures = Path(__file__).parent / "fixtures"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_client = SimpleNamespace()
            auditor = SimpleNamespace(
                analyze=lambda release: (), generate_support_tests=lambda release, count: ()
            )
            with (
                patch("eii.cli_learning.model_client", return_value=fake_client),
                patch("eii.cli_learning.LLMEditorialAuditor", return_value=auditor),
            ):
                self.assertEqual(
                    main(
                        [
                            "mri",
                            str(fixtures / "plct.json"),
                            "--spec",
                            str(fixtures / "curriculum.json"),
                            "--model-base-url",
                            "http://localhost",
                            "--model",
                            "m",
                            "--output",
                            str(root / "mri"),
                        ]
                    ),
                    0,
                )
            with patch("eii.cli_learning.model_client", return_value=fake_client):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            "safety-case",
                            str(fixtures / "plct.json"),
                            "--suite",
                            str(fixtures / "safety-suite.json"),
                            "--responses",
                            str(fixtures / "safety-responses.json"),
                            "--prompt-version",
                            "p",
                            "--model-base-url",
                            "http://localhost",
                            "--model",
                            "m",
                        ]
                    )
            fake_tutor = MagicMock()
            fake_case = SimpleNamespace(release_decision="configured_gates_failed")
            with (
                patch("eii.cli_learning.model_client", return_value=fake_client),
                patch("eii.cli_learning.GroundedTutor", return_value=fake_tutor),
                patch("eii.cli_learning.SafetyCaseRunner.run_with_human", return_value=fake_case),
                patch("eii.cli_learning.write_safety_case"),
            ):
                self.assertEqual(
                    main(
                        [
                            "safety-case",
                            str(fixtures / "plct.json"),
                            "--suite",
                            str(fixtures / "safety-suite.json"),
                            "--prompt-version",
                            "p",
                            "--model-base-url",
                            "http://localhost",
                            "--model",
                            "m",
                            "--output",
                            str(root / "case"),
                        ]
                    ),
                    2,
                )
            case = root / "case.json"
            case.write_text('{"release_decision":"configured_gates_passed"}')
            for command, key_option in (
                ("safety-sign", "--private-key-file"),
                ("safety-verify", "--public-key-file"),
            ):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            command,
                            str(case),
                            key_option,
                            str(root / "key"),
                            "--course",
                            str(root / "missing"),
                        ]
                    )
            with patch("eii.cli_learning.safety_trust.sign_safety_case"):
                self.assertEqual(
                    main(
                        [
                            "safety-sign",
                            str(case),
                            "--private-key-file",
                            str(root / "key"),
                            "--course",
                            str(Path(__file__).parent / "fixtures/plct.json"),
                        ]
                    ),
                    0,
                )
            with patch("eii.cli_learning.safety_trust.verify_signed_safety_case_document"):
                self.assertEqual(
                    main(
                        [
                            "safety-verify",
                            str(case),
                            "--public-key-file",
                            str(root / "key"),
                            "--course",
                            str(Path(__file__).parent / "fixtures/plct.json"),
                            "--require-passing-gates",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "safety-verify",
                            str(case),
                            "--public-key-file",
                            str(root / "key"),
                            "--course",
                            str(Path(__file__).parent / "fixtures/plct.json"),
                        ]
                    ),
                    0,
                )

            source = root / "source"
            source.write_text("x")
            key = root / "key"
            key.write_text("0123456789abcdef0123456789abcdef")
            key.chmod(0o600)
            safety = root / "safety.json"
            safety.write_text('{"id":"case"}')
            with self.assertRaises(SystemExit):
                main(
                    [
                        "appliance-package",
                        str(source),
                        "--version",
                        "1",
                        "--output",
                        str(root / "partial-model"),
                        "--private-key-file",
                        str(key),
                        "--model",
                        "m",
                    ]
                )
            with (
                patch("eii.cli_learning.safety_trust.validate_safety_case_document"),
                patch("eii.cli_learning.safety_trust.authorize_safety_case"),
                patch(
                    "eii.cli_appliance.create_package",
                    return_value=SimpleNamespace(package_id="p", version="1"),
                ),
            ):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            "appliance-package",
                            str(source),
                            "--version",
                            "1",
                            "--output",
                            str(root / "bad"),
                            "--private-key-file",
                            str(key),
                            "--safety-case",
                            str(safety),
                        ]
                    )
                self.assertEqual(
                    main(
                        [
                            "appliance-package",
                            str(source),
                            "--version",
                            "1",
                            "--output",
                            str(root / "good"),
                            "--private-key-file",
                            str(key),
                            "--model-base-url",
                            "http://localhost",
                            "--model",
                            "m",
                            "--course-path",
                            "content/source",
                            "--safety-case",
                            str(safety),
                        ]
                    ),
                    0,
                )

    def test_database_status_and_verified_backup_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ("weather", "review-study"):
                database = root / f"{kind}.db"
                backup = root / "backups" / f"{kind}.db"
                if kind == "weather":
                    WeatherStore(database, secret=b"0123456789abcdef0123456789abcdef").close()
                else:
                    ReviewStudy(database).close()
                self.assertEqual(main(["database-status", str(database), "--kind", kind]), 0)
                self.assertEqual(
                    main(
                        ["database-backup", str(database), "--kind", kind, "--output", str(backup)]
                    ),
                    0,
                )
                self.assertTrue(backup.is_file())
                self.assertEqual(main(["database-status", str(backup), "--kind", kind]), 0)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from eii.appliance import (
    _ed25519_sign,
    _ed25519_verify,
    apply_trust_rotation,
    capability_check,
    create_package,
    install_package,
    install_trusted_package,
    make_handler,
    public_key_fingerprint,
    rollback,
    serve,
    verify_package,
)

KEY = b"0123456789abcdef0123456789abcdef"


class ApplianceUpdateEdgeTests(unittest.TestCase):
    def test_capability_all_constraints_and_missing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_read = Path.read_text

            def read(path, *args, **kwargs):
                if str(path) == "/proc/meminfo":
                    return "MemTotal: 1024 kB\n"
                return original_read(path, *args, **kwargs)

            with (
                patch.object(Path, "read_text", read),
                patch("eii.appliance.shutil.disk_usage") as disk,
                patch("eii.appliance.os.cpu_count", return_value=2),
            ):
                disk.return_value.free = 1
                report = capability_check(
                    root, minimum_memory_bytes=2_000_000, minimum_disk_bytes=2
                )
            self.assertEqual(len(report.reasons), 3)
            self.assertEqual(report.model_profile, "small-local")

            def no_total(path, *args, **kwargs):
                if str(path) == "/proc/meminfo":
                    return "Other: 1 kB\n"
                return original_read(path, *args, **kwargs)

            with (
                patch.object(Path, "read_text", no_total),
                patch("eii.appliance.shutil.disk_usage") as disk,
                patch("eii.appliance.os.cpu_count", return_value=8),
            ):
                disk.return_value.free = 10**15
                report = capability_check(root, minimum_disk_bytes=1)
            self.assertTrue(report.suitable)
            self.assertIsNone(report.memory_bytes)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                create_package(
                    (root / "missing",), root / "x", version="1", private_key=TEST_PRIVATE_KEY
                )

    def test_ed25519_failure_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing"
            fake = root / "fake"
            fake.write_text("bad")
            fake.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "private key is missing"):
                _ed25519_sign(b"x", missing)
            process = MagicMock(returncode=1, stderr=b"bad", stdout=b"")
            with (
                patch("eii.crypto._probe_openssl", return_value="OpenSSL 3.0.0"),
                patch("eii.crypto.subprocess.run", return_value=process),
            ):
                with self.assertRaisesRegex(ValueError, "signing failed"):
                    _ed25519_sign(b"x", fake)
                with self.assertRaisesRegex(ValueError, "invalid Ed25519"):
                    public_key_fingerprint(fake)
            self.assertFalse(_ed25519_verify(b"x", "bad", fake))
            self.assertFalse(_ed25519_verify(b"x", "ed25519:!", fake))

    def test_each_update_metadata_gate_and_staging_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            box = root / "box"
            first_source = root / "first"
            first_source.write_text("first")
            first = root / "first.eii"
            create_package((first_source,), first, version="1", private_key=TEST_PRIVATE_KEY)
            install_package(first, box, public_key=TEST_PUBLIC_KEY)
            safety = root / "safety.json"
            safety.write_text(
                json.dumps(
                    {
                        "id": "case",
                        "prompt_version": "p",
                        "course_hash": "hash",
                        "cases": [{"response": {"model_run": {"model": "m"}}}],
                    }
                )
            )
            course = root / "course.txt"
            course.write_text("not canonical")
            base = {
                "safety_case_path": "content/safety.json",
                "safety_case_id": "case",
                "course_path": "content/course.txt",
                "model": "m",
                "prompt_version": "p",
            }
            cases = [
                (base, None, "public key"),
                ({**base, "safety_case_id": "wrong"}, root / "pub", "case id"),
                ({k: v for k, v in base.items() if k != "model"}, root / "pub", "course and model"),
                ({**base, "prompt_version": "wrong"}, root / "pub", "prompt version"),
                ({**base, "model": "wrong"}, root / "pub", "packaged model"),
                ({**base, "course_path": "../course.txt"}, root / "pub", "unsafe canonical"),
                (base, root / "pub", "cannot be loaded"),
            ]
            for index, (metadata, public, message) in enumerate(cases):
                package = root / f"u{index}.eii"
                create_package(
                    (course, safety),
                    package,
                    version=str(index + 2),
                    private_key=TEST_PRIVATE_KEY,
                    metadata=metadata,
                )
                with (
                    self.subTest(message=message),
                    patch("eii.appliance.verify_safety_case_document"),
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        install_package(
                            package, box, public_key=TEST_PUBLIC_KEY, safety_public_key=public
                        )
            self.assertFalse(
                any(path.name.startswith(".staging") for path in (box / "releases").iterdir())
            )

    def test_remaining_service_and_handler_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "activation-history.jsonl"
            history.write_text('{"previous":{"package_id":"gone","version":"1"}}\n')
            with self.assertRaisesRegex(ValueError, "files are missing"):
                rollback(root)
            with self.assertRaisesRegex(ValueError, "rate limit"):
                make_handler(root, max_queries_per_minute=0)
            with self.assertRaisesRegex(ValueError, "concurrent query limit"):
                make_handler(root, max_concurrent_queries=0)
            with (
                patch("eii.appliance.configured_tutor", return_value=(None, None)),
                patch("eii.appliance.read_config", return_value=None),
                patch("eii.appliance.HardenedThreadingHTTPServer") as server,
            ):
                instance = server.return_value.__enter__.return_value
                with (root / "audit").open("w") as audit_stream:
                    serve(root, host="127.0.0.1", port=1, audit_stream=audit_stream)
                instance.serve_forever.assert_called_once()

    def test_public_verification_activation_failure_and_trust_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "x"
            source.write_text("x")
            package = root / "p.eii"
            create_package((source,), package, version="1", private_key=TEST_PRIVATE_KEY)
            public = root / "public"
            public.write_text("bad")
            with self.assertRaisesRegex(ValueError, "signature verification"):
                verify_package(package, public_key=public)
            box = root / "box"
            real_replace = __import__("os").replace
            calls = []

            def replace(source_path, destination_path):
                calls.append(1)
                if len(calls) == 2:
                    raise OSError("pointer failure")
                return real_replace(source_path, destination_path)

            with patch("eii.appliance.os.replace", side_effect=replace):
                with self.assertRaisesRegex(OSError, "pointer failure"):
                    install_package(package, box, public_key=TEST_PUBLIC_KEY)
            self.assertFalse(
                any(path.name.startswith(".staging") for path in (box / "releases").iterdir())
            )

            trust = root / "trust"
            (trust / "keys").mkdir(parents=True)
            (trust / "state.json").write_text(json.dumps({"trusted_keys": ["old"]}))
            authorization = root / "rotation"
            authorization.write_text(
                json.dumps(
                    {
                        "statement": {
                            "old_fingerprint": "other",
                            "new_fingerprint": "new",
                            "new_public_key": "key",
                            "revoke_old": False,
                        },
                        "signature": "x",
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "currently trusted"):
                apply_trust_rotation(root, authorization)
            document = json.loads(authorization.read_text())
            document["statement"]["old_fingerprint"] = "old"
            authorization.write_text(json.dumps(document))
            (trust / "keys/old.pem").write_text("old")
            with patch("eii.appliance_trust.verify_ed25519", return_value=False):
                with self.assertRaisesRegex(ValueError, "rotation signature"):
                    apply_trust_rotation(root, authorization)
            with (
                patch("eii.appliance_trust.verify_ed25519", return_value=True),
                patch("eii.appliance_trust.public_key_fingerprint", return_value="different"),
            ):
                with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                    apply_trust_rotation(root, authorization)

    def test_trusted_package_multiple_key_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trust = root / "trust"
            (trust / "keys").mkdir(parents=True)
            (trust / "state.json").write_text(json.dumps({"trusted_keys": ["a", "b"]}))
            for key in ("a", "b"):
                (trust / f"keys/{key}.pem").write_text(key)
            manifest = MagicMock(version="1")
            with patch(
                "eii.appliance.install_package",
                side_effect=[ValueError("signature verification failed"), manifest],
            ):
                self.assertIs(install_trusted_package(root / "p", root), manifest)
            with patch("eii.appliance.install_package", side_effect=ValueError("other failure")):
                with self.assertRaisesRegex(ValueError, "other failure"):
                    install_trusted_package(root / "p", root)
            with (
                patch(
                    "eii.appliance.install_package",
                    side_effect=ValueError("signature verification failed"),
                ),
                self.assertRaisesRegex(ValueError, "currently trusted"),
            ):
                install_trusted_package(root / "p", root)


if __name__ == "__main__":
    unittest.main()

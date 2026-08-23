import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from eii.cli import main
from eii.domain import ContentBlock, CourseRelease, EvidenceBundle, SourceLocator, UnitKind
from eii.evidence import write_bundle
from eii.federation import _NoRedirect, create_envelope, submit_envelope, verify_envelope


class FederationTests(unittest.TestCase):
    def setUp(self):
        if subprocess.run(["openssl", "version"], capture_output=True).returncode:
            self.skipTest("OpenSSL unavailable")

    def test_redirect_handler_fails_closed(self):
        request = Request("https://example.org")
        with self.assertRaises(HTTPError) as raised:
            _NoRedirect().redirect_request(
                request, None, 302, "redirect", {}, "https://other.example"
            )
        raised.exception.close()

    def test_signed_envelope_round_trip_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", private], check=True
            )
            private.chmod(0o600)
            subprocess.run(
                ["openssl", "pkey", "-in", private, "-pubout", "-out", public], check=True
            )
            block = ContentBlock(
                "b", UnitKind.ACTIVITY, "Title", "Text", 0, SourceLocator("test", "repo", "p")
            )
            release = CourseRelease(
                "r", "c", "en", "1", "Course", (block,), SourceLocator("test", "repo", ".")
            )
            bundle = EvidenceBundle.create((release,), ())
            bundle_path = root / "bundle.json"
            write_bundle(bundle, bundle_path)
            envelope_path = root / "envelope.json"
            envelope = create_envelope(
                bundle_path,
                envelope_path,
                private_key=private,
                public_key=public,
                provider_id="0f4ff1d8-5972-44cc-8d0b-2f59f40fa793",
            )
            self.assertEqual(verify_envelope(envelope_path, public)["bundle"]["id"], bundle.id)
            envelope["bundle"]["tool_version"] = "tampered"
            envelope_path.write_text(json.dumps(envelope))
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_envelope(envelope_path, public)

    def test_envelope_rejects_shape_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", private], check=True
            )
            private.chmod(0o600)
            subprocess.run(
                ["openssl", "pkey", "-in", private, "-pubout", "-out", public], check=True
            )
            malformed = root / "malformed.json"
            malformed.write_text("[]")
            with self.assertRaisesRegex(ValueError, "fields"):
                verify_envelope(malformed, public)
            malformed.write_text(
                json.dumps(
                    {"bundle": {}, "signature": "ed25519:x", "signing_key_fingerprint": "wrong"}
                )
            )
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                verify_envelope(malformed, public)

    def test_submission_requires_https_and_token(self):
        path = Path("envelope.json")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            submit_envelope(path, "http://example.org/ingest", token="secret", institution_id="i")
        with self.assertRaisesRegex(ValueError, "empty"):
            submit_envelope(path, "https://example.org/ingest", token=" ", institution_id="i")

    def test_submission_success_empty_oversize_non_object_and_transport_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "envelope.json"
            path.write_text(json.dumps({"provider_id": "p"}))

            class Response:
                status = 201

                def __init__(self, body):
                    self.body = body

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def read(self, _):
                    return self.body

            opener = MagicMock()
            opener.open.return_value = Response(b'{"ok":true}')
            with patch("eii.federation.build_opener", return_value=opener):
                self.assertEqual(
                    submit_envelope(path, "https://example.org/e", token="t", institution_id="i"),
                    (201, {"ok": True}),
                )
            opener.open.return_value = Response(b"")
            with patch("eii.federation.build_opener", return_value=opener):
                self.assertEqual(
                    submit_envelope(path, "https://example.org/e", token="t", institution_id="i")[
                        1
                    ],
                    {},
                )
            opener.open.return_value = Response(b"x" * 1_000_001)
            with patch("eii.federation.build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "size limit"):
                    submit_envelope(path, "https://example.org/e", token="t", institution_id="i")
            opener.open.return_value = Response(b"[]")
            with patch("eii.federation.build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    submit_envelope(path, "https://example.org/e", token="t", institution_id="i")
            opener.open.side_effect = URLError("offline")
            with patch("eii.federation.build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "submission failed"):
                    submit_envelope(path, "https://example.org/e", token="t", institution_id="i")
            opener.open.side_effect = HTTPError(
                "https://example.org/e", 503, "unavailable", {}, None
            )
            with patch("eii.federation.build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "submission failed"):
                    submit_envelope(path, "https://example.org/e", token="t", institution_id="i")
            path.write_text("[]")
            with self.assertRaisesRegex(ValueError, "institution and provider"):
                submit_envelope(path, "https://example.org/e", token="t", institution_id="i")
            path.write_text(json.dumps({"provider_id": "p"}))
            with self.assertRaisesRegex(ValueError, "institution and provider"):
                submit_envelope(path, "https://example.org/e", token="t", institution_id="")

    def test_federation_cli_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "token"
            token.write_text("secret")
            token.chmod(0o600)
            with patch("eii.cli.create_envelope") as create:
                self.assertEqual(
                    main(
                        [
                            "federation-envelope",
                            "bundle.json",
                            "--private-key-file",
                            "private.pem",
                            "--public-key-file",
                            "public.pem",
                            "--output",
                            "envelope.json",
                        ]
                    ),
                    0,
                )
                create.assert_called_once()
            with patch("eii.cli.verify_envelope") as verify:
                self.assertEqual(
                    main(["federation-verify", "envelope.json", "--public-key-file", "public.pem"]),
                    0,
                )
                verify.assert_called_once()
            with patch("eii.cli.submit_envelope", return_value=(201, {"ok": True})) as submit:
                self.assertEqual(
                    main(
                        [
                            "federation-submit",
                            "envelope.json",
                            "--endpoint",
                            "https://example.org/e",
                            "--token-file",
                            str(token),
                            "--institution-id",
                            "i",
                        ]
                    ),
                    0,
                )
                submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()

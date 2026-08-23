import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, generate_keypair

from eii.adapters import PlctExportAdapter
from eii.appliance import (
    ApplianceConfig,
    active_release,
    apply_trust_rotation,
    configure,
    create_package,
    create_trust_rotation,
    initialize_trust,
    install_package,
    install_trusted_package,
    public_key_fingerprint,
    read_config,
    recover_active_release,
    rollback,
    verify_package,
)
from eii.cli import main
from eii.domain import ModelRun, content_hash
from eii.safety import (
    AssistantResponse,
    ReleaseGate,
    ReplayAssistant,
    RetrievedEvidence,
    SafetyCaseRunner,
    SafetyFixture,
    write_safety_case,
)
from eii.safety_verification import sign_safety_case

FIXTURES = Path(__file__).parent / "fixtures"


def signed_safety_case(root: Path, course_path: Path, *, model: str = "fixture"):
    course = PlctExportAdapter().load(course_path)
    block = course.blocks[0]
    answer = block.text
    request = {"question": "Q"}
    run = ModelRun(
        "local",
        model,
        "p1",
        {"request_payload": request},
        content_hash(request),
        content_hash(answer),
    )
    response = AssistantResponse(
        answer, (block.id,), (RetrievedEvidence(block.id, block.hash, block.text),), run
    )
    fixture = SafetyFixture(
        "grounded", "groundedness", "Q", course.language, block.id, {"citations_required": True}
    )
    case = SafetyCaseRunner().run(
        course,
        ReplayAssistant({"Q": response}),
        (fixture,),
        (ReleaseGate("groundedness", 1),),
        dataset_version="1",
        prompt_version="p1",
    )
    private, public = root / "evaluator-private.pem", root / "evaluator-public.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    path = root / "safety.json"
    write_safety_case(case, path)
    sign_safety_case(path, private, course=course)
    return path, public, case


class ApplianceTests(unittest.TestCase):
    def test_signed_package_installs_and_activates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "site"
            content.mkdir()
            (content / "index.html").write_text("offline course")
            package = root / "release.eii"
            manifest = create_package(
                (content,), package, version="1", private_key=TEST_PRIVATE_KEY
            )
            self.assertEqual(
                verify_package(package, public_key=TEST_PUBLIC_KEY).package_id,
                manifest.package_id,
            )
            install_package(package, root / "appliance", public_key=TEST_PUBLIC_KEY)
            self.assertEqual(
                (active_release(root / "appliance") / "content/site/index.html").read_text(),
                "offline course",
            )

    def test_rejects_wrong_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "course.txt"
            source.write_text("course")
            package = root / "release.eii"
            create_package((source,), package, version="1", private_key=TEST_PRIVATE_KEY)
            _, wrong_public = generate_keypair(root, "wrong")
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_package(package, public_key=wrong_public)

    def test_cli_packages_and_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "site"
            source.mkdir()
            (source / "index.html").write_text("classroom")
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                check=True,
                capture_output=True,
            )
            package = root / "school.eii"
            self.assertEqual(
                main(
                    [
                        "appliance-package",
                        str(source),
                        "--version",
                        "1",
                        "--private-key-file",
                        str(private),
                        "--output",
                        str(package),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "appliance-install",
                        str(package),
                        "--root",
                        str(root / "box"),
                        "--public-key-file",
                        str(public),
                    ]
                ),
                0,
            )
            self.assertTrue((active_release(root / "box") / "content/site/index.html").exists())

    def test_update_requires_approved_safety_case_and_can_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plct.json"
            source.write_text((FIXTURES / "plct.json").read_text())
            box = root / "box"
            first = root / "first.eii"
            create_package((source,), first, version="1", private_key=TEST_PRIVATE_KEY)
            first_manifest = install_package(first, box, public_key=TEST_PUBLIC_KEY)
            changed = json.loads(source.read_text())
            changed["version"] = "3"
            changed["activities"][0]["text"] += " Novi primer."
            source.write_text(json.dumps(changed))
            unsafe = root / "unsafe.eii"
            create_package((source,), unsafe, version="2", private_key=TEST_PRIVATE_KEY)
            with self.assertRaisesRegex(ValueError, "safety case"):
                install_package(unsafe, box, public_key=TEST_PUBLIC_KEY)
            safety, evaluator_public, case = signed_safety_case(root, source)
            evaluated_source = source.read_text()
            tampered = json.loads(evaluated_source)
            tampered["activities"][0]["text"] = "Unevaluated replacement"
            source.write_text(json.dumps(tampered))
            mismatched = root / "mismatched.eii"
            binding_metadata = {
                "safety_case_path": "content/safety.json",
                "safety_case_id": case.id,
                "course_path": "content/plct.json",
                "model": "fixture",
                "prompt_version": "p1",
            }
            create_package(
                (source, safety),
                mismatched,
                version="2-bad",
                private_key=TEST_PRIVATE_KEY,
                metadata=binding_metadata,
            )
            with self.assertRaisesRegex(ValueError, "course hash"):
                install_package(
                    mismatched, box, public_key=TEST_PUBLIC_KEY, safety_public_key=evaluator_public
                )
            source.write_text(evaluated_source)
            update = root / "update.eii"
            create_package(
                (source, safety),
                update,
                version="2",
                private_key=TEST_PRIVATE_KEY,
                metadata=binding_metadata,
            )
            second = install_package(
                update, box, public_key=TEST_PUBLIC_KEY, safety_public_key=evaluator_public
            )
            self.assertEqual(active_release(box).name, second.package_id)
            target = rollback(box)
            self.assertEqual(target["package_id"], first_manifest.package_id)
            self.assertEqual(active_release(box).name, first_manifest.package_id)

    def test_teacher_configuration_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = ApplianceConfig(("loops",), ("sr", "en"), "socratic")
            configure(root, expected)
            self.assertEqual(read_config(root), expected)

    def test_recovers_deleted_active_pointer_from_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "course.txt"
            source.write_text("recoverable")
            package = root / "release.eii"
            box = root / "box"
            manifest = create_package((source,), package, version="1", private_key=TEST_PRIVATE_KEY)
            install_package(package, box, public_key=TEST_PUBLIC_KEY)
            (box / "active.json").unlink()
            recovered = recover_active_release(box)
            self.assertEqual(recovered["package_id"], manifest.package_id)
            self.assertEqual(active_release(box).name, manifest.package_id)

    @unittest.skipUnless(
        shutil.which("openssl"), "OpenSSL required for Ed25519 package verification"
    )
    def test_ed25519_publisher_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "course.txt"
            source.write_text("public release")
            private = root / "private.pem"
            public = root / "public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                check=True,
                capture_output=True,
            )
            package = root / "public.eii"
            create_package((source,), package, version="1", private_key=private)
            manifest = verify_package(package, public_key=public)
            self.assertEqual(manifest.version, "1")

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for trust rotation")
    def test_signed_trust_rotation_authorizes_new_publisher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            box = root / "box"
            source = root / "plct.json"
            source.write_text((FIXTURES / "plct.json").read_text())

            def keypair(name):
                private, public = root / f"{name}-private.pem", root / f"{name}-public.pem"
                subprocess.run(
                    ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                    check=True,
                    capture_output=True,
                )
                return private, public

            old_private, old_public = keypair("old")
            new_private, new_public = keypair("new")
            initialize_trust(box, old_public)
            first = root / "first.eii"
            create_package((source,), first, version="1", private_key=old_private)
            install_trusted_package(first, box)
            authorization = root / "rotation.json"
            create_trust_rotation(
                old_private, old_public, new_public, authorization, revoke_old=True
            )
            new_fingerprint = apply_trust_rotation(box, authorization)
            changed = json.loads(source.read_text())
            changed["version"] = "3"
            changed["activities"][0]["text"] += " Novi primer."
            source.write_text(json.dumps(changed))
            safety, evaluator_public, case = signed_safety_case(root, source)
            second = root / "second.eii"
            create_package(
                (source, safety),
                second,
                version="2",
                private_key=new_private,
                metadata={
                    "safety_case_path": "content/safety.json",
                    "safety_case_id": case.id,
                    "course_path": "content/plct.json",
                    "model": "fixture",
                    "prompt_version": "p1",
                },
            )
            manifest = install_trusted_package(second, box, safety_public_key=evaluator_public)
            self.assertEqual(manifest.version, "2")
            state = (box / "trust/state.json").read_text()
            self.assertIn(new_fingerprint, state)
            self.assertNotIn(public_key_fingerprint(old_public), state)


if __name__ == "__main__":
    unittest.main()

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.adapters import PlctExportAdapter
from eii.domain import ModelRun, content_hash, to_dict
from eii.safety import (
    AssistantResponse,
    AssistantUnderTest,
    ReleaseGate,
    ReplayAssistant,
    RetrievedEvidence,
    SafetyCaseRunner,
    SafetyEvaluator,
    SafetyFixture,
    compare_safety_cases,
    load_human_evaluations,
)
from eii.safety_reviews import sign_human_review
from eii.safety_verification import (
    _sign_ed25519,
    _verify_ed25519,
    authorize_safety_case,
    safety_case_payload,
    validate_safety_case_document,
    verify_safety_case_document,
)

FIXTURES = Path(__file__).parent / "fixtures"


class SafetyDefensiveTests(unittest.TestCase):
    def test_protocol_default_is_explicitly_non_executable(self):
        with self.assertRaises(NotImplementedError):
            AssistantUnderTest.answer(
                None, "q", course=self.course, activity_id=None, language="en"
            )

    def setUp(self):
        self.course = PlctExportAdapter().load(FIXTURES / "plct.json")
        self.block = self.course.blocks[0]

    def response(self, answer="safe hint", citations=(), retrieved=()):
        request = {"fixture": "defensive"}
        return AssistantResponse(
            answer,
            citations,
            retrieved,
            ModelRun(
                "p",
                "m",
                "v",
                {"request_payload": request},
                content_hash(request),
                content_hash(answer),
            ),
        )

    def signed_review(
        self,
        root: Path,
        *,
        created_at="2026-01-01T00:00:00+00:00",
        subject_hash=None,
    ):
        private, public = root / "review-private.pem", root / "review-public.pem"
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
        return sign_human_review(
            fixture_id="f",
            subject_hash=subject_hash or content_hash({"test": "subject"}),
            reviewer="reviewer",
            approved=True,
            rationale="reviewed",
            created_at=created_at,
            private_key=private,
            public_key=public,
        )

    def approved(self):
        response = self.response(
            "safe",
            (self.block.id,),
            (RetrievedEvidence(self.block.id, self.block.hash, self.block.text),),
        )
        case = SafetyCaseRunner().run(
            self.course,
            ReplayAssistant({"q": response}),
            (SafetyFixture("f", "claim", "q", "en", None, {"citations_required": True}),),
            (ReleaseGate("claim", 1),),
            dataset_version="1",
            prompt_version="v",
        )
        return to_dict(case)

    @staticmethod
    def redigest(document):
        document["manifest_digest"] = content_hash(safety_case_payload(document))
        document["id"] = content_hash({"manifest": document["manifest_digest"]})

    def test_replay_missing_and_every_automatic_property(self):
        with self.assertRaisesRegex(ValueError, "no replay"):
            ReplayAssistant({}).answer("missing")
        props = {
            "citations_required": True,
            "expected_citation_ids": ["b"],
            "refuse_without_evidence": True,
            "forbidden_phrases": ["bad"],
            "hint_only": True,
            "complete_solution": "full solution",
            "max_sentence_words": 2,
            "required_phrases": ["needed"],
            "must_refuse": True,
            "must_not_request_personal_data": True,
            "prompt_injection_canary": "canary",
            "stereotype_terms": ["inferior"],
        }
        results = SafetyEvaluator().evaluate(
            SafetyFixture("f", "c", "q", "en", None, props),
            self.response("bad full solution email canary inferior"),
        )
        self.assertEqual(len(results), 11)
        self.assertTrue(all(not x.passed for x in results))
        fallback = SafetyEvaluator().evaluate(
            SafetyFixture("f", "c", "q", "en", None, {}), self.response()
        )
        self.assertEqual(fallback[0].evaluator, "fixture_validity")

    def test_runner_human_gate_missing_present_and_no_gate(self):
        fixture = SafetyFixture(
            "f", "c", "q", "en", None, {"required_phrases": ["safe"], "human_review_required": True}
        )
        assistant = ReplayAssistant({"q": self.response("safe")})
        rejected = SafetyCaseRunner().run_with_human(
            self.course,
            assistant,
            (fixture,),
            (ReleaseGate("c", 1),),
            dataset_version="1",
            prompt_version="v",
        )
        self.assertFalse(rejected.gate_results["human:f"])
        with tempfile.TemporaryDirectory() as directory:
            human = self.signed_review(
                Path(directory), subject_hash=content_hash(to_dict(rejected.cases[0]))
            )
            approved = SafetyCaseRunner().run_with_human(
                self.course,
                assistant,
                (fixture,),
                (ReleaseGate("c", 1),),
                dataset_version="1",
                prompt_version="v",
                human_evaluations=(human,),
            )
        self.assertEqual(approved.release_decision, "configured_gates_passed")
        with self.assertRaisesRegex(ValueError, "at least one fixture"):
            SafetyCaseRunner().run(
                self.course, assistant, (), (), dataset_version="1", prompt_version="v"
            )

    def test_verifier_rejects_each_integrity_layer(self):
        mutations = [
            (lambda d: d.update(manifest_digest="bad"), "manifest digest"),
            (lambda d: d.update(id="bad"), "case id"),
            (lambda d: d.update(cases=[]), "cases and release gates"),
            (lambda d: d.update(gate_results={}), "gate results"),
            (lambda d: d["gates"][0].update(minimum_cases=0), "minimum cases"),
            (lambda d: d.update(course_hash="bad"), "course identity"),
            (
                lambda d: d["cases"][0]["response"]["model_run"].update(output_hash="bad"),
                "output hash",
            ),
            (
                lambda d: d["cases"][0]["response"]["model_run"].update(configuration={}),
                "replayable request",
            ),
            (
                lambda d: d["cases"][0]["response"]["model_run"].update(input_hash="bad"),
                "input hash",
            ),
            (
                lambda d: d["cases"][0]["response"].update(model_run=[]),
                "model run must be an object",
            ),
            (lambda d: d["cases"][0].update(evaluations=None), "lacks evaluation"),
            (
                lambda d: d["cases"][0]["evaluations"].append(
                    copy.deepcopy(d["cases"][0]["evaluations"][-1])
                ),
                "one retrieval",
            ),
            (lambda d: d["cases"][0].update(passed=False), "case result"),
            (lambda d: d["gates"].append(copy.deepcopy(d["gates"][0])), "unique"),
            (lambda d: d["gates"][0].update(required_pass_rate="x"), "invalid required"),
            (lambda d: d["gates"][0].update(required_pass_rate=2), "between zero"),
            (lambda d: d["gates"][0].update(claim="other"), "no fixtures"),
            (lambda d: d.update(release_decision="configured_gates_failed"), "release decision"),
        ]
        for mutate, message in mutations:
            document = self.approved()
            mutate(document)
            if document.get("manifest_digest") != "bad":
                self.redigest(document)
                if message == "case id":
                    document["id"] = "bad"
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_safety_case_document(document, course=self.course)

    def test_rejected_approval_and_signature_format_failures(self):
        document = self.approved()
        document["cases"][0]["response"]["citations"] = []
        document["cases"][0]["evaluations"][0]["passed"] = False
        document["cases"][0]["evaluations"][0]["evidence"]["citations"] = []
        document["cases"][0]["passed"] = False
        document["gate_results"]["claim"] = False
        document["release_decision"] = "configured_gates_failed"
        self.redigest(document)
        with self.assertRaisesRegex(ValueError, "did not pass"):
            validate_safety_case_document(document)
            authorize_safety_case(document)
        self.assertFalse(_verify_ed25519(b"x", "bad", Path("missing")))
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("x")
            self.assertFalse(_verify_ed25519(b"x", "ed25519:!", key))
            with patch("eii.crypto.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stdout = b""
                with self.assertRaisesRegex(ValueError, "signing failed"):
                    _sign_ed25519(b"x", key)

    def test_validation_rejects_evaluator_time_identity_and_review_tampering(self):
        mutations = (
            (lambda d: d.update(extra=True), "fields do not match"),
            (lambda d: d.update(created_at="invalid"), "creation time is invalid"),
            (lambda d: d.update(created_at="2026-01-01T00:00:00"), "include a timezone"),
            (lambda d: d.update(evaluator_id="substituted"), "evaluator identity"),
            (
                lambda d: d["cases"][0]["response"]["model_run"].update(prompt_version="different"),
                "prompt version differs",
            ),
            (lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])), "fixture ids"),
            (lambda d: d.update(human_evaluations={}), "must be an array"),
        )
        for mutate, message in mutations:
            document = self.approved()
            mutate(document)
            self.redigest(document)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_safety_case_document(document)

        for created_at, message in (("invalid", "time is invalid"), ("2026-01-01", "timezone")):
            document = self.approved()
            document["human_evaluations"] = [
                {
                    "fixture_id": "f",
                    "subject_hash": content_hash({"test": "subject"}),
                    "reviewer": "reviewer",
                    "approved": True,
                    "rationale": "reviewed",
                    "created_at": created_at,
                    "reviewer_public_key": "x" * 64,
                    "reviewer_key_fingerprint": "0" * 64,
                    "signature": "ed25519:AAAA",
                }
            ]
            self.redigest(document)
            with self.subTest(created_at=created_at), self.assertRaisesRegex(ValueError, message):
                validate_safety_case_document(document)

        with tempfile.TemporaryDirectory() as directory:
            document = self.approved()
            review = to_dict(self.signed_review(Path(directory)))
            document["human_evaluations"] = [review]
            self.redigest(document)
            validate_safety_case_document(document)
            review["reviewer"] = ""
            self.redigest(document)
            with self.assertRaisesRegex(ValueError, "unique fixture"):
                validate_safety_case_document(document)

    def test_serialization_human_and_signature_edge_failures(self):
        document = self.approved()
        del document["cases"][0]["response"]["model_run"]["provider"]
        self.redigest(document)
        with self.assertRaisesRegex(ValueError, "invalid serialized"):
            validate_safety_case_document(document)
        document = self.approved()
        extra = copy.deepcopy(document["cases"][0])
        extra["fixture"]["id"] = "f-other"
        extra["fixture"]["claim"] = "other"
        document["cases"].append(extra)
        self.redigest(document)
        with self.assertRaisesRegex(ValueError, "every fixture claim"):
            validate_safety_case_document(document)
        document = self.approved()
        document["human_evaluations"] = [
            {"fixture_id": "f", "approved": True},
            {"fixture_id": "f", "approved": True},
        ]
        self.redigest(document)
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            validate_safety_case_document(document)
        document = self.approved()
        document["cases"][0]["fixture"]["properties"]["human_review_required"] = True
        document["gate_results"]["human:f"] = False
        document["release_decision"] = "configured_gates_failed"
        self.redigest(document)
        with self.assertRaisesRegex(ValueError, "did not pass"):
            validate_safety_case_document(document)
            authorize_safety_case(document)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public"
            public.write_text("x")
            document = self.approved()
            with patch("eii.safety_verification._verify_ed25519", return_value=False):
                with self.assertRaisesRegex(ValueError, "signature verification"):
                    verify_safety_case_document(document, public_key=public)
            reviews = root / "reviews.json"
            reviews.write_text(json.dumps({"reviews": [to_dict(self.signed_review(root))]}))
            self.assertTrue(load_human_evaluations(reviews)[0].approved)

    def test_safety_case_comparison_all_change_categories(self):
        previous = SafetyCaseRunner().run(
            self.course,
            ReplayAssistant({"q": self.response("bad")}),
            (SafetyFixture("f", "c", "q", "en", None, {"required_phrases": ["safe"]}),),
            (ReleaseGate("c", 1),),
            dataset_version="1",
            prompt_version="v",
        )
        current = SafetyCaseRunner().run(
            self.course,
            ReplayAssistant({"q": self.response("safe")}),
            (SafetyFixture("f", "c", "q", "en", None, {"required_phrases": ["safe"]}),),
            (ReleaseGate("c", 1),),
            dataset_version="1",
            prompt_version="v",
        )
        result = compare_safety_cases(previous, current)
        self.assertEqual(result["improvements"], ["f"])
        self.assertTrue(result["decision_changed"])


if __name__ == "__main__":
    unittest.main()

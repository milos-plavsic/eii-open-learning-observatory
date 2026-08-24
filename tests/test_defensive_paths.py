import copy
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from eii.adapters.plct import PlctExportAdapter
from eii.adapters.repository import RepositoryAdapter, _slug
from eii.babelbridge import Alignment
from eii.compare import compare_files
from eii.curriculum import Assessment, CurriculumMRI, CurriculumSpec, Objective
from eii.domain import (
    ContentBlock,
    CourseRelease,
    EvidenceBundle,
    Finding,
    FindingStatus,
    ReviewDecision,
    Severity,
    SourceLocator,
    UnitKind,
    canonical_json,
    to_dict,
)
from eii.editorial import LLMEditorialAuditor
from eii.models import OpenAICompatibleClient, _http_transport
from eii.models import _NoRedirect as ModelNoRedirect
from eii.report import write_html
from eii.reviews import append_review, read_reviews
from eii.semantics import LLMSemanticComparator, SemanticComparator
from eii.tutor import BilingualGroundedTutor, _parse_citations, retrieve
from eii.weather import MinimizedEvent, Signal, WeatherStore, load_events

FIXTURES = Path(__file__).parent / "fixtures"


def release(text="loops repeat", *, language="en", block_id="b", order=1):
    locator = SourceLocator("test", "repo", "lesson.md")
    block = ContentBlock(
        block_id, UnitKind.SECTION, "Loops", text, order, locator, concepts=("loop",)
    )
    return CourseRelease(
        f"r-{language}", "c", language, "1", "Course", (block,), locator, canonical_course_id="c"
    )


def client_response(value):
    return OpenAICompatibleClient(
        "http://localhost/v1",
        "m",
        transport=lambda *args: {
            "choices": [
                {"message": {"content": value if isinstance(value, str) else json.dumps(value)}}
            ]
        },
    )


class AdapterDefensiveTests(unittest.TestCase):
    def test_can_load_rejections_and_repository_edge_shapes(self):
        adapter = PlctExportAdapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(adapter.can_load(root))
            bad = root / "bad.json"
            bad.write_text("{")
            self.assertFalse(adapter.can_load(bad))
            scalar = root / "scalar.json"
            scalar.write_text("[]")
            self.assertFalse(adapter.can_load(scalar))
            self.assertFalse(RepositoryAdapter().can_load(root))
            hidden = root / ".hidden"
            hidden.mkdir()
            (hidden / "x.md").write_text("hidden")
            self.assertTrue(RepositoryAdapter().can_load(root))
            with self.assertRaisesRegex(ValueError, "language"):
                RepositoryAdapter().load(root)
            (root / "visible.md").write_text("preamble\n# Same\na\n## Child\nb\n# Same\nc")
            loaded = RepositoryAdapter().load(root, language="sr")
            self.assertEqual(
                [b.locator.anchor for b in loaded.blocks], ["visible", "same", "child", "same-2"]
            )
            self.assertEqual(_slug("!!!"), "section")

    def test_repository_empty_and_headingless(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "empty.md").write_text("")
            with self.assertRaisesRegex(ValueError, "no Markdown"):
                RepositoryAdapter().load(root, language="en")
            (root / "empty.md").write_text("plain body")
            self.assertEqual(RepositoryAdapter().load(root, language="en").blocks[0].title, "empty")

    def test_every_plct_validation_boundary(self):
        base = json.loads((FIXTURES / "plct.json").read_text())
        mutations = [
            ({k: v for k, v in base.items() if k != "version"}, "missing"),
            ({**base, "activities": {}}, "non-empty"),
            ({**base, "course_key": []}, "scalar"),
            ({**base, "activities": ["x"]}, "activity 0"),
            ({**base, "activities": [{"activity_key": ""}]}, "unique"),
            ({**base, "activities": [{"activity_key": "a", "metadata": []}]}, "metadata"),
            ({**base, "activities": [{"activity_key": "a", "chunks": {}}]}, "chunks"),
            ({**base, "activities": [{"activity_key": "a", "chunks": [{}]}]}, "requires"),
            (
                {**base, "activities": [{"activity_key": "a", "chunks": [{"chunk_key": ""}]}]},
                "unique",
            ),
            (
                {
                    **base,
                    "activities": [
                        {"activity_key": "a", "chunks": [{"chunk_key": "x"}, {"chunk_key": "x"}]}
                    ],
                },
                "unique",
            ),
            (
                {
                    **base,
                    "activities": [
                        {"activity_key": "a", "chunks": [{"chunk_key": "x", "metadata": []}]}
                    ],
                },
                "metadata",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            for data, message in mutations:
                with self.subTest(message=message, data=data):
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, message):
                        PlctExportAdapter().load(path)


class DomainAndReviewTests(unittest.TestCase):
    def test_domain_rejects_empty_and_tampered_values(self):
        loc = SourceLocator("a", "r", "p")
        with self.assertRaisesRegex(ValueError, "requires"):
            ContentBlock("", UnitKind.SECTION, "t", "x", 0, loc)
        block = release().blocks[0]
        with self.assertRaisesRegex(ValueError, "requires language"):
            CourseRelease("r", "c", "", "1", "t", (block,), loc)
        with self.assertRaisesRegex(ValueError, "release hash"):
            CourseRelease("r", "c", "en", "1", "t", (block,), loc, hash="bad")
        with self.assertRaisesRegex(ValueError, "confidence"):
            Finding("f", "x", "t", "e", Severity.LOW, 1.01, ())
        self.assertEqual(canonical_json(UnitKind.SECTION), '"section"')
        self.assertIn('"adapter":"a"', canonical_json(loc))
        self.assertEqual(to_dict({1: (UnitKind.SECTION,)}), {"1": ["section"]})

    def test_all_review_validation_and_round_trip(self):
        base = {"finding_id": "f", "reviewer": "r", "rationale": "why", "created_at": "now"}
        invalid = [
            ReviewDecision(decision=FindingStatus.PROPOSED, **base),
            ReviewDecision(decision=FindingStatus.CONFIRMED, evidence_quality="maybe", **base),
            ReviewDecision(decision=FindingStatus.CONFIRMED, severity_assessment="huge", **base),
            ReviewDecision(decision=FindingStatus.CONFIRMED, usefulness=0, **base),
            ReviewDecision(decision=FindingStatus.CONFIRMED, actionability="later", **base),
            ReviewDecision(decision=FindingStatus.CONFIRMED, seconds_spent=-1, **base),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "reviews.jsonl"
            self.assertEqual(read_reviews(path), ())
            for item in invalid:
                with self.assertRaises(ValueError):
                    append_review(path, item)
            valid = ReviewDecision(
                decision=FindingStatus.RESOLVED,
                evidence_quality="sufficient",
                severity_assessment="low",
                usefulness=5,
                actionability="usable",
                seconds_spent=0,
                **base,
            )
            append_review(path, valid)
            self.assertEqual(read_reviews(path), (valid,))


class ModelEditorialSemanticTests(unittest.TestCase):
    def test_semantic_protocol_default_is_explicitly_non_executable(self):
        course = release()
        block = course.blocks[0]
        with self.assertRaises(NotImplementedError):
            SemanticComparator.compare(None, block, block, left_language="en", right_language="en")

    def test_model_configuration_response_and_retry_failures(self):
        for kwargs in (
            {"model": ""},
            {"model": "m", "timeout": 0},
            {"model": "m", "retries": -1},
            {"model": "m", "retries": 11},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                OpenAICompatibleClient("http://localhost", **kwargs)
        for endpoint in (
            "http://example.org",
            "https://user:password@example.org",
            "https://example.org?query=1",
            "https://example.org#fragment",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                OpenAICompatibleClient(endpoint, "m")
        with self.assertRaisesRegex(ValueError, "revision"):
            OpenAICompatibleClient("https://example.org", "m", model_revision=" ")
        with self.assertRaises(HTTPError) as raised:
            ModelNoRedirect().redirect_request(
                unittest.mock.MagicMock(full_url="https://example.org"),
                None,
                302,
                "redirect",
                {},
                "https://other.example",
            )
        raised.exception.close()
        calls = []
        messages = [{"role": "user", "content": "question"}]

        def failing(*args):
            calls.append(1)
            raise OSError("down")

        with patch("eii.models.time.sleep") as sleep:
            with self.assertRaises(OSError):
                OpenAICompatibleClient("http://localhost", "m", transport=failing, retries=2).chat(
                    messages, prompt_version="p"
                )
            self.assertEqual(sleep.call_count, 2)
        transient_calls = []

        def transient(*args):
            transient_calls.append(1)
            if len(transient_calls) == 1:
                raise HTTPError("https://example.org", 503, "busy", {}, None)
            return {"choices": [{"message": {"content": "ok"}}]}

        with patch("eii.models.time.sleep"):
            result = OpenAICompatibleClient(
                "https://example.org", "m", transport=transient, retries=1
            ).chat(messages, prompt_version="p")
        self.assertEqual(result.text, "ok")
        with self.assertRaises(HTTPError):
            OpenAICompatibleClient(
                "https://example.org",
                "m",
                transport=lambda *args: (_ for _ in ()).throw(
                    HTTPError("https://example.org", 400, "bad", {}, None)
                ),
            ).chat(messages, prompt_version="p")
        for response in (
            {},
            {"choices": []},
            {"choices": [{"message": {}}]},
            {"choices": [{"message": {"content": 3}}]},
            {"choices": [{"message": {"content": "ok"}}], "usage": []},
            {"choices": [{"message": {"content": "ok"}}], "cost": -1},
            {"choices": [{"message": {"content": "ok"}}], "cost": True},
            {"choices": [{"message": {"content": "ok"}}], "model": ""},
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                OpenAICompatibleClient(
                    "http://localhost", "m", transport=lambda *a, r=response: r
                ).chat(messages, prompt_version="p")
        captured = {}
        keyed = OpenAICompatibleClient(
            "http://localhost/",
            "m",
            api_key="secret",
            transport=lambda u, b, h, t: (
                captured.update(headers=h)
                or {"choices": [{"message": {"content": "ok"}}], "cost": 0.1}
            ),
        )
        self.assertEqual(
            keyed.chat(
                messages, prompt_version="p", response_format={"type": "json"}
            ).model_run.cost,
            0.1,
        )
        self.assertIn("Authorization", captured["headers"])
        configuration = keyed.chat(messages, prompt_version="p").model_run.configuration
        identified = OpenAICompatibleClient(
            "https://example.org",
            "m",
            transport=lambda *args: {
                "id": "request-secret",
                "model": "m-2026",
                "system_fingerprint": "fp-1",
                "choices": [{"message": {"content": "ok"}}],
            },
        ).chat(messages, prompt_version="p")
        self.assertEqual(
            identified.model_run.configuration["effective_model_revision"], "m-2026@fp-1"
        )
        self.assertNotIn("request-secret", str(identified.model_run.configuration))
        for invalid_messages, prompt, temperature in (
            ([], "p", 0),
            ([{"role": "invalid", "content": "x"}], "p", 0),
            (messages, "", 0),
            (messages, "p", float("inf")),
        ):
            with self.assertRaises(ValueError):
                keyed.chat(invalid_messages, prompt_version=prompt, temperature=temperature)
        self.assertNotIn("base_url", configuration)
        self.assertIn("endpoint_hash", configuration)
        self.assertIn("response_envelope_hash", configuration)

    def test_http_transport_bounds_and_json(self):
        class Response:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, size):
                value, self.value = self.value, b""
                return value

        opener = unittest.mock.MagicMock()
        opener.open.return_value = Response(b"{}")
        with patch("eii.models.build_opener", return_value=opener):
            self.assertEqual(_http_transport("http://x", b"{}", {}, 1), {})
        socket_response = Response(b"{}")
        socket_response.fp = unittest.mock.MagicMock()
        socket_response.fp.raw._sock = unittest.mock.MagicMock()
        opener.open.return_value = socket_response
        with patch("eii.models.build_opener", return_value=opener):
            self.assertEqual(_http_transport("http://x", b"{}", {}, 1), {})
            socket_response.fp.raw._sock.settimeout.assert_called()
        opener.open.return_value = Response(b"x" * 4_194_305)
        with patch("eii.models.build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "4 MiB"):
                _http_transport("http://x", b"{}", {}, 1)

    def test_editorial_rejects_every_untrusted_output_shape(self):
        course = release()
        invalid = [
            "{",
            {},
            {"findings": [{"kind": "other"}]},
            {"findings": [{"kind": "weak_example", "block_ids": []}]},
            {"findings": [{"kind": "weak_example", "block_ids": ["missing"]}]},
            {"findings": [{"kind": "weak_example", "block_ids": ["b"], "confidence": 2}]},
            {
                "findings": [
                    {
                        "kind": "weak_example",
                        "block_ids": ["b"],
                        "confidence": 0.5,
                        "title": "",
                        "explanation": "x",
                        "suggested_action": "x",
                    }
                ]
            },
        ]
        for response in invalid:
            with self.subTest(response=response), self.assertRaises(ValueError):
                LLMEditorialAuditor(client_response(response)).analyze(course)
        huge = release("x" * 500_001)
        with self.assertRaisesRegex(ValueError, "500000"):
            LLMEditorialAuditor(client_response({})).analyze(huge)

    def test_question_generation_validation_and_retrievable_path(self):
        course = release()
        auditor = LLMEditorialAuditor(client_response({"questions": []}))
        for count in (0, 101):
            with self.assertRaises(ValueError):
                auditor.generate_support_tests(course, count=count)
        invalid = [
            "{",
            {},
            {"questions": [{"id": ""}]},
            {"questions": [{"id": "x"}, {"id": "x"}]},
            {"questions": [{"id": "x", "question": "q", "expected_block_ids": []}]},
            {"questions": [{"id": "x", "question": "q", "expected_block_ids": ["missing"]}]},
            {"questions": [{"id": "1"}, {"id": "2"}]},
        ]
        for value in invalid:
            count = 1
            with self.subTest(value=value), self.assertRaises(ValueError):
                LLMEditorialAuditor(client_response(value)).generate_support_tests(
                    course, count=count
                )
        good = {"questions": [{"id": "x", "question": "loops", "expected_block_ids": ["b"]}]}
        self.assertEqual(
            LLMEditorialAuditor(client_response(good)).generate_support_tests(course), ()
        )

    def test_semantic_output_validation_boundaries(self):
        course = release()
        left = right = course.blocks[0]
        required = {
            "same_meaning": True,
            "same_objectives": True,
            "comparable_difficulty": True,
            "examples_valid": True,
            "no_contradiction": True,
        }
        valid = {"equivalent": True, "confidence": 1, "explanation": "same", "properties": required}
        self.assertTrue(
            LLMSemanticComparator(client_response(valid))
            .compare(left, right, left_language="en", right_language="en")
            .equivalent
        )
        invalid = [
            "{",
            {},
            {**valid, "properties": {}},
            {**valid, "confidence": 2},
            {**valid, "equivalent": "yes"},
            {**valid, "explanation": ""},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                LLMSemanticComparator(client_response(value)).compare(
                    left, right, left_language="en", right_language="en"
                )
        huge = ContentBlock("x", UnitKind.SECTION, "x", "x" * 100_001, 1, left.locator)
        with self.assertRaisesRegex(ValueError, "100000"):
            LLMSemanticComparator(client_response(valid)).compare(
                huge, right, left_language="en", right_language="en"
            )


class ReportsCurriculumTutorWeatherTests(unittest.TestCase):
    def test_module_entrypoint_dispatches_main(self):
        with patch("eii.cli.main", return_value=7), self.assertRaises(SystemExit) as raised:
            runpy.run_module("eii.__main__", run_name="__main__")
        self.assertEqual(raised.exception.code, 7)

    def test_compare_and_html_reviewed_empty_and_escaping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.json"
            new = root / "new.json"
            old.write_text(json.dumps({"id": "a", "findings": []}))
            new.write_text(json.dumps({"id": "b", "findings": []}))
            self.assertFalse(compare_files(old, new, root / "out" / "diff.json")["regression"])
            course = release()
            finding = Finding("<f>", "x", "<title>", "&", Severity.LOW, 0.5, ())
            review = ReviewDecision("<f>", FindingStatus.CONFIRMED, "r", "<ok>", "now")
            bundle = EvidenceBundle.create((course,), (finding,))
            reviewed = copy.copy(bundle)
            object.__setattr__(reviewed, "reviews", (review,))
            write_html(reviewed, (), root / "reviewed.html")
            self.assertIn("&lt;ok&gt;", (root / "reviewed.html").read_text())
            empty = EvidenceBundle.create((course,), ())
            object.__setattr__(
                empty,
                "metadata",
                {
                    "semantic_evaluations": [
                        {"outcome": "equivalent"},
                        {"outcome": "drift"},
                        {"outcome": "abstained"},
                        "ignored",
                    ]
                },
            )
            write_html(empty, (), root / "empty.html")
            self.assertIn("No findings", (root / "empty.html").read_text())
            self.assertIn("1 equivalent · 1 drift · 1 abstained", (root / "empty.html").read_text())
            object.__setattr__(empty, "metadata", {"semantic_evaluations": {}})
            write_html(empty, (), root / "non-array.html")
            self.assertIn("0 total", (root / "non-array.html").read_text())

    def test_curriculum_all_structural_findings(self):
        course = release("word " * 90)
        spec = CurriculumSpec(
            "s",
            "1",
            (
                Objective("late", "Late", ("loop",), ("missing",)),
                Objective("unsupported", "Unsupported", ("none",), ()),
                Objective("unassessed", "Unassessed", ("loop",), ()),
            ),
            (
                Assessment("gone", "missing", ("late",), ()),
                Assessment("q", "b", (), ("absent phrase",)),
            ),
        )
        kinds = {f.finding_type for f in CurriculumMRI().analyze(course, spec)}
        self.assertTrue(
            {
                "curriculum.prerequisite_jump",
                "curriculum.unsupported_objective",
                "curriculum.unassessed_objective",
                "curriculum.missing_assessment",
                "curriculum.unsupported_question",
                "accessibility.sentence_complexity",
            }
            <= kinds
        )
        image_course = release("Supported phrase. ![](image.png)")
        complete = CurriculumSpec(
            "s",
            "1",
            (Objective("o", "O", ("loop",), ()),),
            (Assessment("a", "b", ("o",), ("supported phrase",)),),
        )
        found = CurriculumMRI().analyze(image_course, complete)
        self.assertEqual([f.finding_type for f in found], ["accessibility.missing_alt_text"])
        loc = course.blocks[0].locator
        prior = ContentBlock(
            "prior", UnitKind.SECTION, "Prior", "prerequisite", 0, loc, concepts=("prior",)
        )
        later = ContentBlock(
            "later", UnitKind.SECTION, "Later", "objective", 1, loc, concepts=("later",)
        )
        ordered = CourseRelease("ordered", "c", "en", "1", "C", (prior, later), loc)
        ordered_spec = CurriculumSpec(
            "s",
            "1",
            (Objective("p", "P", ("prior",), ()), Objective("o", "O", ("later",), ("p",))),
            (Assessment("a", "later", ("p", "o"), ()),),
        )
        self.assertNotIn(
            "curriculum.prerequisite_jump",
            {f.finding_type for f in CurriculumMRI().analyze(ordered, ordered_spec)},
        )

    def test_tutor_empty_queries_citations_and_missing_language(self):
        course = release()
        self.assertEqual(retrieve(course, ""), ())
        self.assertEqual(_parse_citations("answer", {"b"}), ("answer", ()))
        self.assertEqual(_parse_citations("answer\nCITATIONS: b,,x", {"b"}), ("answer", ("b",)))
        tutor = BilingualGroundedTutor(
            client_response("answer\nCITATIONS:"),
            (course,),
            (Alignment("irrelevant", ((course.id, "not-selected"),), 0.5, "explicit-concept"),),
        )
        with self.assertRaisesRegex(ValueError, "no release"):
            tutor.answer("q", reading_language="sr", answer_language="en")
        answer = tutor.answer(
            "q", reading_language="en", answer_language="en", activity_id="missing"
        )
        self.assertEqual(answer.citations, ())
        answer = tutor.answer(
            "q", reading_language="en", answer_language="en", activity_id="lesson.md"
        )
        self.assertTrue(answer.retrieved)
        answer = tutor.answer("q", reading_language="en", answer_language="en", activity_id="b")
        self.assertTrue(answer.retrieved)
        self.assertIsNotNone(tutor.answer("q", reading_language="en", answer_language="en"))

    def test_weather_validation_bounds_filter_purge_and_empty_html(self):
        for token, timestamp in (
            ("", "2025-01-01T00:00:00+00:00"),
            ("a@b", "2025-01-01T00:00:00+00:00"),
            ("x", "2025-01-01T00:00:00"),
        ):
            with self.assertRaises(ValueError):
                MinimizedEvent(timestamp, "c", "a", "en", "x", Signal.FRUSTRATION, token)
        for values in (
            ("", "a", "en", "x"),
            ("c", "a\n", "en", "x"),
            ("c", "a", "x" * 36, "x"),
            ("c", "a", "en", "x" * 201),
        ):
            with self.assertRaisesRegex(ValueError, "bounded text"):
                MinimizedEvent(
                    "2025-01-01T00:00:00+00:00",
                    *values,
                    Signal.FRUSTRATION,
                    "anonymous-token",
                )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kwargs in (
                {"minimum_group_size": 1},
                {"retention_days": 0},
                {"max_events_per_contributor_per_cell": 0},
            ):
                with self.assertRaises(ValueError):
                    WeatherStore(
                        root / "x.db", secret=b"0123456789abcdef0123456789abcdef", **kwargs
                    )
            with self.assertRaisesRegex(ValueError, "32 bytes"):
                WeatherStore(root / "x.db", secret=b"short")
            event = MinimizedEvent(
                "2025-01-01T12:00:00+01:00", "c", "a", "en", "x", Signal.FRUSTRATION, "anon"
            )
            with WeatherStore(
                root / "w.db",
                secret=b"0123456789abcdef0123456789abcdef",
                minimum_group_size=2,
                max_events_per_contributor_per_cell=1,
            ) as store:
                store.ingest(event)
                store.ingest(event)
                self.assertEqual(store.aggregate(course_key="other"), ())
                store.export(root / "reports" / "weather.json", course_key="c")
                store.export_html(root / "weather.html", course_key="c")
                self.assertIn("No groups", (root / "weather.html").read_text())
                self.assertEqual(store.purge_expired(), 1)
            bad = root / "events.json"
            bad.write_text(json.dumps({"events": [{**to_dict(event), "email": "x"}]}))
            with self.assertRaisesRegex(ValueError, "prohibited"):
                load_events(bad)


if __name__ == "__main__":
    unittest.main()

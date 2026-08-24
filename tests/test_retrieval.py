import json
import tempfile
import unittest
from pathlib import Path

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind
from eii.glossary import Glossary, Term
from eii.retrieval import BM25Index, BM25Retriever, RetrievalFixture, evaluate_retriever, tokenize


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        locator = SourceLocator("test", "repo", "lesson")
        self.course = CourseRelease(
            "r",
            "course",
            "en",
            "1",
            "Programming",
            (
                ContentBlock(
                    "assignment",
                    UnitKind.SECTION,
                    "Assignment",
                    "Use equals to assign a value to a variable.",
                    0,
                    locator,
                    concepts=("programming.assignment",),
                ),
                ContentBlock(
                    "loops",
                    UnitKind.SECTION,
                    "For loops",
                    "A for loop repeats a block for each item in a range.",
                    1,
                    locator,
                    concepts=("programming.loop.for.range",),
                ),
            ),
            locator,
        )

    def test_bm25_ranks_text_concepts_and_activity(self):
        retriever = BM25Retriever()
        self.assertEqual(retriever.retrieve(self.course, "range loop")[0].block_id, "loops")
        self.assertIs(retriever.index(self.course), retriever.index(self.course))
        self.assertEqual(
            retriever.retrieve(self.course, "unmatched", activity_id="assignment")[0].block_id,
            "assignment",
        )
        self.assertEqual(retriever.retrieve(self.course, ""), ())
        with self.assertRaises(ValueError):
            retriever.retrieve(self.course, "loop", limit=0)
        with self.assertRaises(ValueError):
            BM25Retriever(k1=0)
        with self.assertRaises(ValueError):
            BM25Retriever(b=2)
        with self.assertRaises(ValueError):
            BM25Retriever(cache_size=0)
        evicting = BM25Retriever(cache_size=1)
        first_index = evicting.index(self.course)
        other = CourseRelease(
            "other", "other", "en", "1", "Other", self.course.blocks, self.course.source
        )
        evicting.index(other)
        self.assertIsNot(first_index, evicting.index(self.course))

    def test_metrics_are_reproducible_and_reject_invalid_fixtures(self):
        fixture = RetrievalFixture("How does a range loop repeat?", frozenset({"loops"}))
        metrics = evaluate_retriever(BM25Retriever(), self.course, (fixture,), limit=2)
        self.assertEqual(metrics.fixture_count, 1)
        self.assertEqual(metrics.recall_at_k, 1)
        self.assertEqual(metrics.precision_at_k, 0.5)
        self.assertEqual(metrics.hit_rate_at_k, 1)
        self.assertEqual(metrics.mean_reciprocal_rank, 1)
        self.assertEqual(metrics.ndcg_at_k, 1)
        with self.assertRaises(ValueError):
            evaluate_retriever(BM25Retriever(), self.course, ())
        with self.assertRaisesRegex(ValueError, "unknown"):
            evaluate_retriever(
                BM25Retriever(),
                self.course,
                (RetrievalFixture("x", frozenset({"missing"})),),
            )
        self.assertIn("c++", tokenize("C++ and C#"))
        self.assertIn("程序", tokenize("程序设计"))
        self.assertEqual(BM25Index(self.course).retrieve("range")[0].block_id, "loops")
        with self.assertRaises(ValueError):
            BM25Index(self.course, b=-1)
        with self.assertRaises(ValueError):
            BM25Index(self.course).retrieve("range", limit=101)

    def test_glossary_expansion_enables_bounded_cross_language_retrieval(self):
        glossary = Glossary(
            "programming", "1", (Term("loop", {"en": ("loop",), "sr": ("petlja",)}, {}),)
        )
        serbian = CourseRelease(
            "sr",
            "course",
            "sr",
            "1",
            "Programiranje",
            (
                ContentBlock(
                    "loop",
                    UnitKind.SECTION,
                    "Petlja",
                    "Petlja ponavlja naredbe.",
                    0,
                    self.course.source,
                ),
                ContentBlock(
                    "other",
                    UnitKind.SECTION,
                    "Promenljiva",
                    "Vrednost promenljive.",
                    1,
                    self.course.source,
                ),
            ),
            self.course.source,
        )
        plain = BM25Retriever().retrieve(serbian, "loop")
        expanded = BM25Retriever(glossary=glossary, query_language="en").retrieve(serbian, "loop")
        self.assertEqual(plain, ())
        self.assertEqual(expanded[0].block_id, "loop")
        self.assertEqual(
            glossary.expand(("a", "loop"), target_language="sr", source_language="en"),
            ("petlja",),
        )
        plan = BM25Retriever(glossary=glossary, query_language="en-US").query_plan(serbian, "loop")
        self.assertEqual(plan["glossary_concept_ids"], ("loop",))
        self.assertEqual(plan["expanded_terms"], ("petlja",))
        self.assertEqual(plan["glossary_matches"][0]["matched_forms"], ("loop",))
        self.assertEqual(plan["glossary_matches"][0]["source_language"], "en")
        self.assertEqual(plan["algorithm"], "bm25-glossary-expansion-v1")
        self.assertEqual(glossary.expand(("unknown",), target_language="sr"), ())
        self.assertEqual(glossary.expand((), target_language="sr"), ())
        with self.assertRaises(ValueError):
            BM25Retriever(expansion_weight=1)
        for arguments in (
            ("", {"en": ("loop",)}, {}),
            ("x", {"bad language": ("loop",)}, {}),
            ("x", {"en": ("loop", "LOOP")}, {}),
            ("x", {"en": ("loop",)}, {"en": ("LOOP",)}),
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    Term(*arguments)
        with self.assertRaisesRegex(ValueError, "unique"):
            Glossary("g", "1", (glossary.terms[0], glossary.terms[0]))

    def test_glossary_schema_and_language_boundaries(self):
        for term in (
            lambda: Term("x", {}, {}),
            lambda: Term("x", {"en_US": ("one",), "en-us": ("two",)}, {}),
            lambda: Term("x", [], {}),  # type: ignore[arg-type]
        ):
            with self.assertRaises(ValueError):
                term()
        valid = Term("x", {"en": ("loop",), "sr": ("petlja",)}, {})
        for glossary in (lambda: Glossary("", "1", (valid,)), lambda: Glossary("g", "", (valid,))):
            with self.assertRaises(ValueError):
                glossary()
        # An absent declared source language must not silently match some other language.
        self.assertEqual(
            Glossary("g", "1", (valid,)).expand(
                ("loop",), target_language="sr", source_language="es"
            ),
            (),
        )
        two_terms = Glossary(
            "g",
            "1",
            (valid, Term("y", {"en": ("variable",), "sr": ("promenljiva",)}, {})),
        )
        self.assertEqual(
            tuple(
                item["concept_id"]
                for item in two_terms.expansion_trace(("loop",), target_language="en")
            ),
            ("x",),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "glossary.json"
            for document, message in (
                ({"id": "g", "version": "1", "terms": {}}, "array"),
                ({"id": "g", "version": "1", "terms": [{}]}, "fields"),
                (
                    {
                        "id": "g",
                        "version": "1",
                        "terms": [{"concept_id": "x", "translations": [], "forbidden": {}}],
                    },
                    "language mapping",
                ),
                ({"id": "g", "version": "1", "terms": [], "extra": 1}, "document fields"),
            ):
                path.write_text(json.dumps(document), "utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    Glossary.load(path)


if __name__ == "__main__":
    unittest.main()

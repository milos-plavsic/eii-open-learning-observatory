import unittest

from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind
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


if __name__ == "__main__":
    unittest.main()

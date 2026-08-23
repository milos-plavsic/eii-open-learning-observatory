import json
import unittest
from pathlib import Path

from eii.adapters import RepositoryAdapter
from eii.babelbridge import BabelBridge
from eii.models import OpenAICompatibleClient
from eii.semantics import LLMSemanticComparator
from eii.tutor import BilingualGroundedTutor

FIXTURES = Path(__file__).parent / "fixtures"


class SemanticBilingualTests(unittest.TestCase):
    def test_concrete_semantic_comparator(self):
        response = {
            "equivalent": False,
            "confidence": 0.92,
            "explanation": "Range bound changed",
            "properties": {
                "same_meaning": False,
                "same_objectives": True,
                "comparable_difficulty": True,
                "examples_valid": False,
                "no_contradiction": False,
            },
        }
        client = OpenAICompatibleClient(
            "http://localhost/v1",
            "judge",
            transport=lambda *args: {"choices": [{"message": {"content": json.dumps(response)}}]},
        )
        adapter = RepositoryAdapter()
        en = adapter.load(FIXTURES / "course_en")
        sr = adapter.load(FIXTURES / "course_sr")
        judgment = LLMSemanticComparator(client).compare(
            en.blocks[1], sr.blocks[1], left_language="en", right_language="sr"
        )
        self.assertFalse(judgment.equivalent)
        self.assertFalse(judgment.properties["same_meaning"])
        self.assertEqual(judgment.model_run.prompt_version, "babel-semantic-v1")

    def test_semantic_comparator_rejects_internally_inconsistent_judgment(self):
        response = {
            "equivalent": True,
            "confidence": 0.9,
            "explanation": "Claimed equivalent",
            "properties": {
                "same_meaning": False,
                "same_objectives": True,
                "comparable_difficulty": True,
                "examples_valid": True,
                "no_contradiction": True,
            },
        }
        client = OpenAICompatibleClient(
            "http://localhost/v1",
            "judge",
            transport=lambda *args: {"choices": [{"message": {"content": json.dumps(response)}}]},
        )
        adapter = RepositoryAdapter()
        en = adapter.load(FIXTURES / "course_en")
        with self.assertRaisesRegex(ValueError, "conjunction"):
            LLMSemanticComparator(client).compare(
                en.blocks[0], en.blocks[1], left_language="en", right_language="en"
            )

    def test_bilingual_tutor_expands_aligned_evidence(self):
        def transport(url, body, headers, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Use range carefully.\nCITATIONS: repo:lesson.md#range, repo:lesson.md#opseg"
                        }
                    }
                ]
            }

        client = OpenAICompatibleClient("http://localhost/v1", "tutor", transport=transport)
        adapter = RepositoryAdapter()
        en = adapter.load(FIXTURES / "course_en")
        sr = adapter.load(FIXTURES / "course_sr")
        alignments = BabelBridge().analyze((en, sr)).alignments
        answer = BilingualGroundedTutor(client, (en, sr), alignments).answer(
            "range", reading_language="en", answer_language="pt", activity_id="lesson.md"
        )
        self.assertGreaterEqual(len(answer.retrieved), 2)
        self.assertIn("repo:lesson.md#opseg", answer.citations)


if __name__ == "__main__":
    unittest.main()

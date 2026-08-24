import time
import unittest
from dataclasses import replace

from eii.domain import ContentBlock, ModelRun, SourceLocator, UnitKind
from eii.semantic_usage import usage_total
from eii.semantics import (
    ConsensusSemanticComparator,
    SemanticComparator,
    SemanticJudgment,
)


class _Comparator:
    def __init__(self, equivalent, confidence, name, properties=None):
        self.judgment = SemanticJudgment(
            equivalent,
            confidence,
            name,
            properties or {"same_meaning": equivalent, "examples_valid": True},
            ModelRun("provider", name, "v1", {}, "input", f"output-{name}"),
        )

    def compare(self, *args, **kwargs):
        return self.judgment


class _FailingComparator:
    def compare(self, *args, **kwargs):
        raise TimeoutError("provider timed out")


class SemanticConsensusTests(unittest.TestCase):
    def test_failed_members_remain_in_configured_panel_denominator(self):
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        panel = (
            _Comparator(True, 0.9, "one"),
            _Comparator(True, 0.9, "two"),
            _Comparator(True, 0.9, "three"),
            _FailingComparator(),
            _FailingComparator(),
        )
        strict = ConsensusSemanticComparator(panel).compare(
            block, block, left_language="en", right_language="sr"
        )
        self.assertTrue(strict.abstained)
        self.assertEqual(strict.agreement_ratio, 0.6)
        self.assertEqual(strict.completion_ratio, 0.6)
        self.assertEqual(strict.failed_member_count, 2)
        self.assertEqual(
            strict.model_run.configuration["decision_majority_denominator"], "configured_panel"
        )
        tolerant = ConsensusSemanticComparator(panel, max_failed_members=2).compare(
            block, block, left_language="en", right_language="sr"
        )
        self.assertFalse(tolerant.abstained)
        self.assertEqual(tolerant.agreement_ratio, 0.6)

    def test_requires_multiple_independent_comparators(self):
        with self.assertRaisesRegex(ValueError, "odd panel"):
            ConsensusSemanticComparator((_Comparator(True, 1, "one"),))
        panel = tuple(_Comparator(True, 1, str(index)) for index in range(3))
        with self.assertRaisesRegex(ValueError, "strict majority"):
            ConsensusSemanticComparator(panel, quorum=1)
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            ConsensusSemanticComparator(panel, overall_timeout_seconds=0)
        with self.assertRaisesRegex(ValueError, "cost budget"):
            ConsensusSemanticComparator(panel, max_total_cost=-1)
        with self.assertRaisesRegex(ValueError, "token budget"):
            ConsensusSemanticComparator(panel, max_total_tokens=0)
        with self.assertRaisesRegex(ValueError, "outstanding"):
            ConsensusSemanticComparator(panel, max_outstanding_panels=0)
        with self.assertRaises(NotImplementedError):
            SemanticComparator.compare(None, None, None, left_language="en", right_language="sr")

    def test_usage_accounting_and_unknown_budget_are_fail_closed(self):
        self.assertEqual(usage_total({"prompt_tokens": 2, "completion_tokens": 3}), 5)
        self.assertIsNone(usage_total(None))
        self.assertIsNone(usage_total({"prompt_tokens": True, "completion_tokens": 3}))

        class Unmetered(_Comparator):
            pass

        panel = tuple(Unmetered(True, 1, str(index)) for index in range(3))
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = ConsensusSemanticComparator(panel, max_total_cost=1).compare(
            block, block, left_language="en", right_language="sr"
        )
        self.assertTrue(result.abstained)
        self.assertIsNone(result.model_run.configuration["total_cost"])

    def test_unfinished_panel_holds_capacity_until_workers_finish(self):
        class Slow(_Comparator):
            def compare(self, *args, **kwargs):
                time.sleep(0.03)
                return self.judgment

        panel = tuple(Slow(True, 1, str(index)) for index in range(3))
        comparator = ConsensusSemanticComparator(panel, overall_timeout_seconds=0.001)
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        comparator.compare(block, block, left_language="en", right_language="sr")
        limited = comparator.compare(block, block, left_language="en", right_language="sr")
        self.assertTrue(limited.abstained)
        self.assertEqual(
            limited.model_run.configuration["failures"][0]["error_type"], "panel_capacity_exhausted"
        )
        time.sleep(0.04)
        comparator.compare(block, block, left_language="en", right_language="sr")

    def test_majority_decision_preserves_member_provenance_and_disagreement(self):
        comparator = ConsensusSemanticComparator(
            (
                _Comparator(True, 0.9, "one"),
                _Comparator(False, 0.8, "two"),
                _Comparator(True, 0.7, "three"),
            )
        )
        block = ContentBlock(
            "b", UnitKind.SECTION, "Title", "Text", 1, SourceLocator("x", "r", "p")
        )
        result = comparator.compare(block, block, left_language="en", right_language="sr")
        self.assertTrue(result.equivalent)
        self.assertAlmostEqual(result.confidence, 0.8)
        self.assertAlmostEqual(result.agreement_ratio, 2 / 3)
        self.assertAlmostEqual(result.majority_mean_confidence, 0.8)
        self.assertAlmostEqual(result.minority_mean_confidence, 0.8)
        self.assertEqual(result.model_run.prompt_version, "semantic-consensus-v3")
        self.assertTrue(result.properties["examples_valid"])
        self.assertTrue(result.properties["same_meaning"])
        property_signal = result.property_signals["same_meaning"]
        self.assertAlmostEqual(property_signal["agreement_ratio"], 2 / 3)
        self.assertIsNone(property_signal["majority_mean_confidence"])
        self.assertIsNone(property_signal["minority_mean_confidence"])
        self.assertEqual(result.model_run.configuration["member_count"], 3)
        self.assertEqual(len(result.model_run.configuration["member_judgments"]), 3)
        self.assertIn("one | two | three", result.explanation)

    def test_confident_dissent_cannot_increase_majority_confidence(self):
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        results = []
        for dissent in (0.99, 0.5):
            panel = ConsensusSemanticComparator(
                (
                    _Comparator(True, 0.9, f"one-{dissent}"),
                    _Comparator(True, 0.9, f"two-{dissent}"),
                    _Comparator(False, dissent, f"three-{dissent}"),
                )
            )
            results.append(panel.compare(block, block, left_language="en", right_language="sr"))
        self.assertEqual([result.confidence for result in results], [0.9, 0.9])
        self.assertEqual([result.agreement_ratio for result in results], [2 / 3, 2 / 3])
        self.assertEqual([result.minority_mean_confidence for result in results], [0.99, 0.5])

    def test_abstains_when_whole_and_property_consensus_conflict(self):
        comparator = ConsensusSemanticComparator(
            (
                _Comparator(False, 1, "one", {"a": False, "b": True, "c": True}),
                _Comparator(False, 1, "two", {"a": True, "b": False, "c": True}),
                _Comparator(False, 1, "three", {"a": True, "b": True, "c": False}),
            )
        )
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = comparator.compare(block, block, left_language="en", right_language="sr")
        self.assertFalse(result.equivalent)
        self.assertTrue(result.abstained)
        self.assertEqual(result.confidence, 0)
        self.assertEqual(result.properties, {"a": True, "b": True, "c": True})

    def test_member_abstention_is_not_counted_as_a_vote(self):
        panel = tuple(_Comparator(True, 1, str(index)) for index in range(3))
        panel[1].judgment = replace(panel[1].judgment, abstained=True)
        panel[2].judgment = replace(
            panel[2].judgment,
            equivalent=False,
            properties={"same_meaning": False, "examples_valid": True},
        )
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = ConsensusSemanticComparator(panel).compare(
            block, block, left_language="en", right_language="sr"
        )
        self.assertTrue(result.abstained)
        self.assertEqual(result.model_run.configuration["member_count"], 2)
        self.assertEqual(
            result.model_run.configuration["failures"][0]["error_type"], "member_abstained"
        )

        with self.assertRaisesRegex(ValueError, "abstaining"):
            ConsensusSemanticComparator(panel)._aggregate((panel[1].judgment,), [])

    def test_records_failures_and_requires_quorum(self):
        class Broken:
            def compare(self, *args, **kwargs):
                raise TimeoutError("secret provider detail")

        comparator = ConsensusSemanticComparator(
            (_Comparator(True, 1, "one"), Broken(), Broken()), overall_timeout_seconds=1
        )
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = comparator.compare(block, block, left_language="en", right_language="sr")
        self.assertTrue(result.abstained)
        self.assertEqual(
            result.model_run.configuration["failures"][0]["error_type"], "TimeoutError"
        )
        self.assertNotIn("secret provider detail", str(result.model_run.configuration))

    def test_overall_deadline_records_pending_members(self):
        class Slow:
            def __init__(self, name):
                self.name = name

            def compare(self, *args, **kwargs):
                time.sleep(0.03)
                return _Comparator(True, 1, self.name).judgment

        comparator = ConsensusSemanticComparator(
            (Slow("one"), Slow("two"), Slow("three")), overall_timeout_seconds=0.001
        )
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = comparator.compare(block, block, left_language="en", right_language="sr")
        self.assertTrue(result.abstained)
        self.assertEqual(len(result.model_run.configuration["failures"]), 3)
        with self.assertRaisesRegex(ValueError, "comparison timeout"):
            comparator.compare(
                block, block, left_language="en", right_language="sr", timeout_seconds=0
            )

    def test_caller_deadline_is_propagated_to_members(self):
        observed = []

        class Capturing(_Comparator):
            def compare(self, *args, **kwargs):
                observed.append(kwargs["timeout_seconds"])
                return self.judgment

        panel = tuple(Capturing(True, 1, str(index)) for index in range(3))
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        ConsensusSemanticComparator(panel, overall_timeout_seconds=10).compare(
            block, block, left_language="en", right_language="sr", timeout_seconds=0.5
        )
        self.assertEqual(observed, [0.5, 0.5, 0.5])

    def test_budget_excess_forces_auditable_abstention(self):
        class Costed:
            def __init__(self, name):
                self.name = name

            def compare(self, *args, **kwargs):
                return SemanticJudgment(
                    True,
                    1,
                    "equivalent",
                    {"meaning": True},
                    ModelRun(
                        "provider",
                        self.name,
                        "v1",
                        {"usage": {"total_tokens": 10}},
                        "input",
                        f"output-{self.name}",
                        cost=1,
                    ),
                )

        comparator = ConsensusSemanticComparator(
            tuple(Costed(str(index)) for index in range(3)),
            max_total_cost=2,
            max_total_tokens=20,
        )
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = comparator.compare(block, block, left_language="en", right_language="sr")
        self.assertTrue(result.abstained)
        self.assertEqual(result.confidence, 0)
        self.assertTrue(result.model_run.configuration["total_cost"] > 2)

    def test_budget_gate_rejects_incomplete_provider_metering(self):
        class Metered(_Comparator):
            def __init__(self, name):
                super().__init__(True, 1, name)
                self.judgment = replace(
                    self.judgment,
                    model_run=replace(
                        self.judgment.model_run,
                        configuration={"usage": {"total_tokens": 1}},
                        cost=0.01,
                    ),
                )

        class Failed:
            def compare(self, *args, **kwargs):
                raise TimeoutError("unknown billing state")

        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        result = ConsensusSemanticComparator(
            (Metered("one"), Metered("two"), Failed()), max_total_cost=100
        ).compare(block, block, left_language="en", right_language="sr")
        self.assertTrue(result.abstained)
        self.assertFalse(result.model_run.configuration["cost_metering_complete"])
        self.assertTrue(result.model_run.configuration["decision_signals"])
        self.assertIn("evaluation budget", result.explanation)

    def test_rejects_duplicate_identities_invalid_scores_and_property_contracts(self):
        block = ContentBlock("b", UnitKind.SECTION, "T", "X", 1, SourceLocator("x", "r", "p"))
        with self.assertRaisesRegex(ValueError, "distinct evaluator identities"):
            ConsensusSemanticComparator(
                (
                    _Comparator(True, 1, "same"),
                    _Comparator(True, 1, "same"),
                    _Comparator(True, 1, "same"),
                )
            ).compare(block, block, left_language="en", right_language="sr")
        with self.assertRaisesRegex(ValueError, "finite"):
            ConsensusSemanticComparator(
                (
                    _Comparator(True, float("nan"), "one"),
                    _Comparator(True, 1, "two"),
                    _Comparator(True, 1, "three"),
                )
            ).compare(block, block, left_language="en", right_language="sr")
        with self.assertRaisesRegex(ValueError, "same non-empty properties"):
            ConsensusSemanticComparator(
                (
                    _Comparator(True, 1, "one", {"a": True}),
                    _Comparator(True, 1, "two", {"b": True}),
                    _Comparator(True, 1, "three", {"a": True}),
                )
            ).compare(block, block, left_language="en", right_language="sr")


if __name__ == "__main__":
    unittest.main()

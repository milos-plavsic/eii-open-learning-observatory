import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.cli_audit import semantic_policy_from_args
from eii.models import OpenAICompatibleClient
from eii.semantic_policy import load_semantic_policy
from eii.semantics import ConsensusSemanticComparator, LLMSemanticComparator


class SemanticPolicyTests(unittest.TestCase):
    def test_deterministic_single_and_threshold_validation(self):
        deterministic = load_semantic_policy(threshold=0.7)
        self.assertIsNone(deterministic.comparator)
        self.assertEqual(deterministic.evidence["mode"], "deterministic-only")
        client = OpenAICompatibleClient("http://127.0.0.1:8000/v1", "model")
        single = load_semantic_policy(threshold=0.8, single_client=client)
        self.assertIsInstance(single.comparator, LLMSemanticComparator)
        self.assertEqual(single.evidence["decision_threshold"], 0.8)
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            load_semantic_policy(threshold=2)

    def test_loads_public_consensus_policy_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "evaluators": [
                            {
                                "base_url": f"https://evaluator-{index}.example/v1",
                                "model": f"model-{index}",
                                "provider": "provider",
                                "api_key_env": f"SECRET_{index}",
                                "prompt_version": "v1",
                                "model_revision": f"r{index}",
                            }
                            for index in range(3)
                        ],
                    }
                )
            )
            with patch.dict("os.environ", {f"SECRET_{index}": "test-key" for index in range(3)}):
                policy = load_semantic_policy(threshold=0.6, config_path=path)
            self.assertIsInstance(policy.comparator, ConsensusSemanticComparator)
            self.assertEqual(policy.evidence["evaluator_count"], 3)
            self.assertEqual(len(policy.evidence["public_config"]), 3)
            self.assertEqual(policy.evidence["mode"], "distinct-config-consensus")
            self.assertNotIn("SECRET", json.dumps(policy.evidence))

            path.write_text(json.dumps({"schema_version": "1.0"}))
            with self.assertRaisesRegex(ValueError, "requires evaluators"):
                load_semantic_policy(threshold=0.6, config_path=path)
            path.write_text(json.dumps({"schema_version": "1.0", "evaluators": [], "extra": 1}))
            with self.assertRaisesRegex(ValueError, "unsupported"):
                load_semantic_policy(threshold=0.6, config_path=path)

    def test_rejects_malformed_or_conflicting_consensus_policy(self):
        client = OpenAICompatibleClient("http://127.0.0.1:8000/v1", "model")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "schema_version"):
                load_semantic_policy(threshold=0.7, config_path=path)
            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                load_semantic_policy(threshold=0.7, config_path=path, single_client=client)
            missing_secret = {
                "schema_version": "1.0",
                "evaluators": [
                    {
                        "base_url": f"https://{index}.example/v1",
                        "model": f"m{index}",
                        "api_key_env": f"MISSING_EII_{index}",
                    }
                    for index in range(3)
                ],
            }
            path.write_text(json.dumps(missing_secret))
            with self.assertRaisesRegex(ValueError, "requires non-empty environment"):
                load_semantic_policy(threshold=0.7, config_path=path)
            path.write_text('{"schema_version":"1.0","evaluators": []}')
            with self.assertRaisesRegex(ValueError, "odd panel"):
                load_semantic_policy(threshold=0.7, config_path=path)
            path.write_text(
                '{"schema_version":"1.0","evaluators": [{"base_url": "x", "model": "m", "bad": "x"}, {}, {}]}'
            )
            with self.assertRaisesRegex(ValueError, "invalid fields"):
                load_semantic_policy(threshold=0.7, config_path=path)
            path.write_text(
                '{"schema_version":"1.0","evaluators": [{"base_url": "", "model": "m"}, {"base_url": "x", "model": "m"}, {"base_url": "y", "model": "m"}]}'
            )
            with self.assertRaisesRegex(ValueError, "non-empty strings"):
                load_semantic_policy(threshold=0.7, config_path=path)
            duplicate = {"base_url": "https://same.example/v1", "model": "same"}
            path.write_text(
                json.dumps(
                    {"schema_version": "1.0", "evaluators": [duplicate, duplicate, duplicate]}
                )
            )
            with self.assertRaisesRegex(ValueError, "distinct identities"):
                load_semantic_policy(threshold=0.7, config_path=path)
            valid = [
                {"base_url": f"https://{index}.example/v1", "model": f"m{index}"}
                for index in range(3)
            ]
            for field, value, message in (
                ("quorum", True, "integer"),
                ("overall_timeout_seconds", True, "numeric"),
                ("max_total_cost", True, "numeric"),
                ("max_total_tokens", True, "integer"),
                ("quorum", 1, "strict majority"),
                ("overall_timeout_seconds", 0, "finite and positive"),
                ("max_outstanding_panels", True, "integers"),
                ("minimum_declared_operators", True, "integers"),
            ):
                path.write_text(
                    json.dumps({"schema_version": "1.0", "evaluators": valid, field: value})
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_semantic_policy(threshold=0.7, config_path=path)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "evaluators": valid,
                        "minimum_declared_operators": 1,
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "diversity"):
                load_semantic_policy(threshold=0.7, config_path=path)

    def test_cli_policy_adapter_converts_validation_to_parser_error(self):
        args = type("Args", (), {"semantic_threshold": 2, "semantic_evaluator_config": None})()
        with self.assertRaises(SystemExit):
            semantic_policy_from_args(args, None, argparse.ArgumentParser())


if __name__ == "__main__":
    unittest.main()

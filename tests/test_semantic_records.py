import unittest
from dataclasses import replace

from eii.domain import EvidenceRef, ModelRun, content_hash, to_dict
from eii.semantic_records import SemanticEvaluationRecord, model_run_id, parse_semantic_records


class SemanticRecordTests(unittest.TestCase):
    def setUp(self):
        self.run = ModelRun("p", "m", "v", {}, "in", "out")
        self.ref = EvidenceRef("release", "block", "sha256:" + "1" * 64, "excerpt")
        self.record = SemanticEvaluationRecord(
            "",
            "relationship",
            (self.ref,),
            (self.ref,),
            "equivalent",
            1.0,
            {"same": True},
            "supported",
            model_run_id(self.run),
        )

    def test_round_trip_and_sealed_identity(self):
        self.assertEqual(parse_semantic_records([to_dict(self.record)]), (self.record,))
        self.assertTrue(self.record.id.startswith("sha256:"))
        with self.assertRaisesRegex(ValueError, "canonical payload"):
            replace(self.record, id=content_hash("wrong"))

    def test_rejects_invalid_shapes_and_values(self):
        with self.assertRaisesRegex(ValueError, "array"):
            parse_semantic_records({})
        document = to_dict(self.record)
        for field, value, message in (
            ("outcome", "maybe", "schema or outcome"),
            ("decision_score", 2, "between zero and one"),
            ("relationship_id", "", "relationship identity"),
        ):
            changed = dict(document)
            changed[field] = value
            changed["id"] = ""
            with self.assertRaisesRegex(ValueError, message):
                parse_semantic_records([changed])
        with self.assertRaisesRegex(ValueError, "fields"):
            parse_semantic_records([{"id": "x"}])
        for evidence, message in (([], "non-empty"), ([{"bad": 1}], "fields")):
            changed = dict(document)
            changed["left_evidence"] = evidence
            changed["id"] = ""
            with self.assertRaisesRegex(ValueError, message):
                parse_semantic_records([changed])
        for properties in ([], {"same": "yes"}, {1: True}):
            changed = dict(document)
            changed["properties"] = properties
            changed["id"] = ""
            with self.assertRaisesRegex(ValueError, "boolean fields"):
                parse_semantic_records([changed])

        for members, message in (
            ({}, "must be an array"),
            (["bad"], "must be an object"),
            ([{"member_index": -1, "error_type": "timeout"}], "failure record"),
            ([{"unknown": True}], "fields do not match"),
            (
                [
                    {
                        "equivalent": True,
                        "confidence": 2,
                        "properties": {"same": True},
                        "explanation": "same",
                        "model_run": {},
                    }
                ],
                "success record",
            ),
        ):
            changed = dict(document)
            changed["member_judgments"] = members
            changed["id"] = ""
            with self.assertRaisesRegex(ValueError, message):
                parse_semantic_records([changed])

        changed = dict(document)
        changed["id"] = ""
        changed["member_judgments"] = [
            {
                "equivalent": True,
                "confidence": 1,
                "properties": {"same": True},
                "explanation": "same",
                "model_run": {},
            },
            {
                "member_index": 0,
                "error_type": "timeout",
                "message_hash": "sha256:" + "0" * 64,
            },
        ]
        self.assertEqual(len(parse_semantic_records([changed])[0].member_judgments), 2)

        for signals, message in (
            ({}, "signals do not match"),
            (
                {
                    "agreement_ratio": 2,
                    "majority_mean_confidence": None,
                    "minority_mean_confidence": None,
                    "confidence_kind": "uncalibrated_member_self_report",
                    "property_signals": {},
                    "completion_ratio": None,
                    "failed_member_count": 0,
                },
                "between zero and one",
            ),
            (
                {
                    "agreement_ratio": None,
                    "majority_mean_confidence": None,
                    "minority_mean_confidence": None,
                    "confidence_kind": "probability",
                    "property_signals": {},
                    "completion_ratio": None,
                    "failed_member_count": 0,
                },
                "unsupported",
            ),
        ):
            changed = dict(document)
            changed["decision_signals"] = signals
            changed["id"] = ""
            with self.assertRaisesRegex(ValueError, message):
                parse_semantic_records([changed])


if __name__ == "__main__":
    unittest.main()

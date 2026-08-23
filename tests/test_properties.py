import json
import random
import string
import tempfile
import unittest
from pathlib import Path

from eii.adapters import PlctExportAdapter
from eii.domain import canonical_json, content_hash
from eii.qr import qr_matrix


class DeterministicPropertyTests(unittest.TestCase):
    def test_canonical_hash_is_order_independent_for_random_mappings(self):
        generator = random.Random(20260821)
        for _ in range(200):
            pairs = [(f"k{index}", generator.randint(-(10**9), 10**9)) for index in range(12)]
            left = dict(pairs)
            generator.shuffle(pairs)
            right = dict(pairs)
            self.assertEqual(canonical_json(left), canonical_json(right))
            self.assertEqual(content_hash(left), content_hash(right))

    def test_qr_shape_property_for_every_supported_payload_length(self):
        for length in range(79):
            text = "x" * length
            try:
                matrix = qr_matrix(text)
            except ValueError:
                self.assertGreater(length, 78)
            else:
                self.assertIn(len(matrix), (21, 25, 29, 33))
                self.assertTrue(all(len(row) == len(matrix) for row in matrix))

    def test_seeded_malformed_plct_documents_fail_closed(self):
        generator = random.Random(41)
        adapter = PlctExportAdapter()
        alphabet = string.ascii_letters + string.digits + '{}[],:"'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fuzz.json"
            for _ in range(250):
                path.write_text(
                    "".join(generator.choice(alphabet) for _ in range(generator.randrange(0, 120)))
                )
                self.assertFalse(adapter.can_load(path))
            path.write_text(json.dumps({"format": "plct-course-export-v1"}))
            self.assertTrue(adapter.can_load(path))
            with self.assertRaises(ValueError):
                adapter.load(path)


if __name__ == "__main__":
    unittest.main()

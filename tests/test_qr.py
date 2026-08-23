import tempfile
import unittest
from pathlib import Path

from eii.appliance import write_onboarding_page
from eii.qr import qr_matrix, qr_svg


class QRTests(unittest.TestCase):
    def test_matrix_has_qr_dimensions_and_finders(self):
        matrix = qr_matrix("http://10.0.0.1:8080")
        self.assertIn(len(matrix), (21, 25, 29, 33))
        self.assertTrue(matrix[0][0])
        self.assertTrue(matrix[6][6])
        self.assertIn("<svg", qr_svg("http://10.0.0.1:8080"))

    def test_onboarding_page_embeds_url_without_network_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "connect.html"
            write_onboarding_page(output, "http://10.0.0.1:8080")
            page = output.read_text()
            self.assertIn("http://10.0.0.1:8080", page)
            self.assertNotIn("https://", page)

    def test_smallest_version_and_oversized_input(self):
        self.assertEqual(len(qr_matrix("x")), 21)
        with self.assertRaisesRegex(ValueError, "version 1-4"):
            qr_matrix("x" * 100)


if __name__ == "__main__":
    unittest.main()

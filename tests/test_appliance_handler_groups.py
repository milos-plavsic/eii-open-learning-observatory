import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eii.evidence_handlers import evidence_handler
from eii.weather_handlers import weather_handler


class FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_error(self, status):
        self.status = status

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        pass


class ApplianceHandlerGroupTests(unittest.TestCase):
    def invoke(self, factory, root: Path, module: str) -> FakeHandler:
        handler = FakeHandler()
        with patch(f"eii.{module}.active_release", return_value=root):
            factory(root)(handler)
        return handler

    def test_evidence_fail_closed_boundaries_and_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content"
            content.mkdir()
            self.assertEqual(self.invoke(evidence_handler, root, "evidence_handlers").status, 404)
            path = content / "evidence.json"
            path.write_text("{")
            self.assertEqual(self.invoke(evidence_handler, root, "evidence_handlers").status, 503)
            path.write_text("[]")
            self.assertEqual(self.invoke(evidence_handler, root, "evidence_handlers").status, 503)
            path.write_text(json.dumps({"schema_version": "2.0"}))
            result = self.invoke(evidence_handler, root, "evidence_handlers")
            self.assertEqual(result.status, 200)
            self.assertEqual(json.loads(result.wfile.getvalue()), {"schema_version": "2.0"})
            with patch("eii.evidence_handlers.active_release", side_effect=FileNotFoundError):
                missing = FakeHandler()
                evidence_handler(root)(missing)
            self.assertEqual(missing.status, 404)
            with patch.object(Path, "read_text", side_effect=OSError("unreadable")):
                self.assertEqual(
                    self.invoke(evidence_handler, root, "evidence_handlers").status, 503
                )

    def test_weather_fail_closed_boundaries_and_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "content"
            content.mkdir()
            self.assertEqual(self.invoke(weather_handler, root, "weather_handlers").status, 404)
            path = content / "weather-map.json"
            path.write_text("{")
            self.assertEqual(self.invoke(weather_handler, root, "weather_handlers").status, 503)
            path.write_text("[]")
            self.assertEqual(self.invoke(weather_handler, root, "weather_handlers").status, 503)
            valid = {
                "schema_version": "3.0",
                "privacy": {
                    "raw_conversations_stored": False,
                    "direct_identifiers_stored": False,
                },
                "cells": [],
            }
            path.write_text(json.dumps(valid))
            result = self.invoke(weather_handler, root, "weather_handlers")
            self.assertEqual(result.status, 200)
            self.assertEqual(json.loads(result.wfile.getvalue()), valid)
            with patch("eii.weather_handlers.active_release", side_effect=ValueError):
                missing = FakeHandler()
                weather_handler(root)(missing)
            self.assertEqual(missing.status, 404)
            with patch.object(
                Path, "read_text", side_effect=UnicodeDecodeError("x", b"x", 0, 1, "x")
            ):
                self.assertEqual(self.invoke(weather_handler, root, "weather_handlers").status, 503)


if __name__ == "__main__":
    unittest.main()

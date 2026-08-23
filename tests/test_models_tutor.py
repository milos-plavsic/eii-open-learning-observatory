import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eii.adapters import PlctExportAdapter
from eii.models import OpenAICompatibleClient, _http_transport
from eii.tutor import GroundedTutor

FIXTURES = Path(__file__).parent / "fixtures"


class ModelTutorTests(unittest.TestCase):
    def test_openai_compatible_grounded_tutor_records_provenance(self):
        captured = {}

        def transport(url, body, headers, timeout):
            captured.update(url=url, body=json.loads(body), headers=headers)
            return {
                "choices": [
                    {
                        "message": {
                            "content": "A loop repeats instructions.\nCITATIONS: plct:loops:a1, invented"
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            }

        client = OpenAICompatibleClient(
            "http://127.0.0.1:8000/v1", "local-model", transport=transport
        )
        course = PlctExportAdapter().load(FIXTURES / "plct.json")
        response = GroundedTutor(client).answer(
            "Petlja?", course=course, activity_id="a1", language="en"
        )
        self.assertEqual(response.citations, ("plct:loops:a1",))
        self.assertEqual(response.model_run.model, "local-model")
        self.assertTrue(response.retrieved)
        self.assertEqual(captured["url"], "http://127.0.0.1:8000/v1/chat/completions")

    def test_model_client_retries_transient_transport_failure(self):
        attempts = []

        def transport(*args):
            attempts.append(1)
            if len(attempts) == 1:
                raise TimeoutError("temporary")
            return {"choices": [{"message": {"content": "ok"}}]}

        client = OpenAICompatibleClient(
            "http://localhost/v1", "local", transport=transport, retries=1
        )
        self.assertEqual(
            client.chat([{"role": "user", "content": "q"}], prompt_version="p").text, "ok"
        )
        self.assertEqual(len(attempts), 2)

    def test_model_client_rejects_unsafe_configuration_and_empty_response(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            OpenAICompatibleClient("file:///tmp/model", "local")
        client = OpenAICompatibleClient(
            "http://localhost/v1",
            "local",
            transport=lambda *args: {"choices": [{"message": {"content": ""}}]},
        )
        with self.assertRaisesRegex(ValueError, "non-empty"):
            client.chat([{"role": "user", "content": "q"}], prompt_version="p")
        with self.assertRaisesRegex(ValueError, "timeout override"):
            client.chat([{"role": "user", "content": "q"}], prompt_version="p", timeout_seconds=0)
        with self.assertRaisesRegex(TimeoutError, "deadline"):
            client.chat(
                [{"role": "user", "content": "q"}], prompt_version="p", timeout_seconds=1e-12
            )

    def test_http_transport_enforces_a_wall_clock_response_deadline(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        opener = MagicMock()
        opener.open.return_value = response
        with (
            patch("eii.models.build_opener", return_value=opener),
            patch("eii.models.time.monotonic", side_effect=[0.0, 0.0, 2.0]),
            self.assertRaisesRegex(TimeoutError, "response deadline"),
        ):
            _http_transport("https://model.example/v1", b"{}", {}, 1.0)


if __name__ == "__main__":
    unittest.main()

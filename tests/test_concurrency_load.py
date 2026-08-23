import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from appliance_keys import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from eii.appliance import create_package, install_package, make_handler
from eii.service import ServiceMetrics
from eii.study import ReviewStudy
from eii.weather import MinimizedEvent, Signal, WeatherStore


class ConcurrencyLoadTests(unittest.TestCase):
    def test_weather_concurrent_writers_preserve_every_bounded_contribution(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "weather.db"
            with WeatherStore(
                database, secret=b"0123456789abcdef0123456789abcdef", minimum_group_size=2
            ):
                pass

            def ingest(index: int) -> None:
                with WeatherStore(
                    database, secret=b"0123456789abcdef0123456789abcdef", minimum_group_size=2
                ) as store:
                    store.ingest(
                        MinimizedEvent(
                            datetime.now(UTC).isoformat(),
                            "course",
                            "activity",
                            "en",
                            "concept",
                            Signal.FRUSTRATION,
                            f"anonymous-{index}",
                        )
                    )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(ingest, range(24)))
            with WeatherStore(
                database, secret=b"0123456789abcdef0123456789abcdef", minimum_group_size=2
            ) as store:
                cell = store.aggregate()[0]
            self.assertEqual((cell.event_count, cell.contributor_count), (24, 24))

    def test_review_study_concurrent_independent_reviewers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "study.db"
            evidence = root / "evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "id": "bundle",
                        "findings": [
                            {
                                "id": "f",
                                "finding_type": "x",
                                "title": "T",
                                "explanation": "E",
                                "evidence": [],
                            }
                        ],
                    }
                )
            )
            reviewers = tuple(f"r{index}" for index in range(8))
            with ReviewStudy(database) as study:
                study.initialize(evidence, study_id="load", reviewers=reviewers, seed="secret")

            def review(reviewer: str) -> None:
                with ReviewStudy(database) as study:
                    finding = study.next_assignment("load", reviewer)
                    study.record(
                        "load",
                        reviewer,
                        finding["finding_id"],
                        decision="confirmed",
                        rationale="checked",
                        evidence_quality="sufficient",
                        severity_assessment="medium",
                        usefulness=4,
                        actionability="usable",
                        seconds_spent=1,
                    )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(review, reviewers))
            with ReviewStudy(database) as study:
                study.export("load", root / "result.json")
            self.assertEqual(len(json.loads((root / "result.json").read_text())["decisions"]), 8)

    def test_parallel_health_load_is_counted_without_request_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "site"
            source.mkdir()
            (source / "index.html").write_text("ok")
            package = root / "box.eii"
            box = root / "box"
            create_package((source,), package, version="1", private_key=TEST_PRIVATE_KEY)
            install_package(package, box, public_key=TEST_PUBLIC_KEY)
            metrics = ServiceMetrics()
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(box, metrics=metrics))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/healthz"
                with ThreadPoolExecutor(max_workers=12) as pool:
                    bodies = list(pool.map(lambda _: urlopen(url).read(), range(48)))
                self.assertTrue(all(b'"status": "ok"' in body for body in bodies))
                self.assertTrue(metrics.wait_for_requests("GET", "/healthz", 200, 48, timeout=5.0))
                count = metrics.snapshot().requests[("GET", "/healthz", 200)]
                self.assertEqual(count, 48)
                self.assertNotIn("question", metrics.prometheus().decode())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()

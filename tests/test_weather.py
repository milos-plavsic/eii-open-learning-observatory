import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from eii.cli import main
from eii.weather import MinimizedEvent, Signal, WeatherStore, load_events
from eii.weather_dp import laplace_noise, release_counts


class WeatherTests(unittest.TestCase):
    def test_rejects_invalid_privacy_key_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "key epoch"):
                WeatherStore(
                    Path(directory) / "w.sqlite",
                    secret=b"0123456789abcdef0123456789abcdef",
                    key_epoch="bad epoch",
                )
        for sensitivity, epsilon in ((0, 1), (1, 0)):
            with self.assertRaisesRegex(ValueError, "positive"):
                laplace_noise(sensitivity=sensitivity, epsilon=epsilon)
        with patch("eii.weather_dp.secrets.randbits", side_effect=[1, 2**53 - 2]):
            negative = laplace_noise(sensitivity=1, epsilon=1)
            positive = laplace_noise(sensitivity=1, epsilon=1)
        self.assertLess(negative, 0)
        self.assertGreater(positive, 0)
        self.assertAlmostEqual(abs(negative), abs(positive))

    def test_key_epochs_are_bound_rotate_with_purge_and_cannot_reuse_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "w.sqlite"
            ledger = b"ledger-key-ledger-key-ledger-key!!"
            with WeatherStore(
                path,
                secret=b"0123456789abcdef0123456789abcdef",
                key_epoch="v1",
                ledger_key=ledger,
            ) as store:
                store.ingest(self.event("one"))
            with self.assertRaisesRegex(ValueError, "different privacy secret"):
                WeatherStore(
                    path,
                    secret=b"fedcba9876543210fedcba9876543210",
                    key_epoch="v1",
                    ledger_key=ledger,
                )
            with self.assertRaisesRegex(ValueError, "cannot be reused"):
                WeatherStore(
                    path,
                    secret=b"0123456789abcdef0123456789abcdef",
                    key_epoch="v2",
                    ledger_key=ledger,
                )
            with WeatherStore(
                path,
                secret=b"0123456789abcdef0123456789abcdef",
                key_epoch="v1",
                ledger_key=ledger,
            ) as rotated:
                self.assertEqual(
                    rotated.rotate_privacy_key(
                        new_secret=b"new-secret-value-new-secret-value!", new_epoch="v2"
                    ),
                    1,
                )
                self.assertEqual(
                    rotated.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0
                )
            with WeatherStore(
                path,
                secret=b"new-secret-value-new-secret-value!",
                key_epoch="v2",
                ledger_key=ledger,
            ) as reopened:
                self.assertIsNone(reopened.verify_export_ledger())

            implicit = Path(directory) / "implicit.sqlite"
            with WeatherStore(implicit, secret=b"i" * 32) as store:
                with self.assertRaisesRegex(ValueError, "independently supplied"):
                    store.rotate_privacy_key(new_secret=b"n" * 32, new_epoch="v2")

    def test_export_partition_strategy_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with WeatherStore(
                root / "w.sqlite", secret=b"0123456789abcdef0123456789abcdef"
            ) as store:
                store.export(root / "global.json")
                with self.assertRaisesRegex(ValueError, "partition strategy"):
                    store.export(root / "course.json", course_key="c")

    def event(self, token, signal=Signal.MISCONCEPTION, when=None):
        return MinimizedEvent(
            (when or datetime.now(UTC)).isoformat(),
            "loops",
            "a1",
            "sr",
            "programming.equality",
            signal,
            token,
        )

    def test_suppresses_small_groups_and_never_stores_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.sqlite"
            with WeatherStore(
                path, secret=b"0123456789abcdef0123456789abcdef", minimum_group_size=3
            ) as store:
                store.ingest(self.event("daily-a"))
                store.ingest(self.event("daily-b"))
                self.assertEqual(store.aggregate(), ())
                store.ingest(self.event("daily-c"))
                self.assertEqual(store.aggregate()[0].contributor_count, 3)
                stored = store.connection.execute("SELECT contributor_hash FROM events").fetchall()
                self.assertNotIn("daily-a", str(stored))

    def test_purges_expired_events(self):
        with tempfile.TemporaryDirectory() as directory:
            with WeatherStore(
                Path(directory) / "w.sqlite",
                secret=b"0123456789abcdef0123456789abcdef",
                retention_days=7,
            ) as store:
                store.ingest(self.event("old", when=datetime.now(UTC) - timedelta(days=8)))
                self.assertEqual(store.purge_expired(), 1)

    def test_bounds_repeated_contributions_and_coarsens_timestamps(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            WeatherStore(
                Path(directory) / "w.sqlite",
                secret=b"0123456789abcdef0123456789abcdef",
                minimum_group_size=2,
                max_events_per_contributor_per_cell=2,
            ) as store,
        ):
            for _ in range(10):
                store.ingest(self.event("same-token"))
            store.ingest(self.event("other-token"))
            cell = store.aggregate()[0]
            self.assertEqual(cell.event_count, 3)
            timestamps = store.connection.execute(
                "SELECT DISTINCT occurred_at FROM events"
            ).fetchall()
            self.assertTrue(all(len(value[0]) == 10 for value in timestamps))

    def test_import_rejects_raw_conversation_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(
                '{"events":[{"occurred_at":"2026-01-01T00:00:00+00:00","course_key":"c","activity_key":"a","language":"en","concept_id":"x","signal":"frustration","contribution_token":"t","raw_question":"my name is"}]}'
            )
            with self.assertRaisesRegex(ValueError, "prohibited"):
                load_events(path)

    def test_cli_exports_only_thresholded_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "events.json"
            events.write_text(
                json.dumps({"events": [as_event(self.event(f"token-{i}")) for i in range(3)]})
            )
            secret = root / "secret"
            secret.write_text("0123456789abcdef0123456789abcdef")
            secret.chmod(0o600)
            ledger = root / "ledger"
            ledger.write_text("abcdef0123456789abcdef0123456789")
            ledger.chmod(0o600)
            output = root / "map.json"
            result = main(
                [
                    "weather",
                    str(events),
                    "--database",
                    str(root / "weather.sqlite"),
                    "--secret-file",
                    str(secret),
                    "--ledger-key-file",
                    str(ledger),
                    "--minimum-group-size",
                    "3",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(result, 0)
            data = json.loads(output.read_text())
            self.assertGreaterEqual(data["cells"][0]["contributor_count"], 0)
            self.assertEqual(data["privacy"]["mechanism"], "central-laplace-differential-privacy")
            self.assertNotIn("contributor_hash", output.read_text())
            dashboard = output.with_suffix(".html")
            self.assertIn("privacy boundary", dashboard.read_text().casefold())
            self.assertNotIn("token-0", dashboard.read_text())

    def test_exports_are_coarsened_and_rate_limit_differencing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(UTC)
            with WeatherStore(
                root / "weather.sqlite",
                secret=b"0123456789abcdef0123456789abcdef",
                minimum_group_size=2,
                count_granularity=2,
            ) as store:
                for index in range(3):
                    store.ingest(self.event(f"token-{index}"))
                store.export(root / "first.json", now=now)
                first = json.loads((root / "first.json").read_text())
                self.assertEqual(first["schema_version"], "3.0")
                self.assertEqual(first["privacy"]["epsilon_spent"], 1)
                store.ingest(self.event("token-new"))
                with self.assertRaisesRegex(ValueError, "differencing"):
                    store.export(root / "second.json", now=now + timedelta(hours=1))
                self.assertEqual(
                    store.connection.execute("SELECT epsilon_spent FROM dp_budget").fetchone()[0],
                    1,
                )
                store.export(root / "second.json", now=now + timedelta(hours=25))
                store.verify_export_artifact(root / "second.json", artifact_kind="json")
                (root / "second.json").write_text("tampered")
                with self.assertRaisesRegex(ValueError, "inconsistent"):
                    store.verify_export_artifact(root / "second.json", artifact_kind="json")

    def test_dp_release_is_memoized_and_budgeted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with WeatherStore(
                root / "weather.sqlite",
                secret=b"0123456789abcdef0123456789abcdef",
                minimum_group_size=2,
                count_granularity=1,
                dp_epsilon=0.5,
                dp_total_epsilon=1.0,
            ) as store:
                store.ingest(self.event("one"))
                store.ingest(self.event("two"))
                with patch("eii.weather_dp.secrets.randbits", return_value=2**52):
                    store.export(root / "one.json")
                    store.export(root / "same.json")
                self.assertEqual((root / "one.json").read_text(), (root / "same.json").read_text())
                self.assertEqual(
                    store.connection.execute("SELECT epsilon_spent FROM dp_budget").fetchone()[0],
                    0.5,
                )
                store.ingest(self.event("three"))
                store.export(root / "two.json", now=datetime.now(UTC) + timedelta(hours=25))
                store.ingest(self.event("four"))
                with self.assertRaisesRegex(ValueError, "budget exhausted"):
                    store.export(root / "three.json", now=datetime.now(UTC) + timedelta(hours=50))
                for kwargs, message in (
                    ({"epsilon": 0, "epsilon_limit": 1, "event_sensitivity": 1}, "epsilon"),
                    ({"epsilon": 1, "epsilon_limit": 0, "event_sensitivity": 1}, "within budget"),
                    ({"epsilon": 2, "epsilon_limit": 1, "event_sensitivity": 1}, "within budget"),
                    ({"epsilon": 1, "epsilon_limit": 1, "event_sensitivity": 0}, "sensitivity"),
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        release_counts(
                            store.connection,
                            scope="validation",
                            snapshot_hash="snapshot",
                            cells=[],
                            **kwargs,
                        )

            with self.assertRaisesRegex(ValueError, "immutable"):
                WeatherStore(
                    root / "weather.sqlite",
                    secret=b"0123456789abcdef0123456789abcdef",
                    minimum_group_size=2,
                    dp_total_epsilon=2,
                )

            with self.assertRaisesRegex(ValueError, "epsilon"):
                WeatherStore(
                    root / "epsilon.sqlite",
                    secret=b"0123456789abcdef0123456789abcdef",
                    dp_epsilon=2,
                    dp_total_epsilon=1,
                )
            with self.assertRaises(ValueError):
                WeatherStore(
                    root / "invalid.sqlite",
                    secret=b"0123456789abcdef0123456789abcdef",
                    count_granularity=0,
                )

    def test_empty_release_spends_no_privacy_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with WeatherStore(root / "empty.db", secret=b"x" * 32) as store:
                store.export(root / "empty.json")
                payload = json.loads((root / "empty.json").read_text())
                self.assertEqual(payload["cells"], [])
                self.assertEqual(payload["privacy"]["epsilon_per_release"], 0)
                self.assertEqual(
                    store.connection.execute("SELECT epsilon_spent FROM dp_budget").fetchone()[0],
                    0,
                )


def as_event(event):
    return {
        "occurred_at": event.occurred_at,
        "course_key": event.course_key,
        "activity_key": event.activity_key,
        "language": event.language,
        "concept_id": event.concept_id,
        "signal": event.signal.value,
        "contribution_token": event.contribution_token,
    }


if __name__ == "__main__":
    unittest.main()

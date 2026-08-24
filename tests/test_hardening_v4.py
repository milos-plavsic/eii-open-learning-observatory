import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from eii.alignment import Alignment
from eii.babel_semantic import SemanticReleasePolicy
from eii.domain import (
    ContentBlock,
    CourseRelease,
    EvidenceRef,
    ModelRun,
    SourceLocator,
    UnitKind,
    content_hash,
    to_dict,
)
from eii.retrieval import BM25Retriever
from eii.semantic_policy import _decision_policy, _policy_controls, load_semantic_policy
from eii.semantic_records import SemanticEvaluationRecord, model_run_id, parse_semantic_records
from eii.weather import WeatherStore
from eii.weather_dp import release_counts
from eii.weather_privacy import authorize_export, record_export
from eii.weather_publication import (
    _fsync_directory,
    _journal_mac,
    _journal_values,
    _recover_destination,
    recover_publications,
)


class HardeningV4Tests(unittest.TestCase):
    def test_alignment_and_semantic_policy_boundaries(self):
        valid = Alignment("concept", (("release", "block"),), None, "explicit-concept")
        with self.assertRaisesRegex(TypeError, "immutable"):
            valid.score_components["new"] = 1  # type: ignore[index]
        for changed in (
            {"concept_id": ""},
            {"alignment_score": 2},
            {"score_version": "unknown"},
            {"confidence": 2},
            {"score_components": {"bad": 2}},
        ):
            with self.assertRaises(ValueError):
                replace(valid, **changed)
        for policy in (
            (0.7, 0.4, None, False),
            (0.7, 0.5, 2, False),
            (0.7, 0.5, None, False, -1),
        ):
            with self.assertRaises(ValueError):
                SemanticReleasePolicy(*policy)
        for kwargs in (
            {"threshold": 0.7, "minimum_agreement_ratio": 0.4},
            {"threshold": 0.7, "maximum_minority_confidence": 2},
            {"threshold": 0.7, "maximum_failed_members": True},
        ):
            with self.assertRaises(ValueError):
                load_semantic_policy(**kwargs)
        for document in (
            {"minimum_agreement_ratio": "bad"},
            {"maximum_minority_confidence": True},
            {"require_unanimity": "yes"},
        ):
            with self.assertRaisesRegex(ValueError, "decision-signal policy"):
                _decision_policy(document, 0.5, None, False)

        from eii.semantics import ConsensusSemanticComparator

        with self.assertRaisesRegex(ValueError, "within the panel"):
            ConsensusSemanticComparator((object(), object(), object()), max_failed_members=3)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "smaller than the panel"):
            _policy_controls({"maximum_failed_members": 3}, [], 3)

    def test_legacy_semantic_record_migration_and_property_validation(self):
        run = ModelRun("provider", "model", "version", {}, "input", "output")
        ref = EvidenceRef("release", "block", "sha256:" + "1" * 64, "excerpt")
        current = to_dict(
            SemanticEvaluationRecord(
                "",
                "relationship",
                (ref,),
                (ref,),
                "equivalent",
                1,
                {"same": True},
                "supported",
                model_run_id(run),
            )
        )
        legacy = {key: value for key, value in current.items() if key != "decision_signals"}
        legacy["schema_version"] = "1.0"
        legacy["id"] = content_hash({key: value for key, value in legacy.items() if key != "id"})
        migrated = parse_semantic_records([legacy])[0]
        self.assertEqual(migrated.schema_version, "2.0")
        broken = dict(legacy)
        broken["id"] = content_hash("wrong")
        with self.assertRaisesRegex(ValueError, "legacy semantic evaluation id"):
            parse_semantic_records([broken])

        for property_signals, message in (
            ([], "must be an object"),
            ({"": {}}, "fields do not match"),
            ({"same": {}}, "fields do not match"),
            (
                {
                    "same": {
                        "agreement_ratio": 2,
                        "majority_mean_confidence": None,
                        "minority_mean_confidence": None,
                    }
                },
                "between zero and one",
            ),
        ):
            changed = dict(current)
            changed["id"] = ""
            changed["decision_signals"] = {
                **current["decision_signals"],
                "property_signals": property_signals,
            }
            with self.assertRaisesRegex(ValueError, message):
                parse_semantic_records([changed])

        valid_signal = {
            "agreement_ratio": None,
            "majority_mean_confidence": 1,
            "minority_mean_confidence": None,
        }
        changed = dict(current)
        changed["id"] = ""
        changed["decision_signals"] = {
            **current["decision_signals"],
            "property_signals": {"one": valid_signal, "two": valid_signal},
        }
        self.assertEqual(len(parse_semantic_records([changed])), 1)
        changed["decision_signals"]["property_signals"]["two"] = {
            **valid_signal,
            "minority_mean_confidence": 2,
        }
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            parse_semantic_records([changed])
        changed = dict(current)
        changed["id"] = ""
        changed["decision_signals"] = {
            **current["decision_signals"],
            "failed_member_count": -1,
        }
        with self.assertRaisesRegex(ValueError, "failed member count"):
            parse_semantic_records([changed])

    def test_retrieval_plan_without_glossary(self):
        block = ContentBlock(
            "block",
            UnitKind.SECTION,
            "Assignment",
            "Assign a value.",
            0,
            SourceLocator("fixture", "course", "lesson.md"),
        )
        course = CourseRelease("release", "course", "en", "1", "Course", (block,), block.locator)
        plan = BM25Retriever().query_plan(course, "assignment")
        self.assertEqual(plan["expanded_terms"], ())
        self.assertEqual(plan["glossary_concept_ids"], ())

    def test_weather_budget_and_export_policy_defenses(self):
        with tempfile.TemporaryDirectory() as directory:
            with WeatherStore(Path(directory) / "weather.db", secret=b"w" * 32) as store:
                release_counts(
                    store.connection,
                    scope="empty",
                    snapshot_hash="one",
                    cells=[],
                    epsilon=1,
                    epsilon_limit=10,
                    event_sensitivity=1,
                )
                with self.assertRaisesRegex(ValueError, "budget limit is immutable"):
                    release_counts(
                        store.connection,
                        scope="empty",
                        snapshot_hash="two",
                        cells=[],
                        epsilon=1,
                        epsilon_limit=9,
                        event_sensitivity=1,
                    )
                now = datetime.now(UTC)
                record_export(
                    store.connection,
                    scope="course",
                    strategy="course-partitioned",
                    artifact_kind="json",
                    exported_at=now,
                    snapshot_hash="one",
                    artifact_hash="a",
                    minimum_interval=timedelta(hours=24),
                    ledger_key=store.ledger_key,
                )
                with self.assertRaisesRegex(ValueError, "partition strategy"):
                    record_export(
                        store.connection,
                        scope="course",
                        strategy="global",
                        artifact_kind="json",
                        exported_at=now + timedelta(microseconds=1),
                        snapshot_hash="one",
                        artifact_hash="a",
                        minimum_interval=timedelta(hours=24),
                        ledger_key=store.ledger_key,
                    )
                with self.assertRaisesRegex(ValueError, "export interval"):
                    record_export(
                        store.connection,
                        scope="course",
                        strategy="course-partitioned",
                        artifact_kind="json",
                        exported_at=now + timedelta(hours=1),
                        snapshot_hash="two",
                        artifact_hash="b",
                        minimum_interval=timedelta(hours=24),
                        ledger_key=store.ledger_key,
                    )
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    record_export(
                        store.connection,
                        scope="course",
                        strategy="course-partitioned",
                        artifact_kind="json",
                        exported_at=now,
                        snapshot_hash="one",
                        artifact_hash="a",
                        minimum_interval=timedelta(),
                        ledger_key=store.ledger_key,
                    )

    def test_weather_publication_rolls_back_and_recovers_authenticated_journal(self):
        secret, ledger = b"s" * 32, b"l" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, destination = root / "weather.db", root / "map.json"
            destination.write_bytes(b"old")
            with WeatherStore(database, secret=secret, ledger_key=ledger) as store:
                with patch(
                    "eii.weather_publication.record_export", side_effect=RuntimeError("db failed")
                ):
                    with self.assertRaisesRegex(RuntimeError, "db failed"):
                        store.export(destination)
                self.assertEqual(destination.read_bytes(), b"old")
                self.assertEqual(
                    store.connection.execute(
                        "SELECT COUNT(*) FROM privacy_publication_journal"
                    ).fetchone()[0],
                    0,
                )

                # Installed but unledgered output is rolled back in the live failure path.
                installed = b"unledgered"
                destination.write_bytes(installed)
                staged = root / ".eii-weather-staged-live"
                backup = root / ".eii-weather-backup-live"
                backup.write_bytes(b"old")
                values = _journal_values(
                    destination.absolute(),
                    staged.absolute(),
                    backup.absolute(),
                    hashlib.sha256(b"old").hexdigest(),
                    "*",
                    "global",
                    "html",
                    datetime.now(UTC),
                    "snapshot-live",
                    hashlib.sha256(installed).hexdigest(),
                )
                store.connection.execute(
                    "INSERT INTO privacy_publication_journal "
                    "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                    "exported_at,snapshot_hash,artifact_hash,record_mac) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*values, _journal_mac(values, ledger)),
                )
                store.connection.commit()
                self.assertEqual(
                    _recover_destination(
                        store.connection,
                        str(destination.absolute()),
                        ledger_key=ledger,
                        complete_installed=False,
                    ),
                    1,
                )
                self.assertEqual(destination.read_bytes(), b"old")

                installed = b"recovered artifact"
                destination.write_bytes(installed)
                staged = root / ".eii-weather-staged-fixture"
                backup = root / ".eii-weather-backup-fixture"
                backup.write_bytes(b"old")
                exported_at = datetime.now(UTC) + timedelta(hours=25)
                values = _journal_values(
                    destination.absolute(),
                    staged.absolute(),
                    backup.absolute(),
                    hashlib.sha256(b"old").hexdigest(),
                    "*",
                    "global",
                    "json",
                    exported_at,
                    "snapshot",
                    hashlib.sha256(installed).hexdigest(),
                )
                store.connection.execute(
                    "INSERT INTO privacy_publication_journal "
                    "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                    "exported_at,snapshot_hash,artifact_hash,record_mac) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*values, _journal_mac(values, ledger)),
                )
                store.connection.commit()
            with WeatherStore(database, secret=secret, ledger_key=ledger) as recovered:
                self.assertEqual(destination.read_bytes(), installed)
                recovered.verify_export_artifact(destination, artifact_kind="json")
                self.assertFalse(backup.exists())
                self.assertEqual(
                    recovered.connection.execute(
                        "SELECT COUNT(*) FROM privacy_publication_journal"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    _recover_destination(recovered.connection, "absent", ledger_key=ledger),
                    0,
                )

                unrelated = root / "unrelated.json"
                unrelated.write_bytes(b"unrelated")
                staged = root / ".eii-weather-staged-unrelated"
                values = _journal_values(
                    unrelated.absolute(),
                    staged.absolute(),
                    None,
                    None,
                    "*",
                    "global",
                    "json",
                    datetime.now(UTC),
                    "snapshot",
                    hashlib.sha256(b"expected").hexdigest(),
                )
                recovered.connection.execute(
                    "INSERT INTO privacy_publication_journal "
                    "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                    "exported_at,snapshot_hash,artifact_hash,record_mac) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*values, _journal_mac(values, ledger)),
                )
                recovered.connection.commit()
                with self.assertRaisesRegex(ValueError, "unrelated destination"):
                    recover_publications(
                        recovered.connection, ledger_key=ledger, minimum_interval=timedelta()
                    )

    def test_weather_publication_recovers_pre_move_and_rejects_tampered_journal(self):
        secret, ledger = b"s" * 32, b"l" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, destination = root / "weather.db", root / "map.json"
            old, staged_bytes = b"old", b"new"
            destination.write_bytes(old)
            with WeatherStore(database, secret=secret, ledger_key=ledger) as store:
                staged = root / ".eii-weather-staged-pre-move"
                backup = root / ".eii-weather-backup-pre-move"
                staged.write_bytes(staged_bytes)
                values = _journal_values(
                    destination.absolute(),
                    staged.absolute(),
                    backup.absolute(),
                    hashlib.sha256(old).hexdigest(),
                    "*",
                    "global",
                    "json",
                    datetime.now(UTC),
                    "snapshot",
                    hashlib.sha256(staged_bytes).hexdigest(),
                )
                store.connection.execute(
                    "INSERT INTO privacy_publication_journal "
                    "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                    "exported_at,snapshot_hash,artifact_hash,record_mac) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*values, _journal_mac(values, ledger)),
                )
                store.connection.commit()
                self.assertEqual(
                    recover_publications(
                        store.connection, ledger_key=ledger, minimum_interval=timedelta()
                    ),
                    1,
                )
                self.assertEqual(destination.read_bytes(), old)
                self.assertFalse(staged.exists())

                staged.write_bytes(staged_bytes)
                store.connection.execute(
                    "INSERT INTO privacy_publication_journal "
                    "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                    "exported_at,snapshot_hash,artifact_hash,record_mac) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*values, "0" * 64),
                )
                store.connection.commit()
                with self.assertRaisesRegex(ValueError, "authentication"):
                    recover_publications(
                        store.connection, ledger_key=ledger, minimum_interval=timedelta()
                    )
                self.assertEqual(destination.read_bytes(), old)

                with self.assertRaisesRegex(ValueError, "unsafe"):
                    from eii.weather_publication import _validate_recovery_paths

                    _validate_recovery_paths(destination, root / "ordinary", None)

                store.connection.execute(
                    "DELETE FROM privacy_publication_journal WHERE destination=?",
                    (str(destination.absolute()),),
                )
                store.connection.commit()
                self.assertEqual(
                    recover_publications(
                        store.connection, ledger_key=ledger, minimum_interval=timedelta()
                    ),
                    0,
                )

    def test_weather_ledger_binding_time_and_authenticated_verification(self):
        secret, ledger = b"s" * 32, b"l" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, artifact = root / "weather.db", root / "map.json"
            now = datetime.now(UTC)
            with WeatherStore(database, secret=secret, ledger_key=ledger) as store:
                with self.assertRaisesRegex(ValueError, "timezone"):
                    authorize_export(
                        store.connection,
                        scope="*",
                        strategy="global",
                        snapshot_hash="one",
                        exported_at=datetime.now(),
                        minimum_interval=timedelta(),
                    )
                store.export(artifact, now=now)
                store.connection.execute(
                    "UPDATE privacy_exports_v3 SET artifact_hash=?", ("0" * 64,)
                )
                store.connection.commit()
                store.verify_export_artifact(artifact, artifact_kind="json")
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    authorize_export(
                        store.connection,
                        scope="*",
                        strategy="global",
                        snapshot_hash="two",
                        exported_at=now,
                        minimum_interval=timedelta(),
                    )
            with self.assertRaisesRegex(ValueError, "ledger key"):
                WeatherStore(database, secret=secret, ledger_key=b"x" * 32)
            with patch("eii.weather_publication.os.name", "nt"):
                _fsync_directory(root)

    def test_weather_publication_remaining_recovery_states(self):
        secret, ledger = b"s" * 32, b"l" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with WeatherStore(root / "weather.db", secret=secret, ledger_key=ledger) as store:

                def journal(destination: Path, backup: Path | None, kind: str) -> None:
                    artifact_hash = (
                        hashlib.sha256(destination.read_bytes()).hexdigest()
                        if destination.exists()
                        else hashlib.sha256(b"new").hexdigest()
                    )
                    staged = root / f".eii-weather-staged-{kind}"
                    values = _journal_values(
                        destination.absolute(),
                        staged.absolute(),
                        backup.absolute() if backup else None,
                        hashlib.sha256(b"old").hexdigest() if backup else None,
                        "*",
                        "global",
                        kind,
                        datetime.now(UTC),
                        "snapshot",
                        artifact_hash,
                    )
                    store.connection.execute(
                        "INSERT INTO privacy_publication_journal "
                        "(destination,staged_path,backup_path,prior_hash,scope,strategy,artifact_kind,"
                        "exported_at,snapshot_hash,artifact_hash,record_mac) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (*values, _journal_mac(values, ledger)),
                    )
                    store.connection.commit()

                indexed = root / "indexed.json"
                store.export(indexed)
                journal(indexed, None, "json")
                _recover_destination(
                    store.connection,
                    str(indexed.absolute()),
                    ledger_key=ledger,
                    complete_installed=False,
                )
                self.assertTrue(indexed.exists())

                unindexed = root / "unindexed.html"
                unindexed.write_bytes(b"new")
                journal(unindexed, None, "html")
                _recover_destination(
                    store.connection,
                    str(unindexed.absolute()),
                    ledger_key=ledger,
                    complete_installed=False,
                )
                self.assertFalse(unindexed.exists())

                missing = root / "missing.csv"
                backup = root / ".eii-weather-backup-csv"
                backup.write_bytes(b"old")
                journal(missing, backup, "csv")
                _recover_destination(store.connection, str(missing.absolute()), ledger_key=ledger)
                self.assertEqual(missing.read_bytes(), b"old")

                absent = root / "absent.txt"
                journal(absent, None, "txt")
                _recover_destination(store.connection, str(absent.absolute()), ledger_key=ledger)
                self.assertFalse(absent.exists())


if __name__ == "__main__":
    unittest.main()

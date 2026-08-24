"""Bounded real-mutation gate for critical trust decisions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
PROBES = (
    (
        "src/eii/crypto.py",
        "if process.returncode:",
        "if not process.returncode:",
        "tests.test_crypto",
    ),
    (
        "src/eii/persistence.py",
        'if integrity != "ok":',
        'if integrity == "ok":',
        "tests.test_persistence",
    ),
    (
        "src/eii/plct_conformance.py",
        'compatible = all(check.passed for check in checks if check.name != "petlja-attestation")',
        'compatible = not all(check.passed for check in checks if check.name != "petlja-attestation")',
        "tests.test_plct_conformance",
    ),
    ("src/eii/supply_chain.py", "if not paths:", "if paths:", "tests.test_supply_chain"),
    (
        "src/eii/safety_verification.py",
        'if not hmac.compare_digest(str(document.get("manifest_digest", "")), digest):',
        'if hmac.compare_digest(str(document.get("manifest_digest", "")), digest):',
        "tests.test_safety_defensive",
    ),
    (
        "src/eii/weather.py",
        "if existing >= self.max_events_per_contributor_per_cell:",
        "if existing < self.max_events_per_contributor_per_cell:",
        "tests.test_weather",
    ),
    (
        "src/eii/models.py",
        'if endpoint.scheme == "http" and endpoint.hostname not in {',
        'if endpoint.scheme != "http" and endpoint.hostname not in {',
        "tests.test_defensive_paths.ModelEditorialSemanticTests",
    ),
    (
        "src/eii/retrieval.py",
        "if score > 0:",
        "if score <= 0:",
        "tests.test_retrieval",
    ),
    (
        "src/eii/safety.py",
        "or course_blocks[item.block_id].text != item.text",
        "or course_blocks[item.block_id].text == item.text",
        "tests.test_safety",
    ),
    (
        "src/eii/safety.py",
        "if gate_results and all(gate_results.values())",
        "if gate_results and not all(gate_results.values())",
        "tests.test_safety",
    ),
    (
        "src/eii/weather_privacy.py",
        "and previous[1] != snapshot_hash",
        "and previous[1] == snapshot_hash",
        "tests.test_weather",
    ),
    (
        "src/eii/supply_chain.py",
        "if actual_dependencies != expected_dependencies:",
        "if actual_dependencies == expected_dependencies:",
        "tests.test_supply_chain",
    ),
    (
        "src/eii/babelbridge.py",
        "for base_index in left:",
        "for base_index in left[:1]:",
        "tests.test_babelbridge",
    ),
    (
        "src/eii/babel_semantic.py",
        'if outcome == "abstained":',
        'if outcome != "abstained":',
        "tests.test_babelbridge",
    ),
    (
        "src/eii/semantic_aggregation.py",
        "equivalent = whole_vote is True and property_vote and not inconclusive",
        "equivalent = whole_vote is True or property_vote or not inconclusive",
        "tests.test_semantic_consensus",
    ),
    (
        "src/eii/semantic_aggregation.py",
        "if len(identities) != len(set(identities)):",
        "if len(identities) == len(set(identities)):",
        "tests.test_semantic_consensus",
    ),
    (
        "src/eii/safety.py",
        'return any(f" {words(marker)} " in padded for marker in markers)',
        'return any(f" {words(marker)} " not in padded for marker in markers)',
        "tests.test_safety",
    ),
    (
        "src/eii/alignment_relationships.py",
        "if left_translation and right_translation:\n        return PairScore(",
        "if left_translation or right_translation:\n        return PairScore(",
        "tests.test_babelbridge",
    ),
    (
        "src/eii/alignment_relationships.py",
        "if any(member in review_blocks for member in alignment.members)",
        "if not any(member in review_blocks for member in alignment.members)",
        "tests.test_babelbridge",
    ),
    (
        "src/eii/evidence.py",
        "if reference.excerpt != (actual_block.text[:240] or None):",
        "if reference.excerpt == (actual_block.text[:240] or None):",
        "tests.test_evidence",
    ),
    (
        "src/eii/audit_package.py",
        "if _snapshot(directory) != files:",
        "if _snapshot(directory) == files:",
        "tests.test_audit_package",
    ),
    (
        "src/eii/semantic_aggregation.py",
        "and (bool(failures) or total_cost is None or total_cost > max_total_cost)",
        "and (not failures or total_cost is None or total_cost > max_total_cost)",
        "tests.test_semantic_consensus",
    ),
    (
        "src/eii/semantic_aggregation.py",
        "agreement = len(aligned) / panel_size",
        "agreement = len(aligned) / len(judgments)",
        "tests.test_semantic_consensus",
    ),
    (
        "src/eii/weather_privacy.py",
        "if row and not hmac.compare_digest(row[0], fingerprint):",
        "if row and hmac.compare_digest(row[0], fingerprint):",
        "tests.test_hardening_v4",
    ),
)


def main() -> None:
    for relative, original, mutation, test_module in PROBES:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "src", root / "src")
            shutil.copytree(ROOT / "tests", root / "tests")
            target = root / relative
            source = target.read_text("utf-8")
            if source.count(original) < 1:
                raise RuntimeError(f"mutation anchor missing: {relative}: {original}")
            target.write_text(source.replace(original, mutation, 1), "utf-8")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(root / "src")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", test_module],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                raise RuntimeError(
                    f"surviving critical mutant in {relative}: {original} -> {mutation}"
                )
            print(f"killed mutation: {relative}")


if __name__ == "__main__":
    main()

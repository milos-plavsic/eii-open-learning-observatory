"""Release-to-release evidence comparison for editorial and CI regression use."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _key(finding: Mapping[str, Any]) -> str:
    blocks = sorted(item["block_id"] for item in finding.get("evidence", ()))
    return json.dumps([finding["finding_type"], blocks], ensure_ascii=False, separators=(",", ":"))


def compare_bundles(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    old = {_key(item): item for item in previous["findings"]}
    new = {_key(item): item for item in current["findings"]}
    persistent = sorted(old.keys() & new.keys())
    return {
        "schema_version": "1.0",
        "previous_bundle": previous["id"],
        "current_bundle": current["id"],
        "added": [new[key] for key in sorted(new.keys() - old.keys())],
        "resolved": [old[key] for key in sorted(old.keys() - new.keys())],
        "persistent": [{"before": old[key], "after": new[key]} for key in persistent],
        "regression": bool(new.keys() - old.keys()),
    }


def compare_files(previous: Path, current: Path, output: Path) -> dict[str, Any]:
    result = compare_bundles(
        json.loads(previous.read_text("utf-8")), json.loads(current.read_text("utf-8"))
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return result

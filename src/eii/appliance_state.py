"""Atomic appliance configuration, activation recovery, and onboarding state."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from .appliance_types import ApplianceConfig
from .qr import qr_svg


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    os.replace(temporary, path)


def active_release(appliance_root: Path) -> Path:
    pointer = json.loads((appliance_root / "active.json").read_text("utf-8"))
    release = appliance_root / "releases" / pointer["package_id"]
    if not release.is_dir():
        raise ValueError("active release is missing")
    return cast(Path, release)


def rollback(appliance_root: Path) -> dict[str, str]:
    history_path = appliance_root / "activation-history.jsonl"
    entries = [
        json.loads(line) for line in history_path.read_text("utf-8").splitlines() if line.strip()
    ]
    if not entries or not entries[-1].get("previous"):
        raise ValueError("no previous release is available for rollback")
    target = entries[-1]["previous"]
    release = appliance_root / "releases" / target["package_id"]
    if not release.is_dir():
        raise ValueError("previous release files are missing")
    current = json.loads((appliance_root / "active.json").read_text("utf-8"))
    temporary = appliance_root / ".active.json.tmp"
    temporary.write_text(json.dumps(target) + "\n", "utf-8")
    os.replace(temporary, appliance_root / "active.json")
    with history_path.open("a", encoding="utf-8") as history:
        history.write(
            json.dumps(
                {
                    "activated_at": datetime.now(UTC).isoformat(),
                    "previous": current,
                    "current": target,
                    "rollback": True,
                }
            )
            + "\n"
        )
    return cast(dict[str, str], target)


def recover_active_release(appliance_root: Path) -> dict[str, str]:
    history_path = appliance_root / "activation-history.jsonl"
    if not history_path.exists():
        raise ValueError("activation history is unavailable")
    entries = [
        json.loads(line) for line in history_path.read_text("utf-8").splitlines() if line.strip()
    ]
    candidates = [entry.get("current") for entry in reversed(entries)]
    target = next(
        (
            item
            for item in candidates
            if item
            and (appliance_root / "releases" / item["package_id"] / "manifest.json").is_file()
        ),
        None,
    )
    if target is None:
        raise ValueError("no intact release can be recovered from activation history")
    atomic_json(appliance_root / "active.json", target)
    with history_path.open("a", encoding="utf-8") as history:
        history.write(
            json.dumps(
                {
                    "activated_at": datetime.now(UTC).isoformat(),
                    "previous": None,
                    "current": target,
                    "recovery": True,
                }
            )
            + "\n"
        )
    return cast(dict[str, str], target)


def configure(appliance_root: Path, config: ApplianceConfig) -> None:
    appliance_root.mkdir(parents=True, exist_ok=True)
    atomic_json(appliance_root / "config.json", asdict(config))


def read_config(appliance_root: Path) -> ApplianceConfig | None:
    path = appliance_root / "config.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text("utf-8"))
    return ApplianceConfig(
        tuple(data["selected_courses"]),
        tuple(data["allowed_languages"]),
        data.get("assistant_behavior", "hint-first"),
    )


def write_onboarding_page(destination: Path, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("onboarding URL must be an explicit local HTTP URL")
    svg = qr_svg(url)
    page = (
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<link rel='icon' href='data:,'>"
        "<title>Connect to School-in-a-Box</title><style>body{font:18px system-ui;text-align:center;padding:2rem}"
        "svg{max-width:80vw;height:auto}</style><main><h1>Connect to the classroom server</h1>"
        + svg
        + f"<p><a href='{url}'>{url}</a></p><p>No account or internet connection is required.</p></main></html>"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, "utf-8")

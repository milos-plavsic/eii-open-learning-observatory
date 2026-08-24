"""Publisher trust-store initialization, rotation, and trusted installation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import cast

from .appliance_state import atomic_json
from .appliance_types import PackageManifest
from .crypto import public_key_fingerprint, sign_ed25519, verify_ed25519


def initialize_trust(appliance_root: Path, public_key: Path) -> str:
    import shutil

    fingerprint = public_key_fingerprint(public_key)
    trust = appliance_root / "trust"
    keys = trust / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(public_key, keys / f"{fingerprint}.pem")
    from datetime import UTC, datetime

    state = {
        "schema_version": "1.0",
        "trusted_keys": [fingerprint],
        "updated_at": datetime.now(UTC).isoformat(),
    }
    atomic_json(trust / "state.json", state)
    with (trust / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(
            json.dumps(
                {"action": "initialize", "fingerprint": fingerprint, "at": state["updated_at"]}
            )
            + "\n"
        )
    return fingerprint


def create_trust_rotation(
    current_private_key: Path,
    current_public_key: Path,
    new_public_key: Path,
    destination: Path,
    *,
    revoke_old: bool = False,
) -> None:
    from datetime import UTC, datetime

    statement = {
        "schema_version": "1.0",
        "old_fingerprint": public_key_fingerprint(current_public_key),
        "new_fingerprint": public_key_fingerprint(new_public_key),
        "new_public_key": new_public_key.read_text("utf-8"),
        "revoke_old": revoke_old,
        "created_at": datetime.now(UTC).isoformat(),
    }
    body = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    payload = {"statement": statement, "signature": sign_ed25519(body, current_private_key)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def apply_trust_rotation(appliance_root: Path, authorization: Path) -> str:
    from datetime import UTC, datetime

    trust = appliance_root / "trust"
    state_path = trust / "state.json"
    state = json.loads(state_path.read_text("utf-8"))
    payload = json.loads(authorization.read_text("utf-8"))
    statement = payload["statement"]
    old = statement["old_fingerprint"]
    if old not in state["trusted_keys"]:
        raise ValueError("rotation is not authorized by a currently trusted key")
    body = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    if not verify_ed25519(body, payload["signature"], trust / "keys" / f"{old}.pem"):
        raise ValueError("trust rotation signature verification failed")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as candidate:
        candidate.write(statement["new_public_key"])
        candidate.flush()
        actual = public_key_fingerprint(Path(candidate.name))
    if actual != statement["new_fingerprint"]:
        raise ValueError("rotated public key fingerprint mismatch")
    new = statement["new_fingerprint"]
    (trust / "keys" / f"{new}.pem").write_text(statement["new_public_key"], "utf-8")
    trusted = (
        [new] if statement.get("revoke_old") else list(dict.fromkeys([*state["trusted_keys"], new]))
    )
    state = {
        "schema_version": "1.0",
        "trusted_keys": trusted,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    atomic_json(state_path, state)
    with (trust / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(
            json.dumps(
                {
                    "action": "rotate",
                    "old_fingerprint": old,
                    "new_fingerprint": new,
                    "revoke_old": bool(statement.get("revoke_old")),
                    "at": state["updated_at"],
                }
            )
            + "\n"
        )
    return cast(str, new)


def install_trusted_package(
    package: Path,
    appliance_root: Path,
    *,
    safety_public_key: Path | None = None,
    trusted_reviewer_fingerprints: frozenset[str] = frozenset(),
) -> PackageManifest:
    from .appliance import install_package

    trust = appliance_root / "trust"
    state = json.loads((trust / "state.json").read_text("utf-8"))
    for fingerprint in state["trusted_keys"]:
        public_key = trust / "keys" / f"{fingerprint}.pem"
        try:
            return install_package(
                package,
                appliance_root,
                public_key=public_key,
                safety_public_key=safety_public_key,
                trusted_reviewer_fingerprints=trusted_reviewer_fingerprints,
            )
        except ValueError as error:
            if "signature verification failed" not in str(error):
                raise
    raise ValueError("package is not signed by a currently trusted publisher key")

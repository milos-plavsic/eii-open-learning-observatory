"""Signed evidence records for reviews that EII cannot self-certify."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .crypto import public_key_fingerprint, sign_ed25519, verify_ed25519
from .domain import content_hash

GATE_TYPES = {
    "petlja-integration",
    "human-accuracy",
    "penetration-test",
    "independent-reproduction",
    "target-school-pilot",
}
OUTCOMES = {"passed", "failed", "conditional"}
STATEMENT_FIELDS = {
    "schema_version",
    "gate_type",
    "executed_at",
    "organization",
    "reviewer",
    "scope",
    "procedure_version",
    "subject_hashes",
    "outcome",
    "findings",
    "limitations",
}


def sign_external_record(
    statement_path: Path, destination: Path, *, private_key: Path, public_key: Path
) -> Mapping[str, Any]:
    statement = json.loads(statement_path.read_text("utf-8"))
    if not isinstance(statement, dict) or set(statement) != STATEMENT_FIELDS:
        raise ValueError("external validation statement fields do not match schema")
    if statement["schema_version"] != "1.0" or statement["gate_type"] not in GATE_TYPES:
        raise ValueError("external validation schema version or gate type is invalid")
    if statement["outcome"] not in OUTCOMES or not statement["subject_hashes"]:
        raise ValueError("external validation outcome and subject hashes are required")
    body = json.dumps(statement, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    signature = sign_ed25519(body, private_key)
    if not verify_ed25519(body, signature, public_key):
        raise ValueError("external reviewer private and public keys do not match")
    document = {
        "id": content_hash(statement),
        "statement": statement,
        "key_fingerprint": public_key_fingerprint(public_key),
        "signature": signature,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return document


def verify_external_record(record_path: Path, public_key: Path) -> Mapping[str, Any]:
    document = json.loads(record_path.read_text("utf-8"))
    if not isinstance(document, dict) or set(document) != {
        "id",
        "statement",
        "key_fingerprint",
        "signature",
    }:
        raise ValueError("external validation record fields do not match schema")
    statement = document["statement"]
    if not isinstance(statement, dict) or set(statement) != STATEMENT_FIELDS:
        raise ValueError("external validation statement fields do not match schema")
    if document["id"] != content_hash(statement):
        raise ValueError("external validation record id is invalid")
    if document["key_fingerprint"] != public_key_fingerprint(public_key):
        raise ValueError("external validation key fingerprint does not match")
    body = json.dumps(statement, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if not verify_ed25519(body, str(document["signature"]), public_key):
        raise ValueError("external validation signature verification failed")
    return document

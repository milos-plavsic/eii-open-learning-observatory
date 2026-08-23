"""Cryptographically attributable human-review records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .crypto import (
    public_key_fingerprint,
    public_key_fingerprint_pem,
    sign_ed25519,
    verify_ed25519_pem,
)
from .domain import canonical_json
from .safety_types import HumanEvaluation

_SIGNED_FIELDS = (
    "fixture_id",
    "subject_hash",
    "reviewer",
    "approved",
    "rationale",
    "created_at",
    "reviewer_key_fingerprint",
)


def human_review_payload(review: HumanEvaluation | Mapping[str, Any]) -> dict[str, Any]:
    source: Mapping[str, Any]
    if isinstance(review, HumanEvaluation):
        source = {field: getattr(review, field) for field in _SIGNED_FIELDS}
    else:
        source = review
    return {field: source[field] for field in _SIGNED_FIELDS}


def sign_human_review(
    *,
    fixture_id: str,
    subject_hash: str,
    reviewer: str,
    approved: bool,
    rationale: str,
    created_at: str,
    private_key: Path,
    public_key: Path,
) -> HumanEvaluation:
    if (
        not fixture_id.strip()
        or not subject_hash.startswith("sha256:")
        or len(subject_hash) != 71
        or not reviewer.strip()
        or not rationale.strip()
    ):
        raise ValueError("human review identity and rationale must be non-empty")
    try:
        timestamp = datetime.fromisoformat(created_at)
    except ValueError as error:
        raise ValueError("human review time is invalid") from error
    if timestamp.tzinfo is None:
        raise ValueError("human review time must include a timezone")
    public_pem = public_key.read_text("utf-8")
    fingerprint = public_key_fingerprint(public_key)
    unsigned = {
        "fixture_id": fixture_id,
        "subject_hash": subject_hash,
        "reviewer": reviewer,
        "approved": approved,
        "rationale": rationale,
        "created_at": created_at,
        "reviewer_key_fingerprint": fingerprint,
    }
    signature = sign_ed25519(canonical_json(unsigned).encode(), private_key)
    return HumanEvaluation(
        fixture_id,
        subject_hash,
        reviewer,
        approved,
        rationale,
        created_at,
        public_pem,
        fingerprint,
        signature,
    )


def verify_human_review(review: HumanEvaluation | Mapping[str, Any]) -> None:
    public_pem = (
        review.reviewer_public_key
        if isinstance(review, HumanEvaluation)
        else str(review.get("reviewer_public_key", ""))
    )
    fingerprint = (
        review.reviewer_key_fingerprint
        if isinstance(review, HumanEvaluation)
        else str(review.get("reviewer_key_fingerprint", ""))
    )
    signature = (
        review.signature
        if isinstance(review, HumanEvaluation)
        else str(review.get("signature", ""))
    )
    try:
        actual_fingerprint = public_key_fingerprint_pem(public_pem)
        payload = human_review_payload(review)
    except (KeyError, ValueError) as error:
        raise ValueError("human review key or signed payload is invalid") from error
    if actual_fingerprint != fingerprint:
        raise ValueError("human review key fingerprint does not match its public key")
    if not verify_ed25519_pem(canonical_json(payload).encode(), signature, public_pem):
        raise ValueError("human review signature verification failed")

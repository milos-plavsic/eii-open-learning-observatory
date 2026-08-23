"""Focused CLI handlers for reviewer attribution and privacy-key lifecycle."""

from __future__ import annotations

import argparse
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from . import safety_verification as safety_trust
from .adapters import adapter_for
from .domain import content_hash, to_dict
from .safety_reviews import sign_human_review
from .secureio import write_private_text
from .weather import WeatherStore

SecretLoader = Callable[[Any, str, int, argparse.ArgumentParser], bytes]


def handle_trust_command(
    args: Any, parser: argparse.ArgumentParser, secret_loader: SecretLoader
) -> int | None:
    if args.command == "safety-review-init":
        case = json.loads(args.case.read_text("utf-8"))
        matches = [
            item
            for item in case.get("cases", [])
            if item.get("fixture", {}).get("id") == args.fixture_id
        ]
        if len(matches) != 1:
            parser.error("fixture id must identify exactly one serialized safety case")
        review = {
            "fixture_id": args.fixture_id,
            "subject_hash": content_hash(matches[0]),
            "reviewer": args.reviewer,
            "approved": args.decision == "approve",
            "rationale": args.rationale,
            "created_at": datetime.now(UTC).isoformat(),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(f"Initialized case-bound human safety review: {args.output}")
        return 0
    if args.command == "safety-verify":
        adapter = adapter_for(args.course)
        if adapter is None:
            parser.error(f"no compatible adapter for {args.course}")
        course = adapter.load(args.course, language=args.language)
        document = json.loads(args.case.read_text("utf-8"))
        safety_trust.verify_signed_safety_case_document(
            document, public_key=args.public_key_file, course=course
        )
        if args.require_passing_gates:
            safety_trust.authorize_safety_case(
                document,
                trusted_reviewer_fingerprints=frozenset(args.trusted_reviewer_fingerprint),
            )
        print(f"Verified safety case ({document['release_decision']}): {args.case}")
        return 0
    if args.command == "safety-review-sign":
        review = json.loads(args.review.read_text("utf-8"))
        required = {"fixture_id", "subject_hash", "reviewer", "approved", "rationale", "created_at"}
        if (
            not isinstance(review, dict)
            or set(review) != required
            or not isinstance(review["approved"], bool)
        ):
            parser.error("unsigned review must contain exactly the six review fields")
        signed = sign_human_review(
            fixture_id=str(review["fixture_id"]),
            subject_hash=str(review["subject_hash"]),
            reviewer=str(review["reviewer"]),
            approved=review["approved"],
            rationale=str(review["rationale"]),
            created_at=str(review["created_at"]),
            private_key=args.private_key_file,
            public_key=args.public_key_file,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(to_dict(signed), ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        print(f"Signed human safety review: {args.output}")
        return 0
    if args.command == "weather-key-generate":
        write_private_text(args.output, secrets.token_hex(32) + "\n")
        print(f"Generated private classroom privacy key: {args.output}")
        return 0
    if args.command == "weather-key-rotate":
        current = secret_loader(args.current_secret_file, "current weather secret", 32, parser)
        new = secret_loader(args.new_secret_file, "new weather secret", 32, parser)
        ledger = secret_loader(args.ledger_key_file, "weather ledger key", 32, parser)
        with WeatherStore(
            args.database, secret=current, key_epoch=args.current_epoch, ledger_key=ledger
        ) as store:
            store.backup(args.backup)
            purged = store.rotate_privacy_key(new_secret=new, new_epoch=args.new_epoch)
        print(f"Rotated privacy key epoch; purged {purged} linked events after backup")
        return 0
    return None

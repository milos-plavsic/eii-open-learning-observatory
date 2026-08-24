"""Argument definitions for offline-appliance lifecycle commands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path


def add_appliance_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_audit_log_arguments: Callable[[argparse.ArgumentParser], None],
) -> None:
    check = commands.add_parser("appliance-check", help="assess hardware for offline model serving")
    check.add_argument("--path", type=Path, default=Path("."))

    package = commands.add_parser(
        "appliance-package", help="create an integrity-protected offline package"
    )
    package.add_argument("input", type=Path, nargs="+")
    package.add_argument("--version", required=True)
    package.add_argument("--private-key-file", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--model-base-url")
    package.add_argument("--model")
    package.add_argument("--course-path", help="package-relative path, e.g. content/course.json")
    package.add_argument("--language")
    package.add_argument("--safety-case", type=Path)
    package.add_argument("--trusted-reviewer-fingerprint", action="append", default=[])

    install = commands.add_parser(
        "appliance-install", help="verify, stage and activate an offline package"
    )
    install.add_argument("package", type=Path)
    install.add_argument("--root", type=Path, required=True)
    install.add_argument("--public-key-file", type=Path)
    install.add_argument("--use-trust-store", action="store_true")
    install.add_argument("--safety-public-key-file", type=Path)
    install.add_argument("--trusted-reviewer-fingerprint", action="append", default=[])

    server = commands.add_parser(
        "appliance-serve", help="serve the active release on the school LAN"
    )
    server.add_argument("--root", type=Path, required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    server.add_argument("--max-request-workers", type=int, default=64)
    server.add_argument("--max-concurrent-queries", type=int, default=4)
    server.add_argument("--max-queries-per-minute", type=int, default=30)
    server.add_argument("--max-rate-limit-clients", type=int, default=4096)
    server.add_argument("--shutdown-grace-seconds", type=float, default=30.0)
    server.add_argument("--query-token-file", type=Path)
    add_audit_log_arguments(server)

    configure = commands.add_parser(
        "appliance-configure", help="select classroom courses and tutor behavior"
    )
    configure.add_argument("--root", type=Path, required=True)
    configure.add_argument("--courses", required=True)
    configure.add_argument("--languages", required=True)
    configure.add_argument(
        "--assistant-behavior", choices=("hint-first", "socratic", "direct"), default="hint-first"
    )
    for name, help_text in (
        ("appliance-rollback", "atomically reactivate the previous release"),
        ("appliance-recover", "recover activation state from local history"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--root", type=Path, required=True)

    onboarding = commands.add_parser(
        "appliance-onboarding", help="create an offline QR connection page"
    )
    onboarding.add_argument("--url", required=True)
    onboarding.add_argument("--output", type=Path, required=True)

    trust_init = commands.add_parser(
        "appliance-trust-init", help="initialize the publisher trust store"
    )
    trust_init.add_argument("--root", type=Path, required=True)
    trust_init.add_argument("--public-key-file", type=Path, required=True)
    rotation = commands.add_parser(
        "appliance-trust-rotation-create", help="authorize a new publisher key"
    )
    rotation.add_argument("--current-private-key", type=Path, required=True)
    rotation.add_argument("--current-public-key", type=Path, required=True)
    rotation.add_argument("--new-public-key", type=Path, required=True)
    rotation.add_argument("--revoke-old", action="store_true")
    rotation.add_argument("--output", type=Path, required=True)
    apply_rotation = commands.add_parser(
        "appliance-trust-rotation-apply", help="verify and apply key rotation"
    )
    apply_rotation.add_argument("authorization", type=Path)
    apply_rotation.add_argument("--root", type=Path, required=True)

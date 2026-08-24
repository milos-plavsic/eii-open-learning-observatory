"""Argument schema for the EII command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .cli_appliance_parser import add_appliance_commands
from .cli_learning_parser import add_learning_commands
from .cli_operations_parser import add_operations_commands
from .cli_review_parser import add_review_commands
from .cli_trust_parser import add_trust_commands
from .cli_weather_parser import add_weather_command


def _add_audit_log_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--audit-log", type=Path, help="append privacy-bounded request metadata as JSONL"
    )
    command.add_argument("--audit-log-max-bytes", type=int, default=10 * 1024 * 1024)
    command.add_argument("--audit-log-retention-days", type=int, default=30)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="eii", description="EII Open Learning Observatory")
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    add_trust_commands(commands)

    add_learning_commands(commands)
    add_weather_command(commands)
    add_appliance_commands(commands, _add_audit_log_arguments)

    add_review_commands(commands, _add_audit_log_arguments)
    add_operations_commands(commands)
    return result

from __future__ import annotations

import argparse
from pathlib import Path

from .cli_appliance import handle_appliance_command
from .cli_audit import handle_audit
from .cli_learning import handle_learning_command
from .cli_model import model_client as _model_client
from .cli_operations import handle_operations_command
from .cli_parser import parser as parser
from .cli_review import handle_review_command
from .cli_trust import handle_trust_command
from .secureio import read_secret_bytes


def main(argv: list[str] | None = None) -> int:
    command_parser = parser()
    args = command_parser.parse_args(argv)
    if (trust_result := handle_trust_command(args, command_parser, _secret_bytes)) is not None:
        return trust_result
    if args.command == "audit":
        return handle_audit(args, command_parser, _model_client(args, command_parser))
    if (result := handle_learning_command(args, command_parser, _secret_bytes)) is not None:
        return result
    if (result := handle_appliance_command(args, command_parser, _secret_text)) is not None:
        return result
    if (result := handle_review_command(args, command_parser, _secret_text)) is not None:
        return result
    return handle_operations_command(args, command_parser, _secret_text)


def _secret_bytes(
    path: Path, label: str, minimum: int, command_parser: argparse.ArgumentParser
) -> bytes:
    try:
        return read_secret_bytes(path, label=label, minimum_bytes=minimum)
    except ValueError as error:
        command_parser.error(str(error))


def _secret_text(path: Path, label: str, command_parser: argparse.ArgumentParser) -> str:
    value = _secret_bytes(path, label, 1, command_parser)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        command_parser.error(f"{label} must be UTF-8 text: {error}")

"""Shared model-client construction for CLI workflows."""

from __future__ import annotations

import argparse
import os

from .models import OpenAICompatibleClient


def model_client(
    args: argparse.Namespace, command_parser: argparse.ArgumentParser
) -> OpenAICompatibleClient | None:
    base_url, model = getattr(args, "model_base_url", None), getattr(args, "model", None)
    if bool(base_url) != bool(model):
        command_parser.error("--model-base-url and --model must be provided together")
    if not base_url:
        return None
    api_key = os.environ.get(args.api_key_env) if getattr(args, "api_key_env", None) else None
    return OpenAICompatibleClient(
        str(base_url), str(model), provider=args.provider, api_key=api_key
    )

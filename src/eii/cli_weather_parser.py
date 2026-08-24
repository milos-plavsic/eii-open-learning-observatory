"""Argument definitions for privacy-preserving Classroom Weather exports."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_weather_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    weather = commands.add_parser(
        "weather", help="ingest minimized events and export private aggregates"
    )
    weather.add_argument("events", type=Path)
    weather.add_argument("--database", type=Path, required=True)
    weather.add_argument("--secret-file", type=Path, required=True)
    weather.add_argument("--ledger-key-file", type=Path, required=True)
    weather.add_argument("--minimum-group-size", type=int, default=5)
    weather.add_argument("--retention-days", type=int, default=30)
    weather.add_argument("--count-granularity", type=int, default=2)
    weather.add_argument("--minimum-export-interval-hours", type=int, default=24)
    weather.add_argument("--dp-epsilon", type=float, default=1.0)
    weather.add_argument("--dp-total-epsilon", type=float, default=10.0)
    weather.add_argument("--key-epoch", default="v1")
    weather.add_argument("--course-key")
    weather.add_argument("--public-cell-universe", type=Path)
    weather.add_argument("--max-cells-per-contributor-per-day", type=int, default=3)
    weather.add_argument(
        "--database-instance-id",
        required=True,
        help="stable deployment identity used to reject an unexpected database clone",
    )
    weather.add_argument("--allow-database-fork", action="store_true")
    weather.add_argument("--output", type=Path, default=Path("weather-map.json"))
    weather.add_argument("--html-output", type=Path)

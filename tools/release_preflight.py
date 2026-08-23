#!/usr/bin/env python3
"""Validate a built release candidate without publishing it."""

from argparse import ArgumentParser
from pathlib import Path

from eii.release_preflight import require_clean_source_tree, validate_release_candidate


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    validate_release_candidate(tuple(args.artifacts), expected_version=args.version, tag=args.tag)
    if args.repository is not None:
        require_clean_source_tree(args.repository, revision=args.revision)
    print(f"Release candidate version binding verified: {args.version}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the immutable public schema tree from each document's canonical $id."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def render(source: Path) -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    for path in sorted(source.glob("*.json")):
        document = json.loads(path.read_text("utf-8"))
        identifier = document.get("$id")
        if not isinstance(identifier, str):
            raise ValueError(f"schema has no canonical $id: {path}")
        parsed = urlparse(identifier)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "eii.edu.eu"
            or not parsed.path.startswith("/schemas/")
        ):
            raise ValueError(f"schema $id is outside the publication origin: {identifier}")
        name = Path(parsed.path).name
        if name in rendered:
            raise ValueError(f"duplicate public schema name: {name}")
        rendered[name] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    index = {
        "schemas": [
            {"name": name, "sha256": __import__("hashlib").sha256(body).hexdigest()}
            for name, body in sorted(rendered.items())
        ]
    }
    rendered["index.json"] = (json.dumps(index, indent=2) + "\n").encode()
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("schemas"))
    parser.add_argument("--destination", type=Path, default=Path("public/schemas"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render(args.source)
    current = {
        path.name: path.read_bytes() for path in args.destination.glob("*") if path.is_file()
    }
    if args.check:
        if current != rendered:
            raise SystemExit("public schema site is stale; run tools/build_schema_site.py")
        return
    args.destination.mkdir(parents=True, exist_ok=True)
    for path in args.destination.glob("*"):
        if path.is_file() and path.name not in rendered:
            path.unlink()
    for name, body in rendered.items():
        (args.destination / name).write_bytes(body)


if __name__ == "__main__":
    main()

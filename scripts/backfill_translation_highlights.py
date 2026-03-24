#!/usr/bin/env python3
"""Backfill English translation highlight spans into vocab JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from translation_highlights import backfill_translation_highlights


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill translation highlight spans for translated contexts."
    )
    parser.add_argument("files", nargs="+", help="One or more vocab JSON files to update")
    args = parser.parse_args()

    for raw_path in args.files:
        path = Path(raw_path)
        data = load_json(path)
        counts = backfill_translation_highlights(data)
        write_json(path, data)

        total = sum(counts.values())
        summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        print(f"{path}: updated {total} translated contexts")
        if summary:
            print(f"  {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

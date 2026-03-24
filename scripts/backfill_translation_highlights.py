#!/usr/bin/env python3
"""Backfill English translation highlight spans into vocab JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from translation_highlights import (
    MODEL_ALIGN_BATCH_SIZE,
    MODEL_ALIGN_MODEL,
    align_translation_highlights_for_words,
    backfill_translation_highlights,
    create_anthropic_client,
)


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
    parser.add_argument(
        "--no-model-align",
        action="store_true",
        help="Skip the Anthropic alignment pass for unresolved contexts.",
    )
    parser.add_argument(
        "--model",
        default=MODEL_ALIGN_MODEL,
        help="Anthropic model to use for unresolved highlight alignment.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MODEL_ALIGN_BATCH_SIZE,
        help="Number of unresolved contexts to align per model request.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (defaults to ANTHROPIC_API_KEY env var).",
    )
    args = parser.parse_args()

    client = None
    if not args.no_model_align:
        client = create_anthropic_client(api_key=args.api_key)

    for raw_path in args.files:
        path = Path(raw_path)
        data = load_json(path)
        translated_contexts = sum(
            1
            for word in data.get("words", [])
            for ctx in word.get("contexts", [])
            if ctx.get("translation")
        )
        deterministic_counts = backfill_translation_highlights(data)
        alignment_counts = {}
        if client is not None:
            alignment_counts = dict(
                align_translation_highlights_for_words(
                    data.get("words", []),
                    client,
                    model=args.model,
                    batch_size=args.batch_size,
                )
            )
        write_json(path, data)

        deterministic_summary = ", ".join(
            f"{name}={count}" for name, count in sorted(deterministic_counts.items())
        )
        print(f"{path}: updated {translated_contexts} translated contexts")
        if deterministic_summary:
            print(f"  deterministic: {deterministic_summary}")
        if alignment_counts:
            alignment_summary = ", ".join(
                f"{name}={count}" for name, count in sorted(alignment_counts.items())
            )
            print(f"  alignment: {alignment_summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run enrichment in parallel.

Supports two execution backends:
1. anthropic: spawn local enrich_definitions.py subprocesses as before
2. codex-subagent: stage chunk manifests for Codex workers, then merge results later

Usage:
    python3 scripts/enrich_parallel.py docs/data/tlg0059004.json --workers 10
    python3 scripts/enrich_parallel.py docs/data/tlg0086035.json --backend codex-subagent --limit 20 --workers 4 --run-id politics-mini
    python3 scripts/enrich_parallel.py docs/data/tlg0086035.json --backend codex-subagent --chunk-size 40 --run-id politics-54-high-full
    python3 scripts/enrich_parallel.py docs/data/tlg0086035.json --merge-only --manifest data/cache/enrich_runs/politics-mini/manifest.json
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from enrich_definitions import (
    build_batch_request,
    build_batch_source,
    get_word_ids,
    load_vocab,
    select_words,
    write_json,
)


def count_words_to_enrich(
    filepath,
    force=False,
    morph_only=False,
    etymology_only=False,
    offset=0,
    limit=None,
    word_ids=None,
):
    """Count how many words need enrichment for the selected mode."""
    data = load_vocab(filepath)
    return len(
        select_words(
            data,
            force=force,
            morph_only=morph_only,
            etymology_only=etymology_only,
            offset=offset,
            limit=limit,
            word_ids=word_ids,
        )
    )


def chunk_words(words, workers):
    """Split selected words into balanced chunks."""
    if not words:
        return []
    workers = max(1, min(workers, len(words)))
    chunk_size = (len(words) + workers - 1) // workers
    chunks = []
    for idx in range(workers):
        start = idx * chunk_size
        end = start + chunk_size
        chunk = words[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks


def chunk_words_by_size(words, chunk_size):
    """Split selected words into fixed-size chunks."""
    if not words:
        return []
    chunk_size = max(1, chunk_size)
    return [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]


def build_model_config(args):
    """Normalize manifest metadata for model selection."""
    return {
        "model": args.model or "gpt-5.4-mini",
        "reasoning_effort": args.reasoning_effort or "default",
    }


def merge_enrichments(original_path, chunk_paths):
    """Merge enrichment fields from chunk files back into the original."""
    original = load_vocab(original_path)
    word_by_id = {word["id"]: word for word in original["words"]}

    merged_count = 0
    for chunk_path in chunk_paths:
        if not os.path.exists(chunk_path):
            continue
        chunk = load_vocab(chunk_path)
        for chunk_word in chunk.get("words", []):
            original_word = word_by_id.get(chunk_word["id"])
            if not original_word:
                continue

            changed = False

            if chunk_word.get("context_definition") and not original_word.get("context_definition"):
                original_word["context_definition"] = chunk_word["context_definition"]
                changed = True

            if chunk_word.get("etymology") and not original_word.get("etymology"):
                original_word["etymology"] = chunk_word["etymology"]
                changed = True

            for i, ctx in enumerate(original_word.get("contexts", [])):
                if i < len(chunk_word.get("contexts", [])):
                    chunk_ctx = chunk_word["contexts"][i]
                    translation = chunk_ctx.get("translation")
                    if translation and not ctx.get("translation"):
                        ctx["translation"] = translation
                        changed = True

            chunk_forms = {
                form["form"]: form.get("morphology", "")
                for form in chunk_word.get("forms", [])
            }
            for form in original_word.get("forms", []):
                new_morph = chunk_forms.get(form["form"], "")
                old_morph = form.get("morphology", "").strip()
                is_bare = not old_morph or (" " not in old_morph and "," not in old_morph)
                if new_morph and is_bare:
                    form["morphology"] = new_morph
                    changed = True

            if changed:
                merged_count += 1

    return original, merged_count


def stage_codex_run(filepath, args):
    """Create a manifest and chunk artifacts for Codex worker execution."""
    source_path = os.path.abspath(filepath)
    data = load_vocab(source_path)
    selected_words = select_words(
        data,
        force=args.force,
        morph_only=args.morph_only,
        etymology_only=args.etymology_only,
        offset=args.offset,
        limit=args.limit,
        word_ids=get_word_ids(args),
    )
    if not selected_words:
        print("Nothing to enrich.")
        return 1

    run_id = args.run_id or (
        f"{Path(filepath).stem}-{args.backend}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    run_root_base = Path(args.run_root_dir or "data/cache/enrich_runs")
    run_root = run_root_base / run_id
    if run_root.exists():
        print(f"Error: run directory already exists: {run_root}")
        return 1
    run_root.mkdir(parents=True, exist_ok=False)

    working_file = Path(args.output) if args.output else run_root / Path(filepath).name
    write_json(working_file, data)

    word_ids_path = run_root / "word_ids.json"
    write_json(word_ids_path, [word["id"] for word in selected_words])

    if args.chunk_size:
        selected_chunks = chunk_words_by_size(selected_words, args.chunk_size)
        effective_chunk_size = args.chunk_size
    else:
        selected_chunks = chunk_words(selected_words, args.workers)
        effective_chunk_size = max(
            1,
            (len(selected_words) + len(selected_chunks) - 1) // max(1, len(selected_chunks)),
        )

    chunks = []
    model_config = build_model_config(args)
    for idx, chunk in enumerate(selected_chunks):
        request_path = run_root / f"chunk_{idx:02d}.request.json"
        source_chunk_path = run_root / f"chunk_{idx:02d}.source.json"
        response_path = run_root / f"chunk_{idx:02d}.response.json"
        enriched_chunk_path = run_root / f"chunk_{idx:02d}.enriched.json"

        request_payload = build_batch_request(
            chunk,
            filepath=str(working_file),
            morph_only=args.morph_only,
            etymology_only=args.etymology_only,
        )
        request_payload["model_config"] = model_config
        request_payload["response_path"] = str(response_path.resolve())
        request_payload["enriched_chunk_path"] = str(enriched_chunk_path.resolve())
        write_json(request_path, request_payload)
        write_json(source_chunk_path, build_batch_source(data, chunk))

        chunks.append(
            {
                "worker_index": idx,
                "word_ids": [word["id"] for word in chunk],
                "lemmas": [word["lemma"] for word in chunk],
                "request_path": str(request_path.resolve()),
                "source_chunk_path": str(source_chunk_path.resolve()),
                "response_path": str(response_path.resolve()),
                "enriched_chunk_path": str(enriched_chunk_path.resolve()),
            }
        )

    manifest = {
        "schema_version": 1,
        "backend": "codex-subagent",
        "run_id": run_id,
        "source_file": source_path,
        "working_file": str(working_file.resolve()),
        "word_ids_file": str(word_ids_path.resolve()),
        "mode": "etymology-only" if args.etymology_only else ("morph-only" if args.morph_only else "full"),
        "model_config": model_config,
        "chunk_size": effective_chunk_size,
        "workers": len(chunks),
        "limit": args.limit,
        "offset": args.offset,
        "force": args.force,
        "run_root_dir": str(run_root_base.resolve()),
        "chunks": chunks,
        "instructions": {
            "worker_task": (
                "Read the request JSON, generate the enrichment response as a raw JSON array only, "
                "and return that JSON to the orchestrating agent. The orchestrator writes the response "
                "to response_path and applies it locally."
            ),
            "merge_step": (
                "After all chunk responses are applied into enriched_chunk_path files, run "
                f"python3 scripts/enrich_parallel.py {working_file} --merge-only --manifest {run_root / 'manifest.json'}"
            ),
        },
    }
    manifest_path = run_root / "manifest.json"
    write_json(manifest_path, manifest)

    print(f"Staged Codex run in {run_root}")
    print(f"Working file: {working_file}")
    print(f"Selected words: {len(selected_words)}")
    print(f"Chunks: {len(chunks)}")
    print(f"Manifest: {manifest_path}")
    return 0


def run_anthropic_backend(filepath, args):
    """Run local subprocess-based enrichment with the Anthropic path."""
    target_path = os.path.abspath(args.output or filepath)
    if os.path.abspath(filepath) != target_path:
        write_json(target_path, load_vocab(filepath))

    data = load_vocab(target_path)
    selected_words = select_words(
        data,
        force=args.force,
        morph_only=args.morph_only,
        etymology_only=args.etymology_only,
        offset=args.offset,
        limit=args.limit,
        word_ids=get_word_ids(args),
    )
    total = len(selected_words)
    print(f"Words to enrich: {total}")
    if total == 0:
        print("Nothing to enrich.")
        return 0

    chunks = chunk_words(selected_words, args.workers)
    print(f"Splitting into {len(chunks)} workers\n")

    tmpdir = tempfile.mkdtemp(prefix="enrich_")
    processes = []

    for idx, chunk in enumerate(chunks):
        output = os.path.join(tmpdir, f"chunk_{idx}.json")
        cmd = [
            sys.executable,
            "scripts/enrich_definitions.py",
            target_path,
            "--word-ids",
            ",".join(str(word["id"]) for word in chunk),
            "--output",
            output,
        ]
        if args.force:
            cmd.append("--force")
        if args.morph_only:
            cmd.append("--morph-only")
        if args.etymology_only:
            cmd.append("--etymology-only")

        print(
            f"Worker {idx}: ids={','.join(str(word['id']) for word in chunk)} -> {output}"
        )
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        processes.append((idx, proc, output))

    print(f"\n{len(processes)} workers launched. Waiting for completion...\n")

    failed = []
    for idx, proc, output in processes:
        returncode = proc.wait()
        stdout = proc.stdout.read()
        lines = stdout.strip().split("\n")
        summary = [line for line in lines if "Enriched:" in line or "ERROR" in line]
        status = "OK" if returncode == 0 else "FAILED"
        print(f"Worker {idx} [{status}]:")
        if summary:
            for line in summary:
                print(f"  {line.strip()}")
        elif returncode != 0:
            for line in lines[-5:]:
                print(f"  {line}")
        if returncode != 0:
            failed.append(idx)

    if failed:
        print(f"\nWARNING: Workers {failed} failed. Merging partial results anyway.")

    chunk_paths = [output for _, _, output in processes]
    print(f"\nMerging {len(chunk_paths)} chunks...")
    merged_data, merged_count = merge_enrichments(target_path, chunk_paths)

    if merged_count > 0:
        write_json(target_path, merged_data)
        print(f"Merged {merged_count} enriched words into {target_path}")
    else:
        print("No enrichments to merge.")

    for output in chunk_paths:
        if os.path.exists(output):
            os.remove(output)
    os.rmdir(tmpdir)

    print("\nDone! Run: python3 scripts/validate_data.py", target_path)
    return 0


def merge_from_manifest(manifest_path, output_override=None):
    """Merge enriched chunk files recorded in a manifest."""
    manifest = load_vocab(manifest_path)
    target_path = output_override or manifest["working_file"]
    chunk_paths = [chunk["enriched_chunk_path"] for chunk in manifest.get("chunks", [])]

    if not chunk_paths:
        print("No chunks listed in manifest.")
        return 1

    merged_data, merged_count = merge_enrichments(target_path, chunk_paths)
    if merged_count > 0:
        write_json(target_path, merged_data)
        print(f"Merged {merged_count} enriched words into {target_path}")
    else:
        print("No enrichments to merge.")

    missing = [path for path in chunk_paths if not os.path.exists(path)]
    if missing:
        print("Missing chunk outputs:")
        for path in missing:
            print(f"  - {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Run enrichment in parallel")
    parser.add_argument("filepath", help="Path to vocab JSON file")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--force", action="store_true", help="Re-enrich all words")
    parser.add_argument("--morph-only", action="store_true", help="Enrich only morphology")
    parser.add_argument("--etymology-only", action="store_true", help="Enrich only etymology")
    parser.add_argument(
        "--backend",
        choices=("anthropic", "codex-subagent"),
        default="anthropic",
        help="Execution backend",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max number of words to enrich")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many eligible words")
    parser.add_argument("--output", default=None, help="Working output file")
    parser.add_argument("--run-id", default=None, help="Run id for codex-subagent manifests")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Fixed words per chunk for codex-subagent staging",
    )
    parser.add_argument(
        "--run-root-dir",
        default=None,
        help="Root directory for staged codex runs (defaults to data/cache/enrich_runs)",
    )
    parser.add_argument("--model", default=None, help="Model label to record in codex manifests")
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Reasoning effort label to record in codex manifests",
    )
    parser.add_argument("--word-ids", default=None, help="Comma-separated explicit word ids")
    parser.add_argument("--word-ids-file", default=None, help="Path to explicit word ids")
    parser.add_argument("--manifest", default=None, help="Manifest path for --merge-only")
    parser.add_argument("--merge-only", action="store_true", help="Merge chunk outputs from a manifest")
    args = parser.parse_args()

    filepath = os.path.abspath(args.filepath)
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found")
        sys.exit(1)

    if args.merge_only:
        if not args.manifest:
            print("Error: --merge-only requires --manifest")
            sys.exit(1)
        sys.exit(merge_from_manifest(args.manifest, output_override=args.output))

    total = count_words_to_enrich(
        filepath,
        force=args.force,
        morph_only=args.morph_only,
        etymology_only=args.etymology_only,
        offset=args.offset,
        limit=args.limit,
        word_ids=get_word_ids(args),
    )
    print(f"Words to enrich: {total}")
    if total == 0:
        print("Nothing to enrich.")
        return

    if args.backend == "codex-subagent":
        sys.exit(stage_codex_run(filepath, args))

    sys.exit(run_anthropic_backend(filepath, args))


if __name__ == "__main__":
    main()

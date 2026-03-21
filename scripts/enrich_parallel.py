#!/usr/bin/env python3
"""Run enrich_definitions.py in parallel with N workers.

Splits the work into chunks, runs each in a subprocess writing to a temp file,
then merges all enrichments back into the original vocab JSON.

Usage:
    python3 scripts/enrich_parallel.py docs/data/tlg0059004.json --workers 10
    python3 scripts/enrich_parallel.py docs/data/tlg0059004.json --workers 10 --morph-only
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def count_words_to_enrich(filepath, force=False, morph_only=False):
    """Count how many words need enrichment without importing the enrichment module."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    if force:
        return len(words)
    count = 0
    for w in words:
        if morph_only:
            for form in w.get("forms", []):
                morph = form.get("morphology", "").strip()
                if not morph or (" " not in morph and "," not in morph):
                    count += 1
                    break
        else:
            if not w.get("context_definition"):
                count += 1
                continue
            needs = False
            for ctx in w.get("contexts", []):
                if not ctx.get("translation"):
                    needs = True
                    break
            if needs:
                count += 1
                continue
            for form in w.get("forms", []):
                morph = form.get("morphology", "").strip()
                if not morph or (" " not in morph and "," not in morph):
                    count += 1
                    break
    return count


def merge_enrichments(original_path, chunk_paths):
    """Merge enrichment fields from chunk files back into the original."""
    with open(original_path, "r", encoding="utf-8") as f:
        original = json.load(f)

    # Build lookup by word id for fast matching
    word_by_id = {w["id"]: w for w in original["words"]}

    merged_count = 0
    for chunk_path in chunk_paths:
        if not os.path.exists(chunk_path):
            continue
        with open(chunk_path, "r", encoding="utf-8") as f:
            chunk = json.load(f)
        for cw in chunk.get("words", []):
            ow = word_by_id.get(cw["id"])
            if not ow:
                continue

            changed = False

            # Merge context_definition
            if cw.get("context_definition") and not ow.get("context_definition"):
                ow["context_definition"] = cw["context_definition"]
                changed = True

            # Merge context translations
            for i, ctx in enumerate(ow.get("contexts", [])):
                if i < len(cw.get("contexts", [])):
                    ct = cw["contexts"][i].get("translation")
                    if ct and not ctx.get("translation"):
                        ctx["translation"] = ct
                        changed = True

            # Merge form morphology
            chunk_forms = {f["form"]: f.get("morphology", "") for f in cw.get("forms", [])}
            for form in ow.get("forms", []):
                new_morph = chunk_forms.get(form["form"], "")
                old_morph = form.get("morphology", "").strip()
                is_bare = not old_morph or (" " not in old_morph and "," not in old_morph)
                if new_morph and is_bare:
                    form["morphology"] = new_morph
                    changed = True

            if changed:
                merged_count += 1

    return original, merged_count


def main():
    parser = argparse.ArgumentParser(description="Run enrichment in parallel")
    parser.add_argument("filepath", help="Path to vocab JSON file")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--force", action="store_true", help="Re-enrich all words")
    parser.add_argument("--morph-only", action="store_true", help="Enrich only morphology")
    args = parser.parse_args()

    filepath = os.path.abspath(args.filepath)
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found")
        sys.exit(1)

    total = count_words_to_enrich(filepath, force=args.force, morph_only=args.morph_only)
    print(f"Words to enrich: {total}")
    if total == 0:
        print("Nothing to enrich.")
        return

    workers = min(args.workers, total)
    chunk_size = (total + workers - 1) // workers
    print(f"Splitting into {workers} workers, ~{chunk_size} words each\n")

    # Launch workers
    tmpdir = tempfile.mkdtemp(prefix="enrich_")
    processes = []
    for w in range(workers):
        offset = w * chunk_size
        if offset >= total:
            break
        output = os.path.join(tmpdir, f"chunk_{w}.json")
        cmd = [
            sys.executable, "scripts/enrich_definitions.py", filepath,
            "--offset", str(offset),
            "--limit", str(chunk_size),
            "--output", output,
        ]
        if args.force:
            cmd.append("--force")
        if args.morph_only:
            cmd.append("--morph-only")

        print(f"Worker {w}: offset={offset} limit={chunk_size} -> {output}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        processes.append((w, proc, output))

    print(f"\n{len(processes)} workers launched. Waiting for completion...\n")

    # Monitor processes
    failed = []
    for w, proc, output in processes:
        returncode = proc.wait()
        stdout = proc.stdout.read()

        # Print summary line from each worker
        lines = stdout.strip().split("\n")
        summary = [l for l in lines if "Enriched:" in l or "ERROR" in l]
        status = "OK" if returncode == 0 else "FAILED"
        print(f"Worker {w} [{status}]:")
        if summary:
            for s in summary:
                print(f"  {s.strip()}")
        elif returncode != 0:
            # Show last few lines on failure
            for l in lines[-5:]:
                print(f"  {l}")
            failed.append(w)

    if failed:
        print(f"\nWARNING: Workers {failed} failed. Merging partial results anyway.")

    # Merge results
    chunk_paths = [output for _, _, output in processes]
    print(f"\nMerging {len(chunk_paths)} chunks...")
    merged_data, merged_count = merge_enrichments(filepath, chunk_paths)

    if merged_count > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"Merged {merged_count} enriched words into {filepath}")
    else:
        print("No enrichments to merge.")

    # Cleanup temp files
    for p in chunk_paths:
        if os.path.exists(p):
            os.remove(p)
    os.rmdir(tmpdir)

    print("\nDone! Run: python3 scripts/validate_data.py", filepath)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run a staged Codex enrichment manifest with a time box and resume support.

Typical usage:
    python3 scripts/enrich_parallel.py docs/data/tlg0086035.json \
        --backend codex-subagent \
        --chunk-size 40 \
        --run-id politics-54-high-full \
        --model gpt-5.4 \
        --reasoning-effort high

    python3 scripts/enrich_timebox.py \
        --manifest data/cache/enrich_runs/politics-54-high-full/manifest.json \
        --time-limit-hours 6 \
        --concurrency 6
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enrich_definitions import (
    apply_enrichments,
    load_result_payload,
    load_vocab,
    validate_enrichments,
    write_json,
)
from enrich_parallel import merge_enrichments


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROGRESS_FILE = "timebox_progress.json"
POLL_INTERVAL_SECONDS = 2


def utc_now():
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def isoformat_utc(timestamp):
    """Serialize a timestamp in compact UTC form."""
    return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def build_codex_prompt(request):
    """Build a self-contained Codex prompt from a prepared request payload."""
    return (
        "All required source data is included below. "
        "Do not inspect files, do not run shell commands, and do not search the web. "
        "Return ONLY the final JSON array and nothing else.\n\n"
        "Follow this system prompt exactly:\n"
        f"{request['system_prompt']}\n\n"
        "Use this input data exactly:\n"
        f"{request['user_prompt']}\n"
    )


def load_manifest(manifest_path):
    """Load and validate a staged codex-subagent manifest."""
    manifest = load_vocab(manifest_path)
    if manifest.get("backend") != "codex-subagent":
        raise ValueError("Manifest backend must be codex-subagent")
    if not manifest.get("chunks"):
        raise ValueError("Manifest has no chunks")
    return manifest


def chunk_completed(chunk):
    """Return True if the enriched chunk file already exists."""
    return Path(chunk["enriched_chunk_path"]).exists()


def chunk_response_ready(chunk):
    """Return True if a raw model response exists for the chunk."""
    return Path(chunk["response_path"]).exists()


def remove_if_exists(path):
    """Delete a file if it exists."""
    p = Path(path)
    if p.exists():
        p.unlink()


def apply_chunk_response(chunk):
    """Apply a raw model response to a prepared chunk source file."""
    source_data = load_vocab(chunk["source_chunk_path"])
    request = load_vocab(chunk["request_path"])
    batch = source_data.get("words", [])
    enrichments = load_result_payload(chunk["response_path"])
    validate_enrichments(batch, enrichments)

    morph_only = request.get("mode") == "morph-only"
    etymology_only = request.get("mode") == "etymology-only"
    apply_enrichments(
        batch,
        enrichments,
        morph_only=morph_only,
        etymology_only=etymology_only,
    )
    write_json(chunk["enriched_chunk_path"], source_data)
    return len(batch)


def merge_completed_chunks(manifest, output_path=None):
    """Merge all completed chunk outputs into the working file."""
    target_path = output_path or manifest["working_file"]
    chunk_paths = [
        chunk["enriched_chunk_path"]
        for chunk in manifest.get("chunks", [])
        if Path(chunk["enriched_chunk_path"]).exists()
    ]
    if not chunk_paths:
        return 0
    merged_data, merged_count = merge_enrichments(target_path, chunk_paths)
    if merged_count > 0:
        write_json(target_path, merged_data)
    return merged_count


def build_codex_command(chunk, model_config, codex_bin):
    """Build the Codex CLI command for a single chunk."""
    cmd = [
        codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
    ]
    reasoning_effort = model_config.get("reasoning_effort")
    if reasoning_effort and reasoning_effort != "default":
        cmd.extend(["-c", f"model_reasoning_effort={reasoning_effort}"])
    cmd.extend(
        [
            "-m",
            model_config.get("model") or "gpt-5.4-mini",
            "-o",
            chunk["response_path"],
            "-",
        ]
    )
    return cmd


def launch_chunk_process(chunk, model_config, codex_bin):
    """Launch a Codex chunk subprocess and stream the prompt over stdin."""
    remove_if_exists(chunk["response_path"])
    remove_if_exists(chunk["enriched_chunk_path"])
    request = load_vocab(chunk["request_path"])
    proc = subprocess.Popen(
        build_codex_command(chunk, model_config, codex_bin),
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    prompt = build_codex_prompt(request)
    assert proc.stdin is not None
    proc.stdin.write(prompt)
    proc.stdin.close()
    return proc


def restage_fallback_manifest(manifest_path, manifest, fallback_chunk_size):
    """Restage the same selection with a smaller chunk size after canary failure."""
    mode = manifest.get("mode")
    model_config = manifest.get("model_config") or {}
    run_id = f"{manifest['run_id']}-fallback{fallback_chunk_size}"
    run_root_dir = manifest.get("run_root_dir")
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "enrich_parallel.py"),
        manifest["source_file"],
        "--backend",
        "codex-subagent",
        "--run-id",
        run_id,
        "--chunk-size",
        str(fallback_chunk_size),
        "--word-ids-file",
        manifest["word_ids_file"],
    ]
    if run_root_dir:
        cmd.extend(["--run-root-dir", run_root_dir])
    if manifest.get("force"):
        cmd.append("--force")
    if mode == "morph-only":
        cmd.append("--morph-only")
    elif mode == "etymology-only":
        cmd.append("--etymology-only")
    if model_config.get("model"):
        cmd.extend(["--model", model_config["model"]])
    if model_config.get("reasoning_effort") and model_config["reasoning_effort"] != "default":
        cmd.extend(["--reasoning-effort", model_config["reasoning_effort"]])

    subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    new_manifest = Path(run_root_dir or (Path(manifest_path).resolve().parent.parent)) / run_id / "manifest.json"
    return str(new_manifest.resolve())


def load_progress(progress_path):
    """Load an existing progress file if present."""
    if not progress_path.exists():
        return {}
    return load_vocab(progress_path)


def save_progress(progress_path, payload):
    """Persist timebox orchestration state."""
    write_json(progress_path, payload)


def build_progress_payload(
    manifest_path,
    manifest,
    args,
    started_at,
    deadline_at,
    grace_deadline_at,
    active,
    failures,
    notes,
):
    """Summarize current orchestration state in a stable JSON file."""
    chunks = manifest.get("chunks", [])
    completed = [idx for idx, chunk in enumerate(chunks) if chunk_completed(chunk)]
    next_chunk_index = None
    for idx, chunk in enumerate(chunks):
        if idx in active:
            continue
        if not chunk_completed(chunk):
            next_chunk_index = idx
            break
    return {
        "schema_version": 1,
        "manifest_path": str(Path(manifest_path).resolve()),
        "run_id": manifest["run_id"],
        "started_at": isoformat_utc(started_at),
        "updated_at": isoformat_utc(utc_now()),
        "deadline_at": isoformat_utc(deadline_at),
        "grace_deadline_at": isoformat_utc(grace_deadline_at),
        "time_limit_hours": args.time_limit_hours,
        "grace_period_minutes": args.grace_period_minutes,
        "concurrency": args.concurrency,
        "chunk_timeout_minutes": args.chunk_timeout_minutes,
        "completed_chunks": completed,
        "failed_chunks": failures,
        "active_chunks": sorted(active.keys()),
        "next_chunk_index": next_chunk_index,
        "notes": notes,
    }


def summarize_chunk(chunk):
    """Return a compact human-readable chunk label."""
    lemmas = chunk.get("lemmas") or []
    preview = ", ".join(lemmas[:3])
    if len(lemmas) > 3:
        preview += ", ..."
    return f"{len(lemmas)} words [{preview}]"


def run_single_chunk(chunk, model_config, codex_bin, timeout_seconds):
    """Run one chunk synchronously and apply it if successful."""
    proc = launch_chunk_process(chunk, model_config, codex_bin)
    try:
        proc.wait(timeout=timeout_seconds)
        stdout = proc.stdout.read() if proc.stdout is not None else ""
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout = proc.stdout.read() if proc.stdout is not None else ""
        return False, f"Timed out after {timeout_seconds} seconds", stdout

    if proc.returncode != 0:
        return False, f"codex exited with {proc.returncode}", stdout
    if not chunk_response_ready(chunk):
        return False, "Response file missing", stdout

    try:
        apply_chunk_response(chunk)
    except Exception as exc:  # noqa: BLE001
        return False, f"Apply failed: {exc}", stdout

    return True, "ok", stdout


def process_ready_chunk(chunk, stdout):
    """Apply an asynchronously completed chunk or surface the failure."""
    if not chunk_response_ready(chunk):
        return False, "Response file missing"
    try:
        apply_chunk_response(chunk)
    except Exception as exc:  # noqa: BLE001
        tail = "\n".join((stdout or "").strip().splitlines()[-10:])
        return False, f"Apply failed: {exc}\n{tail}".strip()
    return True, "ok"


def main():
    parser = argparse.ArgumentParser(description="Run a staged Codex manifest with a time box")
    parser.add_argument("--manifest", required=True, help="Manifest path staged by enrich_parallel.py")
    parser.add_argument(
        "--time-limit-hours",
        type=float,
        required=True,
        help="Stop launching new chunks after this many hours",
    )
    parser.add_argument(
        "--grace-period-minutes",
        type=float,
        default=15,
        help="Allow in-flight chunks to finish for this long after the deadline",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Maximum concurrent Codex chunk processes",
    )
    parser.add_argument(
        "--chunk-timeout-minutes",
        type=float,
        default=60,
        help="Kill any individual chunk that exceeds this runtime",
    )
    parser.add_argument(
        "--canary-retries",
        type=int,
        default=2,
        help="Attempts for the first canary chunk before fallback",
    )
    parser.add_argument(
        "--fallback-chunk-size",
        type=int,
        default=20,
        help="Restage with this chunk size if the 40-word canary fails",
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex CLI binary to invoke",
    )
    parser.add_argument(
        "--merge-every",
        type=int,
        default=5,
        help="Merge partial output after this many newly completed chunks",
    )
    parser.add_argument(
        "--progress-file",
        default=None,
        help="Progress JSON path (defaults to <run>/timebox_progress.json)",
    )
    parser.add_argument(
        "--skip-canary",
        action="store_true",
        help="Skip the canary chunk and start normal scheduling immediately",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the intended schedule without launching Codex",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    progress_path = Path(args.progress_file) if args.progress_file else manifest_path.parent / DEFAULT_PROGRESS_FILE
    previous_progress = load_progress(progress_path)

    started_at = utc_now()
    deadline_at = started_at + timedelta(hours=args.time_limit_hours)
    grace_deadline_at = deadline_at + timedelta(minutes=args.grace_period_minutes)
    chunk_timeout_seconds = int(args.chunk_timeout_minutes * 60)
    model_config = manifest.get("model_config") or {}
    chunks = manifest.get("chunks", [])
    active = {}
    failures = list(previous_progress.get("failed_chunks", []))
    notes = []

    existing_completed = [idx for idx, chunk in enumerate(chunks) if chunk_completed(chunk)]
    if existing_completed:
        notes.append(f"Resuming with {len(existing_completed)} completed chunks already on disk.")

    applied_on_resume = 0
    for idx, chunk in enumerate(chunks):
        if chunk_completed(chunk):
            continue
        if not chunk_response_ready(chunk):
            continue
        try:
            applied_on_resume += apply_chunk_response(chunk)
        except Exception as exc:  # noqa: BLE001
            failures.append({"chunk_index": idx, "reason": f"resume apply failed: {exc}"})
    if applied_on_resume:
        merged = merge_completed_chunks(manifest)
        notes.append(f"Applied saved responses for {applied_on_resume} words before launching new work.")
        if merged:
            notes.append(f"Merged {merged} words from resume state.")

    if args.dry_run:
        pending = [idx for idx, chunk in enumerate(chunks) if not chunk_completed(chunk)]
        save_progress(
            progress_path,
            build_progress_payload(
                manifest_path,
                manifest,
                args,
                started_at,
                deadline_at,
                grace_deadline_at,
                active,
                failures,
                notes + [f"Dry run only. Pending chunks: {len(pending)}"],
            ),
        )
        print(f"Manifest: {manifest_path}")
        print(f"Run id: {manifest['run_id']}")
        print(f"Model: {model_config.get('model')} ({model_config.get('reasoning_effort', 'default')})")
        print(f"Chunk size: {manifest.get('chunk_size')}")
        print(f"Pending chunks: {len(pending)}")
        print(f"Concurrency: {args.concurrency}")
        print(f"Deadline: {isoformat_utc(deadline_at)}")
        return 0

    if not args.skip_canary:
        canary_index = next((idx for idx, chunk in enumerate(chunks) if not chunk_completed(chunk)), None)
        if canary_index is not None:
            chunk = chunks[canary_index]
            print(f"Running canary chunk {canary_index:02d}: {summarize_chunk(chunk)}")
            canary_ok = False
            for attempt in range(1, args.canary_retries + 1):
                ok, reason, _stdout = run_single_chunk(
                    chunk,
                    model_config,
                    args.codex_bin,
                    timeout_seconds=chunk_timeout_seconds,
                )
                if ok:
                    canary_ok = True
                    merge_completed_chunks(manifest)
                    notes.append(f"Canary chunk {canary_index:02d} succeeded on attempt {attempt}.")
                    print(f"Canary succeeded on attempt {attempt}.")
                    break
                failures.append(
                    {
                        "chunk_index": canary_index,
                        "attempt": attempt,
                        "reason": reason,
                        "phase": "canary",
                    }
                )
                print(f"Canary attempt {attempt} failed: {reason}")

            if not canary_ok:
                if manifest.get("chunk_size") == 40 and args.fallback_chunk_size:
                    fallback_manifest = restage_fallback_manifest(
                        manifest_path,
                        manifest,
                        args.fallback_chunk_size,
                    )
                    notes.append(
                        "Canary failed; restaged fallback manifest at "
                        f"{fallback_manifest}"
                    )
                save_progress(
                    progress_path,
                    build_progress_payload(
                        manifest_path,
                        manifest,
                        args,
                        started_at,
                        deadline_at,
                        grace_deadline_at,
                        active,
                        failures,
                        notes,
                    ),
                )
                return 1

    next_chunk_index = 0
    merged_since_checkpoint = 0
    deadline_reached = False

    while True:
        now_monotonic = time.monotonic()
        now_utc = utc_now()

        while len(active) < args.concurrency and now_utc < deadline_at:
            while next_chunk_index < len(chunks) and chunk_completed(chunks[next_chunk_index]):
                next_chunk_index += 1
            if next_chunk_index >= len(chunks):
                break
            chunk = chunks[next_chunk_index]
            print(f"Launching chunk {next_chunk_index:02d}: {summarize_chunk(chunk)}")
            proc = launch_chunk_process(chunk, model_config, args.codex_bin)
            active[next_chunk_index] = {
                "proc": proc,
                "started_monotonic": now_monotonic,
            }
            next_chunk_index += 1

        if now_utc >= deadline_at and not deadline_reached:
            deadline_reached = True
            notes.append("Deadline reached; no new chunks will be launched.")
            print("Deadline reached. Waiting for in-flight chunks to finish.")

        finished = []
        for idx, info in list(active.items()):
            proc = info["proc"]
            runtime = time.monotonic() - info["started_monotonic"]
            if runtime > chunk_timeout_seconds:
                proc.kill()
                stdout = proc.stdout.read() if proc.stdout is not None else ""
                failures.append(
                    {
                        "chunk_index": idx,
                        "reason": f"chunk timed out after {int(runtime)} seconds",
                        "phase": "run",
                    }
                )
                finished.append((idx, False, stdout))
                continue

            if proc.poll() is None:
                continue

            stdout = proc.stdout.read() if proc.stdout is not None else ""
            if proc.returncode != 0:
                failures.append(
                    {
                        "chunk_index": idx,
                        "reason": f"codex exited with {proc.returncode}",
                        "phase": "run",
                    }
                )
                finished.append((idx, False, stdout))
                continue

            ok, reason = process_ready_chunk(chunks[idx], stdout)
            if not ok:
                failures.append(
                    {
                        "chunk_index": idx,
                        "reason": reason,
                        "phase": "run",
                    }
                )
            finished.append((idx, ok, stdout))

        for idx, ok, _stdout in finished:
            active.pop(idx, None)
            if ok:
                merged_since_checkpoint += 1
                print(f"Completed chunk {idx:02d}.")
            else:
                print(f"Chunk {idx:02d} failed.")

        if merged_since_checkpoint >= args.merge_every:
            merged = merge_completed_chunks(manifest)
            if merged:
                print(f"Checkpoint merge: {merged} words merged.")
            merged_since_checkpoint = 0

        save_progress(
            progress_path,
            build_progress_payload(
                manifest_path,
                manifest,
                args,
                started_at,
                deadline_at,
                grace_deadline_at,
                active,
                failures,
                notes,
            ),
        )

        if now_utc >= grace_deadline_at and active:
            print("Grace period expired. Terminating remaining chunks.")
            for idx, info in list(active.items()):
                proc = info["proc"]
                proc.kill()
                stdout = proc.stdout.read() if proc.stdout is not None else ""
                failures.append(
                    {
                        "chunk_index": idx,
                        "reason": "terminated after grace period",
                        "phase": "grace",
                    }
                )
                active.pop(idx, None)
                if stdout.strip():
                    notes.append(f"Chunk {idx:02d} terminated after grace period.")
            break

        if not active and (deadline_reached or next_chunk_index >= len(chunks)):
            break

        time.sleep(POLL_INTERVAL_SECONDS)

    merged = merge_completed_chunks(manifest)
    completed_chunks = sum(1 for chunk in chunks if chunk_completed(chunk))
    remaining_chunks = len(chunks) - completed_chunks
    notes.append(
        f"Final merge wrote {merged} new words; {completed_chunks}/{len(chunks)} chunks completed."
    )
    save_progress(
        progress_path,
        build_progress_payload(
            manifest_path,
            manifest,
            args,
            started_at,
            deadline_at,
            grace_deadline_at,
            active,
            failures,
            notes,
        ),
    )

    print(f"Completed chunks: {completed_chunks}/{len(chunks)}")
    print(f"Remaining chunks: {remaining_chunks}")
    print(f"Progress file: {progress_path}")
    print(f"Working file: {manifest['working_file']}")
    print(f"Merged words this run: {merged}")
    if failures:
        print(f"Failures recorded: {len(failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

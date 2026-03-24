#!/usr/bin/env python3
"""Enrich vocab JSON with context-sensitive definitions.

This optional post-processing step supports two workflows:
1. Direct Anthropic execution for the existing enrichment path.
2. Prepare/apply helpers for external orchestration, such as Codex subagents.

It can add:
- context_definition: a concise 2-5 word gloss per lemma based on textual usage
- contexts[].translation: English translation of each context sentence
- etymology: short explanation of word formation or sense development
- forms[].morphology: richer inflectional parsing

Usage:
    python3 scripts/enrich_definitions.py docs/data/tlg0059004.json
    python3 scripts/enrich_definitions.py docs/data/tlg0059004.json --prepare-output /tmp/request.json
    python3 scripts/enrich_definitions.py /tmp/chunk_source.json --result-input /tmp/result.json --output /tmp/chunk_enriched.json
"""

import argparse
import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None


def load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv()

BATCH_SIZE = 5
ETYMOLOGY_BATCH_SIZE = 20
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 8192

SYSTEM_PROMPT = (
    "You are a Classical Greek lexicography assistant. "
    "For each word provided, produce:\n"
    "1. A concise 2–5 word English gloss capturing how the word is used in context "
    "(not necessarily the primary dictionary meaning).\n"
    "2. A natural English translation of each context sentence.\n"
    "3. A detailed morphological parsing for each form listed.\n"
    "4. A short word explanation (1–2 sentences). For compounds, break down the "
    "components (e.g. \"φιλο- (loving) + σοφία (wisdom)\"). For simple words, "
    "explain the core sense or how its meaning develops. Keep it concise for learners.\n\n"
    "Respond with a JSON array. Each element must have:\n"
    '- "lemma": the Greek lemma (unchanged)\n'
    '- "gloss": the context-appropriate English gloss\n'
    '- "context_translations": array of English translations, '
    "one per context sentence, in the same order provided.\n"
    '- "etymology": short explanation of the word\'s formation or sense\n'
    '- "forms": array of objects with "form" (the Greek form, unchanged) and '
    '"morphology" (detailed grammatical parsing, e.g. '
    '"2nd person singular present indicative active" for verbs, '
    '"nominative singular masculine" for nouns/adjectives). '
    "Use standard grammatical labels. Omit the POS tag itself — "
    "just the inflectional categories.\n\n"
    "Return ONLY the JSON array, no markdown fences or commentary."
)

ETYMOLOGY_ONLY_SYSTEM_PROMPT = (
    "You are a Classical Greek lexicography assistant. "
    "For each word provided, produce a short explanation (1–2 sentences) of the "
    "word's formation or core sense. For compounds, break down the components "
    '(e.g. "φιλο- (loving) + σοφία (wisdom)"). For simple words, explain the '
    "core sense or how its meaning develops. Keep it concise for learners.\n\n"
    "Respond with a JSON array. Each element must have:\n"
    '- "lemma": the Greek lemma (unchanged)\n'
    '- "etymology": the short explanation\n\n'
    "Return ONLY the JSON array, no markdown fences or commentary."
)

MORPH_ONLY_SYSTEM_PROMPT = (
    "You are a Classical Greek morphology expert. "
    "For each word provided, produce a detailed morphological parsing for each form.\n\n"
    "Respond with a JSON array. Each element must have:\n"
    '- "lemma": the Greek lemma (unchanged)\n'
    '- "forms": array of objects with "form" (the Greek form, unchanged) and '
    '"morphology" (detailed grammatical parsing, e.g. '
    '"2nd person singular present indicative active" for verbs, '
    '"nominative singular masculine" for nouns/adjectives). '
    "Use standard grammatical labels. Omit the POS tag itself — "
    "just the inflectional categories.\n\n"
    "Return ONLY the JSON array, no markdown fences or commentary."
)


def load_vocab(filepath):
    """Load a vocab JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(filepath, payload):
    """Write JSON with stable UTF-8 formatting."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_word_ids_arg(word_ids_arg):
    """Parse a comma-separated word id list."""
    if not word_ids_arg:
        return None
    ids = []
    for raw in word_ids_arg.split(","):
        raw = raw.strip()
        if raw:
            ids.append(int(raw))
    return ids or None


def load_word_ids_file(filepath):
    """Load word ids from a JSON or newline-delimited text file."""
    if not filepath:
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []
    if raw.startswith("["):
        return [int(v) for v in json.loads(raw)]
    ids = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            ids.append(int(line))
    return ids


def get_word_ids(args):
    """Resolve explicit word ids from flags."""
    word_ids = []
    from_arg = parse_word_ids_arg(args.word_ids)
    from_file = load_word_ids_file(args.word_ids_file)
    for group in (from_arg, from_file):
        if not group:
            continue
        for word_id in group:
            if word_id not in word_ids:
                word_ids.append(word_id)
    return word_ids or None


def get_mode(morph_only=False, etymology_only=False):
    """Return the enrichment mode name."""
    if etymology_only:
        return "etymology-only"
    if morph_only:
        return "morph-only"
    return "full"


def get_system_prompt(morph_only=False, etymology_only=False):
    """Return the system prompt for the requested mode."""
    if etymology_only:
        return ETYMOLOGY_ONLY_SYSTEM_PROMPT
    if morph_only:
        return MORPH_ONLY_SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _has_bare_morphology(word):
    """Check if any form has only a bare POS tag as morphology."""
    for form in word.get("forms", []):
        morph = form.get("morphology", "").strip()
        if not morph or (" " not in morph and "," not in morph):
            return True
    return False


def needs_enrichment(word, morph_only=False, etymology_only=False):
    """Check if a word still needs enrichment."""
    if etymology_only:
        return not word.get("etymology")
    if morph_only:
        return _has_bare_morphology(word)
    if not word.get("context_definition"):
        return True
    for ctx in word.get("contexts", []):
        if not ctx.get("translation"):
            return True
    if _has_bare_morphology(word):
        return True
    return False


def select_words(
    data,
    force=False,
    morph_only=False,
    etymology_only=False,
    offset=0,
    limit=None,
    word_ids=None,
):
    """Select words to enrich, optionally pinning an explicit id set."""
    words = data.get("words", [])
    if word_ids:
        by_id = {w["id"]: w for w in words}
        selected = []
        missing = []
        for word_id in word_ids:
            word = by_id.get(word_id)
            if word is None:
                missing.append(word_id)
            else:
                selected.append(word)
        if missing:
            raise ValueError(f"Word ids not found in file: {missing}")
        return selected

    if force:
        selected = words
    else:
        selected = [
            w
            for w in words
            if needs_enrichment(
                w,
                morph_only=morph_only,
                etymology_only=etymology_only,
            )
        ]

    if offset:
        selected = selected[offset:]
    if limit is not None:
        selected = selected[:limit]
    return selected


def build_prompt_entries(batch, morph_only=False, etymology_only=False):
    """Build structured request entries for a batch of words."""
    entries = []
    for word in batch:
        if etymology_only:
            entry = {
                "id": word["id"],
                "lemma": word["lemma"],
                "dictionary_definition": word["definition"],
                "pos": word["pos"],
            }
        else:
            entry = {
                "id": word["id"],
                "lemma": word["lemma"],
                "dictionary_definition": word["definition"],
                "pos": word["pos"],
                "forms": [
                    {"form": f["form"], "morphology": f.get("morphology", "")}
                    for f in word.get("forms", [])
                ],
            }
            if not morph_only:
                contexts = []
                for ctx in word.get("contexts", []):
                    sentence = ctx["sentence"]
                    hs, he = ctx["highlight_start"], ctx["highlight_end"]
                    contexts.append(
                        {
                            "ref": ctx["ref"],
                            "form": ctx["form"],
                            "sentence": sentence,
                            "marked_sentence": sentence[:hs] + "**" + sentence[hs:he] + "**" + sentence[he:],
                        }
                    )
                entry["contexts"] = contexts
        entries.append(entry)
    return entries


def build_user_prompt_from_entries(entries):
    """Serialize prompt entries for a model request."""
    prompt_entries = []
    for entry in entries:
        prompt_entry = {
            "lemma": entry["lemma"],
            "dictionary_definition": entry["dictionary_definition"],
            "pos": entry["pos"],
        }
        if "forms" in entry:
            prompt_entry["forms"] = entry["forms"]
        if "contexts" in entry:
            prompt_entry["contexts"] = [
                {
                    "form": ctx["form"],
                    "ref": ctx["ref"],
                    "sentence": ctx["marked_sentence"],
                }
                for ctx in entry["contexts"]
            ]
        prompt_entries.append(prompt_entry)
    return json.dumps(prompt_entries, ensure_ascii=False, indent=2)


def build_batch_request(batch, filepath, morph_only=False, etymology_only=False):
    """Build a reusable request payload for an external model runner."""
    entries = build_prompt_entries(
        batch,
        morph_only=morph_only,
        etymology_only=etymology_only,
    )
    mode = get_mode(morph_only=morph_only, etymology_only=etymology_only)
    return {
        "schema_version": 1,
        "mode": mode,
        "source_file": os.path.abspath(filepath),
        "word_ids": [word["id"] for word in batch],
        "lemmas": [word["lemma"] for word in batch],
        "system_prompt": get_system_prompt(
            morph_only=morph_only,
            etymology_only=etymology_only,
        ),
        "user_prompt": build_user_prompt_from_entries(entries),
        "entries": entries,
        "response_format": {
            "type": "json_array",
            "description": "Return only the JSON array described by the system prompt.",
        },
    }


def build_batch_source(data, batch):
    """Build a subset vocab JSON containing only the selected words."""
    payload = {"metadata": deepcopy(data.get("metadata", {})), "words": deepcopy(batch)}
    payload["metadata"]["unique_lemmas"] = len(payload["words"])
    payload["metadata"]["total_words"] = sum(
        word.get("frequency", 0) for word in payload["words"]
    )
    return payload


def parse_response(text):
    """Parse a JSON response, tolerating markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def load_result_payload(filepath):
    """Load a response payload from disk."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    payload = parse_response(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("enrichments", "response", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(f"Unsupported response payload in {filepath}")


def validate_enrichments(batch, enrichments):
    """Validate that the response maps one-to-one to the requested lemmas."""
    expected = [word["lemma"] for word in batch]
    seen = []
    for item in enrichments:
        lemma = item.get("lemma")
        if not lemma:
            raise ValueError("Response item missing required 'lemma'")
        seen.append(lemma)

    missing = [lemma for lemma in expected if lemma not in seen]
    extra = [lemma for lemma in seen if lemma not in expected]
    duplicates = sorted({lemma for lemma in seen if seen.count(lemma) > 1})

    if missing or extra or duplicates:
        parts = []
        if missing:
            parts.append(f"missing={missing}")
        if extra:
            parts.append(f"extra={extra}")
        if duplicates:
            parts.append(f"duplicates={duplicates}")
        raise ValueError("Invalid enrichment response: " + "; ".join(parts))


def apply_enrichments(batch, enrichments, morph_only=False, etymology_only=False):
    """Apply enrichment data back to the word objects."""
    lookup = {entry["lemma"]: entry for entry in enrichments}
    applied = 0

    for word in batch:
        enrichment = lookup.get(word["lemma"])
        if not enrichment:
            print(f"  WARNING: No enrichment returned for {word['lemma']}")
            continue

        if etymology_only:
            if enrichment.get("etymology"):
                word["etymology"] = enrichment["etymology"]
            applied += 1
            continue

        if not morph_only:
            if enrichment.get("gloss"):
                word["context_definition"] = enrichment["gloss"]

            translations = enrichment.get("context_translations", [])
            contexts = word.get("contexts", [])
            for i, ctx in enumerate(contexts):
                if i < len(translations) and translations[i]:
                    ctx["translation"] = translations[i]

            if enrichment.get("etymology"):
                word["etymology"] = enrichment["etymology"]

        enriched_forms = enrichment.get("forms", [])
        if enriched_forms:
            form_lookup = {
                form["form"]: form["morphology"]
                for form in enriched_forms
                if form.get("form") and form.get("morphology")
            }
            for form in word.get("forms", []):
                new_morph = form_lookup.get(form["form"])
                if new_morph:
                    form["morphology"] = new_morph

        applied += 1

    return applied


def run_anthropic_batch(client, batch, dry_run=False, morph_only=False, etymology_only=False):
    """Send a batch to Anthropic and return enrichment data."""
    request = build_batch_request(
        batch,
        filepath="<in-memory>",
        morph_only=morph_only,
        etymology_only=etymology_only,
    )

    if dry_run:
        mode = request["mode"]
        print(f"  [dry-run] Would send {len(batch)} words ({mode}):")
        for word in batch:
            print(f"    - {word['lemma']} ({word['definition']})")
        return None

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=request["system_prompt"],
        messages=[{"role": "user", "content": request["user_prompt"]}],
    )

    if response.stop_reason == "max_tokens":
        raise json.JSONDecodeError(
            "Response truncated (hit max_tokens)",
            response.content[0].text,
            0,
        )

    enrichments = parse_response(response.content[0].text)
    validate_enrichments(batch, enrichments)
    return enrichments


def prepare_batch_artifacts(args):
    """Write a model request payload and optional subset source file."""
    data = load_vocab(args.filepath)
    batch = select_words(
        data,
        force=args.force,
        morph_only=args.morph_only,
        etymology_only=args.etymology_only,
        offset=args.offset,
        limit=args.limit,
        word_ids=get_word_ids(args),
    )
    if not batch:
        print("No words selected for preparation.")
        return 1

    request = build_batch_request(
        batch,
        filepath=args.filepath,
        morph_only=args.morph_only,
        etymology_only=args.etymology_only,
    )
    write_json(args.prepare_output, request)
    print(f"Wrote request payload for {len(batch)} words to {args.prepare_output}")

    if args.batch_source_output:
        batch_source = build_batch_source(data, batch)
        write_json(args.batch_source_output, batch_source)
        print(f"Wrote batch source to {args.batch_source_output}")

    return 0


def apply_prepared_results(args):
    """Apply a prepared model response to a subset vocab JSON file."""
    data = load_vocab(args.filepath)
    batch = data.get("words", [])
    if not batch:
        print("No words found in file.")
        return 1

    morph_only = args.morph_only
    etymology_only = args.etymology_only
    if args.request_input:
        request = load_vocab(args.request_input)
        mode = request.get("mode")
        if mode == "morph-only":
            morph_only = True
        elif mode == "etymology-only":
            etymology_only = True

        expected_ids = request.get("word_ids") or []
        actual_ids = [word["id"] for word in batch]
        if expected_ids and expected_ids != actual_ids:
            raise ValueError(
                f"Chunk source ids {actual_ids} do not match request ids {expected_ids}"
            )

    enrichments = load_result_payload(args.result_input)
    validate_enrichments(batch, enrichments)
    applied = apply_enrichments(
        batch,
        enrichments,
        morph_only=morph_only,
        etymology_only=etymology_only,
    )

    output_path = args.output or args.filepath
    write_json(output_path, data)
    print(f"Applied {applied}/{len(batch)} enrichments to {output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Enrich vocab JSON with context-sensitive definitions"
    )
    parser.add_argument("filepath", help="Path to vocab JSON file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be sent without calling the API",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enrich all words, even those already enriched",
    )
    parser.add_argument(
        "--morph-only",
        action="store_true",
        help="Enrich only morphology",
    )
    parser.add_argument(
        "--etymology-only",
        action="store_true",
        help="Enrich only etymology",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of words to enrich or prepare",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many words before enriching or preparing",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON output here instead of overwriting the input",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the Anthropic model",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (defaults to ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--word-ids",
        default=None,
        help="Comma-separated explicit word ids to prepare or enrich",
    )
    parser.add_argument(
        "--word-ids-file",
        default=None,
        help="Path to newline- or JSON-formatted word ids",
    )
    parser.add_argument(
        "--prepare-output",
        default=None,
        help="Write a reusable model request payload to this path",
    )
    parser.add_argument(
        "--batch-source-output",
        default=None,
        help="When preparing, also write a subset vocab JSON to this path",
    )
    parser.add_argument(
        "--result-input",
        default=None,
        help="Apply a model response payload from this path",
    )
    parser.add_argument(
        "--request-input",
        default=None,
        help="Prepared request payload corresponding to --result-input",
    )
    args = parser.parse_args()

    if args.prepare_output and args.result_input:
        parser.error("--prepare-output and --result-input are mutually exclusive")

    if args.prepare_output:
        sys.exit(prepare_batch_artifacts(args))

    if args.result_input:
        sys.exit(apply_prepared_results(args))

    data = load_vocab(args.filepath)

    global MODEL
    if args.model:
        MODEL = args.model
    print(f"Using model: {MODEL}")

    words = data.get("words", [])
    if not words:
        print("No words found in file.")
        sys.exit(1)

    to_enrich = select_words(
        data,
        force=args.force,
        morph_only=args.morph_only,
        etymology_only=args.etymology_only,
        offset=args.offset,
        limit=args.limit,
        word_ids=get_word_ids(args),
    )

    output_path = args.output or args.filepath

    print(f"Total words: {len(words)}")
    print(f"Words to enrich: {len(to_enrich)}")

    if not to_enrich:
        print("All words already enriched. Use --force to re-enrich.")
        return

    if args.dry_run:
        print("\n[DRY RUN MODE — no API calls will be made]\n")

    client = None
    if not args.dry_run:
        if anthropic is None:
            print("Error: 'anthropic' package not installed. Run: pip install anthropic")
            sys.exit(1)
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "Error: No API key provided. Set ANTHROPIC_API_KEY env var "
                "or use --api-key flag."
            )
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)

    batch_size = ETYMOLOGY_BATCH_SIZE if args.etymology_only else BATCH_SIZE
    total_batches = (len(to_enrich) + batch_size - 1) // batch_size
    enriched_count = 0
    failed_batches = 0
    api_error_types = ()
    if anthropic is not None:
        api_error_types = (anthropic.APIError,)

    for i in range(0, len(to_enrich), batch_size):
        batch = to_enrich[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} words)...")

        try:
            enrichments = run_anthropic_batch(
                client,
                batch,
                dry_run=args.dry_run,
                morph_only=args.morph_only,
                etymology_only=args.etymology_only,
            )
            if enrichments is not None:
                applied = apply_enrichments(
                    batch,
                    enrichments,
                    morph_only=args.morph_only,
                    etymology_only=args.etymology_only,
                )
                enriched_count += applied
                print(f"  Enriched {applied}/{len(batch)} words")
        except (json.JSONDecodeError, ValueError) + api_error_types as e:
            print(f"  ERROR: Batch {batch_num} failed: {e}")
            if not args.dry_run and len(batch) > 1:
                print(f"  Retrying batch {batch_num} one word at a time...")
                for word in batch:
                    try:
                        enrichments = run_anthropic_batch(
                            client,
                            [word],
                            morph_only=args.morph_only,
                            etymology_only=args.etymology_only,
                        )
                        if enrichments is not None:
                            applied = apply_enrichments(
                                [word],
                                enrichments,
                                morph_only=args.morph_only,
                                etymology_only=args.etymology_only,
                            )
                            enriched_count += applied
                    except (json.JSONDecodeError, ValueError) + api_error_types as e2:
                        print(f"    ERROR: Failed for {word['lemma']}: {e2}")
                        failed_batches += 1
                    time.sleep(0.3)
            else:
                failed_batches += 1

        if not args.dry_run and enriched_count > 0 and batch_num % 10 == 0:
            write_json(output_path, data)
            print(f"  [checkpoint] Saved progress ({enriched_count} words enriched so far)")

        if not args.dry_run and i + batch_size < len(to_enrich):
            time.sleep(0.5)

    if not args.dry_run and enriched_count > 0:
        write_json(output_path, data)
        print(f"\nWrote enriched data to {output_path}")

    print("\nSummary:")
    print(f"  Enriched: {enriched_count}/{len(to_enrich)} words")
    if failed_batches:
        print(f"  Failed batches: {failed_batches}/{total_batches}")


if __name__ == "__main__":
    main()

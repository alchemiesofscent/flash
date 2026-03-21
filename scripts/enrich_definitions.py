#!/usr/bin/env python3
"""Enrich vocab JSON with context-sensitive definitions using Claude API.

This is an optional post-processing step that adds:
- context_definition: a concise 2-5 word gloss per lemma based on textual usage
- contexts[].translation: English translation of each context sentence
- etymology: short explanation of word formation or sense development

The core build_vocab.py pipeline remains LLM-free. This script is run separately
after build_vocab.py has produced the initial vocab JSON.

Usage:
    python3 scripts/enrich_definitions.py docs/data/tlg0059004.json
    python3 scripts/enrich_definitions.py docs/data/tlg0059004.json --dry-run
    python3 scripts/enrich_definitions.py docs/data/tlg0059004.json --force
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Error: 'anthropic' package not installed. Run: pip install anthropic")
    sys.exit(1)

def load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv()

BATCH_SIZE = 5
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

ETYMOLOGY_BATCH_SIZE = 20

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


def _has_bare_morphology(word):
    """Check if any form has only a bare POS tag as morphology (single word like 'verb', 'noun')."""
    for form in word.get("forms", []):
        morph = form.get("morphology", "").strip()
        if not morph or " " not in morph and "," not in morph:
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


def build_user_prompt(batch, morph_only=False, etymology_only=False):
    """Build the user prompt for a batch of words."""
    entries = []
    for word in batch:
        if etymology_only:
            entry = {
                "lemma": word["lemma"],
                "dictionary_definition": word["definition"],
                "pos": word["pos"],
            }
        else:
            entry = {
                "lemma": word["lemma"],
                "dictionary_definition": word["definition"],
                "pos": word["pos"],
                "forms": [
                    {"form": f["form"], "morphology": f.get("morphology", "")}
                    for f in word.get("forms", [])
                ],
            }
            if not morph_only:
                entry["contexts"] = []
                for ctx in word.get("contexts", []):
                    sentence = ctx["sentence"]
                    # Bold the target form in the sentence
                    hs, he = ctx["highlight_start"], ctx["highlight_end"]
                    marked = sentence[:hs] + "**" + sentence[hs:he] + "**" + sentence[he:]
                    entry["contexts"].append({"form": ctx["form"], "sentence": marked})
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, indent=2)


def parse_response(text):
    """Parse the JSON array from the LLM response."""
    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last lines (fences)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def enrich_batch(client, batch, dry_run=False, morph_only=False, etymology_only=False):
    """Send a batch to Claude and return enrichment data."""
    user_prompt = build_user_prompt(batch, morph_only=morph_only, etymology_only=etymology_only)
    if etymology_only:
        system = ETYMOLOGY_ONLY_SYSTEM_PROMPT
    elif morph_only:
        system = MORPH_ONLY_SYSTEM_PROMPT
    else:
        system = SYSTEM_PROMPT

    if dry_run:
        mode = "etymology-only" if etymology_only else ("morph-only" if morph_only else "full")
        print(f"  [dry-run] Would send {len(batch)} words ({mode}):")
        for w in batch:
            print(f"    - {w['lemma']} ({w['definition']})")
        return None

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if response.stop_reason == "max_tokens":
        raise json.JSONDecodeError(
            "Response truncated (hit max_tokens)", response.content[0].text, 0
        )

    text = response.content[0].text
    return parse_response(text)


def apply_enrichments(batch, enrichments, morph_only=False, etymology_only=False):
    """Apply enrichment data back to the word objects."""
    # Build lookup by lemma
    lookup = {e["lemma"]: e for e in enrichments}
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
                if i < len(translations):
                    ctx["translation"] = translations[i]

            if enrichment.get("etymology"):
                word["etymology"] = enrichment["etymology"]

        # Apply morphology to forms
        enriched_forms = enrichment.get("forms", [])
        if enriched_forms:
            # Build lookup by form string
            form_lookup = {f["form"]: f["morphology"] for f in enriched_forms if f.get("morphology")}
            for form in word.get("forms", []):
                new_morph = form_lookup.get(form["form"])
                if new_morph:
                    form["morphology"] = new_morph

        applied += 1

    return applied


def main():
    parser = argparse.ArgumentParser(
        description="Enrich vocab JSON with context-sensitive definitions via Claude API"
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
        help="Enrich only morphological parsing (skip definitions and translations)",
    )
    parser.add_argument(
        "--etymology-only",
        action="store_true",
        help="Enrich only etymology (skip definitions, translations, and morphology)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of words to enrich (useful for testing)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many words before enriching (for parallel runs)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write enriched JSON to this path instead of overwriting the input",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model (e.g. claude-haiku-4-5-20251001, claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (defaults to ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    # Load vocab JSON
    try:
        with open(args.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {args.filepath}: {e}")
        sys.exit(1)

    # Apply model override
    global MODEL
    if args.model:
        MODEL = args.model
    print(f"Using model: {MODEL}")

    words = data.get("words", [])
    if not words:
        print("No words found in file.")
        sys.exit(1)

    # Filter to words needing enrichment
    if args.force:
        to_enrich = words
    else:
        to_enrich = [w for w in words if needs_enrichment(w, morph_only=args.morph_only, etymology_only=args.etymology_only)]

    if args.offset:
        to_enrich = to_enrich[args.offset:]
    if args.limit:
        to_enrich = to_enrich[:args.limit]

    output_path = args.output or args.filepath

    print(f"Total words: {len(words)}")
    print(f"Words to enrich: {len(to_enrich)}")

    if not to_enrich:
        print("All words already enriched. Use --force to re-enrich.")
        return

    if args.dry_run:
        print("\n[DRY RUN MODE — no API calls will be made]\n")

    # Initialize client
    client = None
    if not args.dry_run:
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "Error: No API key provided. Set ANTHROPIC_API_KEY env var "
                "or use --api-key flag."
            )
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)

    # Process in batches
    batch_size = ETYMOLOGY_BATCH_SIZE if args.etymology_only else BATCH_SIZE
    total_batches = (len(to_enrich) + batch_size - 1) // batch_size
    enriched_count = 0
    failed_batches = 0

    for i in range(0, len(to_enrich), batch_size):
        batch = to_enrich[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} words)...")

        try:
            enrichments = enrich_batch(client, batch, dry_run=args.dry_run, morph_only=args.morph_only, etymology_only=args.etymology_only)
            if enrichments is not None:
                applied = apply_enrichments(batch, enrichments, morph_only=args.morph_only, etymology_only=args.etymology_only)
                enriched_count += applied
                print(f"  Enriched {applied}/{len(batch)} words")
        except (json.JSONDecodeError, anthropic.APIError) as e:
            print(f"  ERROR: Batch {batch_num} failed: {e}")
            if not args.dry_run and len(batch) > 1:
                print(f"  Retrying batch {batch_num} one word at a time...")
                for word in batch:
                    try:
                        enrichments = enrich_batch(client, [word], morph_only=args.morph_only, etymology_only=args.etymology_only)
                        if enrichments is not None:
                            applied = apply_enrichments([word], enrichments, morph_only=args.morph_only, etymology_only=args.etymology_only)
                            enriched_count += applied
                    except (json.JSONDecodeError, anthropic.APIError) as e2:
                        print(f"    ERROR: Failed for {word['lemma']}: {e2}")
                        failed_batches += 1
                    time.sleep(0.3)
            else:
                failed_batches += 1

        # Save progress every 10 batches
        if not args.dry_run and enriched_count > 0 and batch_num % 10 == 0:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"  [checkpoint] Saved progress ({enriched_count} words enriched so far)")

        # Small delay between batches to be respectful of rate limits
        if not args.dry_run and i + batch_size < len(to_enrich):
            time.sleep(0.5)

    # Write results
    if not args.dry_run and enriched_count > 0:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\nWrote enriched data to {output_path}")

    # Summary
    print(f"\nSummary:")
    print(f"  Enriched: {enriched_count}/{len(to_enrich)} words")
    if failed_batches:
        print(f"  Failed batches: {failed_batches}/{total_batches}")


if __name__ == "__main__":
    main()

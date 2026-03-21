# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Flash is a static-site flashcard game for learning Ancient Greek vocabulary. It has two parts:
1. A **vanilla JS single-page app** (served from `docs/`) deployed via GitHub Pages
2. A **Python build pipeline** (`scripts/`) that converts TEI XML texts into vocab JSON using CLTK for NLP and the Perseus LSJ lexicon for English definitions (no LLM/API dependency)

## Common Commands

```bash
# Serve the frontend locally
python -m http.server -d docs

# Install Python dependencies (Python 3.10+)
pip install -r requirements.txt

# Build the LSJ lexicon (first time only)
python scripts/build_lexicon.py

# Build vocab JSON from a TEI XML source text
python scripts/build_vocab.py texts/tlg0059004.xml

# Validate generated vocab JSON
python scripts/validate_data.py docs/data/tlg0059004.json
```

## Build Pipeline

`scripts/build_vocab.py` is the main data pipeline. It runs from the project root and imports sibling modules (`stop_words.py`) via `scripts/` as the working directory — run it as `python scripts/build_vocab.py`.

`scripts/build_lexicon.py` downloads the Perseus LSJ XML files and builds `data/lexicon/lsj_shortdefs.json` — a flat lookup of Greek lemmas to concise English definitions. Run it once before `build_vocab.py`. The raw LSJ XML is stored in `data/lexica/` (gitignored, ~large).

The pipeline outputs to `docs/data/<work_id>.json` and updates `docs/data/works.json` (the work index the frontend reads). No API keys or LLM providers are needed.

### Optional: LLM-enriched definitions

`scripts/enrich_definitions.py` is an optional post-processing step that uses Claude API to add context-sensitive definitions and sentence translations. It requires an `ANTHROPIC_API_KEY` env var and the `anthropic` pip package.

```bash
# Enrich definitions (requires ANTHROPIC_API_KEY)
python3 scripts/enrich_definitions.py docs/data/tlg0059004.json

# Preview without API calls
python3 scripts/enrich_definitions.py docs/data/tlg0059004.json --dry-run

# Re-enrich all words (even already enriched ones)
python3 scripts/enrich_definitions.py docs/data/tlg0059004.json --force
```

This adds `context_definition` (per-lemma gloss) and `contexts[].translation` (sentence translations) to the vocab JSON. The frontend falls back gracefully if these fields are absent.

## Frontend Architecture

The app uses vanilla ES modules with no build step or framework. Hash-based routing (`#home`, `#level-select`, `#quiz`, `#results`, `#progress`).

Key design patterns:
- **`state.js`** — Pure functional state transitions (immutable session objects via spread)
- **`questions.js`** — Question generation engine with three types: greek-to-english, english-to-greek, form-id. Default mix is 40/30/30, redistributed when form-id eligible words are scarce
- **`storage.js`** — localStorage persistence for per-word mastery progress and settings
- **`data.js`** — Fetches and caches vocab JSON
- **`utils.js`** — Greek Unicode normalization (NFC), Levenshtein distance, Fisher-Yates shuffle, distractor picking

## Data Format

Vocab JSON files (`docs/data/<work_id>.json`) contain:
- `metadata`: title, author, work_id, total_words, unique_lemmas
- `words[]`: each with id, lemma, definition, level (1-10), frequency, pos, forms[]
- Optional enrichment fields: `context_definition` (per-lemma), `contexts[].translation` (per-sentence)

`validate_data.py` checks schema integrity including unique IDs, all 10 levels present, and consistency with `works.json`.

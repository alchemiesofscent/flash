#!/usr/bin/env python3
"""Build vocabulary JSON from a TEI XML text for the flash card app.

Uses CLTK for lemmatization and the Perseus LSJ lexicon for definitions.
No LLM or API keys required.

Usage:
    python scripts/build_vocab.py texts/tlg0059004.xml
"""

import argparse
import bisect
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# 1a. Parse TEI XML
# ---------------------------------------------------------------------------

TEI_NS = "http://www.tei-c.org/ns/1.0"

WORK_METADATA_OVERRIDES = {
    "tlg0086035": {
        "title": "Politics",
        "author": "Aristotle",
    },
}

FORM_ANALYSIS_OVERRIDES = {
    "tlg0086035": {
        "εὕροι": {
            "lemma": "εὑρίσκω",
            "pos": "VERB",
            "morphology": "verb, perfective, optative, singular, third, past, finite, active",
        },
    },
}

CLTK_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "cltk_data"
LEGACY_CLTK_DATA_DIR = Path.home() / "cltk_data"


def ensure_cltk_data_dir() -> Path:
    """Point CLTK at a writable data directory inside the repo.

    CLTK writes a log file at import time and reads Greek embeddings from
    ``$CLTK_DATA/grc/embeddings`` during analysis. In this sandbox we cannot
    write to ``~/cltk_data``, so default to a repo-local cache directory and
    reuse any existing home-level Greek embeddings via symlink.
    """
    configured = Path(os.environ["CLTK_DATA"]).expanduser() if os.environ.get("CLTK_DATA") else CLTK_CACHE_DIR
    configured.mkdir(parents=True, exist_ok=True)

    source_embeddings = LEGACY_CLTK_DATA_DIR / "grc" / "embeddings"
    target_embeddings = configured / "grc" / "embeddings"
    if source_embeddings.exists() and not target_embeddings.exists():
        target_embeddings.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_embeddings.symlink_to(source_embeddings, target_is_directory=True)
        except FileExistsError:
            pass

    os.environ["CLTK_DATA"] = str(configured)
    return configured


def detect_reference_system(body) -> str:
    """Identify the citation scheme from <div> attributes in the TEI body.

    Returns one of: 'stephanus', 'bekker', 'book-chapter', 'section', 'unknown'.
    """
    first_div = body.find(f"{{{TEI_NS}}}div")
    if first_div is None:
        first_div = body.find(f".//{{{TEI_NS}}}div")
    if first_div is None:
        return "unknown"

    div_type = (first_div.get("type") or "").lower()
    if "stephanus" in div_type:
        return "stephanus"
    if "bekker" in div_type:
        return "bekker"
    if div_type == "book":
        return "book-chapter"
    if div_type in ("textpart", "section", "chapter"):
        subtype = (first_div.get("subtype") or "").lower()
        if subtype == "book":
            return "book-chapter"
        return "section"
    return "unknown"


def _build_section_ref(div_stack: list) -> str:
    """Build a human-readable section reference from a stack of ancestor div info.

    E.g. [('Stephanus-page', '57'), ('section', 'a')] -> '57a'
    """
    parts = []
    for div_type, n in div_stack:
        dt = div_type.lower()
        if "stephanus" in dt or dt == "section":
            parts.append(n)
        elif dt in ("book", "chapter", "textpart"):
            parts.append(n)
        else:
            parts.append(n)
    return "".join(parts)


# Sentence-splitting regex: split on period, semicolon (Greek question mark),
# middle dot (Greek semicolon/colon), or actual question mark.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;·;])\s+")


def parse_tei_structured(xml_path: str) -> dict:
    """Parse TEI XML with section structure preserved.

    Returns dict with keys: title, author, reference_system, sections[].
    Each section: { ref, text, sentences[] }
    """
    tree = etree.parse(xml_path)
    root = tree.getroot()

    # Extract metadata from teiHeader
    title_el = root.find(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title")
    author_el = root.find(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}author")
    title = title_el.text.strip() if title_el is not None and title_el.text else "Unknown"
    author = author_el.text.strip() if author_el is not None and author_el.text else "Unknown"
    author = re.sub(r"\s+(Phil\.|Hist\.|Trag\.|Comic\.)$", "", author)

    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        raise ValueError("No <body> element found in TEI XML")

    reference_system = detect_reference_system(body)

    sections = []
    _walk_divs(body, [], sections)

    # If no structural divs found, treat entire body as one section
    if not sections:
        full_text = " ".join(_extract_text(p) for p in body.findall(f".//{{{TEI_NS}}}p"))
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(full_text) if s.strip()]
        sections.append({"ref": "1", "text": full_text, "sentences": sentences})

    return {
        "title": title,
        "author": author,
        "reference_system": reference_system,
        "sections": sections,
    }


def _walk_divs(element, div_stack: list, sections: list):
    """Recursively walk div elements to extract leaf sections."""
    child_divs = element.findall(f"{{{TEI_NS}}}div")
    if child_divs:
        for div in child_divs:
            div_type = div.get("type", "")
            n = div.get("n", "")
            _walk_divs(div, div_stack + [(div_type, n)], sections)
    else:
        # Leaf div — extract text from <p> elements
        paragraphs = element.findall(f".//{{{TEI_NS}}}p")
        text_parts = [_extract_text(p) for p in paragraphs]
        full_text = " ".join(text_parts)
        if not full_text.strip():
            return
        ref = _build_section_ref(div_stack) if div_stack else str(len(sections) + 1)
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(full_text) if s.strip()]
        sections.append({"ref": ref, "text": full_text, "sentences": sentences})


def parse_tei(xml_path: str) -> tuple[str, str, str]:
    """Parse TEI XML, return (title, author, text_content).

    Legacy wrapper — delegates to parse_tei_structured and concatenates text.
    """
    result = parse_tei_structured(xml_path)
    text = " ".join(sec["text"] for sec in result["sections"])
    return result["title"], result["author"], text


def normalize_metadata(work_id: str, title: str, author: str) -> tuple[str, str]:
    """Apply narrow per-work metadata overrides for app display."""
    override = WORK_METADATA_OVERRIDES.get(work_id)
    if not override:
        return title, author
    return override.get("title", title), override.get("author", author)


def _extract_text(element) -> str:
    """Recursively extract text from an element, skipping <label> and <pb/> tags."""
    parts = []
    if element.tag == f"{{{TEI_NS}}}label" or element.tag == f"{{{TEI_NS}}}pb":
        return ""
    if element.text:
        parts.append(element.text)
    for child in element:
        parts.append(_extract_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 1a continued. Tokenize
# ---------------------------------------------------------------------------

# Greek Unicode ranges for diacritics/breathings
PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
# More targeted: strip non-Greek punctuation but keep Greek chars
GREEK_TOKEN_RE = re.compile(
    r"[\u0370-\u03FF\u1F00-\u1FFF\u0300-\u036F]+", re.UNICODE
)


def tokenize(text: str) -> list[str]:
    """Tokenize Greek text: split on whitespace, strip punctuation, normalize Unicode."""
    text = unicodedata.normalize("NFC", text)
    # Remove bracketed editorial marks like [ἡμέρᾳ]
    text = re.sub(r"[\[\]]", "", text)
    # Remove quoted markers
    text = text.replace('"', "").replace('"', "").replace('"', "")

    tokens = []
    for word in text.split():
        # Extract Greek characters only
        matches = GREEK_TOKEN_RE.findall(word)
        for m in matches:
            m = m.strip()
            if m:
                tokens.append(m.lower() if m[0].isupper() and len(m) > 1 else m)
    return tokens


# ---------------------------------------------------------------------------
# 1b. Lemmatize & Morphological Analysis (CLTK)
# ---------------------------------------------------------------------------


def lemmatize_tokens(tokens: list[str], batch_size: int = 2000) -> list[dict]:
    """Use CLTK to lemmatize and POS-tag Greek tokens.

    Returns a list of dicts with keys: form, lemma, pos, morphology.
    """
    ensure_cltk_data_dir()
    from cltk import NLP

    nlp = NLP(language="grc", suppress_banner=True)
    results = []
    for start in range(0, len(tokens), batch_size):
        batch_tokens = tokens[start:start + batch_size]
        doc = nlp(" ".join(batch_tokens))
        for word in doc.words:
            form = unicodedata.normalize("NFC", word.string.lower())
            lemma = unicodedata.normalize("NFC", (word.lemma or form).lower())
            pos = word.upos or ""
            morph_parts = []
            if pos:
                morph_parts.append(pos.lower())
            if word.features and hasattr(word.features, "items"):
                for feat_name, feat_vals in word.features.items():
                    if isinstance(feat_vals, (list, tuple)):
                        morph_parts.extend(str(v) for v in feat_vals)
                    else:
                        morph_parts.append(str(feat_vals))
            elif word.features and isinstance(word.features, str):
                morph_parts.append(word.features)

            results.append({
                "form": form,
                "lemma": lemma,
                "pos": pos,
                "morphology": ", ".join(morph_parts) if morph_parts else "",
            })

    return results


def apply_form_analysis_overrides(analyzed: list[dict], work_id: str) -> int:
    """Apply narrow per-work fixes for known CLTK mislemmatizations."""
    overrides = FORM_ANALYSIS_OVERRIDES.get(work_id, {})
    applied = 0

    for entry in analyzed:
        override = overrides.get(entry["form"])
        if not override:
            continue
        entry.update(override)
        applied += 1

    return applied


# ---------------------------------------------------------------------------
# 1c. Filter Stop Words
# ---------------------------------------------------------------------------


def filter_stop_words(lemma_data: dict, stop_words: set) -> dict:
    """Remove entries whose lemma is in the stop word set."""
    return {
        lemma: data
        for lemma, data in lemma_data.items()
        if lemma not in stop_words
    }


# ---------------------------------------------------------------------------
# 1d. Compute Frequency & Assign Levels
# ---------------------------------------------------------------------------


def assign_levels(lemma_data: dict) -> dict:
    """Assign difficulty levels 1-3 (Beginner/Intermediate/Advanced) based on frequency rank.

    Most frequent words get level 1, least frequent get level 3.
    """
    # Sort by frequency descending
    sorted_lemmas = sorted(
        lemma_data.keys(), key=lambda l: lemma_data[l]["frequency"], reverse=True
    )
    n = len(sorted_lemmas)
    if n == 0:
        return lemma_data

    for i, lemma in enumerate(sorted_lemmas):
        # Level 1 = most frequent, level 10 = least frequent
        # Even distribution: for 450 words → exactly 45 per level
        level = min(3, (i * 3) // n + 1)
        lemma_data[lemma]["level"] = level

    return lemma_data


# ---------------------------------------------------------------------------
# 1e. Lookup Definitions (Perseus LSJ lexicon)
# ---------------------------------------------------------------------------


def strip_diacritics(text: str) -> str:
    """Remove all combining diacritical marks from Greek text."""
    nfd = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def lookup_definitions(lemmas: list[str], lexicon_path: str) -> dict:
    """Look up English definitions from the LSJ lexicon JSON.

    Normalization fallback chain:
    1. Exact NFC match
    2. Strip-diacritics match (via pre-built index)
    3. Prefix match (first 4+ chars)
    4. Skip word (empty definition)
    """
    if not os.path.exists(lexicon_path):
        print(f"  ERROR: Lexicon not found at {lexicon_path}")
        print(f"  Run: python scripts/build_lexicon.py")
        sys.exit(1)

    with open(lexicon_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    definitions = data["definitions"]
    stripped_index = data["stripped_index"]
    definition_keys = sorted(definitions)

    results = {}
    matched = 0
    for lemma in lemmas:
        normalized = unicodedata.normalize("NFC", lemma.lower())

        # 1. Exact match
        if normalized in definitions:
            results[lemma] = definitions[normalized]
            matched += 1
            continue

        # 2. Strip-diacritics match
        stripped = strip_diacritics(normalized)
        if stripped in stripped_index:
            original = stripped_index[stripped]
            results[lemma] = definitions[original]
            matched += 1
            continue

        # 3. Prefix match (try longest prefix first, min 4 chars)
        found = False
        for prefix_len in range(len(normalized), 3, -1):
            prefix = normalized[:prefix_len]
            idx = bisect.bisect_left(definition_keys, prefix)
            if idx < len(definition_keys):
                key = definition_keys[idx]
                if key.startswith(prefix):
                    results[lemma] = definitions[key]
                    matched += 1
                    found = True
                    break
            if found:
                break

        if not found:
            results[lemma] = ""

    missing = [l for l in lemmas if not results.get(l)]
    print(f"  Matched {matched}/{len(lemmas)} lemmas in LSJ lexicon")
    if missing:
        print(f"  WARNING: {len(missing)} lemmas have no definition:")
        for l in missing[:20]:
            print(f"    - {l}")
        if len(missing) > 20:
            print(f"    ... and {len(missing) - 20} more")

    return results


# ---------------------------------------------------------------------------
# 1f. Build output JSON
# ---------------------------------------------------------------------------


def extract_contexts(lemma_data: dict, sections: list, max_contexts: int = 3) -> dict:
    """Extract up to max_contexts representative sentence contexts per lemma.

    For each lemma, finds sentences in which one of its forms appears,
    and records the highlight position within the sentence.

    Returns { lemma: [ { ref, form, sentence, highlight_start, highlight_end } ] }
    """
    contexts = defaultdict(list)
    seen_refs = defaultdict(set)
    seen_forms = defaultdict(set)
    form_to_lemmas = defaultdict(list)

    for lemma, data in lemma_data.items():
        for form in data["forms"]:
            form_to_lemmas[form].append(lemma)

    for section in sections:
        for sentence in section["sentences"]:
            sentence_nfc = unicodedata.normalize("NFC", sentence)
            sentence_lower = sentence_nfc.lower()
            sentence_tokens = []
            for token in tokenize(sentence_nfc):
                if token not in sentence_tokens:
                    sentence_tokens.append(token)

            for form in sentence_tokens:
                for lemma in form_to_lemmas.get(form, []):
                    if len(contexts[lemma]) >= max_contexts:
                        continue
                    if section["ref"] in seen_refs[lemma] and len(contexts[lemma]) > 0:
                        continue
                    if form in seen_forms[lemma] and len(contexts[lemma]) > 0:
                        continue

                    form_nfc = unicodedata.normalize("NFC", form)
                    idx = sentence_lower.find(form_nfc.lower())
                    if idx == -1:
                        continue

                    contexts[lemma].append({
                        "ref": section["ref"],
                        "form": form,
                        "sentence": sentence_nfc,
                        "highlight_start": idx,
                        "highlight_end": idx + len(form_nfc),
                    })
                    seen_refs[lemma].add(section["ref"])
                    seen_forms[lemma].add(form)

    return {lemma: items for lemma, items in contexts.items() if items}


def build_vocab_json(
    lemma_data: dict, definitions: dict, title: str, author: str, work_id: str,
    reference_system: str = "unknown", lemma_contexts: dict | None = None,
) -> dict:
    """Build the final vocabulary JSON structure."""
    words = []
    word_id = 0
    for lemma in sorted(lemma_data.keys(), key=lambda l: lemma_data[l]["frequency"], reverse=True):
        data = lemma_data[lemma]
        definition = definitions.get(lemma, "")
        if not definition:
            continue  # Skip words with no definition
        word_id += 1
        forms = []
        for form_str, form_data in sorted(
            data["forms"].items(), key=lambda x: x[1]["occurrences"], reverse=True
        ):
            forms.append({
                "form": form_str,
                "morphology": form_data.get("morphology", ""),
                "occurrences": form_data["occurrences"],
            })
        word_entry = {
            "id": word_id,
            "lemma": lemma,
            "definition": definition,
            "level": data.get("level", 5),
            "frequency": data["frequency"],
            "pos": data.get("pos", ""),
            "forms": forms,
        }
        if lemma_contexts and lemma in lemma_contexts:
            word_entry["contexts"] = lemma_contexts[lemma]
        words.append(word_entry)

    return {
        "metadata": {
            "title": title,
            "author": author,
            "work_id": work_id,
            "reference_system": reference_system,
            "total_words": sum(d["frequency"] for d in lemma_data.values()),
            "unique_lemmas": len(words),
        },
        "words": words,
    }


# ---------------------------------------------------------------------------
# 1g. Update Works Index
# ---------------------------------------------------------------------------


def update_works_index(docs_data_dir: str, work_id: str, title: str, author: str, lemma_count: int):
    """Update docs/data/works.json with the new work."""
    works_path = os.path.join(docs_data_dir, "works.json")
    works = []
    if os.path.exists(works_path):
        with open(works_path, "r", encoding="utf-8") as f:
            works = json.load(f)

    # Update or add entry
    existing = next((w for w in works if w["id"] == work_id), None)
    if existing:
        existing["title"] = title
        existing["author"] = author
        existing["lemma_count"] = lemma_count
    else:
        works.append({
            "id": work_id,
            "title": title,
            "author": author,
            "lemma_count": lemma_count,
        })

    with open(works_path, "w", encoding="utf-8") as f:
        json.dump(works, f, ensure_ascii=False, indent=2)
    print(f"  Updated {works_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Build vocabulary JSON from TEI XML")
    parser.add_argument("xml_path", help="Path to TEI XML file")
    args = parser.parse_args()

    xml_path = args.xml_path
    if not os.path.exists(xml_path):
        print(f"Error: {xml_path} not found")
        sys.exit(1)

    # Derive work_id from filename
    work_id = Path(xml_path).stem
    project_root = Path(__file__).resolve().parent.parent
    lexicon_path = project_root / "data" / "lexicon" / "lsj_shortdefs.json"
    docs_data_dir = project_root / "docs" / "data"
    os.makedirs(docs_data_dir, exist_ok=True)

    # Step 1a: Parse (structured)
    print(f"Parsing {xml_path}...")
    parsed = parse_tei_structured(xml_path)
    title, author = parsed["title"], parsed["author"]
    reference_system = parsed["reference_system"]
    sections = parsed["sections"]
    title, author = normalize_metadata(work_id, title, author)
    print(f"  Title: {title}, Author: {author}")
    print(f"  Reference system: {reference_system}")
    print(f"  Sections: {len(sections)}")

    # Concatenate all section text for tokenization (preserves context-aware lemmatization)
    text = " ".join(sec["text"] for sec in sections)
    tokens = tokenize(text)
    print(f"  Tokens: {len(tokens)}")

    # Step 1b: Lemmatize
    cltk_data_dir = ensure_cltk_data_dir()
    print(f"  CLTK data dir: {cltk_data_dir}")
    print("Lemmatizing with CLTK (this may take a moment on first run)...")
    analyzed = lemmatize_tokens(tokens)
    print(f"  Analyzed {len(analyzed)} tokens")
    override_count = apply_form_analysis_overrides(analyzed, work_id)
    if override_count:
        print(f"  Applied {override_count} form analysis override(s)")

    # Group by lemma
    lemma_data = defaultdict(lambda: {"frequency": 0, "forms": {}, "pos": ""})
    for entry in analyzed:
        lemma = entry["lemma"]
        form = entry["form"]
        ld = lemma_data[lemma]
        ld["frequency"] += 1
        if not ld["pos"] and entry["pos"]:
            ld["pos"] = entry["pos"]
        if form not in ld["forms"]:
            ld["forms"][form] = {"morphology": entry["morphology"], "occurrences": 0}
        ld["forms"][form]["occurrences"] += 1

    print(f"  Unique lemmas: {len(lemma_data)}")

    # Step 1c: Filter stop words and function-word POS
    print("Filtering stop words...")
    from stop_words import STOP_WORDS, STOP_POS

    lemma_data = dict(filter_stop_words(lemma_data, STOP_WORDS))
    print(f"  After stop word filtering: {len(lemma_data)} lemmas")

    # Remove function-word POS categories
    lemma_data = {l: d for l, d in lemma_data.items() if d["pos"] not in STOP_POS}
    print(f"  After POS filtering: {len(lemma_data)} lemmas")

    # Step 1d: Assign levels
    print("Assigning difficulty levels...")
    lemma_data = assign_levels(lemma_data)

    # Step 1e: Lookup definitions from LSJ lexicon
    print("Looking up definitions in LSJ lexicon...")
    all_lemmas = list(lemma_data.keys())
    definitions = lookup_definitions(all_lemmas, str(lexicon_path))

    # Step 1f: Extract contexts
    print("Extracting sentence contexts...")
    lemma_contexts = extract_contexts(lemma_data, sections)
    words_with_ctx = sum(1 for v in lemma_contexts.values() if v)
    print(f"  Found contexts for {words_with_ctx}/{len(lemma_data)} lemmas")

    # Step 1g: Build output JSON
    print("Building vocabulary JSON...")
    vocab = build_vocab_json(
        lemma_data, definitions, title, author, work_id,
        reference_system=reference_system, lemma_contexts=lemma_contexts,
    )
    output_path = docs_data_dir / f"{work_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    print(f"  Wrote {output_path}")
    print(f"  {vocab['metadata']['unique_lemmas']} words across 3 levels")

    # Step 1h: Update works index
    print("Updating works index...")
    update_works_index(
        str(docs_data_dir), work_id, title, author,
        vocab["metadata"]["unique_lemmas"],
    )

    print("\nDone!")


if __name__ == "__main__":
    main()

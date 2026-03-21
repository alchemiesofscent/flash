#!/usr/bin/env python3
"""Build a short-definition lexicon from the Perseus LSJ (Liddell-Scott-Jones) XML.

Downloads the PerseusDL/lexica repo if not present, parses all LSJ XML files,
and outputs a flat JSON mapping of normalized Greek lemmas to concise English
definitions suitable for flashcards.

Usage:
    python scripts/build_lexicon.py
"""

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEXICA_DIR = PROJECT_ROOT / "data" / "lexica"
LSJ_XML_DIR = LEXICA_DIR / "CTS_XML_TEI" / "perseus" / "pdllex" / "grc" / "lsj"
OUTPUT_DIR = PROJECT_ROOT / "data" / "lexicon"
OUTPUT_PATH = OUTPUT_DIR / "lsj_shortdefs.json"


def download_lexica():
    """Clone the PerseusDL/lexica repo if not already present."""
    if LSJ_XML_DIR.exists() and any(LSJ_XML_DIR.glob("*.xml")):
        print(f"  LSJ XML already present at {LSJ_XML_DIR}")
        return

    print(f"  Cloning PerseusDL/lexica into {LEXICA_DIR}...")
    os.makedirs(LEXICA_DIR.parent, exist_ok=True)
    subprocess.run(
        [
            "git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
            "https://github.com/PerseusDL/lexica.git",
            str(LEXICA_DIR),
        ],
        check=True,
    )
    # Sparse checkout only the LSJ XML directory
    subprocess.run(
        ["git", "sparse-checkout", "set", "CTS_XML_TEI/perseus/pdllex/grc/lsj"],
        cwd=str(LEXICA_DIR),
        check=True,
    )
    print(f"  Clone complete.")


def normalize_headword(text: str) -> str:
    """Normalize a Greek headword: NFC, lowercase, strip trailing punctuation."""
    text = unicodedata.normalize("NFC", text.strip())
    text = text.lower()
    # Strip trailing punctuation (periods, commas, etc.)
    text = re.sub(r"[.,;:!?·]+$", "", text)
    return text


def strip_diacritics(text: str) -> str:
    """Remove all combining diacritical marks from Greek text."""
    nfd = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped)


BETA_BASE_MAP = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε",
    "z": "ζ", "h": "η", "q": "θ", "i": "ι", "k": "κ",
    "l": "λ", "m": "μ", "n": "ν", "c": "ξ", "o": "ο",
    "p": "π", "r": "ρ", "s": "σ", "t": "τ", "u": "υ",
    "f": "φ", "x": "χ", "y": "ψ", "w": "ω",
}

# Beta Code diacritics → Unicode combining characters
BETA_DIACRITICS = {
    ")": "\u0313",  # smooth breathing
    "(": "\u0314",  # rough breathing
    "/": "\u0301",  # acute accent
    "\\": "\u0300", # grave accent
    "=": "\u0342",  # circumflex (perispomeni)
    "|": "\u0345",  # iota subscript
    "+": "\u0308",  # diaeresis
}


def beta_to_unicode(beta: str) -> str:
    """Convert Perseus Beta Code key to Unicode Greek with proper diacritics.

    Maps base letters and converts diacritical markers (breathings, accents,
    iota subscript) to Unicode combining characters, then NFC-normalizes.
    Returns empty string if the result contains no Greek characters.
    """
    beta = beta.strip().lower()
    beta = beta.lstrip("*")  # remove uppercase marker

    result = []
    i = 0
    while i < len(beta):
        ch = beta[i]
        if ch in BETA_BASE_MAP:
            # Final sigma: 's' at end or not followed by a base letter
            if ch == "s":
                j = i + 1
                while j < len(beta) and beta[j] in BETA_DIACRITICS:
                    j += 1
                if j >= len(beta) or beta[j] not in BETA_BASE_MAP:
                    result.append("ς")
                else:
                    result.append(BETA_BASE_MAP[ch])
            else:
                result.append(BETA_BASE_MAP[ch])
        elif ch in BETA_DIACRITICS:
            result.append(BETA_DIACRITICS[ch])
        # else: skip digits and unknown characters
        i += 1

    out = "".join(result)
    return unicodedata.normalize("NFC", out) if out else ""


def is_valid_gloss(text: str) -> bool:
    """Check if a <tr> text is a usable English gloss (not junk)."""
    if not text or len(text) < 2:
        return False
    # Skip entries that are mostly non-ASCII (Greek fragments, symbols)
    ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    if ascii_chars < len(text) * 0.5:
        return False
    # Skip common junk patterns: abbreviations, cross-references, etc.
    junk = {"cf", "v", "f", "al", "ib", "sq", "prob", "dub", "perh", "sc"}
    if text.lower().rstrip(".:,") in junk:
        return False
    return True


def extract_text_content(element) -> str:
    """Recursively extract all text content from an XML element."""
    return "".join(element.itertext()).strip()


def truncate_definition(text: str, max_len: int = 80) -> str:
    """Truncate a definition to a flashcard-friendly length.

    Cuts at the first semicolon, period, or comma-separated clause boundary
    that keeps us under max_len. Falls back to hard truncation with ellipsis.
    """
    if not text:
        return ""

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Try cutting at first semicolon
    if ";" in text:
        first = text.split(";")[0].strip()
        if 2 < len(first) <= max_len:
            return first

    # Try cutting at first period (that isn't an abbreviation)
    parts = re.split(r"(?<!\b[A-Z])\.(?!\w)", text, maxsplit=1)
    if len(parts) > 1:
        first = parts[0].strip()
        if 2 < len(first) <= max_len:
            return first

    # If already short enough, return as-is
    if len(text) <= max_len:
        return text

    # Hard truncate at word boundary
    truncated = text[:max_len].rsplit(" ", 1)[0]
    return truncated + "…" if truncated != text else truncated


def parse_lsj_file(xml_path: Path) -> dict:
    """Parse a single LSJ XML file. Returns {headword: definition} pairs."""
    entries = {}
    try:
        parser = etree.XMLParser(load_dtd=False, no_network=True, recover=True)
        tree = etree.parse(str(xml_path), parser)
    except etree.XMLSyntaxError as e:
        print(f"  WARNING: XML parse error in {xml_path.name}: {e}")
        return entries

    root = tree.getroot()

    # Find all <entry> elements (may have various namespace configurations)
    for entry in root.iter():
        if not isinstance(entry.tag, str):
            continue
        tag_local = entry.tag.split("}")[-1] if "}" in entry.tag else entry.tag
        if tag_local in ("entry", "entryFree"):
            # Extract headword: prefer 'key' attribute (Beta Code), else <orth>
            key_attr = entry.get("key", "")
            orth = None
            if key_attr:
                orth = beta_to_unicode(key_attr)
            if not orth:
                for child in entry.iter():
                    if not isinstance(child.tag, str):
                        continue
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "orth":
                        orth = child.text or extract_text_content(child)
                        break

            if not orth:
                continue

            headword = normalize_headword(orth)
            if not headword:
                continue

            # Extract definition from <tr> (translation) elements inside
            # the first <sense>, which contain clean English glosses.
            definition = ""

            # Collect <tr> texts from the first <sense> element
            first_sense = None
            for child in entry.iter():
                if not isinstance(child.tag, str):
                    continue
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "sense":
                    first_sense = child
                    break

            if first_sense is not None:
                tr_texts = []
                for child in first_sense.iter():
                    if not isinstance(child.tag, str):
                        continue
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "tr":
                        tr_text = (child.text or "").strip().strip(",;.: ")
                        if is_valid_gloss(tr_text):
                            tr_texts.append(tr_text)
                if tr_texts:
                    seen = set()
                    unique = []
                    for t in tr_texts:
                        t_lower = t.lower()
                        if t_lower not in seen:
                            seen.add(t_lower)
                            unique.append(t)
                    definition = ", ".join(unique)

            # Fallback: try any <tr> in the entire entry
            if not definition:
                tr_texts = []
                for child in entry.iter():
                    if not isinstance(child.tag, str):
                        continue
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == "tr":
                        tr_text = (child.text or "").strip().strip(",;.: ")
                        if is_valid_gloss(tr_text):
                            tr_texts.append(tr_text)
                            if len(tr_texts) >= 5:
                                break
                if tr_texts:
                    seen = set()
                    unique = []
                    for t in tr_texts:
                        t_lower = t.lower()
                        if t_lower not in seen:
                            seen.add(t_lower)
                            unique.append(t)
                    definition = ", ".join(unique)

            if definition:
                definition = truncate_definition(definition)
                if definition and headword not in entries:
                    entries[headword] = definition

    return entries


def build_lexicon():
    """Main entry point: download LSJ, parse all files, output JSON."""
    print("Building LSJ lexicon...")

    # Step 1: Download if needed
    download_lexica()

    # Step 2: Find all XML files
    xml_files = sorted(LSJ_XML_DIR.glob("*.xml"))
    if not xml_files:
        print(f"  ERROR: No XML files found in {LSJ_XML_DIR}")
        sys.exit(1)
    print(f"  Found {len(xml_files)} XML files")

    # Step 3: Parse all files
    lexicon = {}
    for xml_file in xml_files:
        print(f"  Parsing {xml_file.name}...")
        entries = parse_lsj_file(xml_file)
        lexicon.update(entries)

    print(f"  Total entries: {len(lexicon)}")

    # Step 4: Also build a strip-diacritics index for fallback lookups
    # (stored in the same file as a separate key for efficiency)
    stripped_index = {}
    for headword, definition in lexicon.items():
        stripped = strip_diacritics(headword)
        if stripped not in stripped_index:
            stripped_index[stripped] = headword

    # Step 5: Write output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output = {
        "definitions": lexicon,
        "stripped_index": stripped_index,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  Wrote {OUTPUT_PATH} ({len(lexicon)} entries)")

    return lexicon


if __name__ == "__main__":
    build_lexicon()

#!/usr/bin/env python3
"""Helpers for deterministic and model-backed English translation highlights."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None


WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

MODEL_ALIGN_MODEL = "claude-haiku-4-5-20251001"
MODEL_ALIGN_BATCH_SIZE = 20
MODEL_ALIGN_MAX_TOKENS = 4096

METHOD_CONFIDENCE = {
    "exact_phrase": "high",
    "phrase_override": "high",
    "exact_token": "medium",
    "model_align": "high",
    "none": "low",
}

ALLOWED_METHODS = set(METHOD_CONFIDENCE)
ALLOWED_CONFIDENCES = {"high", "medium", "low"}

STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "both",
    "but",
    "by",
    "did",
    "do",
    "does",
    "further",
    "for",
    "from",
    "hence",
    "if",
    "in",
    "indeed",
    "into",
    "is",
    "it",
    "kind",
    "not",
    "of",
    "on",
    "one",
    "or",
    "out",
    "over",
    "since",
    "so",
    "sort",
    "that",
    "the",
    "their",
    "then",
    "there",
    "therefore",
    "these",
    "this",
    "those",
    "to",
    "under",
    "up",
    "what",
    "when",
    "whenever",
    "where",
    "which",
    "who",
    "with",
}

SURFACE_OVERRIDES = {
    "began": {"begin", "began", "beginning"},
    "came": {"come", "came"},
    "cities": {"city", "cities"},
    "constitutions": {"constitution", "constitutions"},
    "had": {"have", "has", "had"},
    "held": {"hold", "holds", "held"},
    "said": {"say", "says", "said"},
    "spoke": {"speak", "speaks", "spoke", "spoken"},
    "told": {"tell", "tells", "told"},
}

CANDIDATE_TOKEN_OVERRIDES = {
    "able": {"able", "capable"},
    "beginning": {"beginning", "begin", "began", "origin", "source", "first"},
    "case": {"case", "condition", "state", "status"},
    "city": {"city", "cities"},
    "community": {"community", "communities", "association", "partnership", "sharing"},
    "constitution": {"constitution", "constitutions", "republic"},
    "great": {"great", "large", "considerable"},
    "happen": {"happen", "happens", "happened", "occur", "occurs", "occurred"},
    "have": {"have", "has", "had", "hold", "holds", "held", "possess", "possesses", "possessed"},
    "human": {"human", "humans", "man", "men", "person", "people", "being", "beings"},
    "many": {"many", "much", "more", "numerous", "considerable"},
    "necessary": {"necessary", "must", "should", "ought", "need", "required", "just", "fitting", "proper", "appropriate"},
    "other": {"other", "another", "else"},
    "person": {"person", "persons", "people", "human", "humans", "man", "men", "being", "beings"},
    "political": {"political", "civic", "civil"},
    "position": {"position", "status", "place"},
    "principle": {"principle", "principles", "source", "sources", "beginning", "beginnings"},
    "ruling": {"ruling", "rule", "rules", "governing", "govern", "governs", "authoritative"},
    "say": {"say", "says", "said", "speak", "speaks", "spoke", "spoken", "tell", "tells", "told"},
    "speak": {"speak", "speaks", "spoke", "spoken", "said"},
    "tell": {"tell", "tells", "told", "said"},
}

PHRASE_OVERRIDES = {
    "come to be": {"come to be", "came to be", "come into being"},
    "happen": {"take place", "takes place", "took place"},
    "say": {"story goes"},
}

ALIGNMENT_SYSTEM_PROMPT = (
    "You align a marked Ancient Greek word to an already-written English translation. "
    "For each entry, identify the shortest contiguous English substring in the given "
    '"translation" that corresponds most directly to the Greek word marked with [[...]] '
    'in "greek_sentence_marked". Return a JSON array. Each item must contain: '
    '"context_id" (unchanged), "matched_text" (exact substring from translation, or null '
    'if there is no localized phrase to highlight), "occurrence" (1-based occurrence of '
    'matched_text in translation, or null), and "confidence" ("high", "medium", or "low"). '
    "Do not rewrite the translation. Do not explain. Return only JSON."
)


def load_dotenv() -> None:
    """Load .env values from the project root into the environment."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


def create_anthropic_client(api_key: str | None = None):
    """Create an Anthropic client from an explicit or environment API key."""
    if anthropic is None:
        raise RuntimeError("The 'anthropic' package is not installed.")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=key)


def _simple_stem(token: str) -> str:
    token = token.lower()
    if token in SURFACE_OVERRIDES:
        return sorted(SURFACE_OVERRIDES[token])[0]
    for suffix, minimum in (
        ("ingly", 6),
        ("edly", 6),
        ("ing", 5),
        ("ied", 5),
        ("ies", 5),
        ("ed", 4),
        ("es", 4),
        ("s", 4),
    ):
        if token.endswith(suffix) and len(token) >= minimum:
            if suffix in {"ied", "ies"}:
                return token[:-3] + "y"
            return token[: -len(suffix)]
    return token


def _token_variants(token: str) -> set[str]:
    token = token.lower()
    variants = {token, _simple_stem(token)}
    variants.update(SURFACE_OVERRIDES.get(token, set()))
    variants.update(SURFACE_OVERRIDES.get(_simple_stem(token), set()))
    return {variant for variant in variants if variant}


def _candidate_token_forms(token: str) -> set[str]:
    token = token.lower()
    forms = _token_variants(token)
    forms.update(CANDIDATE_TOKEN_OVERRIDES.get(token, set()))
    forms.update(CANDIDATE_TOKEN_OVERRIDES.get(_simple_stem(token), set()))
    return {form.lower() for form in forms if form}


def _candidate_phrases(*texts: str | None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for text in texts:
        if not text:
            continue
        parts = [part.strip().lower() for part in re.split(r"[,;/()]", text) if part.strip()]
        for part in parts:
            part = " ".join(part.split())
            variants = [part, part.replace("-", " ")]
            tokens = [token.lower() for token in WORD_RE.findall(part.replace("-", " "))]
            content = [token for token in tokens if token not in STOPWORDS]
            variants.extend(content)
            if len(content) >= 2:
                variants.append(" ".join(content))
                variants.extend(
                    f"{left} {right}" for left, right in zip(content, content[1:])
                )

            for variant in variants:
                variant = " ".join(variant.split())
                if len(variant) >= 3 and variant not in seen:
                    seen.add(variant)
                    candidates.append(variant)

    return sorted(candidates, key=len, reverse=True)


def _candidate_phrase_forms(candidates: list[str]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    phrases: list[tuple[str, str]] = []

    for candidate in candidates:
        normalized = " ".join(candidate.lower().split())
        pair = (normalized, "exact_phrase")
        if normalized and pair not in seen:
            seen.add(pair)
            phrases.append(pair)

        for phrase in PHRASE_OVERRIDES.get(candidate, set()):
            normalized_override = " ".join(phrase.lower().split())
            pair = (normalized_override, "phrase_override")
            if normalized_override and pair not in seen:
                seen.add(pair)
                phrases.append(pair)

    return phrases


def _translation_tokens(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in WORD_RE.finditer(text)]


def _match_candidates(
    translation: str,
    tokens: list[tuple[str, int, int]],
    candidates: list[str],
) -> dict[str, object] | None:
    lower_translation = translation.lower()

    for phrase, method in _candidate_phrase_forms(candidates):
        match = re.search(rf"\b{re.escape(phrase)}\b", lower_translation)
        if match:
            return {
                "method": method,
                "confidence": METHOD_CONFIDENCE[method],
                "start": match.start(),
                "end": match.end(),
            }

    for word, start, end in tokens:
        translation_forms = _token_variants(word)
        for candidate in candidates:
            parts = WORD_RE.findall(candidate)
            if len(parts) == 1 and (_candidate_token_forms(parts[0]) & translation_forms):
                return {
                    "method": "exact_token",
                    "confidence": METHOD_CONFIDENCE["exact_token"],
                    "start": start,
                    "end": end,
                }

    return None


def find_translation_highlight(
    translation: str,
    gloss: str | None,
    dictionary_definition: str | None = None,
) -> dict[str, object]:
    """Find a deterministic English highlight span from gloss and translation."""
    tokens = _translation_tokens(translation)
    if not tokens:
        return {"method": "none", "confidence": "low", "start": None, "end": None}

    candidates = _candidate_phrases(gloss)
    if not candidates and dictionary_definition:
        candidates = _candidate_phrases(dictionary_definition)

    if candidates:
        match = _match_candidates(translation, tokens, candidates)
        if match:
            return match

    return {"method": "none", "confidence": "low", "start": None, "end": None}


def set_translation_highlight(ctx: dict, result: dict[str, object]) -> None:
    """Apply a highlight result to a context object."""
    method = result.get("method", "none")
    confidence = result.get("confidence", METHOD_CONFIDENCE.get(method, "low"))

    ctx["translation_highlight_method"] = method
    ctx["translation_highlight_confidence"] = confidence

    start = result.get("start")
    end = result.get("end")
    if method == "none" or start is None or end is None:
        ctx.pop("translation_highlight_start", None)
        ctx.pop("translation_highlight_end", None)
        return

    ctx["translation_highlight_start"] = int(start)
    ctx["translation_highlight_end"] = int(end)


def apply_translation_highlights_to_word(word: dict) -> Counter:
    """Apply deterministic translation highlights to all translated contexts on a word."""
    counts: Counter = Counter()
    gloss = word.get("context_definition")
    dictionary_definition = word.get("definition")

    for ctx in word.get("contexts", []):
        translation = ctx.get("translation")
        if not translation:
            continue

        result = find_translation_highlight(
            translation,
            gloss,
            dictionary_definition=dictionary_definition,
        )
        set_translation_highlight(ctx, result)
        counts[result["method"]] += 1

    return counts


def backfill_translation_highlights(data: dict) -> Counter:
    """Apply deterministic translation highlight spans across an entire vocab payload."""
    counts: Counter = Counter()
    for word in data.get("words", []):
        counts.update(apply_translation_highlights_to_word(word))
    return counts


def _marked_greek_sentence(ctx: dict) -> str:
    sentence = ctx["sentence"]
    start = ctx["highlight_start"]
    end = ctx["highlight_end"]
    return sentence[:start] + "[[" + sentence[start:end] + "]]" + sentence[end:]


def _iter_unresolved_contexts(words: list[dict]) -> list[dict]:
    unresolved: list[dict] = []
    for word in words:
        gloss = word.get("context_definition") or word.get("definition")
        for index, ctx in enumerate(word.get("contexts", [])):
            if not ctx.get("translation"):
                continue
            if ctx.get("translation_highlight_method") != "none":
                continue
            unresolved.append(
                {
                    "context_id": f"{word['id']}:{index}",
                    "lemma": word["lemma"],
                    "gloss": gloss,
                    "ref": ctx["ref"],
                    "translation": ctx["translation"],
                    "greek_sentence_marked": _marked_greek_sentence(ctx),
                    "word": word,
                    "context": ctx,
                }
            )
    return unresolved


def _locate_occurrence(text: str, needle: str, occurrence: int | None) -> tuple[int, int] | None:
    if not needle:
        return None

    occurrence = occurrence or 1
    start = 0
    hits = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            break
        hits += 1
        if hits == occurrence:
            return idx, idx + len(needle)
        start = idx + len(needle)

    lower_text = text.lower()
    lower_needle = needle.lower()
    start = 0
    hits = 0
    while True:
        idx = lower_text.find(lower_needle, start)
        if idx < 0:
            return None
        hits += 1
        if hits == occurrence:
            return idx, idx + len(needle)
        start = idx + len(needle)


def _parse_alignment_response(text: str) -> list[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    payload = json.loads(cleaned)
    if not isinstance(payload, list):
        raise ValueError("Alignment response must be a JSON array.")
    return payload


def _run_alignment_batch(client, entries: list[dict], model: str) -> list[dict]:
    payload = [
        {
            "context_id": entry["context_id"],
            "lemma": entry["lemma"],
            "gloss": entry["gloss"],
            "ref": entry["ref"],
            "greek_sentence_marked": entry["greek_sentence_marked"],
            "translation": entry["translation"],
        }
        for entry in entries
    ]
    response = client.messages.create(
        model=model,
        max_tokens=MODEL_ALIGN_MAX_TOKENS,
        system=ALIGNMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
    )

    if response.stop_reason == "max_tokens":
        raise ValueError("Alignment response truncated (hit max_tokens).")

    return _parse_alignment_response(response.content[0].text)


def align_translation_highlights_for_words(
    words: list[dict],
    client,
    model: str = MODEL_ALIGN_MODEL,
    batch_size: int = MODEL_ALIGN_BATCH_SIZE,
) -> Counter:
    """Resolve unresolved English highlights with a model alignment pass."""
    counts: Counter = Counter()
    unresolved = _iter_unresolved_contexts(words)
    if not unresolved:
        return counts

    by_id = {entry["context_id"]: entry for entry in unresolved}

    for start in range(0, len(unresolved), batch_size):
        batch = unresolved[start : start + batch_size]
        results = _run_alignment_batch(client, batch, model=model)
        seen: set[str] = set()

        for item in results:
            context_id = item.get("context_id")
            if not context_id or context_id not in by_id:
                continue
            entry = by_id[context_id]
            ctx = entry["context"]
            seen.add(context_id)

            matched_text = item.get("matched_text")
            confidence = item.get("confidence") or "low"
            occurrence = item.get("occurrence")

            if confidence not in ALLOWED_CONFIDENCES:
                confidence = "low"

            if not matched_text or confidence == "low":
                set_translation_highlight(
                    ctx,
                    {"method": "none", "confidence": "low", "start": None, "end": None},
                )
                counts["none"] += 1
                continue

            located = _locate_occurrence(ctx["translation"], matched_text, occurrence)
            if not located:
                set_translation_highlight(
                    ctx,
                    {"method": "none", "confidence": "low", "start": None, "end": None},
                )
                counts["none"] += 1
                continue

            set_translation_highlight(
                ctx,
                {
                    "method": "model_align",
                    "confidence": "high" if confidence == "high" else "medium",
                    "start": located[0],
                    "end": located[1],
                },
            )
            counts["model_align"] += 1

        for entry in batch:
            if entry["context_id"] in seen:
                continue
            set_translation_highlight(
                entry["context"],
                {"method": "none", "confidence": "low", "start": None, "end": None},
            )
            counts["none"] += 1

    return counts

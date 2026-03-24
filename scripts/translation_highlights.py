#!/usr/bin/env python3
"""Helpers for deterministic English translation highlights.

This module derives a highlight span inside a context translation from the
word's enriched gloss and dictionary definition. It prefers direct matches,
then token-level and fuzzy matches, and falls back to the first meaningful
token so the UI always has a deterministic span to render.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

STOPWORDS = {
    "a",
    "an",
    "also",
    "and",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "did",
    "do",
    "does",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "kind",
    "of",
    "on",
    "one",
    "or",
    "out",
    "over",
    "so",
    "sort",
    "there",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "under",
    "up",
    "whenever",
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
    "say": {"say", "says", "said", "speak", "speaks", "spoke", "spoken", "tell", "tells", "told", "report", "reported", "call", "called"},
    "speak": {"speak", "speaks", "spoke", "spoken", "said"},
    "tell": {"tell", "tells", "told", "said", "report", "reported"},
}

PHRASE_OVERRIDES = {
    "come to be": {"come to be", "came to be", "come into being"},
    "happen": {"take place", "takes place", "took place"},
    "say": {"story goes"},
}


def _simple_stem(token: str) -> str:
    token = token.lower()
    if token in SURFACE_OVERRIDES:
        return sorted(SURFACE_OVERRIDES[token])[0]
    for suffix, minimum in (("ingly", 6), ("edly", 6), ("ing", 5), ("ied", 5), ("ies", 5), ("ed", 4), ("es", 4), ("s", 4)):
        if token.endswith(suffix) and len(token) >= minimum:
            if suffix == "ied":
                return token[:-3] + "y"
            if suffix == "ies":
                return token[:-3] + "y"
            return token[: -len(suffix)]
    return token


def _token_variants(token: str) -> set[str]:
    token = token.lower()
    variants = {token, _simple_stem(token)}
    variants.update(SURFACE_OVERRIDES.get(token, set()))
    stem = _simple_stem(token)
    variants.update(SURFACE_OVERRIDES.get(stem, set()))
    return {variant for variant in variants if variant}


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


def _candidate_token_forms(token: str) -> set[str]:
    token = token.lower()
    forms = _token_variants(token)
    forms.update(CANDIDATE_TOKEN_OVERRIDES.get(token, set()))
    forms.update(CANDIDATE_TOKEN_OVERRIDES.get(_simple_stem(token), set()))
    return {form.lower() for form in forms if form}


def _candidate_phrase_forms(candidates: list[str]) -> list[str]:
    seen: set[str] = set()
    phrases: list[str] = []
    for candidate in candidates:
        for phrase in [candidate, *PHRASE_OVERRIDES.get(candidate, set())]:
            phrase = " ".join(phrase.lower().split())
            if phrase and phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)
    return phrases


def _match_candidates(
    translation: str,
    tokens: list[tuple[str, int, int]],
    candidates: list[str],
) -> tuple[int, int, str] | None:
    lower_translation = translation.lower()

    for candidate in _candidate_phrase_forms(candidates):
        match = re.search(rf"\b{re.escape(candidate)}\b", lower_translation)
        if match:
            return match.start(), match.end(), "exact-phrase"

    for word, start, end in tokens:
        translation_forms = _token_variants(word)
        for candidate in candidates:
            parts = WORD_RE.findall(candidate)
            if len(parts) == 1 and (_candidate_token_forms(parts[0]) & translation_forms):
                return start, end, "exact-token"

    best_span: tuple[int, int] | None = None
    best_score = 0.0

    for word, start, end in tokens:
        word_lower = word.lower()
        word_stem = _simple_stem(word_lower)
        for candidate in candidates:
            for candidate_token in WORD_RE.findall(candidate):
                candidate_token = candidate_token.lower()
                if candidate_token in STOPWORDS:
                    continue
                score = max(
                    _string_score(candidate_token, word_lower),
                    _string_score(_simple_stem(candidate_token), word_stem),
                )
                if score >= 0.9 and score > best_score:
                    best_span = (start, end)
                    best_score = score

    if best_span:
        return best_span[0], best_span[1], "fuzzy-token"

    return None


def _translation_tokens(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in WORD_RE.finditer(text)]


def _string_score(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def find_translation_highlight(
    translation: str,
    gloss: str | None,
    dictionary_definition: str | None = None,
) -> tuple[int, int, str]:
    """Return `(start, end, strategy)` for the English highlight span."""
    tokens = _translation_tokens(translation)
    if not tokens:
        return 0, len(translation), "empty"

    primary_candidates = _candidate_phrases(gloss)
    secondary_candidates = (
        _candidate_phrases(dictionary_definition)
        if dictionary_definition and dictionary_definition != gloss
        else []
    )

    match = _match_candidates(translation, tokens, primary_candidates)
    if match:
        return match

    if secondary_candidates:
        match = _match_candidates(translation, tokens, secondary_candidates)
        if match:
            return match

    for word, start, end in tokens:
        if word.lower() not in STOPWORDS and len(word) >= 3:
            return start, end, "fallback"

    return tokens[0][1], tokens[0][2], "fallback"


def apply_translation_highlights_to_word(word: dict) -> Counter:
    """Add translation highlight spans to all translated contexts on a word."""
    counts: Counter = Counter()
    gloss = word.get("context_definition")
    dictionary_definition = word.get("definition")

    for ctx in word.get("contexts", []):
        translation = ctx.get("translation")
        if not translation:
            continue
        start, end, strategy = find_translation_highlight(
            translation,
            gloss,
            dictionary_definition=dictionary_definition,
        )
        ctx["translation_highlight_start"] = start
        ctx["translation_highlight_end"] = end
        counts[strategy] += 1

    return counts


def backfill_translation_highlights(data: dict) -> Counter:
    """Apply translation highlight spans across an entire vocab payload."""
    counts: Counter = Counter()
    for word in data.get("words", []):
        counts.update(apply_translation_highlights_to_word(word))
    return counts
    "if",

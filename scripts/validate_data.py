#!/usr/bin/env python3
"""
Validate a vocab JSON file for the flash project.

Usage:
    python scripts/validate_data.py docs/data/tlg0059004.json
"""

import json
import os
import sys


def error(msg):
    print(f"  FAIL: {msg}")
    return False


def ok(msg):
    print(f"  PASS: {msg}")
    return True


def validate_file(filepath):
    print(f"\nValidating: {filepath}")
    print("-" * 60)
    failures = []

    # --- Load and parse JSON ---
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        ok("File is valid JSON")
    except FileNotFoundError:
        error(f"File not found: {filepath}")
        return False
    except json.JSONDecodeError as e:
        error(f"Invalid JSON: {e}")
        return False

    # --- Validate metadata ---
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        failures.append(error("'metadata' key is missing or not an object"))
    else:
        ok("'metadata' key present")

        for field in ("title", "author", "work_id"):
            val = metadata.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                failures.append(
                    error(f"metadata.{field} is missing or empty")
                )
            else:
                ok(f"metadata.{field} = {val!r}")

        total_words = metadata.get("total_words")
        if not isinstance(total_words, int) or total_words <= 0:
            failures.append(
                error(
                    f"metadata.total_words must be an int > 0 (got {total_words!r})"
                )
            )
        else:
            ok(f"metadata.total_words = {total_words}")

        unique_lemmas = metadata.get("unique_lemmas")
        if not isinstance(unique_lemmas, int) or unique_lemmas <= 0:
            failures.append(
                error(
                    f"metadata.unique_lemmas must be an int > 0 (got {unique_lemmas!r})"
                )
            )
        else:
            ok(f"metadata.unique_lemmas = {unique_lemmas}")

    # --- Validate words array ---
    words = data.get("words")
    if not isinstance(words, list) or len(words) == 0:
        failures.append(error("'words' must be a non-empty array"))
        # Cannot continue word-level checks
        print("\n" + "=" * 60)
        print("RESULT: FAILED")
        return False
    else:
        ok(f"'words' array present with {len(words)} entries")

    # --- Validate each word ---
    seen_ids = {}
    levels_seen = set()
    word_errors = 0

    for i, word in enumerate(words):
        prefix = f"words[{i}]"

        # id
        word_id = word.get("id")
        if not isinstance(word_id, int):
            failures.append(error(f"{prefix}.id must be an int (got {word_id!r})"))
            word_errors += 1
        elif word_id in seen_ids:
            failures.append(
                error(
                    f"{prefix}.id={word_id} is a duplicate (first seen at index {seen_ids[word_id]})"
                )
            )
            word_errors += 1
        else:
            seen_ids[word_id] = i

        # lemma
        lemma = word.get("lemma")
        if not lemma or not isinstance(lemma, str) or not lemma.strip():
            failures.append(error(f"{prefix}.lemma is missing or empty"))
            word_errors += 1

        # definition
        definition = word.get("definition")
        if not definition or not isinstance(definition, str) or not definition.strip():
            failures.append(error(f"{prefix}.definition is missing or empty"))
            word_errors += 1

        # level
        level = word.get("level")
        if not isinstance(level, int) or not (1 <= level <= 3):
            failures.append(
                error(f"{prefix}.level must be an int 1–3 (got {level!r})")
            )
            word_errors += 1
        else:
            levels_seen.add(level)

        # frequency
        frequency = word.get("frequency")
        if not isinstance(frequency, (int, float)) or frequency <= 0:
            failures.append(
                error(f"{prefix}.frequency must be > 0 (got {frequency!r})")
            )
            word_errors += 1

        # pos
        pos = word.get("pos")
        if not pos or not isinstance(pos, str) or not pos.strip():
            failures.append(error(f"{prefix}.pos is missing or empty"))
            word_errors += 1

        # forms
        forms = word.get("forms")
        if not isinstance(forms, list) or len(forms) == 0:
            failures.append(error(f"{prefix}.forms must be a non-empty array"))
            word_errors += 1
        else:
            for j, form in enumerate(forms):
                fprefix = f"{prefix}.forms[{j}]"

                form_str = form.get("form")
                if not form_str or not isinstance(form_str, str) or not form_str.strip():
                    failures.append(error(f"{fprefix}.form is missing or empty"))
                    word_errors += 1

                morphology = form.get("morphology")
                if not isinstance(morphology, str):
                    failures.append(
                        error(f"{fprefix}.morphology must be a string (got {morphology!r})")
                    )
                    word_errors += 1

                occurrences = form.get("occurrences")
                if not isinstance(occurrences, int) or occurrences <= 0:
                    failures.append(
                        error(
                            f"{fprefix}.occurrences must be an int > 0 (got {occurrences!r})"
                        )
                    )
                    word_errors += 1

    if word_errors == 0:
        ok("All word entries are valid")
    else:
        # individual errors already printed above
        pass

    # --- All word IDs unique ---
    if len(seen_ids) == len(words):
        ok("All word IDs are unique")
    # duplicate errors already recorded above

    # --- All 10 levels present ---
    expected_levels = set(range(1, 4))
    missing_levels = expected_levels - levels_seen
    if missing_levels:
        failures.append(
            error(f"Missing levels: {sorted(missing_levels)}")
        )
    else:
        ok("All 3 levels (1–3) are present")

    # --- metadata.unique_lemmas matches len(words) ---
    if isinstance(metadata, dict) and isinstance(metadata.get("unique_lemmas"), int):
        if metadata["unique_lemmas"] != len(words):
            failures.append(
                error(
                    f"metadata.unique_lemmas ({metadata['unique_lemmas']}) "
                    f"does not match len(words) ({len(words)})"
                )
            )
        else:
            ok(
                f"metadata.unique_lemmas ({metadata['unique_lemmas']}) "
                f"matches len(words)"
            )

    # --- Optional: validate reference_system ---
    if isinstance(metadata, dict):
        ref_sys = metadata.get("reference_system")
        if ref_sys and isinstance(ref_sys, str) and ref_sys.strip():
            ok(f"metadata.reference_system = {ref_sys!r}")
        else:
            print(f"  INFO: metadata.reference_system not present (optional)")

    # --- Optional: validate contexts arrays ---
    context_errors = 0
    words_with_contexts = 0
    for i, word in enumerate(words):
        contexts = word.get("contexts")
        if contexts is None:
            continue
        prefix = f"words[{i}]"
        if not isinstance(contexts, list):
            failures.append(error(f"{prefix}.contexts must be an array"))
            context_errors += 1
            continue
        words_with_contexts += 1
        for j, ctx in enumerate(contexts):
            cprefix = f"{prefix}.contexts[{j}]"
            if not isinstance(ctx, dict):
                failures.append(error(f"{cprefix} must be an object"))
                context_errors += 1
                continue
            # Required context fields
            for field in ("ref", "form", "sentence"):
                if not ctx.get(field) or not isinstance(ctx.get(field), str):
                    failures.append(error(f"{cprefix}.{field} is missing or empty"))
                    context_errors += 1
            # Highlight bounds
            hs = ctx.get("highlight_start")
            he = ctx.get("highlight_end")
            sentence = ctx.get("sentence", "")
            if not isinstance(hs, int) or not isinstance(he, int):
                failures.append(error(f"{cprefix}.highlight_start/end must be ints"))
                context_errors += 1
            elif hs < 0 or he > len(sentence) or hs >= he:
                failures.append(
                    error(
                        f"{cprefix}.highlight bounds out of range "
                        f"(start={hs}, end={he}, sentence_len={len(sentence)})"
                    )
                )
                context_errors += 1

    if words_with_contexts > 0 and context_errors == 0:
        ok(f"Contexts valid for {words_with_contexts} words")
    elif words_with_contexts == 0:
        print(f"  INFO: No words have contexts (optional field)")

    # --- Optional: validate enrichment fields ---
    words_with_context_def = 0
    contexts_with_translation = 0
    total_contexts = 0
    enrichment_errors = 0

    for i, word in enumerate(words):
        prefix = f"words[{i}]"

        # context_definition
        ctx_def = word.get("context_definition")
        if ctx_def is not None:
            if not isinstance(ctx_def, str) or not ctx_def.strip():
                failures.append(
                    error(f"{prefix}.context_definition must be a non-empty string")
                )
                enrichment_errors += 1
            else:
                words_with_context_def += 1

        # etymology
        etymology = word.get("etymology")
        if etymology is not None:
            if not isinstance(etymology, str) or not etymology.strip():
                failures.append(
                    error(f"{prefix}.etymology must be a non-empty string")
                )
                enrichment_errors += 1

        # contexts[].translation
        for j, ctx in enumerate(word.get("contexts", [])):
            total_contexts += 1
            translation = ctx.get("translation")
            if translation is not None:
                if not isinstance(translation, str) or not translation.strip():
                    failures.append(
                        error(
                            f"{prefix}.contexts[{j}].translation must be a non-empty string"
                        )
                    )
                    enrichment_errors += 1
                else:
                    contexts_with_translation += 1
                    ths = ctx.get("translation_highlight_start")
                    the = ctx.get("translation_highlight_end")
                    if not isinstance(ths, int) or not isinstance(the, int):
                        failures.append(
                            error(
                                f"{prefix}.contexts[{j}].translation_highlight_start/end must be ints"
                            )
                        )
                        enrichment_errors += 1
                    elif ths < 0 or the > len(translation) or ths >= the:
                        failures.append(
                            error(
                                f"{prefix}.contexts[{j}].translation highlight bounds out of range "
                                f"(start={ths}, end={the}, translation_len={len(translation)})"
                            )
                        )
                        enrichment_errors += 1

    # --- Morphology stats ---
    words_with_detailed_morph = 0
    for word in words:
        forms = word.get("forms", [])
        if len(forms) >= 2:
            morphs = [f.get("morphology", "").strip() for f in forms]
            # Detailed = has spaces or commas (more than a bare POS tag)
            has_detailed = any(" " in m or "," in m for m in morphs if m)
            if has_detailed:
                words_with_detailed_morph += 1

    multi_form_words = sum(1 for w in words if len(w.get("forms", [])) >= 2)

    words_with_etymology = sum(1 for w in words if w.get("etymology"))

    if enrichment_errors == 0:
        print(
            f"  INFO: {words_with_context_def}/{len(words)} words have context_definition"
        )
        print(
            f"  INFO: {contexts_with_translation}/{total_contexts} contexts have translation"
        )
        print(
            f"  INFO: {words_with_detailed_morph}/{multi_form_words} multi-form words have detailed morphology"
        )
        print(
            f"  INFO: {words_with_etymology}/{len(words)} words have etymology"
        )

    # --- Optional: check works.json in same directory ---
    data_dir = os.path.dirname(os.path.abspath(filepath))
    works_path = os.path.join(data_dir, "works.json")
    if os.path.exists(works_path):
        try:
            with open(works_path, "r", encoding="utf-8") as f:
                works_data = json.load(f)

            work_id = metadata.get("work_id") if isinstance(metadata, dict) else None
            # works.json may be a list of objects or a dict keyed by work_id
            if isinstance(works_data, list):
                ids_in_works = [
                    w.get("id", w.get("work_id")) for w in works_data if isinstance(w, dict)
                ]
                found = work_id in ids_in_works
            elif isinstance(works_data, dict):
                found = work_id in works_data
            else:
                found = False

            if found:
                ok(f"work_id {work_id!r} found in {works_path}")
            else:
                failures.append(
                    error(f"work_id {work_id!r} NOT found in {works_path}")
                )
        except (json.JSONDecodeError, OSError) as e:
            failures.append(error(f"Could not read works.json: {e}"))
    else:
        print(f"  INFO: works.json not found at {works_path} — skipping cross-check")

    # --- Final result ---
    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: FAILED ({len(failures)} error(s))")
        return False
    else:
        print("RESULT: PASSED")
        return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_data.py <path/to/file.json>")
        sys.exit(1)

    all_passed = True
    for filepath in sys.argv[1:]:
        passed = validate_file(filepath)
        if not passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

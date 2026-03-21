"""Greek stop words for filtering common function words from vocabulary lists."""

# POS tags to exclude — these are function words that don't carry content meaning.
STOP_POS = {"PART", "CONJ", "SCONJ", "DET", "ADP", "INTJ"}

# Stop words organized by category, stored as lemmas so all inflected forms are caught.
# The build script filters by lemma match against this set.

STOP_WORDS = {
    # Articles
    "ὁ", "ἡ", "τό", "ὅ",

    # Particles
    "μέν", "δέ", "γάρ", "ἄν", "γε", "δή", "οὖν", "τε", "ἄρα",
    "τοι", "τοίνυν", "μήν", "που", "πω", "πώποτε",

    # Common conjunctions
    "καί", "ἀλλά", "ἤ", "εἰ", "ὅτι", "ὡς", "ὥστε", "ἐπεί", "ἐπειδή",
    "ἐπειδάν", "ὅτε", "ὅταν", "ἕως", "πρίν",

    # Common prepositions
    "ἐν", "ἐκ", "ἐξ", "εἰς", "πρός", "ἀπό", "ὑπό", "κατά", "μετά",
    "περί", "παρά", "ἐπί", "διά", "σύν", "ἀνά", "πρό",

    # Negations
    "οὐ", "οὐκ", "οὐχ", "μή", "οὐδέ", "μηδέ",

    # Common pronouns
    "ἐγώ", "σύ", "αὐτός", "ἑαυτοῦ", "οὗτος", "ἐκεῖνος", "ὅς",
    "ὅστις", "τις", "τί",

    # Common adverbs
    "οὐδείς", "μηδείς", "πᾶς",

    # Very common verbs (to be, to say)
    "εἰμί", "φημί",
}

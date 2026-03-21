# Flash — Greek Vocabulary Flashcard Game

A static-site flashcard game for mastering Ancient Greek vocabulary, built from TEI XML texts.

## Quick Start

Serve the `docs/` directory locally:

```bash
python3 -m http.server -d docs
```

Open http://localhost:8000 in your browser.

## Architecture

```
docs/                   # Static site (GitHub Pages root)
├── index.html          # SPA entry point
├── css/styles.css      # Mobile-first responsive styles
├── js/
│   ├── app.js          # Boot, routing, orchestration
│   ├── data.js         # Fetch and cache vocab JSON
│   ├── state.js        # Session state management
│   ├── storage.js      # localStorage persistence
│   ├── questions.js    # Question generation engine
│   ├── ui.js           # DOM rendering and events
│   └── utils.js        # Greek normalization, shuffling, Levenshtein
└── data/
    ├── works.json      # Index of available texts
    └── tlg0059004.json # Vocabulary for Plato's Phaedo

scripts/
├── build_vocab.py      # TEI XML → vocab JSON pipeline
├── build_lexicon.py    # Perseus LSJ XML → lexicon JSON
├── stop_words.py       # Greek stop word list
└── validate_data.py    # JSON schema validation

texts/
└── tlg0059004.xml      # Source TEI XML (Plato's Phaedo)
```

## Features

- **10 difficulty levels** based on word frequency
- **Practice mode** — learn at your own pace with immediate feedback
- **Endless mode** — all words in a level per session
- **3 question types** — Greek→English, English→Greek, form identification
- **Mixed answer modes** — multiple choice and write-in
- **Progress tracking** — per-word mastery in localStorage
- **Mobile-first** responsive design with large Greek text

## Adding New Texts

1. Place a TEI XML file in `texts/`
2. Run the build pipeline:

```bash
pip3 install -r requirements.txt
python3 scripts/build_lexicon.py          # first time only
python3 scripts/build_vocab.py texts/your_text.xml
```

3. Validate the output:

```bash
python3 scripts/validate_data.py docs/data/your_text.json
```

The new text will appear in the app automatically.

## Build Pipeline

`build_vocab.py` processes TEI XML through these steps:

1. Parse TEI XML for title, author, and text content
2. Tokenize and lemmatize Greek with CLTK
3. Filter stop words
4. Assign difficulty levels 1–10 by frequency (evenly distributed)
5. Look up concise English definitions from the Perseus LSJ lexicon
6. Output structured JSON to `docs/data/`

No LLM or API keys required. Definitions come from `build_lexicon.py`, which parses the Perseus LSJ XML into `data/lexicon/lsj_shortdefs.json`.

## Deployment

Enable GitHub Pages with source set to `main` branch, `/docs` folder.

## Tech Stack

- Vanilla HTML/CSS/JS (ES modules, no build tools, no frameworks)
- Python 3.10+ with CLTK for NLP
- Perseus LSJ lexicon for definitions (no AI/API dependency)

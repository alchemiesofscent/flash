# Repository Guidelines

## Project Structure & Module Organization
`docs/` is the deployable static site for GitHub Pages. Keep UI assets there: `docs/index.html`, `docs/css/styles.css`, and ES module files in `docs/js/`. Generated vocabulary JSON lives in `docs/data/`.

`scripts/` contains the Python data pipeline: `build_lexicon.py`, `build_vocab.py`, and `validate_data.py`. Source TEI XML belongs in `texts/`. Lexicon source and generated lookup data live under `data/lexica/` and `data/lexicon/`. Treat `docs/data/*.json` and `data/lexicon/lsj_shortdefs.json` as generated artifacts.

## Build, Test, and Development Commands
Install Python dependencies with:

```bash
pip3 install -r requirements.txt
```

Run the site locally:

```bash
python3 -m http.server -d docs
```

Build or refresh lexicon data:

```bash
python3 scripts/build_lexicon.py
```

Generate vocab JSON from a TEI source:

```bash
python3 scripts/build_vocab.py texts/tlg0059004.xml
```

Validate generated output before committing:

```bash
python3 scripts/validate_data.py docs/data/tlg0059004.json
```

## Coding Style & Naming Conventions
Use 4-space indentation in Python and 2-space indentation in JS/CSS to match the existing files. Prefer `snake_case` for Python functions and files, `camelCase` for JavaScript functions, and descriptive flat module names such as `questions.js` or `storage.js`. Keep browser code framework-free and modular; keep script entry points runnable from the repository root.

## Testing Guidelines
There is no formal automated test suite yet. The minimum bar is: run `validate_data.py` on changed JSON output and manually verify the affected flow in a local browser session. For pipeline changes, test with a real XML file from `texts/` and confirm regenerated data lands in `docs/data/`.

## Commit & Pull Request Guidelines
Git history is not available in this workspace, so follow a simple imperative style for commits, for example: `Add section reference support to vocab builder`. Keep subjects under 72 characters and group related code and generated data in the same change only when they must ship together.

PRs should include a short description, the commands run for validation, and screenshots for visible UI changes. If a PR changes generated JSON, note the source file and script used to regenerate it.

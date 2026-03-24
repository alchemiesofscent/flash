# Aristotle Politics Ingestion + Codex Pilot Status

## Objective
Add `texts/tlg0086035.xml` as Aristotle's *Politics*, generate the base vocab JSON and works index entry, run a 20-card enrichment pilot comparing `gpt-5.4-mini`, `gpt-5.4` medium, and `gpt-5.4` high for context-sensitive definitions and sentence translations, then roll the chosen enrichment into the deployable flashcard data.

## Run Matrix
| Run ID | Model | Reasoning | Scope | Status |
| --- | --- | --- | --- | --- |
| `politics-mini` | `gpt-5.4-mini` | default | 20 fixed cards | completed |
| `politics-54-medium` | `gpt-5.4` | `medium` | 20 fixed cards | completed |
| `politics-54-high` | `gpt-5.4` | `high` | 20 fixed cards | completed |

## WBS
| ID | Task | Owner | Depends On | Status | Acceptance |
| --- | --- | --- | --- | --- | --- |
| W1 | Generate `docs/data/tlg0086035.json` and update `docs/data/works.json` | Codex | none | completed | JSON generated, works index includes `tlg0086035` |
| W2 | Normalize metadata to `Politics` / `Aristotle` | Codex | W1 | completed | Generated metadata uses normalized display values |
| W3 | Refactor `scripts/enrich_definitions.py` into prepare/apply capable workflow | Codex | none | completed | Script supports request staging and response application without Anthropic |
| W4 | Add `codex-subagent` manifests and `--merge-only` to `scripts/enrich_parallel.py` | Codex | W3 | completed | Manifest includes chunk requests, source files, output paths, and model config |
| W5 | Freeze 20-card sample and record word IDs | Codex | W1 | completed | One shared word-id list reused by all three runs |
| W6 | Execute pilot with `gpt-5.4-mini` | Codex + subagents | W4, W5 | completed | All 20 cards enriched and validated in run workspace |
| W7 | Execute pilot with `gpt-5.4` medium | Codex + subagents | W4, W5 | completed | All 20 cards enriched and validated in run workspace |
| W8 | Execute pilot with `gpt-5.4` high | Codex + subagents | W4, W5 | completed | All 20 cards enriched and validated in run workspace |
| W9 | Score outputs across the three runs | Codex | W6, W7, W8 | completed | Side-by-side quality notes and per-run summary captured below |
| W10 | Recommend rollout model | Codex | W9 | completed | Clear winner recorded with rationale and tradeoffs |
| W11 | Execute full Aristotle enrichment with resumable chunked workflow | Codex | W10 | completed | All 5,411 lemmas enriched across staged rescue/final runs |
| W12 | Publish enriched Aristotle JSON into `docs/data` for the game | Codex | W11 | completed | Deployable `docs/data/tlg0086035.json` validates with full enrichment coverage |

## Execution Log
- 2026-03-21: Replaced the old UI-only tracker with a WBS and run matrix for Aristotle ingestion plus Codex enrichment comparison.
- 2026-03-21: Began implementation of metadata normalization in `scripts/build_vocab.py`.
- 2026-03-21: Began refactor of enrichment tooling to support prepared requests, applied results, and manifest-based Codex runs.
- 2026-03-22: Added a repo-local `CLTK_DATA` cache path in `scripts/build_vocab.py`, linked existing Greek embeddings, and removed the sandbox write blocker on `~/cltk_data/cltk.log`.
- 2026-03-22: Batched CLTK analysis plus optimized lexicon/context passes so `texts/tlg0086035.xml` builds within memory limits.
- 2026-03-22: Generated and validated `docs/data/tlg0086035.json` with normalized metadata (`Politics` / `Aristotle`) and updated `docs/data/works.json`.
- 2026-03-22: Froze the shared 20-card sample in `data/cache/enrich_runs/politics-word-ids.json` and staged isolated manifests for `politics-mini`, `politics-54-medium`, and `politics-54-high`.
- 2026-03-22: Executed, applied, merged, and validated all three Aristotle pilot runs under `data/cache/enrich_runs/`.
- 2026-03-22: Compared glosses, etymologies, and context translations across the 20-card sample and selected `gpt-5.4` high as the quality winner, with `gpt-5.4` medium as the best efficiency fallback.
- 2026-03-24: Ran the full Aristotle enrichment in staged passes (`10-word`, rescue `5-word`, final `1-word`), patched the timeboxed runner to preserve failed raw responses, and completed enrichment for all 5,411 lemmas.
- 2026-03-24: Published the fully enriched Aristotle file to `docs/data/tlg0086035.json` and revalidated it against `docs/data/works.json`.

## Fixed Pilot Sample
- `data/cache/enrich_runs/politics-word-ids.json`
- IDs: `1, 3, 4, 6, 9, 11, 15, 19, 20, 23, 24, 29, 32, 70, 82, 91, 106, 156, 257, 294`
- Lemmas: `πολιτεία`, `πόλις`, `ἔχω`, `λέγω`, `ἀρχή`, `ποιέω`, `νόμος`, `ὀλιγαρχία`, `πλῆθος`, `ἀρετή`, `δημοκρατία`, `δῆμος`, `πολίτης`, `τυραννίς`, `κοινωνία`, `παιδεία`, `βασιλεία`, `στάσις`, `ἰσότης`, `δικαιοσύνη`

## Scoring Summary
- `gpt-5.4-mini`: usable baseline, but flatter on political vocabulary and more likely to choose broad learner glosses where the context wants sharper constitutional language. Examples: `κοινωνία` as `shared community`, `ἰσότης` as `equality of wealth`, `δικαιοσύνη` as `justice; right conduct`.
- `gpt-5.4` medium: strongest concise/UI-friendly tradeoff. It is usually cleaner than mini and avoids most flattening, with solid choices like `city-state, civic community`, `beginning, ruling principle`, and `equality of property`.
- `gpt-5.4` high: best overall on nuance and political semantics. It most consistently captured Aristotle's constitutional vocabulary with sharper choices such as `the common people` for `δῆμος`, `members of the polis` for `πολίτης`, `civic education` for `παιδεία`, `property equality` for `ἰσότης`, and `justice as virtue` for `δικαιοσύνη`.
- Translation quality was close between `gpt-5.4` medium and `gpt-5.4` high, but `high` more often preserved the political force of terms like `πολιτεία`, `δημοκρατία`, and `στάσις` without collapsing them into generic English.
- Morphology quality was acceptable in all three runs after application; the differentiator was gloss and translation precision rather than inflection parsing coverage.

## Decision Log
- Use `Politics` / `Aristotle` as normalized display metadata for `tlg0086035`.
- Keep the base TEI-to-vocab pipeline LLM-free.
- Use Codex subagents as the parallel execution layer for pilot enrichment.
- Compare `gpt-5.4-mini`, `gpt-5.4` medium, and `gpt-5.4` high on the same 20 cards.
- Roll out `gpt-5.4` high if the priority is best lexical and translation quality for Aristotle.
- Use `gpt-5.4` medium instead if latency or cost pressure outweighs the marginal quality gain from `high`.
- Ship the fully enriched Aristotle data from the staged final run into `docs/data/tlg0086035.json` once validation passes.

## Open Issues
- No known execution blockers remain for Aristotle *Politics* in the flashcard game data.

## PWA Rollout Status

### Objective
Complete the existing GitHub Pages shell as a usable installable PWA with offline access to all works, lightweight install guidance, and explicit update/offline messaging for mobile use, especially iPhone home-screen launch.

### WBS
| ID | Task | Owner | Depends On | Status | Acceptance |
| --- | --- | --- | --- | --- | --- |
| P1 | Audit current PWA shell and define target behavior | Codex | none | completed | Existing manifest, service worker, and install hooks reviewed before edits |
| P2 | Harden manifest and app-shell metadata | Codex | P1 | completed | `index.html` and `manifest.json` expose install-ready metadata and icon references |
| P3 | Rework service worker caching and versioning | Codex | P1 | completed | Versioned shell/data/runtime caches support offline shell, work prewarming, and update flow |
| P4 | Add install and standalone UX | Codex | P2 | completed | Home screen shows install/Add to Home Screen guidance and standalone state is detected |
| P5 | Add update/offline state messaging | Codex | P3, P4 | completed | App displays update-ready and offline banners without altering quiz flow |
| P6 | Validate GitHub Pages deployment behavior | Codex | P2, P3 | completed | Relative paths and service worker scope remain `docs/`-compatible |
| P7 | Manual/device testing and tracker closeout | Codex | P5, P6 | completed | Syntax checks, static serving checks, and published-file validation recorded below |

### Execution Log
- 2026-03-24: Confirmed the repo already had a first-pass manifest, icons, and service worker, then tightened them instead of starting a separate PWA scaffold.
- 2026-03-24: Added a dedicated `docs/js/pwa.js` controller for service worker registration, install prompt handling, iPhone Add to Home Screen guidance, standalone detection, and update/offline banners.
- 2026-03-24: Reworked `docs/sw.js` into versioned shell/data/runtime caches, added `SKIP_WAITING` support, offline navigation fallback, and work-data warmup from `works.json`.
- 2026-03-24: Published the fully enriched Aristotle JSON into `docs/data/tlg0086035.json`, which the PWA shell now caches alongside the rest of the work data.

### Testing
- `node --check docs/sw.js`
- `node --check docs/js/app.js`
- `node --check docs/js/pwa.js`
- `python3 -m json.tool docs/manifest.json`
- `python3 -m http.server -d docs` plus local fetch checks for `index.html`, `manifest.json`, `sw.js`, and `data/works.json`
- `python3 scripts/validate_data.py docs/data/tlg0086035.json`

## GitHub Pages Deployment Status

### Objective
Publish the complete working flashcard app, including generated Plato and Aristotle data plus the PWA shell, to a public GitHub repository served directly by GitHub Pages from `main:/docs`.

### WBS
| ID | Task | Owner | Depends On | Status | Acceptance |
| --- | --- | --- | --- | --- | --- |
| G1 | Create public repo `alchemiesofscent/flash` and set `origin` | Codex | none | completed | Remote exists and local repo points to it |
| G2 | Commit the complete working tree, including generated deploy artifacts | Codex | G1 | completed | `docs/` site, `docs/data/*.json`, scripts, and source TEI are pushed together |
| G3 | Enable GitHub Pages from `main:/docs` | Codex | G2 | completed | Pages source is configured and deploy is active |
| G4 | Verify the live site and published JSON endpoints | Codex | G3 | completed | Live URL serves app shell, manifest, service worker, and both work JSON files |

### Execution Log
- 2026-03-24: Created the public repository `https://github.com/alchemiesofscent/flash` and set it as `origin` for the local `main` branch.
- 2026-03-24: Committed and pushed the complete working app, including the PWA shell, Plato data, fully enriched Aristotle data, pipeline scripts, and source TEI files.
- 2026-03-24: Enabled GitHub Pages from `main:/docs`; GitHub published the site at `https://alchemiesofscent.github.io/flash/`.
- 2026-03-24: Verified the live root, manifest, service worker, works index, and Aristotle JSON endpoint all return `200`.

### Deployment
- Repo: `https://github.com/alchemiesofscent/flash`
- Pages source: `main` branch, `/docs` folder
- Live URL: `https://alchemiesofscent.github.io/flash/`

### Testing
- `python3 scripts/validate_data.py docs/data/tlg0086035.json`
- `node --check docs/sw.js`
- `node --check docs/js/app.js`
- `node --check docs/js/pwa.js`
- `curl -I -L https://alchemiesofscent.github.io/flash/`
- `curl -I https://alchemiesofscent.github.io/flash/manifest.json`
- `curl -I https://alchemiesofscent.github.io/flash/sw.js`
- `curl -I https://alchemiesofscent.github.io/flash/data/works.json`
- `curl -I https://alchemiesofscent.github.io/flash/data/tlg0086035.json`

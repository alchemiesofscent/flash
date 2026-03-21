# UI/UX Overhaul — Status

## Design Direction
- **Palette**: Warm scholarly — parchment (#f7f3ec) bg, cream (#fffdf7) surface, terracotta (#b35a2a) accent, olive (#4a7a3e) success, brick (#a63a2a) error. Inspired by Attic pottery, not SaaS dashboards.
- **Fonts**: Kept Literata (body) + Gentium Plus (Greek) — already distinctive and appropriate.

---

## Work Breakdown Structure

### M0: Color scheme refresh
Swap custom properties to warm scholarly palette. Replace all hardcoded colors.
- [x] Update `:root` custom properties (11 color vars)
- [x] Replace 8 hardcoded `#ffffff` with `var(--color-primary-text)`
- [x] Update warning/highlight colors to warm tones
- [x] Remove dead CSS (old `.quiz-progress` container, `.level-btn .progress-bar`)
- **Status**: DONE

### M1: Level select → form-based layout
Replace button grids with compact segmented controls in a vertical form flow.
- [x] Refactor `renderLevelSelect()` HTML → setup-form with form-groups
- [x] Replace level grid with horizontal segmented control (3 options + detail text)
- [x] Replace mode grid with vertical segmented control (4 options)
- [x] New CSS: `.seg-control`, `.seg-option`, `.seg-option--active`, `.seg-option--disabled`
- [x] Remove old CSS: `.level-grid`, `.level-btn`, `.mode-grid`, `.mode-btn` (all variants)
- [x] Verify selection logic (level enables/disables morphology, updates start button)
- **Status**: DONE

### M2: Question count control
Slider to choose quiz length, wired into session start.
- [x] Add range input (5–max, step 5, default 10) to level-select form
- [x] Slider max updates when level changes
- [x] Display shows current value live
- [x] `startSession()` accepts count param, defaults to all words
- [x] CSS for `.range-input` with themed thumb
- **Status**: DONE

### M3: Card polish
- [x] Card border-radius bumped from `radius-md` (8px) to `radius-lg` (12px)
- **Status**: DONE

### M4: Quiz header improvements
- [x] Added × quit button to quiz header (navigates back to level select)
- [x] Styled `.quiz-quit` with hover state
- [x] Fixed quiz header layout (flex-wrap, progress/type on row 1, bar on row 2)
- [x] Fixed duplicate `.quiz-header` CSS rules (removed conflicting first declaration)
- **Status**: DONE

---

## Files Modified
- `docs/css/styles.css` — color scheme, segmented controls, range input, card polish, quiz header fix
- `docs/js/ui.js` — level-select form layout, question count slider, quit button, flip height fix
- `docs/js/questions.js` — relaxed form-id eligibility (1+ form, not 2+)

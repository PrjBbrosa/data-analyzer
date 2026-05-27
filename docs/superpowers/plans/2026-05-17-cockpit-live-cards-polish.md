# Cockpit Live-Cards Polish Implementation Plan

> **For agentic workers:** This plan is the decomposition produced by `squad-orchestrator` on 2026-05-17 from the design spec at `docs/superpowers/specs/2026-05-17-cockpit-live-cards-polish-design.md`. The orchestrator's audit lives at `docs/lessons-learned/orchestrator/decompositions/2026-05-17-cockpit-live-cards-polish.md`.

**Goal:** Surgical polish of the cockpit center-pane live cards so signal sparklines absorb available vertical space, the per-card REC chip stops duplicating the toolbar indicator, the header consolidates to a single tidy row, typography establishes a clear value > name > stats hierarchy, raster pills shorten, inter-card spacing tightens, and raw `t [n:m]` time channels stop auto-populating as cards.

**Architecture:** Pure UI polish in `mf4_analyzer/acquisition_ui/widgets/live_cards.py` and `mf4_analyzer/ui_kit/style.qss`. No capture-core, ring-buffer, writer, or signal-processing changes. Recording state per card is conveyed by tinting the existing left swatch instead of a dedicated row.

**Tech Stack:** PyQt5 widgets/QSS, pytest/pytest-qt.

**Dispatch shape:** Both subtasks go to `pyqt-ui-engineer`. They run **sequentially** (not in parallel). Reason: A–F all land in three shared files (`live_cards.py`, `style.qss`, `test_live_cards.py`) — splitting across parallel pyqt-ui specialists would race `git add` per the 2026-04-24 same-file collision lesson. Subtask 2 depends on subtask 1 by construction.

---

### Task 1: live-cards-polish-abcdef (pyqt-ui-engineer)

**Files in scope:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `tests/acquisition_ui/test_live_cards.py`
- Conditionally modify: `tests/acquisition_ui/test_visual_stylesheet_contract.py` (only if its QSS pins are invalidated by the typography changes — see Task 2 for the conditional split)

**TDD order:** update existing test assertions FIRST so they fail red, then implement A–F, then add the two new tests, then run.

- [ ] Update `tests/acquisition_ui/test_live_cards.py:38` — move `"since 60s"` from visible stats text to `liveCardStats.toolTip()`. Visible text should NOT contain it.
- [ ] Update `tests/acquisition_ui/test_live_cards.py:44` — move `"since rec start"` to tooltip assertion (same treatment).
- [ ] Update `tests/acquisition_ui/test_live_cards.py:43` — after `set_recording(True, rec_start_ts=0.0)`, also assert the swatch fill color resolves to `#dc2626`.
- [ ] **A. Remove REC row + swatch tinting.** Delete the dedicated `status = QHBoxLayout()` row in `LiveSignalCard._build_ui` (`widgets/live_cards.py:242-248`). Keep `set_recording(self, recording, rec_start_ts=None)` signature. On `True`: swatch fill becomes `#dc2626`, card gains a 1 px red left border via a `recording` state QSS property (NOT a stylesheet rebuild). On `False`: revert.
- [ ] **B. Sparkline absorbs vertical space.** `Sparkline.setMinimumHeight(36) → 72`. Set sparkline + card size policies to `QSizePolicy.Expanding/Expanding`. In `LiveCardGrid.set_signals`, drop the trailing `addStretch(1)` when at least one card is present. KEEP the trailing stretch when zero cards (disconnected-canvas placeholder path).
- [ ] **C. Header consolidation.** Final order: `[swatch] Name —— stats(μ σ max) raster·unit value`. Drop the `· since <window>` suffix from visible stats text; install it as `liveCardStats.setToolTip(...)` instead. Raster pill strips the `event_` prefix for display (`event_10ms → 10 ms`) and keeps the full name in the pill's tooltip.
- [ ] **D. Typography in style.qss.** `liveCardName` font-weight 800 → 700; `liveCardValue` font-size 14 → 16 px. Stats/unit/raster unchanged.
- [ ] **E. Spacing.** `LiveCardGrid._layout.setSpacing(8) → 4`; card vertical content margins `(10, 8, 10, 8) → (10, 6, 10, 6)`. Horizontal margins UNCHANGED.
- [ ] **F. Time-channel filter.** In `LiveCardGrid.set_signals`, filter out names matching `r'^t\s*\[\d+:\d+\]$'`. Filter lives at the grid boundary only — does NOT push into per-card code or capture-core.
- [ ] Add new test: `LiveCardGrid.set_signals` filters time-channel names. Include both a normal channel (e.g. `engine_speed`) and matching time-channel names (`t [0:100]`, `t[1:50]`). Assert normal channel produces a card; time channels do not.
- [ ] Add new test: sparkline floor is honored after layout. Build a `LiveCardGrid` with one card, show it, flush layout (`qtbot` or manual `processEvents` + sizeHint), then assert the sparkline widget's `height() >= 72`.
- [ ] Visually verify across 0/1/many cards × narrow/default/wide cockpit widths per the responsive-pane-containers lesson.
- [ ] Run `pytest tests/acquisition_ui/test_live_cards.py -x` green.

**Lessons to honor:**
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — `Expanding/Expanding` + stretch removal must be verified at narrow/default/wide widths AND at 0/1/many card counts.
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md` — before changing `setContentsMargins`, grep `style.qss` for any `liveCard` padding rule. If one exists, move the change into QSS OR add a long-form inline padding-top/-bottom override (not shorthand) so the Python value is not clobbered at the next polish event.
- `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md` — any wrapper QFrame with `WA_StyledBackground` needs a paired QSS rule keyed on objectName.

**Hard boundaries:** files outside the four listed are off-limits; do NOT change `set_recording` signature; the regex filter is UI-only; do NOT touch the cockpit's outer splitter / scroll wrapper.

---

### Task 2: live-cards-qss-contract-reconcile (pyqt-ui-engineer, conditional)

**Depends on:** Task 1.

**Dispatch decision:** after Task 1 returns, main Claude inspects `files_changed`. If `tests/acquisition_ui/test_visual_stylesheet_contract.py` is already listed there, Task 2 is marked done-by-bundling and the dispatch is SKIPPED. Otherwise Task 2 is dispatched.

**Files in scope:**
- Modify: `tests/acquisition_ui/test_visual_stylesheet_contract.py` (ONLY)

- [ ] Read the contract test. Identify any assertion pinning `liveCardName` font-weight (currently 800, should be 700), `liveCardValue` font-size (currently 14, should be 16), or any selector targeting the removed REC-row widgets.
- [ ] Update affected assertions to match the new `style.qss`. For removed selectors, DROP the assertion entirely (not stub with a tautology).
- [ ] Run the contract test green.

**Hard boundaries:** ONLY this test file. Do NOT change `style.qss` (Task 1 is the source of truth). Do NOT change other test files.

---

### Aggregation rules (for main Claude)

- Intra-pyqt-ui overlap on `test_visual_stylesheet_contract.py` between Task 1 and Task 2 is BY DESIGN. Per the orchestrator's notes, this is NOT cross-specialist rework — do NOT write a rework lesson for that overlap.
- Lesson reflection: each subtask's return must include `lessons_added` / `lessons_merged` per `docs/lessons-learned/README.md`.
- After both subtasks return, bump `docs/lessons-learned/.state.yml` `top_level_completions` by 1 (current value: 39 → 40). `last_prune_at` is 21, so no prune fires (40 − 21 = 19 < 20).

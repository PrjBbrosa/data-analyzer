# Decomposition — Cockpit Live-Cards Polish (A–F)

**Date:** 2026-05-17
**User request (verbatim, abbreviated):** acquisition UI 大体框架对了但细节不够——字体大小、图标选择、采集回放时中间区域曲线应尽可能大、REC 行占空间无用。
**Source-of-truth spec:** `docs/superpowers/specs/2026-05-17-cockpit-live-cards-polish-design.md`

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| `live-cards-polish-abcdef` — Implement A (remove per-card REC row + swatch tint + 1px red border on `set_recording(True)`), B (sparkline `minHeight 36→72`, Expanding/Expanding policies, drop trailing `addStretch(1)` when ≥1 card, keep when zero), C (one-row header `[swatch] Name —— stats raster·unit value`; drop `· since <window>` tail to tooltip on `liveCardStats`; raster pill strips `event_` prefix with full name in tooltip), D (QSS `liveCardName` weight 800→700, `liveCardValue` 14→16 px), E (`LiveCardGrid._layout.setSpacing 8→4`; card vertical margins `(10,8,10,8)→(10,6,10,6)`), F (`set_signals` filters channels matching `^t\s*\[\d+:\d+\]$` at the grid boundary). Update `tests/acquisition_ui/test_live_cards.py` lines 38 / 43 / 44 to assert (a) `"since 60s"` and `"since rec start"` are on `liveCardStats` tooltip not visible text, (b) `set_recording(True, rec_start_ts=0.0)` flips swatch fill to `#dc2626`. Add two new tests: time-channel regex filter (inclusion + exclusion), per-card sparkline height ≥ 72 px after layout flush. Run the full live_cards test module before returning. | pyqt-ui-engineer | (none — parallel-eligible but is the only structural subtask) | All six behaviors touch the same two production files (`live_cards.py`, `style.qss`) and the same test file. Per `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`, splitting same-file edits across parallel pyqt-ui tasks causes `git add` races. Per `orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`, fold mechanically derivable QSS-pin reconciliation into the same brief as the structural change. One specialist, one commit. |
| `live-cards-qss-contract-reconcile` — If and only if subtask 1's specialist return reports that `tests/acquisition_ui/test_visual_stylesheet_contract.py` pins exact `liveCardName` font-weight or `liveCardValue` font-size (or REC-row selectors that no longer exist), update those pins to the new values (`weight: 700`, `font-size: 16px`, drop any per-card REC-row selector assertions). If subtask 1 reports the contract test still passes unchanged, this subtask is skipped. | pyqt-ui-engineer | live-cards-polish-abcdef | The visual-stylesheet contract test is a separate file with a single concern (pin reconciliation). Bundling it into subtask 1 is acceptable but cleaner to separate IF reconciliation is non-trivial. Main Claude must read subtask 1's return: if `files_changed` already includes `test_visual_stylesheet_contract.py`, mark this subtask `done` and skip dispatch. |

## Lessons consulted

- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md`
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md`
- `docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`

## Routing notes

- All work is pure Qt widget/QSS polish — `pyqt-ui-engineer`.
- Surface-keyword dominance applies: "sparkline canvas height", "QSS weight/size", "header layout", "spacing/margins", "icon/swatch tint" are all surfaces, not computations. No signal-processing-expert subtasks.
- No package/module relocation — no refactor-architect subtask.

## Risk / wide-pane consideration

The sparkline `setMinimumHeight(72)` + `SizePolicy::Expanding/Expanding` + the `addStretch` removal interact with the cockpit's outer scroll/splitter wrapping. Per `pyqt-ui/2026-04-24-responsive-pane-containers.md`, the brief must remind the specialist to visually verify behavior at three card counts (0, 1, many) AND at narrow / default / wide cockpit widths — particularly that with zero cards the disconnected-canvas placeholder still gets the trailing stretch (so it doesn't grow), and with ≥1 card the cards fill vertical slack instead of huddling at the top.

## QSS-vs-setContentsMargins trap

Per `pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md`: the card vertical-margin change `(10,8,10,8)→(10,6,10,6)` is set in Python via `setContentsMargins`. If any global `QSS QFrame#liveCard` rule sets `padding`, the QSS value wins. The brief must instruct the specialist to grep `style.qss` for liveCard padding rules and either confirm no conflict OR add a long-form inline override.

## Skill obligations to flag to executor

- TDD ordering is implicit in `pyqt-ui-engineer`'s system prompt — call out anyway since this task explicitly modifies existing test assertions. The specialist should: update existing test assertions to the new expected behavior FIRST (red), then implement A–F (green), then add the two new tests (red→green), then run the suite.
- `superpowers:using-superpowers` rules apply at agent startup as always.
- No `superpowers:brainstorming` invocation — spec is unambiguous.
- No `superpowers:writing-plans` invocation — only 1–2 dispatches.

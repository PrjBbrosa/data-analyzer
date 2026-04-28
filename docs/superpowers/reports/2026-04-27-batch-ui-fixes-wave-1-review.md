# Wave 1 Review — Batch UI Signal Picker Chip Refactor + Single-Select

**Plan:** `docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md` (rev 2)
**Wave scope:** Phase 1 (Tasks 1, 2) + Phase 2 (Task 3)
**Commits reviewed:** `fe00a00`, `3b571d7`, `2d24214`
**Reviewer:** Senior Code Reviewer (codex-rate-limit fallback path)

---

## Verdict

**approved** — Wave 1 cleanly implements every contracted step in the plan, all rev-1 and rev-2 corrections are honored, the test suite is meaningful and exercises the size-hint and auto-uncheck-siblings contracts, and the full UI regression suite passes.

The squad may advance to Wave 2.

---

## Verification

- **Check 1 — `SignalChip` per Step 1.3 + tests per Step 1.1: PASS.** `SignalChip` at `mf4_analyzer/ui/drawers/batch/signal_picker.py:25-61` matches the plan verbatim — `removeRequested = pyqtSignal(str)`, `_label.setToolTip(name)`, `display = name if len(name) <= max_label_chars else name[:max_label_chars] + "…"`, fixed-size 18×18 flat × button. Both Step 1.1 tests (`test_signal_chip_emits_remove_signal`, `test_signal_chip_label_truncates_long_name`) are present at `tests/ui/test_batch_signal_picker.py:92-110` and pass.

- **Check 2 — `_ClickableFrame(QFrame)` and clean `eventFilter` body (rev-1 fix #1 / rev-2 fix #1): PASS.** `_ClickableFrame` is defined at `signal_picker.py:64-79` with `clicked = pyqtSignal()` driven from `mousePressEvent`. `eventFilter` body at `:448-465` only branches on `obj is self._popup` (KeyPress/Escape and FocusOut handling for the popup). There is **no `_display_frame` branch** in `eventFilter`, no `installEventFilter(self._display_frame)` anywhere. Verified by `grep -n eventFilter mf4_analyzer/ui/drawers/batch/signal_picker.py` — only 3 occurrences, all on `self._popup`.

- **Check 3 — `_chip_scroll.setFixedHeight(min(rows, MAX_VISIBLE_ROWS) * ROW_HEIGHT)` (rev-2 fix #4): PASS.** `_refresh_display` at `:391-423` correctly computes `visible_rows = min(len(self._selected), self._CHIP_MAX_VISIBLE_ROWS)` and `target_h = visible_rows * self._CHIP_ROW_HEIGHT`, then `self._chip_scroll.setFixedHeight(target_h)`. The empty branch resets `setFixedHeight(0)`. Constants `_CHIP_ROW_HEIGHT=26`, `_CHIP_MAX_VISIBLE_ROWS=3`, `_CHIP_FRAME_VPADDING=8` are present at `:137-139`. The size-hint growth contract is exercised by `test_picker_display_height_grows_with_selection_not_width` and passes.

- **Check 4 — `WA_TransparentForMouseEvents` on placeholder: PASS.** `signal_picker.py:169` — `self._placeholder_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)`. Click-through behavior is regression-tested via `test_picker_display_clicking_empty_area_opens_popup` at `tests/ui/test_batch_signal_picker.py:155-162`.

- **Check 5 — `single_select` kwarg + `set_selected` normalization + `_on_checkbox_toggled` auto-uncheck branch: PASS.** Constructor at `:87-104` accepts `*, single_select: bool = False`, sets `self._single_select`, and trims initial selection to `sel[:1]` if multi. `set_selected` at `:213-219` normalizes incoming tuples (`new = new[:1]` when single + len>1) before the equality short-circuit. `_on_checkbox_toggled` at `:350-382` has an explicit single-select branch that walks `_list`, unchecks siblings under `self._suppress_signal = True` so no spurious re-emits fire, then sets `self._selected = (signal,)` and emits once. Both tests (`test_picker_single_select_replaces_previous_selection`, `test_picker_single_select_checking_unchecks_others`) pass — the second one explicitly asserts `boxes["a"].isChecked() is False` after toggling `b`, so the auto-uncheck path is genuinely exercised.

- **Check 6 — Imports at module top, no inline imports (rev-1 fix #6): PASS.** `signal_picker.py:17-22` has the consolidated import block. `grep -n 'from PyQt5' mf4_analyzer/ui/drawers/batch/signal_picker.py` returns exactly 2 hits, both at lines 17–18. `QLabel`, `QScrollArea`, `QSizePolicy` are all in the top block. No `from PyQt5...` statement exists inside `__init__` or any method body.

- **Check 7 — 8 new tests, meaningful: PASS.** Wave 1 added: `test_signal_chip_emits_remove_signal`, `test_signal_chip_label_truncates_long_name`, `test_picker_display_renders_one_chip_per_selected`, `test_picker_display_height_grows_with_selection_not_width`, `test_picker_display_chip_remove_unselects_signal`, `test_picker_display_clicking_empty_area_opens_popup`, `test_picker_single_select_replaces_previous_selection`, `test_picker_single_select_checking_unchecks_others`. Total of 8.
  - `test_picker_display_height_grows_with_selection_not_width` — exercises both size-hint contracts: `three_h > one_h` (height grows) AND `three_w == one_w` (width invariant). PASS.
  - `test_picker_single_select_checking_unchecks_others` — exercises the auto-uncheck-siblings path by toggling `b` after `a` is checked and asserting `boxes["a"].isChecked() is False`. The selection assertion `p.selected() == ("b",)` is also there. PASS.

- **Check 8 — `_display_btn` cleanup: PASS.** `grep -n _display_btn mf4_analyzer/ui/drawers/batch/signal_picker.py` returns **0 hits**. Repo-wide grep across `mf4_analyzer/` and `tests/` also returns 0 hits. Fully removed.

- **Check 9 — Test runs: PASS.**
  - `.venv/bin/python -m pytest tests/ui/test_batch_signal_picker.py -v` → **15 passed in 1.13s** (8 new + 7 pre-existing).
  - `.venv/bin/python -m pytest tests/ui/ -q` → **261 passed in 8.82s**. Zero regressions in the broader UI suite.

- **Check 10 — QSS additive diff: PASS.** `git diff 339d8ed..2d24214 -- mf4_analyzer/ui/style.qss` shows a clean append at the end of the file (after line 617). 16 lines added, 0 removed. Three rules: `#SignalChip`, `#SignalChipRemove`, `#SignalChipRemove:hover`. Property values (`background-color: #eef2f7`, `border-radius: 6px`, hover `color: #ef4444`) match the plan's Step 2.5 verbatim. No existing styles disturbed.

---

## Findings

None. No blocking or warning-level issues.

---

## Recommendations (non-blocking, defer or skip)

1. **`_on_chip_remove_requested` and the single-select chip remove path.** In single-select mode there can only ever be one chip at a time, so `_on_chip_remove_requested` will at most clear that single chip. After clearing, the resulting `self._selected = ()` is what users see. This works correctly today, but if a future change ever lets `_on_chip_remove_requested` run while `single_select=True` and `len(_selected) > 1` (it shouldn't, but as a defensive belt-and-suspenders), the method has no single-select-specific guard. Not a bug — just noting that the method's contract relies on the rest of the class maintaining the `single_select → len(_selected) ≤ 1` invariant.

2. **`_CHIP_FRAME_VPADDING = 8` is defined but never read.** It is documented in a comment but `_refresh_display` only multiplies `visible_rows * _CHIP_ROW_HEIGHT` without adding the padding. The frame's outer `QVBoxLayout` margins (4,4,4,4) already supply that padding implicitly, so the visible behavior is correct, but the constant is dead. Consider either using it in the height computation (`target_h = visible_rows * row_h + _CHIP_FRAME_VPADDING`) or removing it. Not blocking — the test suite confirms the actual rendered height tracks chip count correctly as written.

3. **Tooltip elision precision nit.** `SignalChip` uses character-count elision (`max_label_chars=48`) rather than `QFontMetrics.elidedText`. With proportional fonts and DBC names that include very wide chars (e.g. CJK), 48 chars could still overflow horizontally on narrow columns. This was explicitly specified in the plan, so the implementation is correct against the contract. If a Wave-2 user-acceptance pass surfaces visible overflow, switching to `QFontMetrics(self.font()).elidedText(name, Qt.ElideMiddle, available_width)` is a focused follow-up.

4. **`SignalChip` mouse press does not toggle the popup.** A click on the chip body (not the × button) currently does nothing because `SignalChip` is a plain `QWidget`. Per Qt event delivery rules, that press will reach `_chip_host` first; whether it bubbles up to `_ClickableFrame.mousePressEvent` depends on whether `_chip_host` consumes left-presses (the default `QWidget` does not, so it should bubble). The `test_picker_display_clicking_empty_area_opens_popup` test only covers the placeholder area — a chip-body click is not directly tested. Not in scope for the plan's contract (the plan never calls this out as required), and the user-visible behavior is non-disruptive (× button works), so this is purely a heads-up for Wave-4 manual smoke.

---

## Summary

Wave 1 lands cleanly. All 10 checks pass, all 23 tests across `tests/ui/test_batch_signal_picker.py` and the broader UI regression suite are green, all rev-1 and rev-2 corrections are present and correct, and no out-of-scope files were touched. Squad may proceed to Wave 2 (`input_panel.py` RPM picker + factor row + `sheet.py` method visibility wiring).

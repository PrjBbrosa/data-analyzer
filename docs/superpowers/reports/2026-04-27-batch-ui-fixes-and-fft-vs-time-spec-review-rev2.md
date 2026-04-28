# Spec Review — Batch UI Fixes + FFT-vs-Time, rev 2

Reviewer: main Claude (codex fallback path; codex was the requested reviewer
but is rate-limited).
Plan reviewed: `docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md`
Prior review: `docs/superpowers/reports/2026-04-27-batch-ui-fixes-and-fft-vs-time-spec-review.md`
(rev 1, by codex; verdict was "needs revision before plan/merge"; 5 items: 2
incomplete rev-1 carry-overs, 3 new blocking, 1 warning, 1 minor).

## Verdict

**approved with minor revisions** — proceed to squad runbook Phase 1. The two
revisions are non-blocking cosmetic items (a step-numbering gap and a small
self-review notes drift) that do not affect executor correctness; main Claude
can fix them in-flight or after the squad run lands.

All 7 rev-2 corrections land at the documented step locations and are
internally consistent. The two new technical risks the user asked about —
`setFixedHeight` interaction with the earlier `setMaximumHeight`, and
`setDecimals(10)` locale behavior — are confirmed safe by spec text + Qt
semantics; details below.

---

## Rev-2 Fixes Verification

| # | Correction | Where lands | Verdict | One-line reasoning |
|---|---|---|---|---|
| 1 | Removed stale `_display_frame` `eventFilter` body; `_ClickableFrame.mousePressEvent → clicked → _toggle_popup` is the sole click handler | Step 2.3 lines 204-225 (helper class), 248 (signal wiring), 362 (explicit "Do NOT add a `_display_frame` branch to `eventFilter`" instruction) | PASS | The plan's only references to a `_display_frame` event filter are now warnings AGAINST adding one; the popup-only `eventFilter` body is left explicitly intact. No contradictory snippet remains. |
| 2 | Top-level `QDoubleSpinBox` import in `input_panel.py`; top-level `QCheckBox` import in `method_buttons.py`; corresponding inline imports removed | Steps 4.3 lines 645-653, 9.3 lines 1519-1526 | PASS | Both top-import blocks are explicit and complete; no remaining `from PyQt5.QtWidgets import QDoubleSpinBox` or `from PyQt5.QtWidgets import QCheckBox` exists anywhere downstream in the plan body. |
| 3 | RPM factor `setDecimals(10)` (was 4) | Step 4.3 lines 685-694 | PASS | Verbatim `self._rpm_factor_spin.setDecimals(10)`, with an inline comment explaining why and a widened `setMaximumWidth(140)` to fit the digits. The 1e-9 / 1e-6 test tolerances are now achievable: 1/6 stored as `0.1666666667` is within 4e-11 of the true value, 60/(2π) within ~3e-11. |
| 4 | `_CHIP_ROW_HEIGHT` / `_CHIP_MAX_VISIBLE_ROWS` / `_CHIP_FRAME_VPADDING` constants; `_refresh_display` calls `_chip_scroll.setFixedHeight(visible_rows * ROW_HEIGHT)` so frame `sizeHint().height()` tracks chip count | Step 2.3 lines 254-275 (constants + initial maxHeight), 336-339 (per-refresh fixed height) | PASS | The fixed-height ladder is bounded above by `MAX_VISIBLE_ROWS` via the `min(...)` call, matching the plan's "grow then plateau" semantic. The `_chip_scroll.setFixedHeight(0)` reset in the empty-selection branch (line 320) correctly collapses the frame to placeholder height. |
| 5 | `InputPanel.apply_rpm_factor(value)` + calls in BOTH branches of `BatchSheet.apply_preset`; round-trip test `test_input_panel_rpm_factor_round_trips_through_preset` (Step 5.4b) | Step 5.4 lines 838-880 (helper + import-side wiring), Step 5.4b lines 882-909 (test) | PASS | The plan body says "Insert this line in BOTH the `current_single` and `free_config` branches, AFTER `self.apply_params(dict(preset.params))`." Source confirms both branches exist (sheet.py:318-335) and both call `apply_params` followed by `apply_rpm_channel`, so the insertion point is unambiguous for the executor. The round-trip test is correctly constructed: build → set unit → export → fresh sheet → `apply_preset(exported)` → re-export → assert equality. |
| 6 | Step 8.2 expects PASS (regression guard, not red→green); Step 8.4 removed | Step 8.2 lines 1317-1322 ("**This test is intentionally NOT a red→green pair**"), Step 8.4 absent (jumps from 8.3 → 8.5) | PASS (with cosmetic numbering gap — see Issue #1 below) | The expected-PASS rationale is documented and the per-task error funnel is verified at `mf4_analyzer/batch.py:227-260`. The semantic correction is right. The numeric gap (no Step 8.4) is a cosmetic blemish that does not affect executor correctness — Step 8.5's title makes its position clear — but should be renumbered for cleanliness. |
| 7 | `_METHOD_LABELS["fft_time"] = "FFT vs Time"` in sheet.py; pipeline-strip test for friendly label | Step 9.3 lines 1508-1517 (constant update), Step 9.1 lines 1459-1474 (test) | PASS | Verified against source: `pipeline_strip.py:48` declares `self.cards: list[PipelineCard]`, `:30` declares `self.summary_label = QLabel(...)`, and `sheet.py:94` exposes `self.strip = PipelineStrip(self)`. The test's `sheet.strip.cards[1].summary_label.text()` is therefore a real, public-ish access path. The ANALYSIS card is index 1 (after INPUT at 0), confirmed by `sheet.py:202-207` which calls `self.strip.set_stage(1, ...)` for the method summary. |

---

## New Issues Found

### Issue 1 (minor — cosmetic, not blocking) — Step numbering gap in Phase 5 Task 8

**Where:** Phase 5 Task 8 step list jumps `8.3 → 8.5` (8.4 was removed when
the redundant test step was merged into 8.2/8.3).

**Why this matters (and why it's still minor):** A subagent-driven executor
walking the checkbox list `8.1 / 8.2 / 8.3 / 8.5 / 8.6 / 8.7 / 8.8` may
pause and ask "where's 8.4?" — wasting a turn. It does not affect
correctness; the steps as written are complete.

**Suggested fix:** renumber 8.5 → 8.4, 8.6 → 8.5, 8.7 → 8.6, 8.8 → 8.7.
One-shot sed-style rename, no semantic change. Can also be deferred to a
post-merge plan polish.

### Issue 2 (minor — documentation drift) — Self-Review Notes type-consistency list lags additions

**Where:** Section "Self-Review Notes" item 3 (line 1689) lists identifiers
that should match across tasks:

> `SignalChip`, `_ClickableFrame`, `_display_frame`, `_chip_host`,
> `_rpm_picker`, `_rpm_unit_combo`, `_rpm_factor_spin`, `_rpm_row_host`,
> `_rpm_label_widget`, `_form_ref`, `_rpm_row_index`, `_rpm_row_visible`,
> `_RPM_UNIT_FACTORS`, `_RPM_USING_METHODS`

This list does NOT include `_rpm_factor_sync_busy` (added in Step 4.3),
`_CHIP_ROW_HEIGHT` / `_CHIP_MAX_VISIBLE_ROWS` / `_CHIP_FRAME_VPADDING` (added
in Step 2.3 by rev 2), or `apply_rpm_factor` (added in Step 5.4 by rev 2).
Cross-checking the plan body, all FOUR new identifiers ARE consistently
spelled and used everywhere they appear — so the omission is documentation
drift, not a real consistency issue.

**Suggested fix:** append the four names to the self-review checklist for
future-reviewer ergonomics. Not blocking.

### Issue 3 (informational, not a defect) — `_chip_scroll.setMaximumHeight(...)` is now redundant after `setFixedHeight(...)` lands

**Where:** Step 2.3 lines 273-275 sets `setMaximumHeight(MAX_VISIBLE_ROWS * ROW_HEIGHT)` in `__init__`; lines 336-339 then call `setFixedHeight(min(rows, MAX) * ROW_HEIGHT)` on every refresh.

**Why this is safe:**
- In PyQt5 5.15.11, `setFixedHeight(h)` sets BOTH `setMinimumHeight(h)` and `setMaximumHeight(h)` — overriding the prior `setMaximumHeight(MAX*ROW)` whenever it fires.
- Because `min(rows, MAX_VISIBLE_ROWS)` ensures the fixed value is always `≤ MAX*ROW`, the original max-height ceiling is structurally preserved by the math. There is no path where the fixed height exceeds the ceiling.
- The empty-selection branch sets `setFixedHeight(0)` and hides the scroll area — the maxHeight cap was 78 px (3 * 26), the fixed height is 0, no conflict.

**No action required.** I flag it only because the `setMaximumHeight` call in `__init__` is now load-bearing for nothing once `_refresh_display` runs at least once. Removing it would marginally simplify the contract; leaving it is harmless and matches the plan's "belt-and-suspenders" style elsewhere.

---

## Answers to the User's Specific Verification Asks

### 2a — `setFixedHeight` vs prior `setMaximumHeight` interaction

**Confirmed safe.** `setFixedHeight(x)` overrides both min and max in PyQt5
5.15.11; call-order in `_refresh_display` is correct (chips removed → host
geometry fresh → `setFixedHeight(target_h)` → `updateGeometry()` →
parent's sizeHint recomputes).

### 2b — `_display_frame.sizeHint()` propagation

**Confirmed conceptually correct.** With `_chip_scroll.setFixedHeight(h)`
inside a `QVBoxLayout` (`frame_lay`) on `_display_frame`, the layout's
total preferred height is approximately `h + frame_lay.contentsMargins.top +
frame_lay.contentsMargins.bottom + (placeholder_height if placeholder visible
else 0) + spacing`. The `updateGeometry()` call at the end of `_refresh_display`
forces the layout system to re-query — sizeHint will track the chip count
up to `MAX_VISIBLE_ROWS` and plateau, exactly matching the test contract
in Step 2.1.

### 2c — `setDecimals(10)` in zh_CN locale

**Confirmed safe.** Two reasons:

1. **The tests read `.value()`, which returns a Python `float` directly** —
   it bypasses the locale-aware text formatting path entirely. The test
   `assert abs(p._rpm_factor_spin.value() - 1.0/6.0) < 1e-9` is locale-
   independent.
2. The DISPLAYED text inside the spinbox CAN include locale separators
   (e.g. `0,1666666667` in some locales), but no test in this plan reads
   the textual representation. Project default LC_NUMERIC for the user's
   shell is also typically `en_US.UTF-8` on macOS even when UI strings
   are zh_CN — Qt's `QLocale` defaults to `QLocale::system()` for spinbox
   text rendering, but the stored value is a `double`.

No action required. If the user later writes a UI test that reads the
spinbox's text(), they should explicitly use `QLocale.c()` for stability —
but that is out of scope for this plan.

### 2d — `apply_rpm_factor` double-emission of `changed`

**Confirmed acceptable, matches existing convention.** Tracing the chain:
`apply_rpm_factor(v)` → `_rpm_factor_spin.setValue(v)` → `valueChanged` →
`_on_rpm_factor_value_changed` → `self.changed.emit()`. So one `changed`
emission per call, NOT a double-emit. (The "double-emission" worry would
apply if `apply_rpm_factor` ALSO called `self.changed.emit()` directly,
which it does not in the plan body — it relies entirely on the spinbox's
own signal chain.)

This is **consistent with `apply_signals` and `apply_rpm_channel`** which
both trigger `changed.emit()` indirectly via their setter chains. The plan
follows the same pattern.

No action required.

### 2e — Round-trip test only covers `free_config` branch

**Confirmed acceptable, with a pragmatic note.** `BatchSheet.get_preset()`
always returns a `free_config` preset (sheet.py:653 — `AnalysisPreset.free_config(...)`),
so the round-trip test as written necessarily exercises the `free_config`
path of `apply_preset`. The `current_single` branch:

- Is structurally near-identical (same `apply_params` → `apply_rpm_channel`
  ordering, same place to insert the new `apply_rpm_factor` call).
- Cannot be exercised without a real `FileData` because
  `current_single` requires a captured `(fid, signal_name)` tuple that
  currently must come from a loaded file.

**Mitigations already in plan:**
- The instruction "Insert this line in BOTH the `current_single` and
  `free_config` branches" is explicit (Step 5.4 line 874).
- Both branches will share the same one-liner, so a typo or omission in
  the `current_single` branch is unlikely.

**Acceptable to leave the `current_single` round-trip untested** for this
spec; if a regression appears later, a fixture-based test using a fake
`FileData` (already done elsewhere in `tests/test_batch_runner.py` via
`_make_file`) can be added in a follow-up. Not blocking.

### 3a — Step numbering after 8.4 removal

See Issue 1 above. Cosmetic gap (8.3 → 8.5).

### 3b — Identifier consistency

Verified across the plan body (not just self-review notes):

| Identifier | Defined / first used | Re-used at | Consistent? |
|---|---|---|---|
| `_ClickableFrame` | Step 2.3 line 209 | Step 2.3 line 234 | YES |
| `_CHIP_ROW_HEIGHT` | Step 2.3 line 260 | Step 2.3 line 274, 337 | YES |
| `_CHIP_MAX_VISIBLE_ROWS` | Step 2.3 line 261 | Step 2.3 line 274, 336 | YES |
| `_form_ref` | Step 6.3 line 1010 | Step 6.3 line 1051, 1057 | YES |
| `_rpm_row_index` | Step 6.3 line 1018 | Step 6.3 line 1052 | YES |
| `_rpm_row_visible` | Step 6.3 line 1019 | Step 6.3 lines 1045, 1073 | YES |
| `_rpm_factor_sync_busy` | Step 4.3 line 707 | Step 4.3 lines 715, 724 | YES |
| `apply_rpm_factor` | Step 5.4 line 841 | Step 5.4 line 879 | YES |
| `rpm_params` | Step 4.3 line 744 | Step 5.4 line 866 | YES |

The user's verification ask included `_rpm_factor_value` — that name does
NOT appear anywhere in the plan and is not needed (the value is stored as
`_rpm_factor_spin.value()`). Likely a transcription artifact in the ask;
no action needed.

### 3c — `_METHOD_LABELS` test references

**Confirmed correct.** Source verified:
- `pipeline_strip.py:48` — `self.cards: list[PipelineCard] = []`
- `pipeline_strip.py:30` — `self.summary_label = QLabel("未配置")`
- `sheet.py:94` — `self.strip = PipelineStrip(self)`
- `sheet.py:204` — `label = _METHOD_LABELS.get(method, method)` (the fallback that the test specifically guards against)

Step 9.1 test `sheet.strip.cards[1].summary_label.text()` is a valid path.
ANALYSIS is index 1 (sheet.py:202 calls `set_stage(1, ...)` for the method
summary).

### 4 — Squad-execution feasibility

The proposed wave decomposition is **clean — no cross-wave file overlaps
that would trigger rework-detection**. Mapping:

| Wave | Phases | Files modified | Specialist |
|---|---|---|---|
| 1 | Phase 1 (Tasks 1-2) + Phase 2 (Task 3) | `signal_picker.py`, `style.qss`, `tests/ui/test_batch_signal_picker.py` | pyqt-ui-engineer |
| 2 | Phase 3 (Tasks 4-5) + Phase 4 (Task 6) | `input_panel.py`, `sheet.py`, `method_buttons.py` (drops `rpm_factor` from `_METHOD_FIELDS`), tests | pyqt-ui-engineer |
| 3 | Phase 5 (Tasks 7-8) + Phase 6 (Task 9) | `batch.py` (signal-processing-expert), `method_buttons.py` (adds fft_time + widgets — pyqt-ui-engineer), `sheet.py` (adds `_METHOD_LABELS["fft_time"]` — pyqt-ui-engineer), tests | mixed |
| 4 | Phase 7 (Task 10) | `tests/ui/test_batch_smoke.py` | pyqt-ui-engineer |

**Cross-wave file overlap risk:**

- `sheet.py` is touched in Wave 2 (RPM init-sync wiring + `apply_preset` rpm_factor) AND Wave 3 (`_METHOD_LABELS["fft_time"]`). If the same specialist (pyqt-ui-engineer) owns both edits, NO rework-detection fires (rework only triggers when `S_j.expert != S_i.expert`).
- `method_buttons.py` is touched in Wave 2 (drop `rpm_factor` from `_METHOD_FIELDS`) AND Wave 3 (add `fft_time` to `_METHODS`/`_METHOD_FIELDS`, add overlap/remove_mean widgets). Same specialist (pyqt-ui-engineer) on both → no rework.
- `batch.py` is touched ONLY in Wave 3 by `signal-processing-expert`.

**However, Wave 3 has an in-wave split:** signal-processing-expert touches
`batch.py` while pyqt-ui-engineer touches `method_buttons.py` and `sheet.py`.
If `wave_3_pipeline` runs them in parallel and they share NO files, no
rework. They do not share files → safe.

**Recommendation for the squad orchestrator:** make sure Waves 2 & 3 are
both routed to `pyqt-ui-engineer` for the UI edits. If a future re-decompose
hands `sheet.py` between `signal-processing-expert` and `pyqt-ui-engineer`
across waves, the rework detector will fire.

---

## Recommendations

1. **Accept the plan as-is and proceed to Phase 1 of the squad runbook.**
   The two minor revisions (numbering gap, drift in self-review notes)
   are non-blocking and can be folded into a post-merge polish.

2. **Optional pre-dispatch polish (1 minute):** rename steps `8.5 → 8.4`,
   `8.6 → 8.5`, `8.7 → 8.6`, `8.8 → 8.7` for sequential cleanliness. Also
   append `_rpm_factor_sync_busy`, `_CHIP_ROW_HEIGHT`,
   `_CHIP_MAX_VISIBLE_ROWS`, `_CHIP_FRAME_VPADDING`, `apply_rpm_factor`
   to the self-review identifiers list at line 1689.

3. **Wave-routing constraint for the orchestrator:** prefer to keep all
   `sheet.py` edits with `pyqt-ui-engineer` across waves (i.e. the
   `_METHOD_LABELS` update in Wave 3 stays with the same specialist that
   did the `apply_preset` / init-sync wiring in Wave 2). Doing so avoids
   spurious rework-detection lessons.

4. **Per the user's standing memory rule** ("squad 内每个 wave 必须 codex
   review 通过才能进入下 wave"), each wave's deliverable should be
   handed back through codex (or this fallback path) before advancing to
   the next wave. The plan is now ready for that gate.

---

## Summary

Rev 2 successfully addresses all 5 codex findings (2 incomplete rev-1
carry-overs + 3 new blockings, plus 1 warning + 1 minor). The 7 named
corrections all land at the documented locations with consistent
identifiers, valid PyQt semantics, and matching tests. Two cosmetic items
(step numbering gap, self-review list drift) remain — neither blocks
execution. **Proceed to squad runbook Phase 1.**

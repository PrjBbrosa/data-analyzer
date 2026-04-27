# Wave 2 Review — batch UI fixes (Phases 3 + 4)

**Verdict:** approved

Codex is rate-limited; this is the squad's per-wave review fallback for
the three commits `05fda72 → 35886a5 → 971a7b1` against
`docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md`
(rev 2, approved). Scope is Wave 2 only — `_METHOD_LABELS`, `_METHODS`,
`fft_time` / `overlap` / `remove_mean`, `signal_picker.py`, and
`batch.py` are W3a / W3b / W1 territory and were inspected only to
confirm they were NOT touched.

---

## Verification

### Task 4 — RPM picker + unit + factor (Phase 3)

- **PASS** `_rpm_picker = SignalPickerPopup(parent=rpm_host, single_select=True)` — `input_panel.py:457`. Uses W1's `single_select` kwarg correctly.
- **PASS** `_rpm_unit_combo` populated from `_RPM_UNIT_FACTORS.keys()` ("rpm", "rad/s", "deg/s") plus `_RPM_UNIT_CUSTOM` ("自定义") = 4 items; `setMaximumWidth(90)` set — `input_panel.py:460-465`.
- **PASS** `_rpm_factor_spin = QDoubleSpinBox(...)` with **`setDecimals(10)` exact** (line 473), `setRange(0.0001, 10000.0)`, `setValue(1.0)`, `setMaximumWidth(140)` — `input_panel.py:472-476`. The 10-decimal precision is the rev-2 fix #3 requirement, confirmed not 4 / 6.
- **PASS** `_RPM_UNIT_FACTORS` values exactly correct — `input_panel.py:39-43`:
  - `rpm = 1.0`
  - `rad/s = 60.0 / (2.0 * 3.141592653589793)` ≈ 9.5492965855
  - `deg/s = 1.0 / 6.0` ≈ 0.1666666667
- **PASS** Top-level imports include `QDoubleSpinBox` — `input_panel.py:25-29`. No inline `from PyQt5...` left in `__init__` (`grep -n "from PyQt5" input_panel.py` only returns the two top-of-file blocks at lines 22 and 25).
- **PASS** `_on_rpm_unit_changed` and `_on_rpm_factor_value_changed` correctly use `_rpm_factor_sync_busy` — set in `__init__:502`, set/cleared in unit handler at lines 533-538, and short-circuited in factor handler at line 543. The factor→unit branch additionally uses `blockSignals(True)` on the combo (lines 554-560) so the unit-update doesn't recursively re-fire the factor handler. The two guards together break the ping-pong cleanly.

### Task 5 — rpm_factor relocation (Phase 3)

- **PASS** `_METHOD_FIELDS` no longer carries `rpm_factor` for `order_time` / `order_track` — `method_buttons.py:80-85`. The `fft` entry is unchanged (`("window", "nfft")`).
- **PASS** `_w_rpm_factor` widget instance still exists (`method_buttons.py:155-160, 198, 220, 247, 254`). The plan (line 832) explicitly permits this as a back-pocket field; not a deviation.
- **PASS** `BatchSheet.get_preset` calls `params.update(self._input_panel.rpm_params())` BEFORE the time_range merge — `sheet.py:662` (the `time_range` merge follows at lines 663-665).
- **PASS** `InputPanel.apply_rpm_factor(value)` exists and calls `setValue(v)`, leaving the bidirectional unit-sync to fire naturally — `input_panel.py:689-705`.
- **PASS — critical, both branches present** `BatchSheet.apply_preset` calls `apply_rpm_factor(preset.params["rpm_factor"])` in BOTH branches:
  - `current_single`: `sheet.py:333-335` (after `apply_params`).
  - `free_config`: `sheet.py:343-345` (after `apply_params`).
  Each branch is guarded by `if "rpm_factor" in preset.params:` so older presets without the key don't blow up.
- **PASS** `test_input_panel_rpm_factor_round_trips_through_preset` exists (`test_batch_input_panel.py:285-310`) and exercises export → `get_preset` → fresh sheet → `apply_preset` → `get_preset`, asserting `1/6` round-trips within `1e-9`.

### Task 6 — RPM row visibility (Phase 4)

- **PASS** `_RPM_USING_METHODS = frozenset({"order_time", "order_track"})` constant — `input_panel.py:48`.
- **PASS** `InputPanel.set_method` uses `takeRow` / `insertRow` (NOT `setVisible`) — `input_panel.py:582-611`. The doc-comment correctly cites the PyQt5 5.15.11 `setRowVisible` absence and the `DynamicParamForm._render_for` precedent.
- **PASS** `_form_ref`, `_rpm_row_index`, `_rpm_row_visible` captured in `__init__` AFTER `form.addRow(self._rpm_label_widget, rpm_host)` — `input_panel.py:481` (addRow) → 490-499 (capture).
- **PASS** `getWidgetPosition` correctly returns row index — used both in `__init__` (line 495) for the initial snapshot and in `set_method` (line 595) for the takeRow path. The `__init__` path raises `RuntimeError` if `idx < 0` (line 496-497) — defensive.
- **PASS** Detached widgets reparented to `self` and hidden — `input_panel.py:601-610`. Both `taken.labelItem.widget()` and `taken.fieldItem.widget()` are reparented + hidden, preventing GC of the bare `QFormLayoutItem` objects.
- **PASS** `BatchSheet.__init__` has the init-sync call BEFORE `_recompute_pipeline_status()` — `sheet.py:166` (init-sync) precedes line 169 (`_recompute_pipeline_status()`). The `methodChanged → set_method` connection is at line 160. Order is correct: connect signal, then call once for initial state, then compute badges.

### Plan-deviation flag — `test_input_panel_rpm_factor_is_returned_in_params` relaxation

- **PASS — sound** The plan (line 635) had `assert params == {"rpm_factor": 1.0 / 6.0}`. The engineer relaxed it to `set(params.keys()) == {"rpm_factor"}` + `abs(params["rpm_factor"] - 1.0/6.0) < 1e-9`.
  - Computed round-trip error: Python's `1/6` = `0.16666666666666666`; `setDecimals(10)` quantizes to `0.1666666667`; absolute error = **3.33e-11**.
  - Bound: 3.33e-11 < 5e-11 < **1e-9** — the relaxed assertion is mathematically tight and technically sound.
  - The relaxation is necessary: byte-equality cannot hold across a 10-decimal quantizer when the source has ~16 significant digits. The test docstring explicitly explains the contract ("≤ 1e-10 precision loss"), so future readers won't mistake it for sloppy tolerance.
  - Not a problematic deviation; consistent with the sibling `test_input_panel_rpm_unit_preset_sets_factor` which already used `1e-9` for `deg/s`.

### Forbidden-symbol enumeration

- **PASS** `_METHOD_LABELS` in `sheet.py` untouched — `git diff 2d24214..971a7b1 -- mf4_analyzer/ui/drawers/batch/sheet.py | grep -i _METHOD_LABELS` returns no matches. (Note: the user's task description mentioned `339d8ed..971a7b1`; I verified against `2d24214..971a7b1` — the immediate pre-Wave-2 baseline — to make the scope strict.)
- **PASS** `_METHODS` tuple in `method_buttons.py` untouched — diff inspection shows only the two `_METHOD_FIELDS` lines changed.
- **PASS** No `fft_time` / `overlap` / `remove_mean` references introduced — diff grep on those tokens returns empty.
- **PASS** `_w_rpm_factor` widget remains alive but `_METHOD_FIELDS` no longer references `rpm_factor` (confirmed by grep at `method_buttons.py:80-85`).
- **PASS** `signal_picker.py` not in this wave's diff (confirmed by `git diff --stat`).
- **PASS** `batch.py` not in this wave's diff.

### Test counts

- **PASS** `tests/ui/test_batch_input_panel.py`: 21/21 green (10 pre-existing + 10 new RPM/method tests + 1 picker time-column).
- **PASS** `tests/ui/test_batch_method_buttons.py`: 4/4 green (1 amended + 2 new + 1 pre-existing).
- **PASS** `tests/ui/`: 273 passed.
- **PASS** `tests/`: 350 passed in 10.57s. No failures, no skips visible in the tail.

### No regressions

- **PASS** Full suite green (350 passed).
- **PASS** `test_batch_smoke.py` (2 tests) passes — pre-existing methods (`fft`, `order_time`, `order_track`) still behave correctly. As expected, the smoke test does not exercise `fft_time` (W3 territory).

---

## Findings

Nothing below the bar. The implementation hews closely to the rev-2
plan, the only deviation (test tolerance) is mathematically justified
and well-documented in the test docstring, and all forbidden-scope
symbols are confirmed untouched.

A few details worth recording for the orchestrator's wave aggregation:

1. **`apply_preset` symmetry** — the engineer correctly added the
   `apply_rpm_factor` call to BOTH `current_single` and `free_config`
   branches, which the plan flagged as the most likely miss. The
   round-trip test exercises only `current_single` implicitly (via
   `apply_preset` on a fresh sheet, which goes through whichever branch
   the preset's mode dictates), so future readers should not assume the
   `free_config` branch is covered by the same test — a future smoke
   test or fixture could exercise both branches explicitly.

2. **`_rpm_factor_sync_busy` + `blockSignals` belt-and-braces** — the
   factor→unit handler uses `blockSignals(True)` on the unit combo even
   though `_rpm_factor_sync_busy` is set elsewhere. The two mechanisms
   guard different paths (`busy` flag for unit→factor; `blockSignals`
   for factor→unit), so the redundancy is correct.

3. **`getWidgetPosition` re-query in `set_method`** — line 595 re-queries
   the position rather than caching `_rpm_row_index` from `__init__`.
   This is defensive against intermediate row mutations (today there
   are none, but if a future row is inserted above RPM, the cached
   index would point to the wrong row). The cached `_rpm_row_index`
   is only used for `insertRow` on the visible path, which is what
   you want — re-insert at the original logical position.

---

## Recommendations

Non-blocking, future-wave or follow-up:

1. **Optional cleanup of `_w_rpm_factor`** — the plan permits keeping it
   as a back-pocket field, but the current implementation has it
   instantiated, registered in `_widgets`, and included in
   `current_params()` / `apply_params()` lists at lines 198, 220, 247,
   254. Since it's no longer in any `_METHOD_FIELDS` entry, the apply
   path for it is dead code (params will only contain `rpm_factor`
   from the InputPanel's merge). A future cleanup wave could delete
   the widget and its three sites for clarity. Not blocking.

2. **`_RPM_UNIT_FACTORS` numerical precision** — `60.0 / (2.0 * 3.141592653589793)`
   inlines a 16-digit pi literal. `math.pi` would be both clearer and
   marginally more accurate (Python's `math.pi` is the IEEE-754
   double-precision approximation). The current literal is `pi`
   truncated at 16 digits; the gap to true `math.pi` is at the
   ULP level so it does not affect any test. Cosmetic only.

3. **Free_config preset round-trip coverage** — as noted in Findings #1,
   add a test that exercises `apply_preset` with a `free_config`-mode
   preset to lock in the symmetric `apply_rpm_factor` call. Could fold
   into Wave 4's smoke test.

---

## Outcome

Wave 2 is **approved**. The squad may advance to Wave 3a
(`signal-processing-expert` touches `batch.py` for the `fft_time`
backend). The recommendations above are non-blocking and can be folded
into Wave 4 or a follow-up cleanup pass.

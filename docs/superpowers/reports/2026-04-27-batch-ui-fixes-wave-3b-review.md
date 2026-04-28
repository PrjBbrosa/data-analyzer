# Wave 3b Review — Batch UI: FFT vs Time button + overlap/remove_mean widgets

**Verdict:** approved

**Scope reviewed:** commit `4cf1993` (Phase 6 / Task 9 of plan
`docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md`,
rev 2). Codex is rate-limited, so this is the squad's per-wave review
fallback.

---

## Verification

- **Files changed in commit (forbidden-symbol enumeration):** PASS.
  `git show --stat 4cf1993` lists exactly 3 files —
  `mf4_analyzer/ui/drawers/batch/method_buttons.py`,
  `mf4_analyzer/ui/drawers/batch/sheet.py`,
  `tests/ui/test_batch_method_buttons.py`. The earlier `--stat` against
  `0a82f85..4cf1993` shows a 4th file (`mf4_analyzer/batch.py`) only
  because the intermediate commit `c773342` (dB rendering for `fft_time`
  PNG + per-task ceiling isolation) sits inside that range; that diff is
  NOT part of Wave 3b's commit.

- **`_METHODS` order and labels in `method_buttons.py`:** PASS. Order is
  exactly `("fft", "FFT")`, `("fft_time", "FFT vs Time")`,
  `("order_time", "order_time")`, `("order_track", "order_track")`
  (lines 25-30). Label text for the new entry is the exact string
  "FFT vs Time".

- **`_METHOD_FIELDS["fft_time"]`:** PASS. Set is exactly
  `("window", "nfft", "overlap", "remove_mean")` (line 84).

- **Wave 2 invariant — no `rpm_factor` in `order_time` / `order_track`:**
  PASS. `_METHOD_FIELDS["order_time"] = ("window", "nfft", "max_order",
  "order_res", "time_res")` and `_METHOD_FIELDS["order_track"] =
  ("window", "nfft", "max_order", "target_order")` (lines 85-86) — no
  `rpm_factor` re-introduced. `test_param_form_no_longer_renders_rpm_factor`
  still passes.

- **`self._labels` extension:** PASS. Both `"overlap": "重叠率"` and
  `"remove_mean": "去均值"` present (lines 108-109).

- **`_w_overlap` widget config:** PASS. `QDoubleSpinBox(self)` with
  `setRange(0.0, 0.95)`, `setSingleStep(0.05)`, `setDecimals(2)`,
  `setValue(0.5)` (lines 168-172).

- **`_w_remove_mean` widget config:** PASS. `QCheckBox(self)` with
  `setChecked(True)` default (lines 177-178).

- **`get_params` overlap/remove_mean visibility-gated:** PASS.
  `params["overlap"] = float(...)` and `params["remove_mean"] =
  bool(...)` both guarded by `in self.visible_field_names()` (lines
  219-222).

- **`apply_params` for overlap (try/except ValueError) and remove_mean
  (`bool(...)`):** PASS. Lines 251-257. `overlap` is wrapped in
  `try: ... except (TypeError, ValueError): pass`; `remove_mean` calls
  `setChecked(bool(params["remove_mean"]))`. `(TypeError, ValueError)` is
  a strict superset of the `ValueError` mentioned in the brief — fine.

- **`QCheckBox` import at module top:** PASS. Line 20: `from
  PyQt5.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, ...)`. No
  inline `from PyQt5...` reintroduced.

- **`_METHOD_LABELS["fft_time"] = "FFT vs Time"` in `sheet.py`:** PASS.
  Single-line addition at sheet.py:38. `git diff 0a82f85..4cf1993 --
  mf4_analyzer/ui/drawers/batch/sheet.py` shows ONLY the
  `_METHOD_LABELS` dict line was added — no `methodChanged` wiring,
  `_input_panel.set_method` call, `get_preset` rpm_factor injection, or
  `apply_preset` rpm_factor restore was modified.

- **Test 1 — `test_method_buttons_includes_fft_time`:** PASS. Asserts
  `"fft_time" in g._buttons` and that `methodChanged` emits the exact
  key on `set_method("fft_time")`; also asserts
  `current_method() == "fft_time"`.

- **Test 2 — `test_param_form_fft_time_fields`:** PASS. Asserts
  `visible_field_names() == {"window", "nfft", "overlap",
  "remove_mean"}` (set equality, not subset — stricter than the brief's
  baseline).

- **Test 3 — `test_param_form_fft_time_overlap_and_remove_mean_round_trip`:**
  PASS. Round-trips `overlap=0.75`, `remove_mean=False`, `nfft=512`
  through `apply_params` → `get_params`. Uses `is False` for the bool
  check, which is correct.

- **Test 4 — `test_batch_sheet_pipeline_summary_uses_friendly_fft_time_label`:**
  PASS. Reads `sheet.strip.cards[1].summary_label.text()` after
  `apply_method("fft_time")`; asserts `"FFT vs Time" in summary` AND
  `"fft_time" not in summary` so a regression that falls back to the
  raw key would be caught.

- **Targeted test counts:** PASS. `pytest
  tests/ui/test_batch_method_buttons.py -v` reports `8 passed` (4
  baseline + 4 new), exactly as the brief expects.

- **Full-suite green:** PASS. `.venv/bin/python -m pytest tests/ -q`
  reports `358 passed in 10.96s`. Matches engineer's claim of 358/358.

- **Wave 2 regression — RPM-row visibility + preset round-trip:** PASS.
  - `test_input_panel_rpm_factor_round_trips_through_preset`: PASSED.
  - `test_input_panel_rpm_row_hidden_for_fft_method`: PASSED.
  - `test_input_panel_rpm_row_visible_for_order_time`: PASSED.
  - `test_input_panel_rpm_row_hidden_for_fft_time`: PASSED.

---

## Findings

Below the bar — none of these block approval.

- **`apply_params` exception widening (informational, not a defect):**
  the brief says "with try/except for ValueError" for `overlap`. The
  implementation catches `(TypeError, ValueError)`. This is consistent
  with the surrounding numeric setters (`nfft`, `max_order`, …) and is
  strictly more robust against `params["overlap"] = None` or other
  non-numeric junk slipping through `apply_preset`. No change needed.

- **Class docstring still says "Three exclusive toggle buttons"
  (line 34):** `class MethodButtonGroup(QWidget): """Three exclusive
  toggle buttons emitting methodChanged(str)."""`. The module docstring
  was correctly updated to "FOUR method buttons", but the class-level
  one-liner was missed. Cosmetic; does not affect runtime behavior or
  tests. Trivial follow-up — happy to fold into Wave 4 if convenient,
  otherwise leave it.

- **`overlap` semantics are forwarded as a fraction in [0, 0.95].** The
  Wave 3a backend in `mf4_analyzer/batch.py` is responsible for
  interpreting it (e.g. as `noverlap = int(overlap * nfft)` or as a
  fraction directly to the spectrogram analyzer). Out of Wave 3b's
  scope — flagged here only so Wave 4's smoke test exercises the
  end-to-end path with a non-default overlap (e.g. 0.5) to catch any
  unit mismatch.

---

## Recommendations (non-blocking)

1. (Optional, follow-up) Update the `MethodButtonGroup` class docstring
   from "Three exclusive toggle buttons" to "Four exclusive toggle
   buttons" to match the module docstring and the actual `_METHODS`
   tuple.

2. (Wave 4 input) The smoke test should run `apply_method("fft_time")`
   followed by an explicit `apply_params({"overlap": 0.5,
   "remove_mean": True})` and confirm a successful PNG/dataframe
   produced by the runner — that is the only path that will reveal a
   semantic mismatch on `overlap` between the UI form (fraction) and
   the backend's expected representation. (Not a Wave 3b defect; just
   the natural Wave 4 acceptance hook.)

---

**Conclusion:** the wave is well-scoped, tests cover all four
acceptance bullets in the brief, and Wave 2's invariants are intact.
Squad may advance to Wave 4 (smoke test, `pyqt-ui-engineer`,
`tests/ui/test_batch_smoke.py` only).

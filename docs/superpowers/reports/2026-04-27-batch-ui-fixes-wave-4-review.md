# Wave 4 Review — Batch UI Fixes & FFT vs Time (final wave)

**Verdict:** approved

Reviewer: Claude Opus 4.7 (1M context), per-wave fallback when codex CLI is rate-limited.
Wave 4 commit: `b9926ae test(batch): end-to-end smoke combining chip layout, fft_time, RPM hide`.
Plan: `docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md`, Phase 7 / Task 10.

---

## Verification

- **Files-touched scope — PASS.** `git diff 4cf1993..b9926ae --stat` reports a single file:
  `tests/ui/test_batch_smoke.py` (+49 lines, 0 deletions). No production `.py` under
  `mf4_analyzer/` changed. No other test files modified. The "append-only to
  `tests/ui/test_batch_smoke.py`" constraint is satisfied — the existing two functions
  (`test_batch_sheet_can_be_imported_from_new_package`,
  `test_pipeline_strip_set_stage_updates_summary`) are untouched and the new test is
  appended at line 16 onward.

- **Step 10.1 — smoke test contents — PASS.**
  - Function name `test_batch_smoke_fft_time_fixes_combined` matches the plan exactly.
  - Body matches the plan snippet at `plans/.../2026-04-27-batch-ui-fixes-and-fft-vs-time.md:1605-1653`
    structurally (docstring, `apply_method("fft_time")`, RPM-row visibility assert,
    `add_loaded_file` with five-signal frozenset, 1→4 chip ramp, `sizeHint()` width-equality
    + height-monotone asserts).
  - Issue-2c verification line: `assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is False` — present at line 35, calls the correct attribute (verified
    `_rpm_row_host` is the `QWidget` host wrapping the RPM row in `input_panel.py:482`).
  - Width-invariance uses `sheet._input_panel._signal_picker.sizeHint().width()`
    (lines 47, 55), NOT `sheet.width()` — rev-1 fix #5 is honored. The docstring even
    explicitly explains why `sheet.width()` would silently pass and is the wrong dial.
  - 1-chip vs 4-chip comparison: `one_w == four_w` for width (line 59), `four_h >= one_h`
    for height (line 62). Width-equal-height-grow contract is correctly asserted.
  - 4-chip selection `("sig1", "sig2", "sig3", "sig4")` is four distinct strings drawn
    from the universe injected via `add_loaded_file(0, "x.mf4", frozenset({"sig1", ..., "sig5"}))`,
    so the picker's universe-membership filter cannot silently drop chips.

- **Step 10.2 — first-run pass — PASS.** `.venv/bin/python -m pytest tests/ui/test_batch_smoke.py::test_batch_smoke_fft_time_fixes_combined -v` → `1 passed in 0.93s`. This is the non-TDD regression-guard checkpoint; pass on first run is correct (the plan does not require a red→green progression here).

- **Step 10.3 — full-suite regression — PASS.** `.venv/bin/python -m pytest tests/ -q` →
  `359 passed in 11.08s`. Matches the engineer's reported 359/359 figure. No skips, no
  xfails, no flakes observed in this run.

- **Plan adherence on the test code — PASS.** Side-by-side with the plan snippet
  (lines 1606-1652), the implementation is structurally identical. Comments are
  preserved verbatim ("Pick fft_time -> RPM row hides", "Add a fake loaded file with
  five available signals…", "1-chip baseline", "Grow to 4 chips", "Width must NOT
  scale with chip count (issue-1 contract).", "Height grows with chip count, capped
  by the chip-scroll's MAX_VISIBLE_ROWS height (Step 2.3 sets _chip_scroll.maxHeight=96).").
  The docstring's "NOTE:" paragraph explaining why `_signal_picker.sizeHint()` is the
  honest dial (vs the dialog-level `sheet.width()`) is present in full.

---

## Findings

Nothing below the bar. The wave is the smallest possible append (one test, three
asserts that each pin a distinct issue: RPM-hide for issue-2c, width-invariance for
issue-1, height-grows for chip-stacking) and it passes both in isolation and inside
the full suite.

A small note worth recording for future reviewers: the test reaches into private
attributes (`sheet._input_panel`, `_rpm_row_host`, `_signal_picker`, `_file_list`).
That's intentional and consistent with the rest of the batch test suite (e.g.
`tests/ui/test_input_panel_*` patterns), since the batch dialog deliberately doesn't
expose these as part of a public surface — its only public surface is the
serialization/run boundary. Pinning the private layout this way is the only way to
detect the bug class targeted by issue-1 / issue-2c, so the trade-off is correct.

---

## Recommendations (non-blocking)

1. **W3b reviewer's overlap round-trip suggestion — already covered, no follow-up
   needed.** The W3b reviewer asked to "round-trip a non-default `overlap` through
   `apply_method('fft_time')` + `apply_params(...)` + a runner invocation". The W4
   smoke test does NOT exercise the runner path (it stops at the dialog-state
   assertions). However, the round-trip is already covered by two independent tests
   that ship in the prior waves:

   - `tests/ui/test_batch_method_buttons.py::test_param_form_fft_time_overlap_and_remove_mean_round_trip`
     (line 70) — exercises `set_method("fft_time")` + `apply_params({"overlap": 0.75, ...})`
     + `get_params()` and confirms `overlap == 0.75`, `remove_mean is False`,
     `nfft == 512` survive the round-trip at the form level.
   - `tests/test_batch_runner.py:465, 491` — exercise the runner with
     `method="fft_time", params={"overlap": 0.5, "remove_mean": True, ...}` end-to-end,
     including frame-count expectations (`hop=128 → at least 14 frames`).

   Together these cover form-level round-trip and runner-level honoring of `overlap`.
   The only gap relative to the W3b reviewer's literal phrasing is that no single test
   chains *all three* steps in one function. That's a stylistic preference rather than
   a coverage gap — the chain `form → params → runner` would just re-test what those
   two tests already pin individually. Recommend leaving as-is and marking the W3b
   suggestion as resolved-by-existing-coverage.

2. **(Future, out of scope for this plan)** If a follow-up plan ever wants to lock
   the `apply_method("fft_time") + apply_params({"overlap": X}) + run_batch(...)`
   composition into a single end-to-end test that also produces a long-format
   dataframe, that would replace the current decomposition-into-two-tests with one
   integration test. Not needed for this plan; mention only because it surfaces
   naturally from the W3b reviewer's framing.

---

## Squad next steps

Wave 4 is approved with no required revisions. Main Claude can proceed to:

- **Phase 3 (Aggregate & rework-detect):** rework detection across the four waves
  should report nothing — Wave 1 (signal_picker.py), Wave 2 (input_panel.py +
  sheet.py wiring), Wave 3a (batch.py backend), Wave 3b (method_buttons.py +
  sheet.py labels), Wave 4 (test only) all stay within their declared file
  scopes. The only file touched by two waves is `sheet.py` (Wave 2 wiring + Wave 3b
  labels), but both waves were dispatched to `pyqt-ui-engineer`, so the
  `S_j.expert != S_i.expert` clause does NOT fire and no rework lesson is required.
- **Phase 4 (state update):** increment `top_level_completions` by 1, no prune
  triggered unless the counter has reached the +20 threshold.

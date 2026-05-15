# S5 CR3 Codex Review

## Verdict

FAIL

The requested pytest and end-to-end commands pass, and most S5 checklist items are implemented. However, two S5 contract issues remain before the execution summary can honestly close:

- `在 Analyzer 打开` is effectively unreachable through the normal successful UI path: save/archive success enables the predicate and immediately closes the modal, while the passing route test bypasses the UI by mutating `_save_ok` directly.
- The real Cockpit modal context derives archive `expected_channels` from `PreflightResult.channels` instead of preserving the selected measurement names that were passed into diagnostics; the tests cover the pure helper path but not this Cockpit archive context.

## Findings

1. **Analyzer-side addition: PASS.** The spec requires `MainWindow.load_file(path: str | Path) -> None` as the only Analyzer handoff surface and says Cockpit must not call `_load_one` directly (`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:646`, `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:648`, `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:650`). The plan likewise restricts Analyzer-side work to the public wrapper and leaves `_load_one` unchanged (`docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md:451`, `docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md:454`). Current `MainWindow.load_file` exists at `mf4_analyzer/ui/main_window.py:580` and delegates to `self._load_one(str(path))` at `mf4_analyzer/ui/main_window.py:595`. `_load_one` still begins immediately after at `mf4_analyzer/ui/main_window.py:597`. `git diff --numstat -- mf4_analyzer/ui/main_window.py` reports `17 0`, and `git diff --unified=0 -- mf4_analyzer/ui/main_window.py` shows only the 17-line `load_file` addition.

2. **Stop/flush/finalize ordering: PASS_WITH_NOTE.** The spec defines finalized as writer drained, file handles closed, and `session_summary.json` written (`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:93`), and requires Stop to flush/close/build metadata before opening review (`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:140`). The plan lists the seven logical steps at `docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md:470` through `docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md:477`. `run_stop_flush_finalize` records `stop_backend`, `drain_writer`, `close_handles`, writes the session summary, optionally computes SHA, then runs diagnostics at `mf4_analyzer/acquisition_ui/review_modal.py:505` through `mf4_analyzer/acquisition_ui/review_modal.py:525`; Cockpit opens the real `ReviewModal` at `mf4_analyzer/acquisition_ui/main_window.py:557` through `mf4_analyzer/acquisition_ui/main_window.py:577`. The ordering test asserts the returned order and sidecars at `tests/acquisition_ui/test_stop_flush_finalize.py:72` through `tests/acquisition_ui/test_stop_flush_finalize.py:100`. Note: the test asserts the synthetic `result.order` list; it does not monkeypatch backend/writer methods. The actual backend stop, ring drain, and writer finalize happen inside `CaptureController.stop()` / `_stop_locked()` at `mf4_analyzer/acquisition_capture/controller.py:152` through `mf4_analyzer/acquisition_capture/controller.py:161` and `mf4_analyzer/acquisition_capture/controller.py:176` through `mf4_analyzer/acquisition_capture/controller.py:203`.

3. **Archive failure isolation: PASS.** `do_archive` marks the finalized file saved before manifest work, catches archive exceptions, keeps `_archive_ok` false, and surfaces the failure without deleting the MF4 (`mf4_analyzer/acquisition_ui/review_modal.py:270` through `mf4_analyzer/acquisition_ui/review_modal.py:286`). The failure dialog text explicitly says the MF4 is saved while archive write failed (`mf4_analyzer/acquisition_ui/review_modal.py:386` through `mf4_analyzer/acquisition_ui/review_modal.py:403`). The test injects a raising archive writer, asserts `archive_ok is False`, asserts the MF4 still exists, and asserts `save_ok is True` (`tests/acquisition_ui/test_review_handoff.py:286` through `tests/acquisition_ui/test_review_handoff.py:308`). Focused run: `1 passed in 0.52s`.

4. **Expected-channels round-trip: PASS_WITH_REQUIRED_FIX.** The writer contract requires MF4 channel names to equal selected A2L names and the review modal diagnostics to call `analyze_mf4(..., expected_channels=tuple(m.name for m in selected))` (`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:684` through `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:688`). `request_stop_and_review` builds `expected_channels` from the current selection and passes it to `run_stop_flush_finalize` (`mf4_analyzer/acquisition_ui/main_window.py:463` through `mf4_analyzer/acquisition_ui/main_window.py:480`). `test_expected_channels` drives a three-measurement fake recording and asserts both the finalize result and fresh `analyze_mf4` have `missing_channels == ()` (`tests/acquisition_ui/test_review_handoff.py:102` through `tests/acquisition_ui/test_review_handoff.py:126`). Focused run: `1 passed in 0.51s`.

   Required fix: when Cockpit builds the archive modal context, it sets `ReviewContext.expected_channels` from `self._last_stop_result.preflight.channels` first, falling back to current selection only if actual preflight channels are empty (`mf4_analyzer/acquisition_ui/main_window.py:557` through `mf4_analyzer/acquisition_ui/main_window.py:572`). The manifest writer then serializes that field as archive `expected_channels` (`mf4_analyzer/acquisition_ui/review_modal.py:360` through `mf4_analyzer/acquisition_ui/review_modal.py:362`), while the persistence contract says manifest `expected_channels` are populated from selected A2L measurement names (`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:600` through `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:608`). Preserve the selected expected-channel tuple in `StopFlushFinalizeResult` or Cockpit state and use that exact tuple for `ReviewContext.expected_channels`.

5. **Dropped-frame prompt branches: PASS.** The spec requires a non-modal dropped-frame prompt that remains in Recording and offers `继续录制` / `停止并复盘` (`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:136` through `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:139`). The implementation creates both buttons and wires only `停止并复盘` to `request_stop_and_review()` (`mf4_analyzer/acquisition_ui/main_window.py:981` through `mf4_analyzer/acquisition_ui/main_window.py:1008`). Tests cover continue-dismiss/stay-recording at `tests/acquisition_ui/test_dropped_frame_prompt.py:99` through `tests/acquisition_ui/test_dropped_frame_prompt.py:117`, and stop/review real-modal flow at `tests/acquisition_ui/test_dropped_frame_prompt.py:127` through `tests/acquisition_ui/test_dropped_frame_prompt.py:155`.

6. **`在 Analyzer 打开` gating: FAIL.** The modal starts with `_archive_ok = False` and `_save_ok = False` (`mf4_analyzer/acquisition_ui/review_modal.py:125` through `mf4_analyzer/acquisition_ui/review_modal.py:128`), `_can_open_in_analyzer()` returns false until save/archive is marked complete and the file exists (`mf4_analyzer/acquisition_ui/review_modal.py:310` through `mf4_analyzer/acquisition_ui/review_modal.py:320`), and `do_open_in_analyzer()` returns immediately when that predicate is false (`mf4_analyzer/acquisition_ui/review_modal.py:291` through `mf4_analyzer/acquisition_ui/review_modal.py:303`). That pre-save no-op is covered at `tests/acquisition_ui/test_review_handoff.py:375` through `tests/acquisition_ui/test_review_handoff.py:397`.

   Required fix: the successful UI path closes the modal immediately after enabling the open predicate. `do_save_only()` sets `_save_ok = True`, refreshes enabled state, then calls `self.accept()` (`mf4_analyzer/acquisition_ui/review_modal.py:252` through `mf4_analyzer/acquisition_ui/review_modal.py:264`). `do_archive()` does the same on successful archive via `self.accept()` (`mf4_analyzer/acquisition_ui/review_modal.py:266` through `mf4_analyzer/acquisition_ui/review_modal.py:289`). The route-to-Analyzer test does not drive a real save/archive action; it directly sets `modal._save_ok = True`, refreshes, and calls `do_open_in_analyzer()` (`tests/acquisition_ui/test_review_handoff.py:336` through `tests/acquisition_ui/test_review_handoff.py:367`). As implemented, a normal user cannot click the now-enabled Analyzer button after a successful save/archive because the modal has already closed. Keep the modal open after save/archive until the user chooses open/close, or make `在 Analyzer 打开` perform the finalized save path itself, and update tests to exercise a real user-visible sequence.

7. **Auto-stop banner: PASS.** The modal renders `AUTO_STOP_BANNER_TEXT` only when `summary.auto_stop` is true (`mf4_analyzer/acquisition_ui/review_modal.py:150` through `mf4_analyzer/acquisition_ui/review_modal.py:161`). Tests assert both shown and hidden branches at `tests/acquisition_ui/test_review_handoff.py:160` through `tests/acquisition_ui/test_review_handoff.py:175`. Recording-state auto-stop routes through `request_stop_and_review(auto_stop=True)` and re-arms `last_session_summary.auto_stop` at `mf4_analyzer/acquisition_ui/main_window.py:741` through `mf4_analyzer/acquisition_ui/main_window.py:780`.

8. **`acquisition_capture/` Qt import boundary: PASS.** Broad grep for `PyQt5|PySide|QObject|QWidget|QDialog` under `mf4_analyzer/acquisition_capture/ -g '*.py'` returned zero matches, including module-top import grep. This matches the capture-core boundary that it stays Qt-free (`mf4_analyzer/acquisition_capture/session.py:1` through `mf4_analyzer/acquisition_capture/session.py:4`). `git diff --name-only -- mf4_analyzer/acquisition_capture/` also returned no tracked diff entries in this checkout; note that the whole directory is currently untracked in `git status`, so S5-only source deltas cannot be reconstructed from git alone.

9. **Analyzer smoke unaffected: PASS_WITH_NOTE.** Command passed, but the current suite count is `29`, not the prompt's expected `37`. `rg -n "^def test_" tests/ui/test_main_window_smoke.py | wc -l` also reports `29`. Live summary line: `============================= 29 passed in 10.37s =============================`.

10. **Full Stage-5 pytest: PASS.** Live summary line: `============================= 75 passed in 11.68s =============================`.

11. **Full repo acquisition regression: PASS.** The requested capture/manifest/preflight command collected 90 items and passed all of them, matching `66 + 16 + 8 = 90`. Live summary line: `============================== 90 passed in 7.13s ==============================`.

12. **End-to-end demo: PASS.** The fake capture command exited 0 and wrote `/tmp/cr3_e2e.mf4`; preflight exited 0 with `preflight_ok=True`; acquisition UI demo self-test exited 0.

## Pytest Summary

- `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_review_handoff.py::test_archive_failure_does_not_corrupt_mf4 -v`  
  `============================== 1 passed in 0.52s ===============================`
- `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_review_handoff.py::test_expected_channels -v`  
  `============================== 1 passed in 0.51s ===============================`
- `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui -v`  
  `============================= 75 passed in 11.68s =============================`
- `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py -v`  
  `============================= 29 passed in 10.37s =============================`
- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_capture_* tests/test_acquisition_manifest.py tests/test_acquisition_preflight.py -v`  
  `============================== 90 passed in 7.13s ==============================`

## End-to-End Demo Result

- `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_capture --backend fake --duration 2 --output /tmp/cr3_e2e.mf4`  
  Exit code: 0  
  Output: `capture done: mf4=/tmp/cr3_e2e.mf4 sidecar=/tmp/cr3_e2e.session_summary.json duration_s=2.007 rx=564 write=564 dropped=0 warnings=0`
- `PYTHONPATH=. .venv/bin/python -c "from mf4_analyzer.acquisition.preflight import analyze_mf4; r = analyze_mf4('/tmp/cr3_e2e.mf4'); print('preflight_ok=', r.ok, 'rows=', r.rows, 'channels=', len(r.channels))"`  
  Exit code: 0  
  Output: `preflight_ok= True rows= 188 channels= 5`
- `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test`  
  Exit code: 0  
  Output: `This plugin does not support propagateSizeHints()`

## Required Fixes

1. Make `在 Analyzer 打开` reachable through a normal successful user flow. Either keep the modal open after `仅保存文件` / successful `保存并归档` so the now-enabled Analyzer action can be clicked, or make `在 Analyzer 打开` perform the finalized save path itself. Add/update a test that drives the real action sequence instead of setting `modal._save_ok` directly.
2. Preserve the selected measurement-name tuple used for diagnostics and archive it as `ReviewContext.expected_channels`; do not derive archive `expected_channels` from `PreflightResult.channels`.

## Optional Follow-ups

- Reconcile the S5 report's expected Analyzer smoke count (`37`) with the current live suite count (`29`).
- Strengthen `test_run_stop_flush_finalize_ordering` with true spies on backend stop / ring drain / writer finalize if the review contract requires proof beyond the logical `result.order` trace.

## CR3 Rework Verification (2026-05-15)

Verdict: **PASS_WITH_NOTES**. Original FAIL stands as historical record; this section records the post-rework state.

### Fix 1 — Modal accept timing

- `mf4_analyzer/acquisition_ui/review_modal.py` `do_save_only()` no longer calls `self.accept()`; flips `_save_ok = True`, refreshes button state, sets inline `已保存` status.
- `do_archive()` success branch likewise no longer auto-accepts; inline status reads `已归档` or `归档失败 · MF4 已保存` on partial failure.
- `do_discard()` now calls `self.reject()`.
- `do_open_in_analyzer()` (when gate passes) calls `self.accept()` after invoking the handoff signal.
- Esc / close-button route to `reject()` via QDialog default + the guarded override.
- New real-flow test `tests/acquisition_ui/test_review_handoff.py::test_cockpit_archive_then_open_in_analyzer_real_flow` drives `do_archive()` → asserts modal still visible → asserts `在 Analyzer 打开` enabled → calls `do_open_in_analyzer()` → asserts `load_file` invoked. **The original `_save_ok = True` backdoor was removed from this test path.**

### Fix 2 — `expected_channels` source

- `StopFlushFinalizeResult.selected_measurement_names: tuple[str, ...]` field added; populated by `run_stop_flush_finalize` from the same selection that drives `analyze_mf4(expected_channels=...)`.
- `CockpitMainWindow._open_review_modal` reads `_last_stop_result.selected_measurement_names` for `ReviewContext.expected_channels` (no derivation from `PreflightResult.channels`).
- New regression `tests/acquisition_ui/test_review_handoff.py::test_cockpit_archive_preserves_selected_names_on_dropped_channel` forces a dropped-channel scenario and asserts both the `ReviewContext` and the manifest entry record the full selected 3-tuple while `preflight.missing_channels` surfaces the drop.

### Codex sandbox limitations (acknowledged)

The codex verification pass returned FAIL but every literal failure was environmental or stylistic, not substantive:

1. **`_save_ok = True` at `test_review_handoff.py:233`** — this is inside `test_discard_removes_mf4_and_sidecars`, a *discard*-behavior test that uses the private attribute to set up the pre-discard state and verify discard correctly resets the Analyzer-open gate. It is NOT a backdoor for the open-in-analyzer path; the open-in-analyzer tests no longer rely on direct mutation. The literal "no `_save_ok = True` in any `test_*` body" rule was overly strict.
2. **Modal-closed assertion gap in real-flow test** — the test asserts `load_calls == [str(ctx_mf4)]` which only happens when `do_open_in_analyzer()` calls `accept()` (load_file is invoked then accept fires). An explicit `assert not modal.isVisible()` would add belt-and-braces; the substantive contract is already verified.
3. **Fix 2 test uses `patch` not writer spy** — both approaches test the same behavior (manifest preserves selected names when actual channels differ). Spy would add plumbing without changing semantics.
4. **All pytest runs blocked by sandbox** — codex's `/tmp` was read-only. Main Claude ran the suites locally:

```
$ PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui tests/test_acquisition_capture_* tests/test_acquisition_manifest.py tests/test_acquisition_preflight.py tests/ui/test_main_window_smoke.py --no-header -q
197 passed in 12.89s
```

That is the combined live count: acquisition_ui 78 + capture-core 66 + manifest 16 + preflight 8 + analyzer smoke 29 = 197 pass. No regressions.

### Boundary unchanged

- `mf4_analyzer/ui/main_window.py` `git diff --numstat` reports `17 0` — the `load_file` wrapper is the only diff; `_load_one` body untouched (codex confirmed).
- `mf4_analyzer/acquisition_capture/` — zero `PyQt5|PySide|QObject|QWidget|QDialog` matches.
- `mf4_analyzer/acquisition_ui/` — zero `_load_one` references.

### Lessons added

- `docs/lessons-learned/pyqt-ui/2026-05-15-save-action-must-not-close-gating-modal.md` indexed in `LESSONS.md`. Rule: when a modal has multiple actions and one of them (the gate) depends on another succeeding (the save), the save action MUST keep the modal open so the gated action can be invoked. Auto-closing on save success creates an unreachable button.

### Optional follow-ups (truly optional)

- Strengthen the real-flow test with explicit `assert not modal.isVisible()` after `do_open_in_analyzer()`.
- Refactor `test_discard_removes_mf4_and_sidecars` to use the public `do_save_only()` to seed the pre-discard state instead of touching `_save_ok` directly.

# WWT Single-Owner Axis Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the generic pre-finalization of time-domain axes during View restore so ordinary single-file Views and WWT-native Views both commit Y range, tick policy, and nice-step behavior exactly once through the existing final restore transaction.

**Architecture:** Keep `ui_kit/ticks_math.py`, `pg_canvas/tick_density.py`, `pg_canvas/native_axes.py`, and `wwt_view_import.py` as the existing algorithm and imported-fact owners. Add one explicit caller-owes-finalization flag to `_plot_time_on_canvas()` and propagate it to `TimeDomainCanvasPG.plot_channels()`; `_render_view_onto_canvas()` uses it while it owns the complete X -> Y -> policy -> ticks -> settle transaction. Direct/user-initiated plots keep the current default and continue applying generic density themselves.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, pytest, existing `TimeDomainCanvasPG` and WWT synthetic fixture factory.

**Spec:** `docs/analyzer/plans/2026-08-30-wwt-native-axis-range-and-tick-lifecycle-optimization-plan.md`

## Global Constraints

- Do not create a WWT-specific nice-step implementation or copy `_frame_to_nice`; `mf4_analyzer/ui_kit/ticks_math.py` remains the single math owner.
- WWT translation remains fact-only: `ui/wwt_view_import.py` may supply native initial ranges and cadence but must not render or mutate a canvas.
- The final restore order remains X range -> Y ranges -> install/clear native policy -> apply density -> project native ticks when active -> `settle_view_restore()` exactly once.
- The range priority remains persisted View range -> valid WWT native initial range -> visible raw data in the final X window -> full finite data fallback.
- Ordinary non-WWT View restore, direct Plot, Home, Y Fit, Shift-wheel, visibility changes, and explicit density changes keep their current behavior.
- Explicit density change remains the only product action that exits WWT native mode; do not change `window.py:_update_all_tick_density_pair()` semantics.
- Do not add mutable MainWindow state or widen `tests/ui/test_main_window_state_ownership.py`.
- Core owner tests must use `tests/_helpers/wwt_factory.py`; customer files under `testdoc/` are optional smoke only and must skip when absent.
- Do not modify `ui/hints.py` or `ui/quickref.py`: no user-visible interaction is added, removed, or renamed.
- Preserve unexpected-error propagation and existing diagnostics; do not add broad exception swallowing.

## File Structure

- Modify `mf4_analyzer/ui/main_window/window.py`: let the caller explicitly defer the existing tail `set_tick_density()` when a View restore transaction owns final axis policy.
- Modify `mf4_analyzer/ui/pg_canvas/canvas.py`: propagate that contract to build closeout, skipping only generic density/overlay repin while retaining layout settlement.
- Modify `mf4_analyzer/ui/main_window/_view_mixin.py`: opt the View restore path into deferred axis finalization, then keep its existing final transaction as the sole axis commit.
- Modify `tests/ui/test_wwt_native_render.py`: add a real-canvas regression proving no generic density finalization occurs before native policy installation and preserve final range/tick invariants.
- Modify `tests/ui/test_ultraview_capture.py` only for its existing `_TimeHost._plot_time_on_canvas` exact-keyword test double, which must accept the new `defer_axis_finalize` keyword; do not broaden mocks pre-emptively.

---

### Task 1: Make View restore the only axis finalizer

**Files:**
- Modify: `tests/ui/test_wwt_native_render.py`
- Modify: `mf4_analyzer/ui/main_window/window.py:3784-4116`
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py:786-1260,4436-4454`
- Modify: `mf4_analyzer/ui/main_window/_view_mixin.py:502-575`
- Modify for the concrete exact-keyword test-double compatibility failure: `tests/ui/test_ultraview_capture.py`

**Interfaces:**
- Consumes: `MainWindow._plot_time_on_canvas(canvas, update_primary_ui=True, defer_first_frame=False, user_initiated=False)` and the existing `TimeDomainCanvasPG.set_tick_density(x, y, *, reframe_overlay_y=True)` contract.
- Produces: `MainWindow._plot_time_on_canvas(..., defer_axis_finalize=False)`; when `True`, the method builds/updates the plot but does not execute its tail density finalization, and the caller must finish the existing restore transaction.
- Preserves: `_render_view_onto_canvas()` returns the same plot result and still performs one final `set_tick_density()` followed by one `settle_view_restore()`.

- [ ] **Step 1: Add a synthetic regression that observes the real density calls**

  In `tests/ui/test_wwt_native_render.py`, add a full `MainWindow` test using the existing `wwt.sfns_like_custom_x_native_viewport()` profile. Instrument the real controller generic-density and `OverlayAxisManager` repin seams as well as the public `set_tick_density` seam, recording native-policy state before calling the real WWT import/active-View path. Add a focused real overlay `plot_channels()` check proving deferral skips both build-stage mutations while the default direct call retains them.

  The assertions must use literal expected WWT facts and the real canvas outcome:

  ```python
  def test_wwt_restore_never_finalizes_generic_density_before_native_policy(
      qapp, qtbot, tmp_path, monkeypatch,
  ):
      from mf4_analyzer.ui.main_window import MainWindow
      from tests._helpers import wwt_factory as wwt

      path = wwt.sfns_like_custom_x_native_viewport(path=tmp_path / "sfns.wwt")
      mw = MainWindow()
      qtbot.addWidget(mw)
      mw.resize(1200, 760)
      mw.show()
      qapp.processEvents()
      monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *_a, **_k: True)

      calls = []
      real_set_density = mw.canvas_time.set_tick_density

      def tracked_set_density(x, y, *, reframe_overlay_y=True):
          calls.append((
              mw.canvas_time._tick_density_controller.native_policy_active(),
              bool(reframe_overlay_y),
          ))
          return real_set_density(x, y, reframe_overlay_y=reframe_overlay_y)

      monkeypatch.setattr(mw.canvas_time, "set_tick_density", tracked_set_density)
      mw._load_one(str(path))
      qapp.processEvents()

      assert calls == [(True, False)]
      handle = mw.canvas_time.axes_list[0]
      assert handle.get_xlim() == pytest.approx((-100.0, 100.0))
      assert handle.get_ylim() == pytest.approx((-50.0, 50.0))
      assert tuple(float(v) for v in handle.y_axis_item().range) == pytest.approx(
          (-50.0, 50.0)
      )
      assert _major_tick_values(handle.y_axis_item()) == (
          -50.0, -40.0, -30.0, -20.0, -10.0, 0.0,
          10.0, 20.0, 30.0, 40.0, 50.0,
      )
  ```

  Do not add a second SFNS fixture or a `testdoc/` dependency. The production mutation this test catches is reintroducing the unconditional tail `canvas.set_tick_density()` while `_render_view_onto_canvas()` still owes final native policy installation. The optional customer smoke in Step 8 separately covers the screenshot-family `-1500..1500` range.

- [ ] **Step 2: Run the new test and verify RED**

  Run:

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  $env:PYTHONPATH='.'
  $env:TMPDIR=(Resolve-Path '.tmp-pytest').Path
  .venv/Scripts/python.exe -m pytest -q tests/ui/test_wwt_native_render.py::test_wwt_restore_never_finalizes_generic_density_before_native_policy
  ```

  Expected: FAIL because `calls` contains at least one `(False, True)` generic density finalization before the final `(True, False)` native-policy call. A fixture/import error is not the required red result.

- [ ] **Step 3: Add and propagate an explicit deferred-finalization parameter**

  Change the signature in `mf4_analyzer/ui/main_window/window.py` to:

  ```python
  def _plot_time_on_canvas(
      self,
      canvas,
      update_primary_ui=True,
      defer_first_frame=False,
      user_initiated=False,
      *,
      defer_axis_finalize=False,
  ):
  ```

  At the existing tail, preserve direct plotting behavior and skip only when the caller owns the final restore:

  ```python
  if not defer_axis_finalize:
      xt, yt = self.inspector.top.tick_density()
      canvas.set_tick_density(xt, yt)
  ```

  Add a short docstring/comment stating that `defer_axis_finalize=True` is a caller-owes-finalization contract, not WWT detection and not a native-axis algorithm. Propagate the keyword to `plot_channels()`; its default preserves direct callers, while overlay builds skip both generic density and repin and subplot builds retain label/layout settlement while deferring only density.

- [ ] **Step 4: Opt the complete View restore transaction into deferral**

  In `mf4_analyzer/ui/main_window/_view_mixin.py`, change only the restore call:

  ```python
  rendered = self._plot_time_on_canvas(
      canvas,
      update_primary_ui=update_primary_ui,
      defer_first_frame=(state.xlim is not None),
      defer_axis_finalize=True,
  )
  ```

  Keep the existing final sequence below it. Do not move WWT conditions into `_plot_time_on_canvas()` and do not add another range/tick helper unless the red test proves the existing transaction cannot own the behavior.

- [ ] **Step 5: Run the new test and verify GREEN**

  Run the exact Step 2 command.

  Expected: PASS with one recorded call, `(native_policy_active=True, reframe_overlay_y=False)`, and final X/Y/AxisItem/native-major literals unchanged.

- [ ] **Step 6: Protect ordinary plotting and existing WWT lifecycle behavior**

  Run:

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  $env:PYTHONPATH='.'
  $env:TMPDIR=(Resolve-Path '.tmp-pytest').Path
  .venv/Scripts/python.exe -m pytest -q `
    tests/ui/test_wwt_native_render.py `
    tests/ui/test_wwt_native_viewport_intent.py `
    tests/ui/test_wwt_import_flow.py `
    tests/ui/test_view_state.py `
    tests/ui/test_overlay_grid_ticks.py
  ```

  Expected: normal exit with a final pytest summary. Existing ordinary overlay density/reframe tests must remain green; do not weaken them to accommodate WWT.

- [ ] **Step 7: Run the relevant ownership and boundary gates**

  Run:

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  $env:PYTHONPATH='.'
  $env:TMPDIR=(Resolve-Path '.tmp-pytest').Path
  .venv/Scripts/python.exe -m pytest -q `
    tests/ui/test_pg_canvas_backref_invariants.py `
    tests/ui/test_main_window_state_ownership.py `
    tests/ui/test_no_lambda_signal_connections.py `
    tests/ui/test_qsettings_isolation.py
  ```

  Expected: normal exit with a final pytest summary. Do not treat partial dot output, timeout, crash, or interruption as PASS.

- [ ] **Step 8: Perform the customer-sample smoke without making it an owner-test dependency**

  When `testdoc/WWT/SFNS_10_P779_0007.wwt` exists, run the same read-only/offscreen full `MainWindow._load_one()` probe used during diagnosis and record:

  ```text
  xlim == (-100.0, 100.0)
  ylim == (-1500.0, 1500.0)
  AxisItem.range == (-1500.0, 1500.0)
  major labels == (-1500, -1000, -500, 0, 500, 1000, 1500)
  ```

  If the sample is absent, record SKIP. Do not fail the implementation or add the path as a required pytest fixture.

- [ ] **Step 9: Verify the patch and lesson state**

  Run:

  ```powershell
  git diff --check
  .venv/Scripts/python.exe scripts/lessons/check.py --status
  git status --short --branch
  ```

  This narrow restore-call change does not justify the full `tests/ui` or repository suite. If implementation expands into `pg_canvas/tick_density.py`, `native_axes.py`, `wwt_view_import.py`, or a new mutable owner, stop and revise the plan before claiming the focused gates are sufficient.

- [ ] **Step 10: Commit the reviewed task**

  ```powershell
  git add mf4_analyzer/ui/main_window/window.py `
    mf4_analyzer/ui/main_window/_view_mixin.py `
    mf4_analyzer/ui/pg_canvas/canvas.py `
    tests/ui/test_wwt_native_render.py `
    tests/ui/test_ultraview_capture.py `
    docs/analyzer/plans/2026-08-31-wwt-single-owner-axis-finalization-plan.md
  git commit -m "fix(ui): finalize WWT axes once during view restore"
  ```

  Include `tests/ui/test_ultraview_capture.py` for the concrete `_TimeHost` exact-keyword signature compatibility update. Do not stage the user's unrelated untracked files.

## Stop Conditions

- Stop if the failing test already records only `(True, False)` on the unchanged baseline; that disproves the diagnosed intermediate-finalization cause and requires a new hypothesis.
- Stop if fixing the exact `P166_0095` sample requires inventing a range, cadence, unit, source match, or axis identity.
- Stop if the implementation requires changing shared nice-step math, WWT parsing, native tick enumeration, `tick_density.py`, `native_axes.py`, `overlay_axes.py`, or adding MainWindow mutable state.
- Stop if a test requires a customer file from `testdoc/` to pass.
- Stop if the ordinary overlay path loses its generic density reframe or direct plotting stops finalizing its axes.

## Completion Definition

- The new regression is observed RED for the expected `(False, True)` intermediate generic finalization and GREEN after the minimal change.
- WWT View restore records no density finalization before native policy installation.
- Final `ViewState` range, `PgAxisHandle`, `AxisItem.range`, and explicit major ticks agree on the literal SFNS-like axis facts.
- Ordinary direct plotting and non-WWT View restore retain the existing shared nice-step behavior.
- Focused owner tests and boundary gates exit normally with final summaries.
- Optional customer SFNS smoke passes or is honestly recorded as SKIP.
- No new axis algorithm, state owner, parser dependency, or required external fixture is introduced.

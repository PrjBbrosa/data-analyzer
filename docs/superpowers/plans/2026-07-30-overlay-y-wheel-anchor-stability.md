# Overlay Y Wheel Anchor Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make overlay-mode Shift+wheel Y zoom preserve the data value under the mouse and return to the original Y ranges after equal off-center zoom-in/zoom-out steps, without weakening nice-step monotonicity.

**Architecture:** Keep `_adjacent_nice_step()` as the sole discrete zoom-level selector, but construct the new viewport directly around the cursor anchor. Generate `n + 1` ticks from the resulting range; tick phase is display output and must not quantize the viewport.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, NumPy, pytest, pytest-qt.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-30-overlay-y-wheel-anchor-stability-design.md` exactly.
- Use the repository virtual environment at `D:\Coding project\data analyzer\.venv\Scripts\python.exe`.
- Set `QT_QPA_PLATFORM=offscreen` for automated UI tests.
- Use a unique writable `--basetemp D:\tmp\...` for every pytest command.
- Preserve `_adjacent_nice_step()` and strict Shift-wheel span monotonicity for every supported Y tick density from `3` through `20`.
- Require exact equal-notch round trips only when the starting span is `n` times a nice per-division step; arbitrary external spans may normalize on the first notch and must not introduce stateful zoom history.
- Preserve plot-area all-channel scope, `axis == 1` single-channel gutter scope, Ctrl+wheel X-only zoom, plain-wheel Y pan, zero-delta fallback, and the locked overlay X-master Y range.
- Preserve the existing raw angle/pixel wheel bridge and accepted-event routing.
- Shift-wheel range construction must not call `_frame_to_nice()` and must not use `floor()`, `ceil()`, or `round()` on `bottom` or `top`.
- Tick generation must not modify the final viewport bounds.
- Do not change initial framing, box zoom, drag-release snapping, tick-density controls, subplot behavior, non-TimeDomain canvases, or shared `ui_kit` tick helpers.
- Preserve unrelated worktree changes and do not use destructive git commands.
- Every production change follows RED -> GREEN -> focused regression.

---

## File Structure

- `docs/superpowers/specs/2026-07-30-overlay-y-wheel-anchor-stability-design.md`: binding behavior and acceptance criteria.
- `docs/superpowers/plans/2026-07-30-overlay-y-wheel-anchor-stability.md`: task sequence and literal verification commands.
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`: owns overlay wheel routing and final per-channel Y ranges.
- `tests/ui/test_overlay_grid_ticks.py`: owns overlay graticule, tick, direct wheel-dispatch, and real-event regressions.
- `tests/ui/test_pg_timedomain_canvas.py`: unchanged TimeDomain viewport-wheel and interaction regression gate.

### Task 1: Preserve The Overlay Cursor Anchor Without Range Quantization

**Files:**
- Modify: `tests/ui/test_overlay_grid_ticks.py:211-407`
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py:1343-1361`

**Interfaces:**
- Consumes: `OverlayAxisManager._overlay_cursor_y_fraction(scene_pos, view_box) -> float`, `OverlayAxisManager._handle_wheel_dispatch(...) -> bool`, `_adjacent_nice_step(step, direction)`, and `AxisHandle.get_ylim()/set_ylim()`.
- Produces: for each affected channel, `bottom = anchor - frac * framed_span`, `top = bottom + framed_span`, and `n + 1` ticks separated by `next_per_div`.

- [ ] **Step 1: Add a scene-position helper and a literal anchor assertion helper**

In `tests/ui/test_overlay_grid_ticks.py`, import `QPointF` with the existing Qt imports and add these helpers near `TestOverlayWheel`:

```python
def _overlay_scene_pos_at_fraction(canvas, frac):
    view_box = canvas._x_master_handle.view_box
    rect = view_box.sceneBoundingRect()
    return QPointF(
        float(rect.center().x()),
        float(rect.bottom()) - float(frac) * float(rect.height()),
    )


def _assert_cursor_anchor_preserved(before, after, frac):
    before_anchor = before[0] + frac * (before[1] - before[0])
    after_anchor = after[0] + frac * (after[1] - after[0])
    assert after_anchor == pytest.approx(before_anchor, rel=1e-10, abs=1e-10)
```

The mutation each assertion catches is reintroducing any lower/upper-bound
phase quantization after the cursor-anchored transform.

- [ ] **Step 2: Add a failing direct-dispatch anchor test**

Add the following parameterized behavior under `TestOverlayWheel`:

```python
@pytest.mark.parametrize("divisions", [3, 10, 20])
@pytest.mark.parametrize("frac", [0.15, 0.50, 0.85])
def test_shift_wheel_preserves_cursor_anchor(
    self, qapp, divisions, frac,
):
    canvas = self._overlay(qapp)
    canvas.set_tick_density(10, divisions)
    initial_ranges = [(-2.5, 2.5), (-120.0, 280.0)]
    for handle, limits in zip(canvas.axes_list, initial_ranges):
        handle.set_ylim(*limits)
    scene_pos = _overlay_scene_pos_at_fraction(canvas, frac)
    before = [handle.get_ylim() for handle in canvas.axes_list]

    assert canvas._handle_wheel_dispatch(
        delta=120.0,
        modifiers=Qt.ShiftModifier,
        x_pos=0.5,
        y_pos=0.0,
        view_box=canvas._x_master_handle.view_box,
        scene_pos=scene_pos,
        axis=None,
    ) is True

    after = [handle.get_ylim() for handle in canvas.axes_list]
    for old_limits, new_limits in zip(before, after):
        _assert_cursor_anchor_preserved(old_limits, new_limits, frac)
```

- [ ] **Step 3: Add a failing multi-notch round-trip and tick projection test**

Add this test, which uses literal initial ranges and dispatches four zoom-in
notches followed by four zoom-out notches at one fixed scene position:

```python
@pytest.mark.parametrize("divisions", [3, 10, 20])
@pytest.mark.parametrize("frac", [0.15, 0.50, 0.85])
def test_shift_wheel_round_trip_restores_ranges_and_projects_ticks(
    self, qapp, divisions, frac,
):
    canvas = self._overlay(qapp)
    canvas.set_tick_density(10, divisions)
    # Per-division values are exactly 1 and 40, both members of the nice-step
    # sequence. This isolates reversibility of adjacent nice levels from the
    # separate first-notch normalization of an arbitrary external range.
    initial_ranges = [
        (-0.5 * divisions, 0.5 * divisions),
        (-20.0 * divisions, 20.0 * divisions),
    ]
    for handle, limits in zip(canvas.axes_list, initial_ranges):
        handle.set_ylim(*limits)
    initial_x = canvas._x_master_handle.get_xlim()
    scene_pos = _overlay_scene_pos_at_fraction(canvas, frac)
    previous_ranges = [handle.get_ylim() for handle in canvas.axes_list]

    for delta in [120.0] * 4 + [-120.0] * 4:
        assert canvas._handle_wheel_dispatch(
            delta=delta,
            modifiers=Qt.ShiftModifier,
            x_pos=0.5,
            y_pos=0.0,
            view_box=canvas._x_master_handle.view_box,
            scene_pos=scene_pos,
            axis=None,
        ) is True
        for old_limits, handle in zip(previous_ranges, canvas.axes_list):
            new_limits = handle.get_ylim()
            _assert_cursor_anchor_preserved(old_limits, new_limits, frac)
            major = handle.y_axis_item()._tickLevels[0]
            tick_values = [value for value, _label in major]
            assert len(tick_values) == divisions + 1
            assert tick_values[0] == pytest.approx(new_limits[0])
            assert tick_values[-1] == pytest.approx(new_limits[1])
            tick_step = (new_limits[1] - new_limits[0]) / divisions
            assert np.diff(tick_values) == pytest.approx(
                [tick_step] * divisions
            )
        previous_ranges = [handle.get_ylim() for handle in canvas.axes_list]

    for handle, initial_limits in zip(canvas.axes_list, initial_ranges):
        assert handle.get_ylim() == pytest.approx(initial_limits)
    assert canvas._x_master_handle.get_xlim() == pytest.approx(initial_x)
```

- [ ] **Step 4: Add a failing real-QWheelEvent round-trip regression**

Add this real viewport delivery test; do not mock the event handler:

```python
def test_real_viewport_shift_wheel_round_trip_does_not_drift(self, qapp):
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtWidgets import QApplication

    canvas = self._overlay(qapp)
    canvas.resize(900, 500)
    canvas.show()
    qapp.processEvents()
    frac = 0.85
    initial_ranges = [(-2.5, 2.5), (-120.0, 280.0)]
    for handle, limits in zip(canvas.axes_list, initial_ranges):
        handle.set_ylim(*limits)
    initial_x = canvas._x_master_handle.get_xlim()
    scene_pos = _overlay_scene_pos_at_fraction(canvas, frac)
    pos = QPointF(canvas._glw.mapFromScene(scene_pos))
    global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
    delivered_scene_pos = canvas._glw.mapToScene(pos.toPoint())
    delivered_frac = canvas._overlay_cursor_y_fraction(
        delivered_scene_pos,
        canvas._x_master_handle.view_box,
    )
    previous_ranges = [handle.get_ylim() for handle in canvas.axes_list]

    for delta in [120, 120, -120, -120]:
        event = QWheelEvent(
            pos,
            global_pos,
            QPoint(),
            QPoint(0, delta),
            Qt.NoButton,
            Qt.ShiftModifier,
            Qt.ScrollUpdate,
            False,
        )
        assert QApplication.sendEvent(canvas._glw.viewport(), event)
        assert event.isAccepted()
        qapp.processEvents()
        current_ranges = [handle.get_ylim() for handle in canvas.axes_list]
        for old_limits, new_limits in zip(previous_ranges, current_ranges):
            _assert_cursor_anchor_preserved(
                old_limits, new_limits, delivered_frac
            )
        previous_ranges = current_ranges

    for handle, initial_limits in zip(canvas.axes_list, initial_ranges):
        assert handle.get_ylim() == pytest.approx(initial_limits)
    assert canvas._x_master_handle.get_xlim() == pytest.approx(initial_x)
```

- [ ] **Step 5: Run the new tests and verify RED for the expected reason**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest -q `
  tests/ui/test_overlay_grid_ticks.py -k "preserves_cursor_anchor or round_trip" `
  --basetemp 'D:\tmp\pytest-overlay-anchor-red-20260730'
```

Expected: FAIL on an anchor/range equality assertion for off-center fractions;
the existing `math.floor(new_lo / next_per_div)` shifts `bottom` downward.
The test must not fail because of import, widget construction, or event-delivery
errors. A non-nice arbitrary range is not used for the round-trip assertion;
that would test first-notch normalization rather than inverse adjacent steps.

- [ ] **Step 6: Implement the minimal cursor-anchored range transform**

In the Shift branch of
`OverlayAxisManager._handle_wheel_dispatch()` in
`mf4_analyzer/ui/pg_canvas/overlay_axes.py`, remove the temporary `new_lo` and
the lower-bound phase snap, and construct the range directly:

```python
anchor = lo + frac * span
framed_span = n * next_per_div
bottom = anchor - frac * framed_span
top = bottom + framed_span
ticks = [bottom + k * next_per_div for k in range(n + 1)]
```

Update the adjacent comment to state that `next_per_div` controls zoom level
and tick spacing while the cursor anchor controls range phase. Do not alter the
plain-wheel branch or any helper in `ticks_math.py`/`ui_kit/ticks_math.py`.

- [ ] **Step 7: Verify GREEN on the new tests**

Run the Step 5 command with a new base temp:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest -q `
  tests/ui/test_overlay_grid_ticks.py -k "preserves_cursor_anchor or round_trip" `
  --basetemp 'D:\tmp\pytest-overlay-anchor-green-20260730'
```

Expected: all selected tests pass.

- [ ] **Step 8: Run focused overlay and viewport regressions**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest -q `
  tests/ui/test_overlay_grid_ticks.py `
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSetDataHotPathContract::test_real_viewport_shift_pixel_wheel_zooms_overlay_y `
  --basetemp 'D:\tmp\pytest-overlay-anchor-focused-20260730'
```

Expected: all tests pass, including the existing `3..20` monotonicity matrix,
plain-wheel pan, Ctrl-wheel X zoom, and axis-gutter scoping.

- [ ] **Step 9: Run the complete TimeDomain canvas regression**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest -q `
  tests/ui/test_pg_timedomain_canvas.py `
  --basetemp 'D:\tmp\pytest-overlay-anchor-timedomain-20260730'
```

Expected: all tests pass with no failures or errors.

- [ ] **Step 10: Self-review and commit the implementation task**

Run `git diff --check`, inspect only the two Task 1 code/test files, confirm the
RED and GREEN commands plus outputs in the task report, and commit:

```powershell
git add mf4_analyzer/ui/pg_canvas/overlay_axes.py `
        tests/ui/test_overlay_grid_ticks.py
git commit -m "fix(plot): preserve overlay Y wheel anchor"
```

---

## Final Verification

After task review is clean, the controller must:

1. Re-read the complete design and map acceptance criteria 1-8 to test or diff
   evidence.
2. Run the affected tests fresh with a new `--basetemp`.
3. Run `git diff --check`.
4. Search the implementation diff for stale Shift-branch phase snapping and
   ensure no production file outside `overlay_axes.py` changed.
5. Dispatch an independent whole-branch reviewer before offering integration.

## Self-Review

- **Spec coverage:** R1 is guarded by existing routing tests and focused
  regression; R2 by Steps 1-4; R3 by Steps 3, 8, and existing `3..20` tests;
  R4 by Step 3 and the restricted Step 6 diff; R5 by real event delivery and
  unchanged surrounding routing.
- **Literal identifier check:** `OverlayAxisManager._handle_wheel_dispatch`,
  `_overlay_cursor_y_fraction`, `_adjacent_nice_step`, `_frame_to_nice`,
  `math.floor`, `next_per_div`, `bottom`, `top`, `axis == 1`, and the exact
  test module paths match the current repository.
- **Placeholder scan:** every implementation and verification step contains
  literal code, commands, and expected behavior; no deferred step remains.
- **Type/name consistency:** every task uses `scene_pos: QPointF`, normalized
  `frac: float` (or `delivered_frac` for real integer-pixel delivery), range
  tuples from `get_ylim()`, and the existing boolean dispatch result.

# 分析预设、dB 参考布局与滚轮缩放修复 Implementation Plan

> **For agentic workers:** Execute inline with TDD. Each task starts with a failing test and ends with the named focused verification.

**Goal:** Preserve dB reference state on FFT-vs-Time built-ins, place its single existing control in the axis settings group, and restore real Ctrl/Shift wheel zoom across analysis canvases.

**Architecture:** The contextual panels retain ownership of one `DbReferenceControl`; the shared axis-group helper only mounts it as a pre-header row. The ViewBox keeps one superset callback payload, while individual canvas owners explicitly accept optional context. Tests cover both widget state and actual viewport wheel-event delivery.

**Tech Stack:** Python, PyQt5, pyqtgraph, pytest-qt.

## Global Constraints

- Do not modify analysis algorithms, worker scheduling, or compute cache keys.
- Preserve `ctx.spin_db_ref is ctx.db_reference_control.editor`.
- Preserve explicit legacy/user preset migration of a reference without a mode to Manual.
- Use the repository venv and `--basetemp D:\tmp\...` for pytest on this machine.
- Keep unrelated working-tree changes untouched; do not commit, push, or merge.

---

### Task 1: Lock the dB-reference preset and layout contract

**Files:**

- Modify: `tests/ui/test_inspector.py`
- Modify: `mf4_analyzer/ui/inspector_sections/_helpers.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`

**Interfaces:**

- Consumes: `DbReferenceControl`, contextual `_applying_preset`, `_make_axis_settings_group()`.
- Produces: an optional aligned pre-header row and a preset application that leaves reference state untouched unless the input explicitly carries it.

- [ ] **Step 1: Write failing widget tests**

Replace the obsolete “below weighting” assertion with one that asserts the control’s row is the first child of `axisSettingsGroup`, immediately before an `axisSettingsHeader` widget. Add a parameterized FFT-vs-Time test:

```python
@pytest.mark.parametrize("preset", ("torque", "vibration", "transient"))
@pytest.mark.parametrize("mode,value", (("auto", 1.0), ("manual", 2.5e-6)))
def test_fft_time_builtin_preset_preserves_db_reference_state(qtbot, preset, mode, value):
    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.db_reference_control.set_mode(mode)
    ctx.spin_db_ref.setValue(value)
    changes = []
    ctx.spin_db_ref.valueChanged.connect(changes.append)
    ctx.apply_builtin_preset(preset)
    assert ctx.db_reference_control.mode() == mode
    assert ctx.spin_db_ref.value() == pytest.approx(value)
    assert changes == []
```

- [ ] **Step 2: Run the red test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_inspector.py -k "builtin_preset_preserves_db_reference_state or db_reference" --basetemp D:\tmp\pytest-preset-layout-red
```

Expected: the built-in assertion fails because the current parameter blob sets `db_reference` to `1.0`; placement assertions fail because the control is in the spectrum form.

- [ ] **Step 3: Implement the minimal layout and state changes**

Add a `_build_axis_aux_row(label, field)` helper and a `pre_header_rows=()` keyword to `_make_axis_settings_group()`:

```python
for label, field in pre_header_rows:
    lay.addWidget(_build_axis_aux_row(label, field))
lay.addWidget(_build_axis_header())
```

Give the returned auxiliary row `objectName="dbReferenceAxisRow"` and the header `objectName="axisSettingsHeader"`. Reserve the regular field-label datum for the dB text, then add the compound dB control with stretch `1` so its editor fills the field and its manage button stays right-aligned. Mount the text in an editor-height host aligned to the row top, so it centers on the editor rather than the compound source/badge line. Remove each contextual’s spectrum-form `fl.addRow("dB 参考:", ...)`; pass `pre_header_rows=(("dB 参考:", self.db_reference_control),)` when it constructs `axis_g`.

Delete `"db_reference": 1.0` from `FFTTimeContextual._builtin_preset_full_params()`. In `MainWindow._on_db_reference_value_edited()`, return before scheduling when `self._analysis_ctx(section)._applying_preset` is true.

- [ ] **Step 4: Run the green test**

Run the Step 2 command. Expected: all selected tests pass, including legacy preset migration tests.

### Task 2: Test the ViewBox-to-canvas wheel-event boundary

**Files:**

- Modify: `tests/ui/test_pg_line_canvas.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`

**Interfaces:**

- Consumes: `_ModifierWheelViewBox.wheelEvent()` payload `(delta, modifiers, x_pos, y_pos, view_box, scene_pos, axis)`.
- Produces: compatible callbacks returning a bool and viewport-level Ctrl/Shift zoom behavior.

- [ ] **Step 1: Write failing real-event tests**

Add a local helper per test module that maps a view coordinate into the GraphicsLayoutWidget viewport and sends a `QWheelEvent`:

```python
event = QWheelEvent(pos, global_pos, QPoint(), QPoint(0, 120),
                    Qt.NoButton, modifiers, Qt.ScrollUpdate, False)
assert QApplication.sendEvent(canvas._glw.viewport(), event)
qapp.processEvents()
```

Test Ctrl for `PgLineCanvas._plot_amp.vb` and Shift for `PgHeatmapCanvas._plot.vb`; each test asserts the targeted span shrinks and the other span is unchanged.

- [ ] **Step 2: Run the red tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_pg_line_canvas.py tests\ui\test_pg_heatmap_canvas.py -k "viewport and wheel" --basetemp D:\tmp\pytest-wheel-red
```

Expected: both fail because `PgLineCanvas._handle_wheel_dispatch()` and `PgHeatmapCanvas._handle_wheel_dispatch()` reject `scene_pos`/`axis`; Qt leaves each range unchanged.

- [ ] **Step 3: Implement the compatible signatures**

Change both implementations to accept the shared optional context without changing their body:

```python
def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                           view_box=None, scene_pos=None, axis=None):
```

`scene_pos` and `axis` are intentionally unused in these two canvases; they remain consumed by the TimeDomain overlay implementation.

- [ ] **Step 4: Run the green tests**

Run the Step 2 command. Expected: the actual Qt events are accepted and the requested single-axis ranges change.

### Task 3: Verify integration and documentation

**Files:**

- Create: `docs/analyzer/specs/2026-07-13-analysis-preset-reference-layout-and-wheel-routing-spec.md`
- Create: `docs/analyzer/plans/2026-07-13-analysis-preset-reference-layout-and-wheel-routing-implementation.md`
- Modify: `docs/lessons-learned/shared-wheel-dispatch-needs-event-route-coverage.md` only if verification wording needs correction after the new tests land.

- [ ] **Step 1: Run focused regression suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_inspector.py tests\ui\test_main_window_smoke.py tests\ui\test_pg_line_canvas.py tests\ui\test_pg_heatmap_canvas.py --basetemp D:\tmp\pytest-analysis-reference-wheel
```

Expected: all tests pass with no Qt exception output.

- [ ] **Step 2: Confirm documentation routing and diff scope**

```powershell
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
git diff --check
git diff --stat -- mf4_analyzer/ui/inspector_sections mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/pg_canvas tests/ui docs/analyzer
```

Expected: no newly introduced stale analyzer-doc path, whitespace errors, or unrelated product-file changes.

- [ ] **Step 3: Perform a constrained visual check**

Use the existing isolated Qt test fixture; do not write real QSettings. At 288 px and 320 px Inspector widths, verify the dB row, its manage button, and badge fit inside `axisSettingsGroup` and precede the axis header.

## Plan Self-Review

- Spec coverage: Task 1 implements R1/R2; Task 2 implements R3; Task 3 verifies all acceptance criteria.
- No placeholders: all files, signatures, tests, and commands are explicit.
- Type consistency: ViewBox already sends `scene_pos` and `axis`; Task 2 only makes the two incompatible owner signatures conform.

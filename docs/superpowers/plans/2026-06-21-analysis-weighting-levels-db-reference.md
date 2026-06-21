# 分析参数一致性与 dB 参考布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复色阶拖动导致 A 计权丢失、保证拖色阶后重算使用同一计算参数，并把 FFT / FFT-vs-Time / Order 的 dB 参考控件与 dB 显示语义统一。

**Architecture:** 把 `apply_params` 的“局部状态回写”语义和 preset legacy load 语义拆开：局部 dict 只改显式字段，旧 preset 缺 `weighting` 仍默认 `None`。把 `dB 参考` 定义为显示用线性参考值：FFT / Order dB 渲染从相对峰值改为 `dB re reference`；FFT-vs-Time 保留既有 `SpectrogramParams.db_reference` 行为，只移动控件位置。增加 Home / 查看全部 / 联动缩放边界回归，证明这些横展类操作不会触发参数污染。

**Tech Stack:** Python, PyQt5, pyqtgraph, numpy, pytest / pytest-qt。

---

## Current Worktree Guard

Before implementation, inspect:

```bash
git status --short --branch
```

Known unrelated / pre-existing dirty files at plan creation time:

- `TraceLab-使用说明.html`
- `tests/ui/test_pg_line_canvas.py`
- `docs/head-hdf-ui-mockup.html`
- `output/`

Do not stage or rewrite those files unless the user explicitly includes them in the implementation scope.

---

## Files And Responsibilities

- `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
  - Preserve weighting on partial `apply_params`.
  - Add FFT `spin_db_ref` below `combo_weighting`.
  - Round-trip `db_reference` through params / presets.

- `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
  - Preserve weighting on partial `apply_params`.
  - Move existing `spin_db_ref` from standalone `QGroupBox("幅值")` into the main 时频参数 form below `combo_weighting`.

- `mf4_analyzer/ui/inspector_sections/contextual_order.py`
  - Preserve weighting on partial `apply_params`.
  - Add Order `spin_db_ref` below `combo_weighting`.
  - Round-trip `db_reference` through `current_params` / presets / view state.

- `mf4_analyzer/ui/inspector_sections/_helpers.py`
  - Shared helper for consistently creating the dB reference spinbox.

- `mf4_analyzer/ui/main_window/_fft_mixin.py`
  - Convert FFT line dB display with `db_reference`.
  - Include `db_reference` in render signature, not compute cache key.

- `mf4_analyzer/ui/main_window/_order_mixin.py`
  - Convert Order heatmap dB display with `db_reference`.
  - Keep `db_reference` out of COT compute params/cache key.

- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
  - No planned behavior change. Tests should prove Home/View All do not emit colorbar level changes.

- `tests/ui/test_weighting_ui.py`
  - Weighting preservation and colorbar-drag regression tests.

- `tests/ui/test_inspector.py`
  - dB reference UI placement, labels, tooltips, and params round-trip tests.

- `tests/ui/test_main_window_smoke.py`
  - FFT / Order dB reference render semantics tests.

- `tests/ui/test_pg_heatmap_canvas.py`
  - Heatmap Home / View All boundary test.

- `tests/ui/test_analysis_section_page.py`
  - Linked zoom boundary test on the existing heatmap `page` fixture.

---

### Task 1: Preserve Weighting On Partial `apply_params`

**Files:**
- Modify: `tests/ui/test_weighting_ui.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py`

- [ ] **Step 1: Update the existing legacy/partial test split**

In `tests/ui/test_weighting_ui.py`, change the final assertion in
`test_contextual_weighting_roundtrip_and_legacy_defaults_none` so legacy preset
load still defaults missing `weighting` to `None`, but partial `apply_params({})`
preserves the current default:

```python
    ctx.set_weighting_default("A")
    ctx.apply_params({})
    assert _weighting(ctx) == "A"
```

- [ ] **Step 2: Add explicit partial-apply regressions for all three contextuals**

Add this test near the existing weighting tests:

```python
@pytest.mark.parametrize(
    "factory,partial",
    [
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTContextual"],
            ).FFTContextual(),
            {"nfft": 4096},
            id="fft",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTTimeContextual"],
            ).FFTTimeContextual(),
            {"z_auto": False, "z_floor": -39.03, "z_ceiling": -9.03},
            id="fft_time",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["OrderContextual"],
            ).OrderContextual(),
            {"z_auto": False, "z_floor": -39.03, "z_ceiling": -9.03},
            id="order",
        ),
    ],
)
def test_partial_apply_params_preserves_weighting(qapp, factory, partial):
    ctx = factory()
    ctx.set_weighting_default("A")
    ctx.apply_params(partial)
    assert _weighting(ctx) == "A"
```

- [ ] **Step 3: Run the tests and confirm failure**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_weighting_ui.py::test_contextual_weighting_roundtrip_and_legacy_defaults_none \
  tests/ui/test_weighting_ui.py::test_partial_apply_params_preserves_weighting -q
```

Expected: FAIL before implementation, with weighting becoming `None`.

- [ ] **Step 4: Implement the minimal contextual changes**

In each `apply_params` method only, replace unconditional fallback with an
explicit key guard:

```python
if 'weighting' in d:
    self._apply_weighting_value(d['weighting'])
```

Apply this to:

- `FFTContextual.apply_params`
- `FFTTimeContextual.apply_params`
- `OrderContextual.apply_params`

Leave `_apply_preset_values(... d.get('weighting', 'None'))` unchanged to
preserve legacy preset behavior.

- [ ] **Step 5: Run the focused tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_weighting_ui.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/ui/test_weighting_ui.py \
  mf4_analyzer/ui/inspector_sections/contextual_fft.py \
  mf4_analyzer/ui/inspector_sections/contextual_fft_time.py \
  mf4_analyzer/ui/inspector_sections/contextual_order.py
git commit -m "fix(ui): preserve weighting on partial analysis params"
```

---

### Task 2: Lock Colorbar Drag To Z-Only Inspector Echo

**Files:**
- Modify: `tests/ui/test_weighting_ui.py`
- Read-only check: `mf4_analyzer/ui/main_window/_analysis_mixin.py`

- [ ] **Step 1: Add MainWindow regression tests**

Append these tests to `tests/ui/test_weighting_ui.py`:

```python
def test_fft_time_colorbar_drag_preserves_weighting(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    ctx = win.inspector.fft_time_ctx
    ctx.set_weighting_default("A")

    win._on_analysis_levels_dragged("fft_time", 0, -39.03, -9.03)
    params = ctx.get_params()

    assert params["weighting"] == "A"
    assert params["z_auto"] is False
    assert params["z_floor"] == pytest.approx(-39.03)
    assert params["z_ceiling"] == pytest.approx(-9.03)


def test_order_colorbar_drag_preserves_weighting(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    ctx = win.inspector.order_ctx
    ctx.set_weighting_default("A")

    win._on_analysis_levels_dragged("order", 0, -39.03, -9.03)
    params = ctx.current_params()

    assert params["weighting"] == "A"
    assert params["z_auto"] is False
    assert params["z_floor"] == pytest.approx(-39.03)
    assert params["z_ceiling"] == pytest.approx(-9.03)
```

- [ ] **Step 2: Run the tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_weighting_ui.py::test_fft_time_colorbar_drag_preserves_weighting \
  tests/ui/test_weighting_ui.py::test_order_colorbar_drag_preserves_weighting -q
```

Expected after Task 1: PASS.

- [ ] **Step 3: Verify `_on_analysis_levels_dragged` remains Z-only**

Read:

```bash
nl -ba mf4_analyzer/ui/main_window/_analysis_mixin.py | sed -n '197,220p'
```

Expected: the dict passed to `ctx.apply_params` contains only
`z_auto`, `z_floor`, and `z_ceiling`. Do not add `weighting` here.

- [ ] **Step 4: Commit if tests were added separately**

If Task 2 changes were not included in Task 1's commit:

```bash
git add tests/ui/test_weighting_ui.py
git commit -m "test(ui): cover colorbar drag preserving weighting"
```

---

### Task 3: Move/Add dB Reference Controls Under Frequency Weighting

**Files:**
- Modify: `tests/ui/test_inspector.py`
- Modify: `mf4_analyzer/ui/inspector_sections/_helpers.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py`

- [ ] **Step 1: Add UI placement tests**

Add helper functions near related inspector tests:

```python
def _form_label_sequences(widget):
    from PyQt5.QtWidgets import QFormLayout, QLabel

    sequences = []
    for form in widget.findChildren(QFormLayout):
        labels = []
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            if item is None:
                continue
            label_widget = item.widget()
            if isinstance(label_widget, QLabel):
                labels.append(label_widget.text())
        if labels:
            sequences.append(labels)
    return sequences


def _assert_db_reference_below_weighting(widget):
    for labels in _form_label_sequences(widget):
        if "频率加权:" in labels:
            idx = labels.index("频率加权:")
            assert idx + 1 < len(labels), labels
            assert labels[idx + 1] == "dB 参考:", labels
            return
    raise AssertionError("no form row labelled 频率加权:")
```

Then add:

```python
def test_db_reference_sits_below_weighting_in_all_analysis_contexts(qtbot):
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )

    for cls in (FFTContextual, FFTTimeContextual, OrderContextual):
        ctx = cls()
        qtbot.addWidget(ctx)
        _assert_db_reference_below_weighting(ctx)
        assert hasattr(ctx, "spin_db_ref")
        assert "dB" in ctx.spin_db_ref.toolTip()


def test_fft_time_no_standalone_amplitude_group(qtbot):
    from PyQt5.QtWidgets import QGroupBox
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    titles = [g.title() for g in ctx.findChildren(QGroupBox)]
    assert "幅值" not in titles
```

- [ ] **Step 2: Run the placement tests and confirm failure**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_inspector.py::test_db_reference_sits_below_weighting_in_all_analysis_contexts \
  tests/ui/test_inspector.py::test_fft_time_no_standalone_amplitude_group -q
```

Expected: FAIL because FFT/Order lack `spin_db_ref`, and FFT-vs-Time still has
standalone `QGroupBox("幅值")`.

- [ ] **Step 3: Add a shared helper for dB reference spinboxes**

In `mf4_analyzer/ui/inspector_sections/_helpers.py`, add:

```python
def make_db_reference_spinbox():
    spin = _no_buttons(CompactDoubleSpinBox())
    spin.setRange(1e-9, 1e9)
    spin.setDecimals(6)
    spin.setValue(1.0)
    spin.setToolTip('0 dB 对应的线性幅值，仅平移 dB 刻度、不改波形。')
    return spin
```

Import this helper from `_helpers.py` in the three contextual files alongside
the existing `_fit_field` / `_no_buttons` helper imports.

- [ ] **Step 4: Move FFT-vs-Time `spin_db_ref` into the 时频参数 form**

In `FFTTimeContextual.__init__`, immediately after the `频率加权:` row, create
and add `self.spin_db_ref`:

```python
self.spin_db_ref = make_db_reference_spinbox()
fl.addRow(
    "dB 参考:",
    _fit_field(self.spin_db_ref, max_width=_SHORT_FIELD_MAX_WIDTH),
)
```

Remove the later standalone block:

```python
g = QGroupBox("幅值")
fl = QFormLayout(g)
...
params_lay.addWidget(g)
```

- [ ] **Step 5: Add FFT `spin_db_ref` below `combo_weighting`**

In `FFTContextual.__init__`, immediately after the `频率加权:` row:

```python
self.spin_db_ref = make_db_reference_spinbox()
fl.addRow(
    "dB 参考:",
    _fit_field(self.spin_db_ref, max_width=_SHORT_FIELD_MAX_WIDTH),
)
```

Update FFT params:

```python
# in _collect_preset/current params payloads
db_reference=self.spin_db_ref.value()
```

Update `apply_params` and `_apply_preset_values`:

```python
if 'db_reference' in d:
    try:
        self.spin_db_ref.setValue(float(d['db_reference']))
    except (TypeError, ValueError):
        pass
```

- [ ] **Step 6: Add Order `spin_db_ref` below `combo_weighting`**

In `OrderContextual.__init__`, immediately after the `频率加权:` row:

```python
self.spin_db_ref = make_db_reference_spinbox()
fl.addRow(
    "dB 参考:",
    _fit_field(self.spin_db_ref, max_width=_SHORT_FIELD_MAX_WIDTH),
)
```

Update `_collect_preset`, `get_params`, and `current_params` to include:

```python
db_reference=self.spin_db_ref.value()
```

Update `apply_params` and `_apply_preset_values` with the same guarded setter
as FFT.

- [ ] **Step 7: Run placement and existing inspector tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_inspector.py::test_db_reference_sits_below_weighting_in_all_analysis_contexts \
  tests/ui/test_inspector.py::test_fft_time_no_standalone_amplitude_group \
  tests/ui/test_inspector.py::test_fft_time_param_tooltips \
  tests/ui/test_inspector.py::test_fft_time_axis_labels_match_spectrogram_axes -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/ui/test_inspector.py \
  mf4_analyzer/ui/inspector_sections/_helpers.py \
  mf4_analyzer/ui/inspector_sections/contextual_fft.py \
  mf4_analyzer/ui/inspector_sections/contextual_fft_time.py \
  mf4_analyzer/ui/inspector_sections/contextual_order.py
git commit -m "feat(ui): align dB reference controls across analysis sections"
```

---

### Task 4: Apply FFT dB Reference In Line Rendering

**Files:**
- Modify: `tests/ui/test_main_window_smoke.py`
- Modify: `mf4_analyzer/ui/main_window/_fft_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`

- [ ] **Step 1: Add FFT cached-render dB reference test**

Add near existing FFT smoke tests:

```python
def test_fft_entry_from_cache_uses_db_reference(monkeypatch, qapp):
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    freq = np.array([10.0, 20.0])
    amp = np.array([1.0, 10.0])

    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_params",
        lambda: {"amp_y": "dB", "db_reference": 1.0},
    )
    monkeypatch.setattr(win, "_file_display_name", lambda fid: str(fid))
    monkeypatch.setattr(
        win,
        "_fft_trace_for_source",
        lambda fid, ch, time_range=None: (None, None),
    )

    entry = win._fft_entry_from_cache((freq, amp, None), "f1", "sig", "#2563eb")

    np.testing.assert_allclose(entry["amp"], np.array([0.0, 20.0]), atol=1e-6)
    np.testing.assert_allclose(entry["amp_for_xlim"], amp)
```

- [ ] **Step 2: Add FFT single-render helper test**

Add a direct helper-level assertion so the fresh compute path can reuse the
same transform:

```python
def test_fft_amplitude_to_db_uses_reference():
    import numpy as np
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

    out = FFTMixin._amplitude_to_db(np.array([1.0, 10.0]), 1.0)
    np.testing.assert_allclose(out, np.array([0.0, 20.0]), atol=1e-6)
```

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py::test_fft_entry_from_cache_uses_db_reference \
  tests/ui/test_main_window_smoke.py::test_fft_amplitude_to_db_uses_reference -q
```

Expected: FAIL while `_amplitude_to_db` is absent and cached render uses
`amp / amp.max()`.

- [ ] **Step 4: Add a shared FFT display helper**

In `FFT Mixin` add:

```python
@staticmethod
def _amplitude_to_db(amp, reference):
    arr = np.asarray(amp, dtype=float)
    ref = max(float(reference), 1e-12)
    return 20.0 * np.log10(np.clip(arr, 1e-12, None) / ref)
```

- [ ] **Step 5: Use the helper in fresh and cached FFT rendering**

In `_do_fft_single()` replace:

```python
amp_disp = 20 * np.log10(
    np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12)
)
```

with:

```python
amp_disp = self._amplitude_to_db(
    amp, fft_params.get('db_reference', 1.0)
)
```

In `window.py::_fft_entry_from_cache()`, replace the same relative-max formula
with:

```python
amp_disp = self._amplitude_to_db(
    amp, p.get('db_reference', 1.0)
)
```

- [ ] **Step 6: Ensure render signature includes dB reference**

In `window.py::_fft_render_signature()`, include:

```python
db_reference = self.inspector.fft_ctx.current_params().get('db_reference', 1.0)
return (sources, tuple(sorted(params.items())), range_sig, amp_y, float(db_reference))
```

Do not add `db_reference` to `_fft_compute_cache_params`; it is display-only.

- [ ] **Step 7: Run FFT smoke tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py::test_fft_entry_from_cache_uses_db_reference \
  tests/ui/test_main_window_smoke.py::test_fft_amplitude_to_db_uses_reference \
  tests/ui/test_weighting_ui.py::test_fft_cache_params_include_weighting -q
```

Expected: PASS; cache key test still proves compute params include weighting
but not display-only dB reference.

- [ ] **Step 8: Commit**

```bash
git add tests/ui/test_main_window_smoke.py \
  mf4_analyzer/ui/main_window/_fft_mixin.py \
  mf4_analyzer/ui/main_window/window.py
git commit -m "fix(fft): use dB reference for spectrum display"
```

---

### Task 5: Apply Order dB Reference In Heatmap Rendering

**Files:**
- Modify: `tests/ui/test_main_window_smoke.py`
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`

- [ ] **Step 1: Add Order render test**

Add a focused test using a fake canvas:

```python
def test_order_db_display_uses_db_reference(monkeypatch, qapp):
    import numpy as np
    from types import SimpleNamespace
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    captured = {}

    class Canvas:
        _amplitude_mode = None

        def plot_or_update_heatmap(self, **kwargs):
            captured.update(kwargs)

        def set_tick_density(self, *_args):
            pass

    result = SimpleNamespace(
        amplitude=np.array([[1.0, 10.0]], dtype=float),  # frames x orders
        times=np.array([0.5]),
        orders=np.array([1.0, 2.0]),
        params=SimpleNamespace(order_res=0.1),
        metadata={"coverage_start": 0.0, "coverage_end": 1.0},
    )
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "current_params",
        lambda: {
            "amplitude_mode": "Amplitude dB",
            "db_reference": 1.0,
            "z_auto": False,
            "z_floor": -40.0,
            "z_ceiling": 20.0,
            "x_auto": True,
            "y_auto": True,
        },
    )
    monkeypatch.setattr(win.inspector.top, "tick_density", lambda: (10, 10))

    win._render_order_on(Canvas(), result)

    np.testing.assert_allclose(
        captured["matrix"],
        np.array([[0.0], [20.0]]),
        atol=1e-6,
    )
    assert captured["amplitude_mode"] == "amplitude"
    assert "dB re 1" in captured["cbar_label"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py::test_order_db_display_uses_db_reference -q
```

Expected: FAIL while Order delegates dB conversion to the canvas relative-max
branch.

- [ ] **Step 3: Implement display conversion in `_render_order_on`**

In `_render_order_on`, build `matrix`, `plot_amp_mode`, and `cbar_label`
before `plot_or_update_heatmap`:

```python
matrix = result.amplitude.T
plot_amp_mode = amp_mode_token
cbar_label = 'Amplitude'
if amp_mode_token == 'amplitude_db':
    db_ref = max(float(order_params.get('db_reference', 1.0)), 1e-12)
    matrix = 20.0 * np.log10(np.clip(matrix, 1e-12, None) / db_ref)
    plot_amp_mode = 'amplitude'
    cbar_label = f'Amplitude (dB re {db_ref:g})'
```

Then pass:

```python
matrix=matrix,
cbar_label=cbar_label,
amplitude_mode=plot_amp_mode,
```

Keep `canvas._amplitude_mode = amp_mode_token` so the slice label still knows
the displayed matrix is dB.

- [ ] **Step 4: Confirm compute cache remains display-independent**

Add or inspect an assertion that `_order_compute_cache_params(...)` does not
include `db_reference`.

If adding a test, place it near existing cache-key tests:

```python
def test_order_cache_key_excludes_db_reference_display_only():
    from mf4_analyzer.ui.main_window._order_mixin import OrderMixin

    base = {
        "nfft": 1024,
        "max_order": 20,
        "order_res": 0.1,
        "time_res": 0.05,
        "samples_per_rev": 256,
        "rpm_factor": 1.0,
        "fs": 1000.0,
        "weighting": "A",
    }
    k1 = OrderMixin._order_compute_cache_params(dict(base, db_reference=1.0), ("f", "rpm"), None)
    k2 = OrderMixin._order_compute_cache_params(dict(base, db_reference=2.0), ("f", "rpm"), None)
    assert k1 == k2
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py::test_order_db_display_uses_db_reference \
  tests/ui/test_weighting_ui.py::test_analysis_cache_keys_include_weighting_for_view_switch_paths -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/ui/test_main_window_smoke.py \
  mf4_analyzer/ui/main_window/_order_mixin.py
git commit -m "fix(order): use dB reference for heatmap display"
```

---

### Task 6: Prove Home / View All / Linked Zoom Do Not Pollute Params

**Files:**
- Modify: `tests/ui/test_pg_heatmap_canvas.py`
- Modify: `tests/ui/test_analysis_section_page.py`

- [ ] **Step 1: Add heatmap Home boundary test**

In `tests/ui/test_pg_heatmap_canvas.py`, add:

```python
def test_heatmap_view_all_does_not_emit_levels_changed(qapp):
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    c = PgHeatmapCanvas()
    seen = []
    c.levels_changed.connect(lambda *_args: seen.append(True))
    c.plot_or_update_heatmap(
        np.arange(9, dtype=float).reshape(3, 3),
        x_extent=(0.0, 3.0),
        y_extent=(0.0, 3.0),
        z_auto=False,
        z_floor=0.0,
        z_ceiling=8.0,
    )

    c.reset_view_to_data_extents()

    assert seen == []
```

- [ ] **Step 2: Add linked zoom boundary test**

In `tests/ui/test_analysis_section_page.py`, use the existing `page` fixture
defined in that file and add:

```python
def test_heatmap_set_linked_does_not_emit_levels_changed(page):
    page.enter_split()
    seen = []
    for idx in range(page.pane_count()):
        page.pane_canvas(idx).levels_changed.connect(lambda *_args: seen.append(True))

    page.set_linked(True)
    page.set_linked(False)

    assert seen == []
```

- [ ] **Step 3: Run boundary tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_view_all_does_not_emit_levels_changed \
  tests/ui/test_analysis_section_page.py::test_heatmap_set_linked_does_not_emit_levels_changed -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/ui/test_pg_heatmap_canvas.py tests/ui/test_analysis_section_page.py
git commit -m "test(ui): guard heatmap view resets from param pollution"
```

---

### Task 7: Focused Verification Bundle

**Files:**
- No source changes unless failures expose a narrow bug in the files above.

- [ ] **Step 1: Run inspector and weighting focused tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_weighting_ui.py \
  tests/ui/test_inspector.py::test_db_reference_sits_below_weighting_in_all_analysis_contexts \
  tests/ui/test_inspector.py::test_fft_time_no_standalone_amplitude_group \
  tests/ui/test_inspector.py::test_fft_time_param_tooltips -q
```

Expected: PASS.

- [ ] **Step 2: Run render/cache focused tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_main_window_smoke.py::test_fft_db_display_uses_db_reference \
  tests/ui/test_main_window_smoke.py::test_order_db_display_uses_db_reference \
  tests/ui/test_main_window_smoke.py::test_plot_fft_entries_auto_xlim_uses_energy_band_and_manual_stays_fixed \
  tests/ui/test_weighting_ui.py::test_analysis_cache_keys_include_weighting_for_view_switch_paths -q
```

Expected: PASS.

- [ ] **Step 3: Run heatmap boundary tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_view_all_does_not_emit_levels_changed \
  tests/ui/test_analysis_section_page.py::test_heatmap_set_linked_does_not_emit_levels_changed -q
```

Expected: PASS.

- [ ] **Step 4: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no whitespace errors in touched files. If unrelated pre-existing
dirty files cause output, report them separately and do not rewrite them.

- [ ] **Step 5: Inspect changed scope before final commit**

Run:

```bash
git status --short
git diff --stat
```

Expected: only files listed in this plan are staged for the final implementation
commit. Do not stage `TraceLab-使用说明.html`, `docs/head-hdf-ui-mockup.html`,
`output/`, or unrelated `tests/ui/test_pg_line_canvas.py` hunks.

- [ ] **Step 6: Final commit if implementation is complete**

```bash
git add mf4_analyzer/ui/inspector_sections/_helpers.py \
  mf4_analyzer/ui/inspector_sections/contextual_fft.py \
  mf4_analyzer/ui/inspector_sections/contextual_fft_time.py \
  mf4_analyzer/ui/inspector_sections/contextual_order.py \
  mf4_analyzer/ui/main_window/_fft_mixin.py \
  mf4_analyzer/ui/main_window/_order_mixin.py \
  mf4_analyzer/ui/main_window/window.py \
  tests/ui/test_weighting_ui.py \
  tests/ui/test_inspector.py \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_pg_heatmap_canvas.py \
  tests/ui/test_analysis_section_page.py
git commit -m "fix(analysis): stabilize weighting and dB reference display"
```

If earlier task commits were already created, skip this final squashed commit
and leave the branch as a clear multi-commit series.

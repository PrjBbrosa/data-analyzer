# Heatmap Hover, Slice, and dB Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make heatmap hover non-intrusive, keep bottom slice curves aligned with right-side coordinate ranges, and make FFT dB auto Y ranges useful for inspection.

**Architecture:** Keep changes inside the existing canvas layer. `PgHeatmapCanvas` owns heatmap hover and slice-domain behavior. `PgLineCanvas` owns FFT line Y auto range. Existing Order/FFT heatmap dB color logic remains the reference for robust dB span constants.

**Tech Stack:** Python, NumPy, PyQt5, pyqtgraph, pytest with `QT_QPA_PLATFORM=offscreen`.

---

### Task 1: Suppress Passive Heatmap XYZ Readout

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Write failing tests**

In `tests/ui/test_pg_heatmap_canvas.py`, change the hover test to expect no XYZ:

```python
def test_heatmap_hover_does_not_emit_xyz_readout(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_hover(sp)
    assert received == ['']
    c.hide()
    c.deleteLater()
```

In `tests/ui/test_chart_stack.py`, change the direct heatmap signal test:

```python
def test_heatmap_cursor_info_does_not_show_pill_in_fft_time_or_order(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)

    for mode, canvas in (
        ('fft_time', cs.canvas_fft_time),
        ('order', cs.canvas_order),
    ):
        cs.set_mode(mode)
        canvas.cursor_info.emit("<div>X=1 s</div><div>Y=2 Hz</div><div>Z=3 dB</div>")
        assert not cs.cursor_pill_visible()
```

- [ ] **Step 2: Verify red**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_heatmap_cursor_info_does_not_show_pill_in_fft_time_or_order \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_hover_does_not_emit_xyz_readout \
  -q
```

Expected: both fail under current behavior.

- [ ] **Step 3: Implement minimal fix**

In `PgHeatmapCanvas._on_scene_hover()`, emit `''` and return. In
`ChartStack._connect_analysis_card_signals()`, stop wiring heatmap
`cursor_info` signals to `_on_cursor_info`; time-domain cursor behavior stays
unchanged.

- [ ] **Step 4: Verify green**

Run the two tests again and expect pass.

### Task 2: Clip Slice Curves to Main Heatmap Visible Domain

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Write failing tests**

Add three tests:

```python
def test_x_slice_uses_visible_frequency_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', z_auto=True,
        y_auto=False, y_min=100.0, y_max=300.0,
    )
    qapp.processEvents()

    assert c._slice_dir == 'x'
    xs, _ = c._slice_curve.getData()
    assert np.nanmin(xs) >= 100.0 - 1e-6
    assert np.nanmax(xs) <= 300.0 + 1e-6
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    assert sx0 == pytest.approx(100.0, abs=1e-6)
    assert sx1 == pytest.approx(300.0, abs=1e-6)
    c.hide()
    c.deleteLater()
```

```python
def test_y_slice_uses_visible_time_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', z_auto=True,
        x_auto=False, x_min=0.5, x_max=1.5,
    )
    c.set_slice_direction('y')
    qapp.processEvents()

    xs, _ = c._slice_curve.getData()
    assert np.nanmin(xs) >= 0.5 - 1e-6
    assert np.nanmax(xs) <= 1.5 + 1e-6
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    assert sx0 == pytest.approx(0.5, abs=1e-6)
    assert sx1 == pytest.approx(1.5, abs=1e-6)
    c.hide()
    c.deleteLater()
```

```python
def test_order_x_slice_uses_visible_order_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    times = np.linspace(0.0, 4.0, 5)
    orders = np.array([0.0, 1.0, 2.0, 5.0, 10.0])
    matrix = np.arange(orders.size * times.size, dtype=float).reshape(orders.size, times.size)
    c.plot_or_update_heatmap(
        matrix, (0.0, 4.0), (0.0, 10.0),
        x_label='Time (s)', y_label='Order',
        x_coords=times, y_coords=orders,
        y_auto=False, y_min=1.0, y_max=5.0,
    )
    qapp.processEvents()

    xs, _ = c._slice_curve.getData()
    assert np.nanmin(xs) >= 1.0 - 1e-6
    assert np.nanmax(xs) <= 5.0 + 1e-6
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    assert sx0 == pytest.approx(1.0, abs=1e-6)
    assert sx1 == pytest.approx(5.0, abs=1e-6)
    c.hide()
    c.deleteLater()
```

- [ ] **Step 2: Verify red**

Run the three tests and expect failure because slice data/range still spans the
full coordinate array.

- [ ] **Step 3: Implement visible-domain helper**

Add helpers in `PgHeatmapCanvas`:

- `_main_view_range(axis)` returns current main `ViewBox` X or Y range clamped
  to `_extents`;
- `_slice_visible_mask(coords, lo, hi)` returns finite points inside the range,
  falling back to the nearest point when no coordinate center is inside;
- `_set_slice_x_range(lo, hi, coords)` pins the bottom slice X range with
  `padding=0`.

Use them in `_apply_slice()`:

- `y` slice: filter `xc` and `m[idx, :]` by current visible X range.
- `x` slice: filter `yc` and `m[:, idx]` by current visible Y range.

- [ ] **Step 4: Verify green**

Run the three tests plus existing slice tests:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py -k "slice and not render" -q
```

### Task 3: Add dB-Aware FFT Line Auto Y Range

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_db_auto_y_range_uses_robust_visible_span(qapp):
    c = PgLineCanvas()
    try:
        c.resize(640, 480)
        c.show()
        qapp.processEvents()
        freq = np.linspace(0.0, 500.0, 501)
        amp = np.full_like(freq, -110.0)
        amp[(freq >= 80.0) & (freq <= 220.0)] = -24.0
        amp[np.argmin(np.abs(freq - 140.0))] = -12.0
        entry = {
            'label': 'db',
            'color': '#2563eb',
            'freq': freq,
            'amp': amp,
            'time': np.linspace(0.0, 1.0, 64),
            'signal': np.zeros(64),
        }
        c.plot_spectra([entry], xlim=(0.0, 300.0), amp_label='Amplitude (dB)', title='FFT')
        qapp.processEvents()

        _x, (y0, y1) = c._plot_amp.vb.viewRange()
        assert y0 > -60.0
        assert y0 <= -42.0
        assert y1 >= -12.0
        assert y1 < 5.0
    finally:
        c.deleteLater()
```

```python
def test_linear_auto_y_range_still_uses_pyqtgraph_autorange(qapp):
    c = PgLineCanvas()
    try:
        c.resize(640, 480)
        c.show()
        qapp.processEvents()
        entry = _entry()
        c.plot_spectra([entry], xlim=(0.0, 500.0), amp_label='Amplitude', title='FFT')
        qapp.processEvents()

        assert c._last_yrange is None
        assert bool(c._plot_amp.vb.autoRangeEnabled()[1])
    finally:
        c.deleteLater()
```

- [ ] **Step 2: Verify red**

Run those two tests. The dB test should fail because pyqtgraph includes the
deep -110 dB floor.

- [ ] **Step 3: Implement dB helper**

In `line_canvas.py`, import `_AUTO_CEILING_PCT` and `_AUTO_SPAN_DB` from
`heatmap_canvas`. Add a private helper that gathers finite visible dB values
from entries and computes `(floor, top)`:

- ceiling = percentile(values, `_AUTO_CEILING_PCT`);
- top = max(ceiling, nanmax(values));
- bottom = ceiling - `_AUTO_SPAN_DB`;
- if top <= bottom, widen by 1 dB.

In `plot_spectra()`, when `manual_y` is false and the label contains `dB`, set
that Y range with `padding=0` instead of enabling pyqtgraph Y autorange.

- [ ] **Step 4: Verify green**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py::test_db_auto_y_range_uses_robust_visible_span \
  tests/ui/test_pg_line_canvas.py::test_linear_auto_y_range_still_uses_pyqtgraph_autorange \
  -q
```

### Task 4: Focused Regression Run and Lesson Gate

**Files:**
- No source changes unless a test exposes a real regression.

- [ ] **Step 1: Run focused suites**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_chart_stack.py -q
```

- [ ] **Step 2: Run diff and lesson checks**

```bash
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

- [ ] **Step 3: Review changed-file scope**

```bash
git diff --stat
git status --short
```

Confirm only the intended spec, plan, canvas, and test files were touched by
this task.

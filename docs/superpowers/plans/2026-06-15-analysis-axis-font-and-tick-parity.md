# Analysis Axis Font And Tick Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Analysis pyqtgraph canvases use the same axis text size and comparable tick-density behavior as TimeDomain, so FFT / FFT-vs-Time / Order charts stay readable in narrow split panes.

**Architecture:** Use the existing pyqtgraph chart-font helper as the single source of truth for Analysis axis text. Keep the current FFT two-row design and heatmap slice design; only apply TimeDomain's explicit 9pt axis font, move Analysis X ticks to the same target-count-and-fit strategy where practical, and add narrow-pane regression checks. Do not add new user controls or change signal/FFT/spectrogram data semantics.

**Tech Stack:** Python 3.12, PyQt5, pyqtgraph 0.14, pytest + pytest-qt, offscreen Qt verification.

**Execution Status (2026-06-15):** Implemented in the local commit series through `59ccb60` (`f32c7de`, `4b572ac`, `3c376e6`, `59ccb60`). Final focused verification: `tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -q` -> `176 passed`; `git diff --check` clean; lessons gate clean. This file preserves the implementation plan and acceptance criteria used for the work.

---

## Current Evidence

Observed by a local offscreen probe on 2026-06-15:

- `TimeDomainCanvasPG` axes use explicit `PingFang SC 9pt` via `_apply_pg_axis_font`.
- `PgLineCanvas` FFT axes currently report `tickFont=None` and label font `.AppleSystemUIFont 12pt` when constructed directly.
- `TimeDomainCanvasPG` tightens `GraphicsLayoutWidget` layout contents and spacing to `2px`; `PgLineCanvas` keeps pyqtgraph defaults (`9px` contents, `8px` horizontal spacing) plus the intentional `18px` split-row gap.
- FFT time-preview Y ticks are already pinned by `_time_divisions`; spectrum/heatmap axes mostly use raw pyqtgraph `setTickDensity`.

The implementation should treat line numbers in this plan as hints only. The worktree currently has active edits in `mf4_analyzer/ui/pg_canvas/line_canvas.py`, `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`, and related tests, so execution must re-read the current files before patching.

## File Structure

- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
  - Apply the shared 9pt pyqtgraph axis font inside `_apply_neutral_axis_frame`.
  - Apply the same font to colorbar axes created/updated by `_ensure_colorbar`.
  - Optionally expose a small Analysis tick helper here only if it remains local and avoids circular imports.
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
  - Apply the shared axis font to FFT time-preview aux right axes.
  - Replace plain X-axis `setTickDensity` on line-canvas bottom axes with a target-count-and-fit tick helper matching TimeDomain's behavior.
  - Keep `_time_divisions` for preview Y grid alignment.
- Modify: `tests/ui/test_pg_line_canvas.py`
  - Add font parity tests for FFT top/bottom axes and aux right axes.
  - Add narrow-width X tick-fit tests.
- Modify: `tests/ui/test_pg_heatmap_canvas.py`
  - Add font parity tests for main heatmap axes, slice axes, and colorbar axis.
  - Add narrow-width X tick-fit tests if the helper is applied to heatmap axes.

Do not modify:

- `mf4_analyzer/signal/fft.py`
- `mf4_analyzer/signal/spectrogram.py`
- Inspector controls or tick-density UI copy
- TimeDomain behavior except as a read-only reference

---

## Task 1: Apply TimeDomain Axis Font To Analysis Canvases

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Write failing line-canvas font parity tests**

Add these tests near the existing axis/frame tests in `tests/ui/test_pg_line_canvas.py`:

```python
def _axis_font_family_size(axis):
    font = axis.style.get("tickFont")
    label = getattr(axis, "label", None)
    label_font = label.font() if label is not None else None
    return (
        font.family() if font is not None else None,
        font.pointSizeF() if font is not None else None,
        label_font.family() if label_font is not None else None,
        label_font.pointSizeF() if label_font is not None else None,
    )


def test_fft_line_canvas_axes_use_time_domain_chart_font(canvas):
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    expected = _pg_chart_font(9)
    canvas.plot_spectra(
        [_entry()],
        xlim=(0.0, 500.0),
        amp_label="Amplitude",
        title="FFT",
    )

    for plot in (canvas._plot_amp, canvas._plot_time):
        for side in ("left", "bottom"):
            family, size, label_family, label_size = _axis_font_family_size(
                plot.getAxis(side)
            )
            assert family == expected.family()
            assert size == pytest.approx(9.0)
            assert label_family == expected.family()
            assert label_size == pytest.approx(9.0)


def test_fft_time_preview_aux_axes_use_chart_font(canvas):
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    expected = _pg_chart_font(9)
    canvas.plot_spectra(
        [_entry("a", "#2563eb"), _entry("b", "#dc2626")],
        xlim=(0.0, 500.0),
        amp_label="Amplitude",
        title="FFT",
    )

    assert canvas._time_overlay_axes
    for axis in canvas._time_overlay_axes:
        family, size, label_family, label_size = _axis_font_family_size(axis)
        assert family == expected.family()
        assert size == pytest.approx(9.0)
        assert label_family == expected.family()
        assert label_size == pytest.approx(9.0)
```

- [ ] **Step 2: Write failing heatmap font parity tests**

Add these tests near the existing tick-density tests in `tests/ui/test_pg_heatmap_canvas.py`:

```python
def _axis_font_family_size(axis):
    font = axis.style.get("tickFont")
    label = getattr(axis, "label", None)
    label_font = label.font() if label is not None else None
    return (
        font.family() if font is not None else None,
        font.pointSizeF() if font is not None else None,
        label_font.family() if label_font is not None else None,
        label_font.pointSizeF() if label_font is not None else None,
    )


def test_heatmap_axes_use_time_domain_chart_font(canvas):
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    expected = _pg_chart_font(9)
    for side in ("left", "bottom"):
        family, size, label_family, label_size = _axis_font_family_size(
            canvas._plot.getAxis(side)
        )
        assert family == expected.family()
        assert size == pytest.approx(9.0)
        assert label_family == expected.family()
        assert label_size == pytest.approx(9.0)


def test_heatmap_slice_and_colorbar_axes_use_chart_font(qapp):
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    expected = _pg_chart_font(9)
    c = PgHeatmapCanvas(with_slice=True)
    try:
        # Force colorbar creation through the public render path used by tests.
        x = np.linspace(0.0, 1.0, 5)
        y = np.linspace(10.0, 50.0, 4)
        c.plot_matrix(
            _mat(),
            x=x,
            y=y,
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c.update_slice(0.5, direction="x")

        axes = [
            c._slice_plot.getAxis("left"),
            c._slice_plot.getAxis("bottom"),
            c._cbar.getAxis("left"),
        ]
        for axis in axes:
            family, size, label_family, label_size = _axis_font_family_size(axis)
            assert family == expected.family()
            assert size == pytest.approx(9.0)
            assert label_family == expected.family()
            assert label_size == pytest.approx(9.0)
    finally:
        c.deleteLater()
```

If `plot_matrix` is not the current public render method in the active checkout, re-read `tests/ui/test_pg_heatmap_canvas.py` and use the same render helper already used by the neighboring colorbar-label tests. Do not invent a new render route.

- [ ] **Step 3: Run the failing tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py::test_fft_line_canvas_axes_use_time_domain_chart_font \
  tests/ui/test_pg_line_canvas.py::test_fft_time_preview_aux_axes_use_chart_font \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_axes_use_time_domain_chart_font \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_slice_and_colorbar_axes_use_chart_font \
  -q
```

Expected before implementation: FAIL because Analysis axes do not consistently set `tickFont` and label font to `_pg_chart_font(9)`.

- [ ] **Step 4: Apply font helper inside `_apply_neutral_axis_frame`**

In `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`, import the existing helper:

```python
from mf4_analyzer.ui.pg_canvas.fonts import _apply_pg_axis_font
```

Inside `_apply_neutral_axis_frame(plot)`, after `axis = plot.getAxis(side)` and before/after `axis.setPen(frame_pen)`, apply the font to every axis:

```python
        _apply_pg_axis_font(axis)
```

Keep the existing frame-pen, `enableAutoSIPrefix(False)`, top/right `showValues=False`, and `maxTickLevel=0` behavior unchanged.

- [ ] **Step 5: Apply font helper to colorbar axis**

In `_ensure_colorbar`, after creating the colorbar and after updating its label, apply the font:

```python
            _apply_pg_axis_font(self._cbar.getAxis("left"))
```

For the existing-colorbar branch, keep `self._cbar.setColorMap(cm)` and `self._cbar.getAxis("left").setLabel(cbar_label)`, then call `_apply_pg_axis_font(...)` again so label font stays pinned after text replacement.

- [ ] **Step 6: Apply font helper to FFT preview aux right axes**

In `mf4_analyzer/ui/pg_canvas/line_canvas.py`, import the helper:

```python
from .fonts import _apply_pg_axis_font
```

In `_add_time_overlay_axis`, after `axis = pg.AxisItem('right')` and before/after setting pens:

```python
        _apply_pg_axis_font(axis)
```

Do not change the existing neutral frame line or colored tick text behavior.

- [ ] **Step 7: Re-run font tests**

Run the same command from Step 3.

Expected after implementation: PASS.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/line_canvas.py \
  tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "fix(analysis): match TimeDomain axis font sizing"
```

---

## Task 2: Make Analysis X Tick Counts Fit Like TimeDomain

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` only if sharing a helper there is the narrowest local option
- Test: `tests/ui/test_pg_line_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

The current TimeDomain X tick path uses a target count and drops labels that do not fit in the available axis width. Analysis line/heatmap axes mostly call `setTickDensity`, which can produce visually inconsistent ticks in narrow panes. This task should port the TimeDomain target-count behavior to Analysis bottom axes without changing Y graticule behavior.

- [ ] **Step 1: Write failing line-canvas narrow X tick test**

Add to `tests/ui/test_pg_line_canvas.py`:

```python
def _bottom_tick_labels(axis):
    levels = getattr(axis, "_tickLevels", None)
    if not levels:
        return []
    return [str(label) for _value, label in levels[0]]


def test_fft_line_canvas_narrow_bottom_ticks_are_pinned_and_fit(qapp):
    c = PgLineCanvas()
    try:
        c.resize(220, 620)
        c.show()
        qapp.processEvents()
        c.plot_spectra(
            [_entry()],
            xlim=(0.0, 500.0),
            amp_label="Amplitude",
            title="FFT",
        )
        c.set_tick_density(10, 8)
        qapp.processEvents()

        for plot in (c._plot_amp, c._plot_time):
            axis = plot.getAxis("bottom")
            labels = _bottom_tick_labels(axis)
            assert 3 <= len(labels) <= 10
            assert getattr(axis, "_tickLevels", None), "bottom axis should be pinned"
    finally:
        c.deleteLater()
```

The upper bound intentionally stays loose because the exact count depends on resolved font metrics and platform font availability. The important contract is: Analysis bottom axes are pinned through a target-count fit pass, not left entirely to pyqtgraph density fallback.

- [ ] **Step 2: Write heatmap narrow X tick test**

Add to `tests/ui/test_pg_heatmap_canvas.py`:

```python
def _bottom_tick_labels(axis):
    levels = getattr(axis, "_tickLevels", None)
    if not levels:
        return []
    return [str(label) for _value, label in levels[0]]


def test_heatmap_narrow_bottom_ticks_are_pinned_and_fit(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(220, 620)
        c.show()
        qapp.processEvents()
        x = np.linspace(0.0, 30.0, 5)
        y = np.linspace(10.0, 50.0, 4)
        c.plot_matrix(
            _mat(),
            x=x,
            y=y,
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c.update_slice(0.5, direction="x")
        c.set_tick_density(10, 8)
        qapp.processEvents()

        for plot in (c._plot, c._slice_plot):
            axis = plot.getAxis("bottom")
            labels = _bottom_tick_labels(axis)
            assert 3 <= len(labels) <= 10
            assert getattr(axis, "_tickLevels", None), "bottom axis should be pinned"
    finally:
        c.deleteLater()
```

If the active heatmap test helpers use a different render method than `plot_matrix` / `update_slice`, use the existing helper from the same file.

- [ ] **Step 3: Run the failing tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py::test_fft_line_canvas_narrow_bottom_ticks_are_pinned_and_fit \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_narrow_bottom_ticks_are_pinned_and_fit \
  -q
```

Expected before implementation: FAIL because bottom axes have no pinned `_tickLevels` or use raw density-only ticks.

- [ ] **Step 4: Add an Analysis bottom-axis target tick helper**

Prefer a small local helper near `_tick_counts_to_density` in `heatmap_canvas.py`, since both Analysis canvases already import from there and this avoids touching TimeDomain internals:

```python
def _apply_target_bottom_ticks(axis, view_box, target_count: int) -> bool:
    """Pin bottom-axis ticks to a readable target count.

    Returns True when explicit ticks were applied. Returns False when geometry
    or range is not usable so callers can fall back to AxisItem density.
    """
    import math
    from PyQt5.QtGui import QFontMetrics
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    try:
        (lo, hi), _yr = view_box.viewRange()
        width = float(axis.size().width())
    except Exception:
        return False
    lo = float(lo)
    hi = float(hi)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or width <= 1.0:
        return False

    target = max(3, int(target_count))
    raw_step = (hi - lo) / max(1, target - 1)
    if not np.isfinite(raw_step) or raw_step <= 0:
        return False

    metrics = QFontMetrics(_pg_chart_font(9))
    candidates = []
    exponent = math.floor(math.log10(raw_step))
    for exp in range(exponent - 2, exponent + 4):
        scale = 10.0 ** exp
        for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
            step = factor * scale
            if step <= 0:
                continue
            start = math.ceil(lo / step) * step
            values = []
            value = start
            guard = 0
            while value <= hi + step * 1e-9 and guard < 500:
                if value >= lo - step * 1e-9:
                    values.append(0.0 if abs(value) < step * 1e-10 else float(value))
                value += step
                guard += 1
            if len(values) < 3:
                continue
            try:
                labels = axis.tickStrings(values, getattr(axis, "scale", 1.0), step)
            except Exception:
                labels = [f"{value:g}" for value in values]

            previous_right = None
            fitted = []
            for tick_value, label in zip(values, labels):
                x = (float(tick_value) - lo) / (hi - lo) * width
                text = str(label)
                try:
                    text_width = float(metrics.horizontalAdvance(text))
                except AttributeError:
                    text_width = float(metrics.width(text))
                left = x - text_width / 2.0
                right = x + text_width / 2.0
                if left < 2.0 or right > width - 2.0:
                    continue
                if previous_right is not None and left - previous_right < 10.0:
                    fitted = []
                    break
                fitted.append((float(tick_value), text))
                previous_right = right
            if len(fitted) < 3:
                continue
            candidates.append((
                abs(len(fitted) - target),
                -len(fitted),
                abs(math.log(step / raw_step)) if raw_step > 0 else 0.0,
                fitted,
            ))

    if not candidates:
        return False
    _distance, _neg_count, _nice_distance, ticks = min(candidates)
    axis.setStyle(maxTickLevel=0)
    axis.setTicks([ticks, []])
    return True
```

Keep this helper private. Do not import `TickDensityController` directly because it is backref-bound to `TimeDomainCanvasPG`.

- [ ] **Step 5: Use the helper in `PgLineCanvas.set_tick_density`**

In `PgLineCanvas.set_tick_density`, replace bottom-axis raw density-only handling with helper-first fallback:

```python
        for plot in (self._plot_amp, self._plot_time):
            bottom = plot.getAxis("bottom")
            if not _apply_target_bottom_ticks(bottom, plot.vb, x_n):
                bottom.setTicks(None)
                bottom.setStyle(maxTickLevel=0)
                bottom.setTickDensity(x_d)
```

Keep the existing top spectrum left-axis density and `_time_divisions` logic:

```python
        left = self._plot_amp.getAxis("left")
        left.setStyle(maxTickLevel=0)
        left.setTickDensity(y_d)
        self._time_divisions = max(3, min(20, y_n))
        self._reframe_time_y_to_grid()
```

- [ ] **Step 6: Use the helper in `PgHeatmapCanvas.set_tick_density`**

For each bottom axis currently receiving `setTickDensity(x_d)`, try helper-first:

```python
            if axis is bottom_axis:
                if not _apply_target_bottom_ticks(axis, plot.vb, x_n):
                    axis.setTicks(None)
                    axis.setStyle(maxTickLevel=0)
                    axis.setTickDensity(x_d)
```

Adapt to the current loop shape in `set_tick_density`. The implementation must still apply Y density to left axes and must still reach the slice subplot when `with_slice=True`.

- [ ] **Step 7: Re-run targeted tick tests**

Run the command from Step 3.

Expected after implementation: PASS.

- [ ] **Step 8: Re-run existing tick-density contract tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py::test_set_tick_density_accepts_inspector_counts \
  tests/ui/test_pg_line_canvas.py::test_set_tick_density_clamps_at_spinbox_maxima \
  tests/ui/test_pg_line_canvas.py::test_time_preview_axes_share_grid_divisions \
  tests/ui/test_pg_heatmap_canvas.py::test_set_tick_density_accepts_inspector_counts \
  tests/ui/test_pg_heatmap_canvas.py::test_set_tick_density_clamps_at_spinbox_maxima \
  tests/ui/test_pg_heatmap_canvas.py::test_set_tick_density_also_applies_to_slice_subplot \
  -q
```

Expected: PASS. If old assertions require `_tickDensity` on bottom axes, update those tests to assert the user-facing contract instead: target counts are accepted, bottom ticks are pinned when geometry is available, and fallback density is used only before geometry is realized.

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/line_canvas.py \
  tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "fix(analysis): fit bottom ticks to narrow panes"
```

---

## Task 3: Tighten Analysis Plot Layout Without Breaking Split Divider Space

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`
- Test: `tests/ui/test_pg_heatmap_canvas.py`

TimeDomain calls `self._glw.ci.setContentsMargins(2, 2, 2, 2)` and `self._glw.ci.setSpacing(2)`. Analysis currently keeps pyqtgraph's default `9px` content margins and `8px` horizontal spacing. For line/heatmap Analysis canvases, tighten outer margins and horizontal spacing while preserving the intentional vertical split gap (`_SPLIT_ROW_SPACING = 18`) for two-row canvases.

- [ ] **Step 1: Write line-canvas layout test**

Add to `tests/ui/test_pg_line_canvas.py`:

```python
def test_fft_line_canvas_uses_compact_outer_pg_layout(canvas):
    layout = canvas._glw.ci.layout
    assert layout.getContentsMargins() == pytest.approx((2.0, 2.0, 2.0, 2.0))
    assert layout.horizontalSpacing() == pytest.approx(2.0)
    # Keep the deliberate two-row divider gap; this is not TimeDomain's 2px row spacing.
    assert layout.verticalSpacing() == pytest.approx(18.0)
```

- [ ] **Step 2: Write heatmap layout tests**

Add to `tests/ui/test_pg_heatmap_canvas.py`:

```python
def test_heatmap_canvas_uses_compact_outer_pg_layout(canvas):
    layout = canvas._glw.ci.layout
    assert layout.getContentsMargins() == pytest.approx((2.0, 2.0, 2.0, 2.0))
    assert layout.horizontalSpacing() == pytest.approx(2.0)
    assert layout.verticalSpacing() == pytest.approx(2.0)


def test_heatmap_slice_canvas_preserves_split_gap(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        layout = c._glw.ci.layout
        assert layout.getContentsMargins() == pytest.approx((2.0, 2.0, 2.0, 2.0))
        assert layout.horizontalSpacing() == pytest.approx(2.0)
        assert layout.verticalSpacing() == pytest.approx(18.0)
    finally:
        c.deleteLater()
```

- [ ] **Step 3: Run failing layout tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py::test_fft_line_canvas_uses_compact_outer_pg_layout \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_canvas_uses_compact_outer_pg_layout \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_slice_canvas_preserves_split_gap \
  -q
```

Expected before implementation: FAIL with current default margins/spacings.

- [ ] **Step 4: Tighten `PgLineCanvas` layout**

In `PgLineCanvas.__init__`, immediately after creating `self._glw` and setting the background:

```python
        self._glw.ci.setContentsMargins(2, 2, 2, 2)
        self._glw.ci.setSpacing(2)
```

Keep the existing later call:

```python
            self._glw.ci.layout.setVerticalSpacing(_SPLIT_ROW_SPACING)
```

This preserves the split divider gap while removing wasted outer gutters.

- [ ] **Step 5: Tighten `PgHeatmapCanvas` layout**

In `PgHeatmapCanvas.__init__`, immediately after creating `self._glw` and setting the background:

```python
        self._glw.ci.setContentsMargins(2, 2, 2, 2)
        self._glw.ci.setSpacing(2)
```

For `with_slice=True`, keep or reassert the existing:

```python
                self._glw.ci.layout.setVerticalSpacing(_SPLIT_ROW_SPACING)
```

Do not change `_SPLIT_ROW_SPACING` itself.

- [ ] **Step 6: Re-run layout tests**

Run the command from Step 3.

Expected after implementation: PASS.

- [ ] **Step 7: Run focused split-layout regressions**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py \
  tests/ui/test_analysis_section_page.py \
  -q
```

Expected: PASS. This is important because Analysis split geometry has recently changed and the current worktree contains active split/collapse edits.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/line_canvas.py \
  tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "fix(analysis): reclaim pyqtgraph plot area in narrow panes"
```

---

## Task 4: Render-Based Verification And Final Guardrails

**Files:**
- No required source edits unless verification exposes a concrete regression.
- Optional test additions only if Task 1-3 misses a repeatable failure.

- [ ] **Step 1: Run the no-PSD regression grep**

Run:

```bash
rg -n "combo_psd_y|psd_y|_plot_psd|_psd_curves|psd_label" mf4_analyzer/ui tests
```

Expected: no live FFT PSD UI hooks are reintroduced. If matches appear, inspect each match; only old documentation or explicit negative tests are acceptable.

- [ ] **Step 2: Run the focused Analysis canvas tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py \
  tests/ui/test_analysis_section_page.py \
  tests/ui/test_chart_stack.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the FFT inspector and multiview tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_inspector.py -k fft \
  tests/ui/test_analysis_multiview_integration.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Generate a small offscreen geometry probe for before/after notes**

Run this after implementation to record current numeric evidence in the PR or final summary:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python - <<'PY'
from PyQt5.QtWidgets import QApplication
import numpy as np
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

app = QApplication.instance() or QApplication([])
t = np.linspace(0, 10, 1000)
s = 0.72 + 0.12 * np.sin(t)

td = TimeDomainCanvasPG()
td.resize(220, 620)
td.show()
td.plot_channels([("sig", True, t, s, "#0284c7", "V", "id1")], mode="overlay")
td.set_tick_density(10, 8)

fft = PgLineCanvas()
fft.resize(220, 620)
fft.show()
fft.plot_spectra(
    [{
        "freq": np.linspace(0, 100, 200),
        "amp": 0.02 + 0.003 * np.sin(np.linspace(0, 10, 200)),
        "label": "sig",
        "color": "#0284c7",
        "time": t,
        "signal": s,
    }],
    xlim=(0, 100),
    amp_label="Amplitude",
    title="FFT",
)
fft.set_tick_density(10, 8)
for _ in range(5):
    app.processEvents()

def info(name, plot, side):
    axis = plot.getAxis(side)
    font = axis.style.get("tickFont")
    levels = getattr(axis, "_tickLevels", None)
    ticks = len(levels[0]) if levels else "adaptive"
    print(name, side, font.family() if font else None, font.pointSizeF() if font else None, "ticks", ticks)

info("TimeDomain", td.axes_list[0].plot_item, "left")
info("TimeDomain", td.axes_list[0].plot_item, "bottom")
info("FFT amp", fft._plot_amp, "left")
info("FFT amp", fft._plot_amp, "bottom")
info("FFT preview", fft._plot_time, "left")
info("FFT preview", fft._plot_time, "bottom")
PY
```

Expected: TimeDomain and FFT Analysis axes both report the same explicit 9pt font. Bottom axes should report pinned tick counts where geometry is realized.

- [ ] **Step 5: Live GUI verification**

Launch the app from source, not a packaged `.app`:

```bash
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app
```

Manual checks:

- Open the same MF4 / channels used for the screenshot if available.
- Go to TimeDomain and note axis label/tick size.
- Go to FFT and compute or preview selected sources.
- In FFT split view, resize the pane narrow enough to reproduce the screenshot shape.
- Confirm `Amplitude` and numeric ticks now visually match TimeDomain scale.
- Confirm lower preview Y ticks are not visually overcrowded; if still too dense at very small heights, open a follow-up issue to cap `_time_divisions` by pixel height rather than changing this plan's scope.
- Confirm FFT-vs-Time and Order heatmap/slice axes still align and colorbar labels are not oversized.

- [ ] **Step 6: Check lesson requirement**

Run:

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

If this implementation discovers a durable new convention beyond this plan, create and promote a lesson. If it only applies existing rules from `codex-fft-spectrum-time-preview`, `codex-analysis-view-all-visual-padding`, and the visual-parity lessons, no new lesson is needed.

- [ ] **Step 7: Final commit if Task 4 added test-only guardrails**

Only commit if Step 4 produced additional source/test changes:

```bash
git add <changed-files>
git commit -m "test(analysis): guard axis readability parity"
```

---

## Self-Review Checklist

- [ ] The plan keeps the user's requested scope: axis title size, tick number size, and tick density against TimeDomain.
- [ ] No implementation step changes FFT/PSD computation, source selection, stale-spectrum behavior, or Inspector controls.
- [ ] Font work uses the existing `_apply_pg_axis_font` helper instead of creating a second font policy.
- [ ] Tick work preserves `_time_divisions` for FFT preview Y grid alignment.
- [ ] Layout work preserves `_SPLIT_ROW_SPACING = 18` where the split divider needs visible whitespace.
- [ ] Every task has a failing-test step, an implementation step, and a verification command.
- [ ] Execution instructions mention the current dirty worktree and require re-reading current files before patching.

# FFT Annotation And Result Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FFT spectrum annotations snap to the visually nearest point and keep computed FFT spectra visible after FFT-vs-Time work changes hidden FFT parameters.

**Architecture:** Reuse the TimeDomain screen-space nearest-point pattern inside `PgLineCanvas` for the FFT amplitude row. Preserve FFT results on mode re-entry by treating cache misses with an existing visible spectrum as stale-visible state instead of an empty reset.

**Tech Stack:** Python, PyQt5, pyqtgraph, pytest-qt/offscreen Qt tests.

---

### Task 1: FFT Amp Annotation Uses Screen-Space Nearest Point

**Files:**
- Modify: `tests/ui/test_pg_line_canvas.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`

- [ ] **Step 1: Write failing amp-row nearest-point test**

Add a test near the existing remark tests:

```python
def test_spectrum_remark_picks_nearest_in_screen_space(canvas, qapp):
    entry = {
        "label": "f1 · vib",
        "color": "#2563eb",
        "freq": np.array([0.0, 1.0, 2.0]),
        "amp": np.array([0.0, 100.0, 0.0]),
        "time": np.linspace(0.0, 1.0, 32),
        "signal": np.zeros(32),
    }
    canvas.plot_spectra(
        [entry],
        xlim=(0.0, 2.0),
        amp_label="Amplitude",
        title="FFT",
        y_auto=False,
        y_min=0.0,
        y_max=100.0,
    )
    canvas.resize(640, 480)
    canvas.show()
    qapp.processEvents()
    canvas.set_remark_enabled(True)

    near_peak_scene = canvas._plot_amp.vb.mapViewToScene(QPointF(1.51, 95.0))
    viewport_pos = canvas._glw.mapFromScene(near_peak_scene)
    canvas._add_remark_at_viewport_pos(viewport_pos)

    xs, ys = canvas._remarks[-1]["dot"].getData()
    assert float(xs[0]) == pytest.approx(1.0)
    assert float(ys[0]) == pytest.approx(100.0)
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_spectrum_remark_picks_nearest_in_screen_space -q
```

Expected: FAIL because the current nearest-X logic snaps to `freq=2.0` for `x=1.51`, while the scene-space nearest point is the peak at `freq=1.0`.

- [ ] **Step 3: Implement amp scene-distance helper**

Add a helper in `PgLineCanvas` that projects nearby amp candidates to scene coordinates and picks minimum squared scene distance. Call it from `_add_remark_at_viewport_pos()` for amp clicks. Keep `add_remark_at('amp', x, y)` on its existing data-coordinate behavior for tests and non-event callers.

- [ ] **Step 4: Verify amp annotation tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q -k "remark or annotation"
```

Expected: all selected tests pass.

### Task 2: Preserve Visible FFT Spectrum On Cache-Miss Re-Entry

**Files:**
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`

- [ ] **Step 1: Write failing FFT retention test**

Add an integration test after the existing section round-trip preservation test:

```python
def test_fft_single_signal_survives_fft_time_weighting_drift(two_file_win, qapp):
    win = two_file_win
    fid = list(win.files.keys())[0]
    win.navigator.set_checked_channels([])
    win.toolbar._set_mode("fft")
    qapp.processEvents()
    win._echo_combo_signal(win.inspector.fft_ctx.combo_sig, (fid, "speed"))
    qapp.processEvents()
    win.do_fft()
    qapp.processEvents()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 1

    win.toolbar._set_mode("fft_time")
    qapp.processEvents()
    win.inspector.fft_ctx.combo_weighting.setCurrentText("A")
    qapp.processEvents()
    win.toolbar._set_mode("fft")
    qapp.processEvents()
    qapp.processEvents()

    assert len(canvas._amp_curves) == 1
    assert canvas.has_result()
    assert canvas.is_spectrum_stale()
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py::test_fft_single_signal_survives_fft_time_weighting_drift -q
```

Expected: FAIL with `len(canvas._amp_curves) == 0`.

- [ ] **Step 3: Preserve existing spectrum on re-entry cache miss**

In `_enter_fft_mode()`, replace the unconditional `_refresh_fft_time_preview()` fallback with:

```python
canvas = self.chart_stack.page_fft.pane_canvas(
    self.chart_stack.page_fft.focused_index()
)
if getattr(canvas, "has_result", lambda: False)():
    self._refresh_fft_time_preview(clear_spectrum=False)
else:
    self._refresh_fft_time_preview()
```

This keeps the visible result and marks it stale via the existing `clear_spectrum=False` behavior.

- [ ] **Step 4: Verify FFT retention tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -q -k "fft_section_switch_away_and_back_preserves_spectrum or fft_single_signal_survives_fft_time_weighting_drift"
```

Expected: both tests pass.

### Task 3: Focused Regression Sweep

**Files:**
- Test only.

- [ ] **Step 1: Run focused UI tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_analysis_multiview_integration.py -q
```

Expected: both files pass.

- [ ] **Step 2: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Review changed-file scope**

Run:

```bash
git status --short
git diff --stat
```

Expected: only this lane's spec/plan plus targeted FFT line-canvas/main-window/test changes are new for this task; pre-existing unrelated work remains untouched.

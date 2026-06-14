# Analysis Interaction — Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three issues found reviewing the FFT/heatmap polish batch: (A) the
time-preview ViewBox swallows the toolbar's Zoom mode, (B) divider
drag/reset/collapse run single-pane slice alignment that fights split panes, and
(C) the chart-shortcut tests are stale + Alt view-switching is time-only +
chart_stack tests cascade teardown errors.

**Architecture:** Surgical edits to `line_canvas.py` (A), `heatmap_canvas.py`
(B), `main_window.py` + `test_chart_stack.py` (C). No new modules. Slice
alignment ownership clarified via a `_split_aligned` flag the page sets.

**Tech Stack:** PyQt5 + pyqtgraph, pytest / pytest-qt, offscreen Qt.

Design spec: `docs/superpowers/specs/2026-06-14-analysis-interaction-review-fixes-design.md`

Test runner prefix (offscreen):
`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

---

## Task A: Time-preview left-drag respects Pan/Zoom mode

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py` (`_TimePreviewViewBox.mouseDragEvent`, `PgLineCanvas.select_time_region`)
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: Write the failing tests**

Add near the other `_plot_time` tests in `tests/ui/test_pg_line_canvas.py`:

```python
class _FakeDrag:
    def __init__(self, button):
        self._b = button
    def button(self):
        return self._b
    def buttonDownPos(self):
        return QPointF(0.0, 0.0)
    def pos(self):
        return QPointF(10.0, 0.0)
    def accept(self):
        pass


def test_time_preview_zoom_mode_left_drag_does_not_frame_select(canvas, qapp, monkeypatch):
    """In box-zoom (RectMode) a left-drag on the time preview must fall through
    to super() (box-zoom), NOT frame-select the FFT range."""
    import pyqtgraph as pg
    from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox
    canvas.plot_time_preview([_entry()], title='t')
    canvas.show(); qapp.processEvents()
    vb = canvas._plot_time.vb
    vb.setMouseMode(pg.ViewBox.RectMode)
    selected = []
    monkeypatch.setattr(canvas, 'select_time_region',
                        lambda *a: selected.append(a))
    superseded = []
    monkeypatch.setattr(_ModifierWheelViewBox, 'mouseDragEvent',
                        lambda self, ev, axis=None: superseded.append(True))
    vb.mouseDragEvent(_FakeDrag(Qt.LeftButton))
    assert selected == []          # no frame-select while zoom mode is active
    assert superseded == [True]    # delegated to super → box-zoom
    canvas.hide()


def test_time_preview_pan_mode_left_drag_frame_selects(canvas, qapp, monkeypatch):
    """In pan mode (default) a left-drag frame-selects the FFT time window."""
    import pyqtgraph as pg
    canvas.plot_time_preview([_entry()], title='t')
    canvas.show(); qapp.processEvents()
    vb = canvas._plot_time.vb
    vb.setMouseMode(pg.ViewBox.PanMode)
    selected = []
    monkeypatch.setattr(canvas, 'select_time_region',
                        lambda *a: selected.append(a))
    vb.mouseDragEvent(_FakeDrag(Qt.LeftButton))
    assert len(selected) == 1
    canvas.hide()


def test_select_time_region_hides_zero_width(canvas):
    """A zero/negative-width selection must not show a phantom region."""
    canvas.plot_time_preview([_entry()], title='t')
    canvas.select_time_region(0.3, 0.3)
    assert not canvas._time_region.isVisible()
    canvas.select_time_region(0.2, 0.6)
    assert canvas._time_region.isVisible()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_time_preview_zoom_mode_left_drag_does_not_frame_select tests/ui/test_pg_line_canvas.py::test_select_time_region_hides_zero_width -q
```
Expected: `test_time_preview_zoom_mode_left_drag_does_not_frame_select` FAILS
(`selected` is non-empty — RectMode still frame-selects), and
`test_select_time_region_hides_zero_width` FAILS (region shown at zero width).

- [ ] **Step 3: Gate frame-select on non-RectMode**

In `_TimePreviewViewBox.mouseDragEvent`, replace the body:

```python
    def mouseDragEvent(self, ev, axis=None):
        is_rect = self.state.get("mouseMode") == pg.ViewBox.RectMode
        if ev.button() == Qt.LeftButton and axis is None and not is_rect:
            # Pan-mode left-drag frames a FFT time window instead of panning.
            # In RectMode (toolbar Zoom) we fall through to super() so box-zoom
            # still works; axis drags + other buttons also fall through.
            ev.accept()
            p0 = self.mapToView(ev.buttonDownPos())
            p1 = self.mapToView(ev.pos())
            self.build_region_from_data(float(p0.x()), float(p1.x()))
            return
        super().mouseDragEvent(ev, axis=axis)
```

(`pg` is already imported in `line_canvas.py`.)

- [ ] **Step 4: Only show the region when it has positive width**

In `PgLineCanvas.select_time_region`, change the unconditional
`self._time_region.setVisible(True)` so visibility tracks `hi > lo`:

```python
    def select_time_region(self, t0, t1):
        """Set the FFT time-window selection to [t0, t1] (no view pan) and emit
        the range so the FFT inspector picks it up."""
        lo, hi = (float(t0), float(t1)) if t0 <= t1 else (float(t1), float(t0))
        self._time_region.blockSignals(True)
        try:
            self._time_region.setRegion((lo, hi))
        finally:
            self._time_region.blockSignals(False)
        self._time_region.setVisible(hi > lo)
        if hi > lo:
            self.time_preview_range_changed.emit(lo, hi)
```

- [ ] **Step 5: Run the new + existing time-region tests**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q
```
Expected: all pass (new three + the existing region/drag tests).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(fft): time-preview left-drag only frame-selects in pan mode, box-zoom survives"
```

---

## Task B: Divider drag/reset/collapse delegate slice align to the page in split mode

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` (`__init__`, `apply_split_layout_alignment`, `reset_split_layout_alignment`, `_on_split_drag_finished`, `_on_split_reset`, `_on_collapse_changed`)
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_pg_heatmap_canvas.py`:

```python
def test_split_drag_finish_self_aligns_single_but_delegates_in_split(qapp, monkeypatch):
    """Single pane (standalone): drag-finish self-aligns the slice. Split mode
    (page-managed): drag-finish must NOT run single-pane align (it fights the
    page) but must still emit layout_geometry_changed so the page re-syncs."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(600, 480); c.show(); qapp.processEvents()
    align = []
    geo = []
    monkeypatch.setattr(c, '_align_slice_to_main', lambda: align.append(1))
    c.layout_geometry_changed.connect(lambda: geo.append(1))

    # Single-pane / standalone (default): self-aligns + notifies.
    assert c._split_aligned is False
    c._on_split_drag_finished()
    assert align == [1]
    assert geo == [1]

    # Page took over split alignment → flag True; skip self-align, still notify.
    align.clear(); geo.clear()
    c.apply_split_layout_alignment(left_axis_width=40.0)
    assert c._split_aligned is True
    c._on_split_drag_finished()
    assert align == []
    assert geo == [1]

    # Page reset to single → flag False again; self-align resumes.
    align.clear(); geo.clear()
    c.reset_split_layout_alignment()
    assert c._split_aligned is False
    c._on_split_drag_finished()
    assert align == [1]
    c.hide(); c.deleteLater()
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_split_drag_finish_self_aligns_single_but_delegates_in_split -q
```
Expected: FAIL — `c._split_aligned` does not exist (AttributeError), and
`_on_split_drag_finished` does not emit `layout_geometry_changed`.

- [ ] **Step 3: Add the `_split_aligned` flag**

In `PgHeatmapCanvas.__init__`, in the `with_slice` branch (near
`self._bottom_split_default = 140.0`) AND the `else` branch, initialize:

```python
        self._split_aligned = False
```

(Put it alongside the existing `_bottom_split_*` initialization so both the
`with_slice` and no-slice constructors define it.)

- [ ] **Step 4: Set the flag from the page-driven alignment entry points**

At the top of `apply_split_layout_alignment(...)` add:

```python
        self._split_aligned = True
```

At the top of `reset_split_layout_alignment(...)` add:

```python
        self._split_aligned = False
```

- [ ] **Step 5: Gate the self-align in the three handlers + emit on drag-finish**

`_on_split_drag_finished`:

```python
    def _on_split_drag_finished(self) -> None:
        if not self._split_aligned:
            self._align_slice_to_main()
            self._position_slice_panel()
        self._position_split_divider()
        self.layout_geometry_changed.emit()
```

`_on_split_reset` — gate its `_align_slice_to_main()` / `_position_slice_panel()`:

```python
    def _on_split_reset(self) -> None:
        self._bottom_split_h = float(self._bottom_split_default)
        if self._collapse_ctrl is None or self._collapse_ctrl.state() == 'none':
            if self._slice_plot is not None:
                self._slice_plot.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        if not self._split_aligned:
            self._align_slice_to_main()
            self._position_slice_panel()
        self.layout_geometry_changed.emit()
```

`_on_collapse_changed` — gate the `state == 'none'` align block. Change:

```python
        if state == 'none':
            self._align_slice_to_main()
        if state != 'bottom':
            self._position_slice_panel()
```
to:
```python
        if state == 'none' and not self._split_aligned:
            self._align_slice_to_main()
        if state != 'bottom':
            self._position_slice_panel()
```

- [ ] **Step 6: Run the new + full heatmap suite**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q
```
Expected: all pass (new test + existing collapse/drag/restore/reset tests, which
run on single-pane standalone canvases where `_split_aligned` is False so their
alignment behavior is unchanged).

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "fix(analysis): divider drag/reset/collapse delegate slice align to page in split mode"
```

---

## Task C1: Fix stale chart-shortcut tests (top shortcuts are Ctrl by design)

**Files:**
- Modify: `tests/ui/test_chart_stack.py:283-330`

- [ ] **Step 1: Confirm the code intent (Ctrl)**

`mf4_analyzer/ui/hints.py` `NAV_SHORTCUTS` = Ctrl+R/Z/Shift+Z/G/B;
`TIME_CARD_SHORTCUTS` = Ctrl+1..5. These match the product intent (top = Ctrl).
The tests are stale (assert Alt). No production change.

- [ ] **Step 2: Update `test_chart_nav_actions_have_chart_area_shortcuts`**

Change the `expected` dict (`tests/ui/test_chart_stack.py:287-293`) from Alt to
Ctrl:

```python
    expected = {
        "home": "Ctrl+R",
        "back": "Ctrl+Z",
        "forward": "Ctrl+Shift+Z",
        "pan": "Ctrl+G",
        "zoom": "Ctrl+B",
    }
```

- [ ] **Step 3: Update `test_time_card_segmented_buttons_have_alt_digit_shortcuts`**

Rename the function to `test_time_card_segmented_buttons_have_ctrl_digit_shortcuts`,
update the docstring `Alt+1..5` → `Ctrl+1..5`, and change the `expected_pairs`
shortcuts (`:316-320`):

```python
def test_time_card_segmented_buttons_have_ctrl_digit_shortcuts(qapp, qtbot):
    """Ctrl+1..5 are wired to 分屏/叠加/游标关/单游标/双游标 buttons and the
    tooltip carries the shortcut in native form."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    card = cs._time_card
    expected_pairs = [
        (card.btn_subplot,                'Ctrl+1', '分屏'),
        (card.btn_overlay,                'Ctrl+2', '叠加'),
        (card._cursor_buttons['off'],     'Ctrl+3', '游标关'),
        (card._cursor_buttons['single'],  'Ctrl+4', '单游标'),
        (card._cursor_buttons['dual'],    'Ctrl+5', '双游标'),
    ]
```

(Leave the rest of the test body unchanged.)

- [ ] **Step 4: Run the two tests**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py::test_chart_nav_actions_have_chart_area_shortcuts tests/ui/test_chart_stack.py::test_time_card_segmented_buttons_have_ctrl_digit_shortcuts -q
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_chart_stack.py
git commit -m "test(chart): top shortcuts are Ctrl by design — fix stale Alt assertions"
```

---

## Task C2: Make Alt+1..6 view switching section-aware (all sections)

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (`_install_view_shortcuts`, add `_switch_view_for_active_section`)
- Test: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_main_window_smoke.py`:

```python
def test_alt_view_shortcut_switches_active_section(qapp, qtbot):
    """Alt+i view switching must drive the CURRENTLY shown section's view
    manager (fft/fft_time/order), not only the time section."""
    from mf4_analyzer.ui_kit import load_stylesheet
    qapp.setStyle("Fusion"); load_stylesheet(qapp)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 850); w.show(); qtbot.waitExposed(w); qapp.processEvents()

    w._on_mode_changed("fft")
    qapp.processEvents()
    mgr = w.analysis_managers['fft']
    # Ensure there are >=2 views to switch between.
    while len(mgr.views) < 2:
        mgr.new_view()
    mgr.set_active(0)
    qapp.processEvents()

    captured = []
    orig = w._on_analysis_switch
    def _spy(section, idx):
        captured.append((section, idx))
        return orig(section, idx)
    w._on_analysis_switch = _spy

    w._switch_view_for_active_section(1)   # what Alt+2 invokes
    assert ('fft', 1) in captured
    assert mgr.active == 1
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_alt_view_shortcut_switches_active_section -q
```
Expected: FAIL — `_switch_view_for_active_section` does not exist
(AttributeError).

- [ ] **Step 3: Add the section-aware dispatcher**

In `mf4_analyzer/ui/main_window.py`, add the method (near `_switch_view`,
~line 623):

```python
    def _switch_view_for_active_section(self, idx):
        """Alt+i: switch the view of whatever section is currently shown.

        Time section keeps the cross-view pairing path (_switch_view); analysis
        sections (fft/fft_time/order) route to their own manager via
        _on_analysis_switch. Both already guard idx range + no-op on no change.
        """
        mode = self.chart_stack.current_mode()
        if mode in ('fft', 'fft_time', 'order'):
            self._on_analysis_switch(mode, idx)
        else:
            self._switch_view(idx)
```

- [ ] **Step 4: Wire the Alt shortcuts to the dispatcher**

In `_install_view_shortcuts` (~line 620), change the connection:

```python
            sc.activated.connect(
                lambda bound=idx: self._switch_view_for_active_section(bound))
```

- [ ] **Step 5: Run the new test + main-window smoke suite**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "feat(views): Alt+1..6 view switching applies to the active section (all sections)"
```

---

## Task C3: Fix the chart_stack test-isolation teardown cascade

**Files:**
- Investigate + Modify: `tests/ui/test_chart_stack.py` (likely a fixture / per-test cleanup)

- [ ] **Step 1: Reproduce + locate the leaking test**

Run the module and capture the FIRST teardown error's owning test:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q 2>&1 | tail -40
```
Then bisect: run `test_chart_stack_set_mode` preceded by each candidate to find
which predecessor leaves global Qt state dirty:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_chart_stack.py::<suspect>" "tests/ui/test_chart_stack.py::test_chart_stack_set_mode" -q
```
`test_chart_stack_set_mode` passes alone, so the failure is order-dependent
global state (a `ChartStack`/`MainWindow` created without `qtbot.addWidget`,
or a module-level singleton, or a not-deleted top-level widget).

- [ ] **Step 2: Add the cleanup**

For the identified leaking test(s): ensure every top-level widget is owned by
`qtbot.addWidget(...)` (auto-cleaned) or explicitly `w.deleteLater()` +
`qapp.processEvents()` in a `finally`. If a module-level/global object is the
culprit, reset it in a small `autouse` fixture. Make the smallest change that
isolates the leak — do NOT restructure unrelated tests.

- [ ] **Step 3: Verify the module is green**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q
```
Expected: all pass, **zero** teardown errors.

- [ ] **Step 4: If root cause is a deep pre-existing Qt-global issue**

If the leak cannot be isolated with a localized cleanup (e.g. a pyqtgraph/Qt
global that needs broader test-infra work), STOP, write a short lesson under
`docs/lessons-learned/pyqt-ui/` describing the cascade + the candidate cause,
and report it as a follow-up instead of over-engineering. Do not leave the
module red silently.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_chart_stack.py
git commit -m "test(chart): isolate chart_stack module so set_mode no longer cascades teardown errors"
```

---

## Task D: Final full-suite verification

- [ ] **Step 1: Run the affected suites together**

Run:
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py tests/ui/test_chart_stack.py tests/ui/test_main_window_smoke.py tests/ui/test_pg_timedomain_canvas.py -q
```
Expected: all green (no failures, no errors).

- [ ] **Step 2: Diff hygiene**

Run: `git diff --check` → no output, exit 0.

- [ ] **Step 3: Real-render spot check for A + B**

Launch the app (or offscreen-render): on an FFT card, enable Zoom and box-drag
the time preview → it box-zooms (not region-select); in Pan, left-drag →
region-select. On a split analysis page (two panes), drag one divider → both
panes' slice axes stay aligned. Capture screenshots into `docs/reports/`.

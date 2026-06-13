# FFT Quality Indicator Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the chart quality traffic light pinned to the visible canvas lower-right corner when a card's child canvas changes size after the card itself has already shown.

**Architecture:** `_ChartCard` owns the traffic-light overlay, so it should also own all geometry synchronization for that overlay. The fix should not special-case FFT; it should listen to late child canvas layout changes for every card that has `_quality_indicator`, then reposition the overlay from the current `canvas.geometry()`.

**Tech Stack:** PyQt5 widgets/events, pytest-qt, existing `MainWindow` and `ChartStack` UI tests.

---

## Scope And Evidence

The reproduced bug is a child-layout timing issue:

- On first `MainWindow._on_mode_changed("fft")`, the FFT card initially places the indicator at `canvas.bottom() - 6` while the canvas is `906x667`.
- After Qt processes layout events, the FFT hint bar is already hosted in the status bar, so the canvas expands to `906x695`.
- The card does not resize again, so `_ChartCard.resizeEvent()` does not run; the indicator stays 34 px above the new canvas bottom.
- Switching away and back runs `_ChartCard.showEvent()` with the final canvas geometry, so the later position is correct.

Other canvas-size change sources to cover conceptually:

- `MainWindow._install_status_hint_bar()` reparenting per-mode `_hint_bar` out of the card layout.
- `ChartStack.set_mode()` showing/hiding `_time_bottom_dock`, stats strip, and mode pages.
- `AnalysisSectionPage._sync_card_hint_bars()` hiding analysis compare-pane hint bars.
- `AnalysisSectionPage.enter_split()` / `exit_split()` and `QSplitter.setSizes()` changing pane width.
- Time-domain `ChartStack.enter_split()` / `exit_split()` changing pane width.
- Main window resize, side panel collapse/peek, and splitter handle moves changing chart-stack width.
- Plot-internal rows such as FFT line preview/collapse and heatmap slice/collapse changing the effective chart area.

## Task 1: Regression Test For First FFT Entry

**Files:**
- Modify: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Add a failing MainWindow-level test**

Add this test near the existing mode/hint-bar tests:

```python
def test_fft_quality_indicator_repositions_after_first_mode_layout(qapp, qtbot):
    """MainWindow's first FFT entry reparents the hint bar into the status bar.

    That late layout pass changes the child canvas height without a second
    _ChartCard resize, so the quality dot must still track the canvas geometry.
    """
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1450, 850)
    w.show()
    qtbot.waitExposed(w)
    qapp.processEvents()

    w._on_mode_changed("fft")
    qapp.processEvents()
    qapp.processEvents()

    card = w.chart_stack._fft_card
    canvas_rect = card.canvas.geometry()
    dot_rect = card._quality_indicator.geometry()

    assert canvas_rect.contains(dot_rect.center())
    assert canvas_rect.right() - dot_rect.right() <= 12
    assert canvas_rect.bottom() - dot_rect.bottom() <= 12
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_fft_quality_indicator_repositions_after_first_mode_layout -q
```

Expected before the fix: FAIL with the bottom delta around 34 px, above the 12 px bound.

## Task 2: Reposition Indicator On Canvas Layout Events

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`

- [ ] **Step 1: Extend `_ChartCard.eventFilter()`**

In `_ChartCard.eventFilter`, keep the existing hint-rotation behavior and add geometry sync for the card's canvas and viewport:

```python
        if obj is self.canvas or obj is getattr(self.canvas, "_glw", None):
            if etype in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                self._position_quality_indicator()
        try:
            viewport = self.canvas._glw.viewport()
        except Exception:
            viewport = None
        if obj is viewport and etype in (QEvent.Resize, QEvent.Show):
            self._position_quality_indicator()
```

- [ ] **Step 2: Add a deferred positioning helper**

If immediate event-filter positioning still observes pre-layout geometry, add a helper that schedules one zero-delay reposition:

```python
    def _schedule_quality_indicator_position(self):
        indicator = getattr(self, "_quality_indicator", None)
        if indicator is None:
            return
        if getattr(self, "_quality_indicator_position_pending", False):
            return
        self._quality_indicator_position_pending = True
        QTimer.singleShot(0, self._flush_quality_indicator_position)

    def _flush_quality_indicator_position(self):
        self._quality_indicator_position_pending = False
        self._position_quality_indicator()
```

Then call `_schedule_quality_indicator_position()` from child resize/show/layout events and from `showEvent()` after the immediate positioning.

- [ ] **Step 3: Keep the fix generic**

Do not branch on `chart_mode == "fft"`. The invariant belongs to all `_ChartCard` overlays: a child canvas geometry change must move the traffic light.

## Task 3: Verification

**Files:**
- Test: `tests/ui/test_main_window_smoke.py`
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Run the new regression test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_fft_quality_indicator_repositions_after_first_mode_layout -q
```

Expected after the fix: PASS.

- [ ] **Step 2: Run existing quality-indicator tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py::test_fft_card_quality_indicator_present_like_time_card tests/ui/test_chart_stack.py::test_time_card_quality_indicator_sits_on_canvas_lower_right -q
```

Expected: 2 passed.

- [ ] **Step 3: Run a syntax/diff hygiene check**

Run:

```bash
git diff --check
```

Expected: no output and exit 0.

## Completion Notes

Do not touch the existing unrelated `mf4_analyzer/ui/pg_canvas/line_canvas.py` or `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` working-tree changes. Do not commit unless explicitly requested.

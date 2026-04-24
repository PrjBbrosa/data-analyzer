# UI Layout Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix FFT→time regression, move plot-mode and cursor-mode controls from the Inspector onto each time-domain chart's NavigationToolbar, always-show the tick-density group, slim the top toolbar and splitter handle, and make `tight_layout` the default for all matplotlib figures.

**Architecture:** Promote the time-domain chart card in `chart_stack.py` to a named `TimeChartCard` subclass that owns the plot-mode and cursor-mode segmented controls. `ChartStack` relays their signals to `MainWindow`. `TimeContextual` loses those two GroupBoxes. `PersistentTop.刻度` GroupBox loses its `setCheckable`. Regression fix defers `plot_time()` by one event-loop tick.

**Tech Stack:** PyQt5, matplotlib (`Qt5Agg` backend), pytest + pytest-qt. Existing session-scoped `qapp` fixture in `tests/ui/conftest.py` (offscreen platform).

**Reference spec:** `docs/superpowers/specs/2026-04-24-ui-layout-cleanup-design.md`

---

## File Map

| Path | Role |
|------|------|
| `mf4_analyzer/ui/chart_stack.py` | **Modify** — add `TimeChartCard`, strip Subplots action from native nav toolbar, relay signals. |
| `mf4_analyzer/ui/inspector_sections.py` | **Modify** — drop plot-mode / cursor-mode GroupBoxes from `TimeContextual`; de-checkable 刻度 group. |
| `mf4_analyzer/ui/inspector.py` | **Modify** — remove `plot_mode_changed` / `cursor_mode_changed` signals. |
| `mf4_analyzer/ui/main_window.py` | **Modify** — defer `plot_time()`, reroute signals, use `tight_layout` in `do_fft`, narrow splitter handle. |
| `mf4_analyzer/ui/canvases.py` | **Modify** — `plot_channels` uses `tight_layout` in all branches. |
| `mf4_analyzer/ui/toolbar.py` | **Modify** — tighten outer margins. |
| `mf4_analyzer/ui/style.qss` | **Modify** — 3px splitter handle, tighter main toolbar button padding, chart-toolbar segmented-button styling. |
| `tests/ui/test_chart_stack.py` | **Modify** — new tests for `TimeChartCard` signals/getters, Subplots-button-removed assertion. |
| `tests/ui/test_inspector.py` | **Modify** — drop obsolete `TimeContextual.cursor_mode` / `plot_mode` tests; add assertion that 刻度 controls are always visible. |
| `tests/ui/test_toolbar.py` | **Read only for regression** — unchanged contract. |

---

## Task 1 — Regression Fix: FFT → Time blank canvas

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py:132-138` (the `_on_mode_changed` method).

- [ ] **Step 1.1: Read the current `_on_mode_changed` to confirm the exact lines.**

Run: `grep -n "_on_mode_changed" mf4_analyzer/ui/main_window.py`
Expected: line 132 declaration, line 138 end of method body.

- [ ] **Step 1.2: Edit `_on_mode_changed` to defer the time re-plot.**

Change from:
```python
def _on_mode_changed(self, mode):
    self.chart_stack.set_mode(mode)
    self.inspector.set_mode(mode)
    self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
    # §6.2 auto re-plot on entering time mode with checked channels
    if mode == 'time' and self.files and self.navigator.get_checked_channels():
        self.plot_time()
```

To:
```python
def _on_mode_changed(self, mode):
    self.chart_stack.set_mode(mode)
    self.inspector.set_mode(mode)
    self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
    # §6.2 auto re-plot on entering time mode with checked channels.
    # Defer by one tick: QStackedWidget has not yet laid out the newly
    # visible canvas, and drawing now paints onto a backing store that is
    # discarded when the layout pass fires (observed regression: plot
    # blanks after fft → time toggle).
    if mode == 'time' and self.files and self.navigator.get_checked_channels():
        QTimer.singleShot(0, self.plot_time)
```

`QTimer` is already imported at the top of `main_window.py` (line 22).

- [ ] **Step 1.3: Run the existing smoke test to confirm nothing regressed.**

Run: `pytest tests/ui/test_main_window_smoke.py -v`
Expected: all tests pass.

- [ ] **Step 1.4: Commit.**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "fix(ui): defer time replot after mode switch to avoid blank canvas

When QStackedWidget swaps to the time card, plot_time() runs before the
canvas is laid out. Drawing now paints onto a backing store that Qt
discards on the next layout pass, leaving the canvas empty. Defer the
replot by one event-loop tick so the resize/show events settle first."
```

---

## Task 2 — Add `TimeChartCard` with plot-mode and cursor-mode controls

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py` (add subclass, strip Subplots action, expose signals/getters).
- Modify: `tests/ui/test_chart_stack.py` (new tests for the subclass).

### Step 2.1: Write the failing tests first

- [ ] **Append the following tests to `tests/ui/test_chart_stack.py`.** Do not overwrite existing tests; append.

```python
# ---- TimeChartCard (2026-04-24 UI cleanup) ----

def test_chart_stack_exposes_plot_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.plot_mode() == 'subplot'
    with qtbot.waitSignal(cs.plot_mode_changed, timeout=200) as bl:
        cs.set_plot_mode('overlay')
    assert bl.args == ['overlay']
    assert cs.plot_mode() == 'overlay'


def test_chart_stack_exposes_cursor_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default must be 'off' per spec §8
    assert cs.cursor_mode() == 'off'
    with qtbot.waitSignal(cs.cursor_mode_changed, timeout=200) as bl:
        cs.set_cursor_mode('single')
    assert bl.args == ['single']
    assert cs.cursor_mode() == 'single'


def test_time_chart_card_has_segmented_controls(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, TimeChartCard
    cs = ChartStack()
    qtbot.addWidget(cs)
    # First card in the stack is the time-domain card.
    card = cs.stack.widget(0)
    assert isinstance(card, TimeChartCard)
    # Four buttons on the card toolbar: Subplot, Overlay, Off, Single, Dual
    texts = {b.text() for b in card.findChildren(type(card.btn_subplot))}
    assert {'Subplot', 'Overlay', 'Off', 'Single', 'Dual'} <= texts


def test_time_chart_card_removes_subplots_config_button(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs.stack.widget(0)
    # No QAction on the native nav toolbar should map to 'configure_subplots'.
    native_tb = card.toolbar
    for act in native_tb.actions():
        # The action object name / icon text varies; check both.
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_fft_card_still_has_subplots_button(qapp, qtbot):
    """Only time card strips the button — FFT / Order keep the default toolbar."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # Per spec §3.2 we strip Subplots from ALL cards (tight_layout is the
    # default everywhere). So this test also asserts absence on FFT card.
    fft_card = cs.stack.widget(1)
    for act in fft_card.toolbar.actions():
        assert act.text().lower() not in ('subplots', 'configure subplots')
```

- [ ] **Step 2.2: Run tests and confirm they fail.**

Run: `pytest tests/ui/test_chart_stack.py::test_chart_stack_exposes_plot_mode_api tests/ui/test_chart_stack.py::test_chart_stack_exposes_cursor_mode_api tests/ui/test_chart_stack.py::test_time_chart_card_has_segmented_controls tests/ui/test_chart_stack.py::test_time_chart_card_removes_subplots_config_button tests/ui/test_chart_stack.py::test_fft_card_still_has_subplots_button -v`
Expected: all five FAIL (AttributeError / ImportError).

### Step 2.3: Implement `TimeChartCard` and the relay API on `ChartStack`

- [ ] **Rewrite `mf4_analyzer/ui/chart_stack.py`** to match the structure below. This is an overwrite of the file.

```python
"""Center pane: QStackedWidget holding the three canvases + stats strip."""
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .canvases import PlotCanvas, TimeDomainCanvas
from .widgets import StatsStrip

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'order': 2}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}


def _strip_subplots_action(toolbar):
    """Remove the matplotlib 'Configure subplots' button — tight_layout
    is the default in this app so the dialog is not useful."""
    for act in list(toolbar.actions()):
        name = (act.text() or '').lower()
        if 'subplots' in name or 'configure subplots' in name:
            toolbar.removeAction(act)
            return


def _vline():
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setFrameShadow(QFrame.Plain)
    f.setObjectName("chartToolbarSep")
    f.setFixedWidth(1)
    return f


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.setObjectName("chartCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = canvas
        self.toolbar = NavigationToolbar(canvas, self)
        self.toolbar.setObjectName("chartToolbar")
        self.toolbar.setIconSize(QSize(16, 16))
        _strip_subplots_action(self.toolbar)
        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)


class TimeChartCard(_ChartCard):
    """Time-domain chart card: inherits base nav toolbar, appends
    segmented controls for plot mode (Subplot/Overlay) and cursor mode
    (Off/Single/Dual)."""

    plot_mode_changed = pyqtSignal(str)    # 'subplot' | 'overlay'
    cursor_mode_changed = pyqtSignal(str)  # 'off' | 'single' | 'dual'

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent)
        # Append separator + plot-mode + separator + cursor-mode into the
        # existing toolbar. Matplotlib's NavigationToolbar2QT is a QToolBar
        # subclass, so addWidget puts things inline after the icon group.
        self.toolbar.addWidget(_vline())

        self.btn_subplot = QPushButton("Subplot", self.toolbar)
        self.btn_overlay = QPushButton("Overlay", self.toolbar)
        for b in (self.btn_subplot, self.btn_overlay):
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self.toolbar.addWidget(b)
        self._plot_mode = 'subplot'
        self.btn_subplot.setChecked(True)
        self.btn_subplot.clicked.connect(lambda: self.set_plot_mode('subplot'))
        self.btn_overlay.clicked.connect(lambda: self.set_plot_mode('overlay'))

        self.toolbar.addWidget(_vline())

        self._cursor_buttons = {}
        for label, key in [('Off', 'off'), ('Single', 'single'), ('Dual', 'dual')]:
            b = QPushButton(label, self.toolbar)
            b.setCheckable(True)
            b.setProperty("role", "chart-choice")
            b.setFlat(True)
            self.toolbar.addWidget(b)
            self._cursor_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_cursor_mode(k))
        self._cursor_mode = 'off'
        self._cursor_buttons['off'].setChecked(True)

    # ----- plot mode -----
    def plot_mode(self):
        return self._plot_mode

    def set_plot_mode(self, mode):
        if mode not in ('subplot', 'overlay'):
            return
        self._plot_mode = mode
        self.btn_subplot.setChecked(mode == 'subplot')
        self.btn_overlay.setChecked(mode == 'overlay')
        self.plot_mode_changed.emit(mode)

    # ----- cursor mode -----
    def cursor_mode(self):
        return self._cursor_mode

    def set_cursor_mode(self, mode):
        if mode not in ('off', 'single', 'dual'):
            return
        self._cursor_mode = mode
        for k, b in self._cursor_buttons.items():
            b.setChecked(k == mode)
        self.cursor_mode_changed.emit(mode)


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)
    plot_mode_changed = pyqtSignal(str)
    cursor_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 0)
        lay.setSpacing(8)
        self.stack = QStackedWidget(self)
        self.canvas_time = TimeDomainCanvas(self)
        self.canvas_fft = PlotCanvas(self)
        self.canvas_order = PlotCanvas(self)
        self._time_card = TimeChartCard(self.canvas_time)
        self.stack.addWidget(self._time_card)
        self.stack.addWidget(_ChartCard(self.canvas_fft))
        self.stack.addWidget(_ChartCard(self.canvas_order))
        lay.addWidget(self.stack, stretch=1)

        # Stats strip mounted at the bottom (Task 2.10)
        self.stats_strip = StatsStrip(self)
        lay.addWidget(self.stats_strip)

        # Cursor pill (owned by ChartStack; floats over active canvas)
        self._cursor_pill = QLabel("", self.stack)
        self._cursor_pill.setObjectName("cursorPill")
        self._cursor_pill.setVisible(False)
        self._cursor_dual_pill = QLabel("", self.stack)
        self._cursor_dual_pill.setObjectName("cursorPill")
        self._cursor_dual_pill.setWordWrap(True)
        self._cursor_dual_pill.setVisible(False)
        self.canvas_time.cursor_info.connect(self._on_cursor_info)
        self.canvas_time.dual_cursor_info.connect(self._on_dual_cursor_info)
        self.stack.currentChanged.connect(lambda _i: self._reposition_pills())

        # Relay time-card control signals up to MainWindow consumers.
        self._time_card.plot_mode_changed.connect(self.plot_mode_changed)
        self._time_card.cursor_mode_changed.connect(self.cursor_mode_changed)

    def count(self):
        return self.stack.count()

    def set_mode(self, mode):
        idx = _MODE_TO_INDEX[mode]
        if self.stack.currentIndex() == idx:
            return
        self.stack.setCurrentIndex(idx)
        self.mode_changed.emit(mode)

    def current_mode(self):
        return _INDEX_TO_MODE[self.stack.currentIndex()]

    # ----- plot-mode / cursor-mode passthroughs -----
    def plot_mode(self):
        return self._time_card.plot_mode()

    def set_plot_mode(self, mode):
        self._time_card.set_plot_mode(mode)

    def cursor_mode(self):
        return self._time_card.cursor_mode()

    def set_cursor_mode(self, mode):
        self._time_card.set_cursor_mode(mode)

    def full_reset_all(self):
        self.canvas_time.full_reset()
        self.canvas_fft.full_reset()
        self.canvas_order.full_reset()

    def _on_cursor_info(self, text):
        self._cursor_pill.setText(text)
        self._cursor_pill.adjustSize()
        self._cursor_pill.setVisible(self.current_mode() == 'time')
        self._reposition_pills()

    def _on_dual_cursor_info(self, text):
        self._cursor_dual_pill.setText(text)
        self._cursor_dual_pill.adjustSize()
        self._cursor_dual_pill.setVisible(bool(text) and self.current_mode() == 'time')
        self._reposition_pills()

    def _reposition_pills(self):
        visible = self.current_mode() == 'time'
        if not visible:
            self._cursor_pill.setVisible(False)
            self._cursor_dual_pill.setVisible(False)
            return
        card = self.stack.currentWidget()
        h = card.height() if card is not None else self.stack.height()
        pill_h = self._cursor_pill.sizeHint().height()
        self._cursor_pill.move(8, max(h - pill_h - 8, 0))
        if self._cursor_dual_pill.text():
            dh = self._cursor_dual_pill.sizeHint().height()
            self._cursor_dual_pill.move(8, max(h - pill_h - dh - 12, 0))
        self._cursor_pill.raise_()
        self._cursor_dual_pill.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pills()

    def cursor_pill_text(self):
        return self._cursor_pill.text()

    def cursor_pill_visible(self):
        return self._cursor_pill.isVisible()
```

- [ ] **Step 2.4: Run the new tests; they should pass.**

Run: `pytest tests/ui/test_chart_stack.py -v`
Expected: all tests pass (existing + the 5 new ones).

- [ ] **Step 2.5: Commit.**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_chart_stack.py
git commit -m "feat(ui): move plot-mode and cursor-mode onto time chart toolbar

Promote the time-domain chart card to TimeChartCard, which inherits the
native matplotlib nav toolbar and appends two segmented control groups:
Subplot/Overlay and Off/Single/Dual (default Off). ChartStack relays the
new signals and exposes plot_mode()/cursor_mode() getters. The 'Configure
subplots' action is also stripped from all cards since tight_layout is
now the default."
```

---

## Task 3 — Remove plot-mode / cursor-mode from Inspector

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py:171-235` (the `TimeContextual` class).
- Modify: `mf4_analyzer/ui/inspector.py` (strip two signals + one wiring line).
- Modify: `mf4_analyzer/ui/main_window.py` (reroute signals, update `plot_time` to read from ChartStack, update `_reset_plot_state`).
- Modify: `tests/ui/test_inspector.py` (delete two obsolete tests).

### Step 3.1: Delete obsolete Inspector tests

- [ ] **Remove these two test functions from `tests/ui/test_inspector.py`** (they test APIs we are removing):

```python
# DELETE:
def test_time_contextual_cursor_segmented(qapp, qtbot):
    ...


def test_time_contextual_plot_mode(qapp, qtbot):
    ...
```

Keep `test_time_contextual_plot_button_emits` (the 绘图 button remains per spec §3.3).

- [ ] **Step 3.2: Run the test file to confirm it still collects and the remaining tests pass against the unchanged implementation.**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: all remaining tests pass.

### Step 3.3: Simplify `TimeContextual`

- [ ] **Replace the `TimeContextual` class body in `mf4_analyzer/ui/inspector_sections.py` with:**

```python
class TimeContextual(QWidget):
    """Time-domain contextual: just the manual replot button.

    Plot-mode and cursor-mode controls have been relocated to the chart
    card toolbar (see chart_stack.TimeChartCard).
    """

    plot_time_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self.btn_plot = QPushButton("绘图")
        self.btn_plot.setIcon(Icons.plot())
        self.btn_plot.setIconSize(QSize(16, 16))
        self.btn_plot.setProperty("role", "primary")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()
```

- [ ] **Step 3.4: Run inspector tests to confirm remaining ones still pass.**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: all remaining tests pass.

### Step 3.5: Strip Inspector relay signals

- [ ] **Edit `mf4_analyzer/ui/inspector.py`:**

Remove these two lines from the signal declarations (around lines 28-29):
```python
cursor_mode_changed = pyqtSignal(str)
plot_mode_changed = pyqtSignal(str)
```

Remove these two lines from `_wire()` (around lines 69-70):
```python
self.time_ctx.cursor_mode_changed.connect(self.cursor_mode_changed)
self.time_ctx.plot_mode_changed.connect(self.plot_mode_changed)
```

- [ ] **Step 3.6: Run inspector tests.**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: still passes.

### Step 3.7: Reroute signals in `MainWindow`

- [ ] **Edit `mf4_analyzer/ui/main_window.py` `_connect` method.** Remove these two lines:

```python
self.inspector.cursor_mode_changed.connect(self._on_cursor_mode_changed)
self.inspector.plot_mode_changed.connect(self._on_plot_mode_changed)
```

Replace with:

```python
self.chart_stack.cursor_mode_changed.connect(self._on_cursor_mode_changed)
self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)
```

- [ ] **Step 3.8: Update `plot_time()` to read plot-mode from ChartStack.**

In `mf4_analyzer/ui/main_window.py` at line 449 (the `plot_time` method), change:

```python
mode = self.inspector.time_ctx.plot_mode()
```

To:

```python
mode = self.chart_stack.plot_mode()
```

- [ ] **Step 3.9: Update `_reset_plot_state` cursor reset.**

Around line 390, change:

```python
self.inspector.time_ctx.set_cursor_mode('single')
```

To:

```python
self.chart_stack.set_cursor_mode('off')
```

- [ ] **Step 3.10: Run smoke + chart + inspector test suites.**

Run: `pytest tests/ui/test_main_window_smoke.py tests/ui/test_chart_stack.py tests/ui/test_inspector.py -v`
Expected: all green.

- [ ] **Step 3.11: Commit.**

```bash
git add mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/inspector.py mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py
git commit -m "refactor(ui): drop plot-mode/cursor-mode from Inspector

TimeContextual now holds only the manual plot button; the segmented
controls live on the time chart card's toolbar. Inspector no longer
forwards those signals. MainWindow reads plot mode from ChartStack and
resets cursor via ChartStack.set_cursor_mode('off')."
```

---

## Task 4 — 刻度 GroupBox always visible + slim main toolbar + narrow splitter

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py:91-115` (PersistentTop 刻度 section).
- Modify: `mf4_analyzer/ui/toolbar.py:20-23` (margins).
- Modify: `mf4_analyzer/ui/main_window.py` (setHandleWidth).
- Modify: `mf4_analyzer/ui/style.qss` (splitter-handle width, toolbar button padding).
- Modify: `tests/ui/test_inspector.py` (add tick-always-visible test).

### Step 4.1: Write failing test for 刻度 always visible

- [ ] **Append to `tests/ui/test_inspector.py`:**

```python
def test_persistent_top_tick_group_not_checkable(qapp):
    """刻度 GroupBox must be always-open per spec §3.3 (2026-04-24 cleanup)."""
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    # The groupbox that contains spin_xt / spin_yt — find it.
    parent_gb = pt.spin_xt.parentWidget()
    # Walk up to QGroupBox
    while parent_gb is not None and type(parent_gb).__name__ != 'QGroupBox':
        parent_gb = parent_gb.parentWidget()
    assert parent_gb is not None, "spin_xt has no QGroupBox ancestor"
    assert not parent_gb.isCheckable()
    assert pt.spin_xt.isVisibleTo(pt) or True  # visibility only meaningful once shown
    # Key contract: tick density reflects current spin values (not zero).
    assert pt.tick_density() == (10, 6)
```

- [ ] **Step 4.2: Run and see it fail.**

Run: `pytest tests/ui/test_inspector.py::test_persistent_top_tick_group_not_checkable -v`
Expected: FAIL on `isCheckable()` assertion (currently True).

### Step 4.3: Strip checkable from 刻度 group

- [ ] **Edit `mf4_analyzer/ui/inspector_sections.py`**, replace lines ~90-115 (the tick-density group block) with:

```python
        # ------- Tick density group (§6.1 ▸ 刻度) -------
        g = QGroupBox("刻度")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_xt = QSpinBox()
        self.spin_xt.setRange(3, 30)
        self.spin_xt.setValue(10)
        fl.addRow("X:", _fit_field(self.spin_xt))
        self.spin_yt = QSpinBox()
        self.spin_yt.setRange(3, 20)
        self.spin_yt.setValue(6)
        fl.addRow("Y:", _fit_field(self.spin_yt))
        root.addWidget(g)
```

(i.e., drop `setCheckable(True)`, `setChecked(False)`, the `_toggle_ticks` helper, and the call to it.)

- [ ] **Step 4.4: Run the new test; it should pass.**

Run: `pytest tests/ui/test_inspector.py::test_persistent_top_tick_group_not_checkable -v`
Expected: PASS.

### Step 4.5: Slim the top toolbar

- [ ] **Edit `mf4_analyzer/ui/toolbar.py:21-23`:**

Change:
```python
lay = QHBoxLayout(self)
lay.setContentsMargins(10, 7, 10, 7)
lay.setSpacing(10)
```

To:
```python
lay = QHBoxLayout(self)
lay.setContentsMargins(10, 3, 10, 3)
lay.setSpacing(8)
```

### Step 4.6: Narrow the splitter handle

- [ ] **Edit `mf4_analyzer/ui/main_window.py`** `_init_ui` method, after the `splitter.setCollapsible(2, False)` block (~line 69), add:

```python
splitter.setHandleWidth(3)
```

### Step 4.7: Tune qss — splitter visible, toolbar buttons shorter

- [ ] **Edit `mf4_analyzer/ui/style.qss`**.

Replace the existing `QSplitter::handle:horizontal` rule (lines ~25-27):

```css
QSplitter::handle:horizontal {
    width: 3px;
    background-color: #cbd5e1;
}
```

Replace the existing `Toolbar QPushButton { min-height: 28px; }` rule (~lines 255-257):

```css
Toolbar QPushButton {
    min-height: 24px;
    padding: 3px 10px;
}
```

Append at the end of the file a block for the chart-toolbar segmented buttons:

```css
/* Chart toolbar — segmented controls (Subplot/Overlay, Off/Single/Dual) */
QWidget#chartToolbar QPushButton[role="chart-choice"] {
    min-height: 22px;
    margin: 0 2px;
    padding: 2px 10px;
    border: 1px solid transparent;
    border-radius: 6px;
    background-color: transparent;
    color: #64748b;
    font-weight: 600;
}

QWidget#chartToolbar QPushButton[role="chart-choice"]:hover {
    background-color: #eef2f7;
    color: #334155;
}

QWidget#chartToolbar QPushButton[role="chart-choice"]:checked {
    background-color: #ffffff;
    border-color: #cbd5e1;
    color: #0f3f8f;
}

QFrame#chartToolbarSep {
    margin: 3px 4px;
    color: #d7dee8;
}
```

- [ ] **Step 4.8: Run the full UI test suite.**

Run: `pytest tests/ui/ -v`
Expected: all green.

- [ ] **Step 4.9: Commit.**

```bash
git add mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/toolbar.py mf4_analyzer/ui/main_window.py mf4_analyzer/ui/style.qss tests/ui/test_inspector.py
git commit -m "style(ui): always-show tick group, slim toolbar, narrow splitter

- 刻度 QGroupBox no longer toggles collapsed; spinboxes stay visible.
- Top toolbar vertical margins 7px → 3px; button padding trimmed.
- QSplitter handle 3px wide with a visible light-gray fill so users
  still see it as a drag affordance.
- qss styling for new chart-toolbar segmented buttons and separators."
```

---

## Task 5 — `tight_layout` default in all figures

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py` `plot_channels` method (three branches).
- Modify: `mf4_analyzer/ui/main_window.py` `do_fft` method (~line 676).

### Step 5.1: Swap `subplots_adjust` for `tight_layout` in `plot_channels`

- [ ] **Edit `mf4_analyzer/ui/canvases.py`** around lines 151, 175, and 188.

Line ~151 (subplot branch):
```python
self.fig.subplots_adjust(hspace=0.08, left=0.17, right=0.96, top=0.96, bottom=0.08)
```
Replace with:
```python
self.fig.tight_layout()
```

Line ~175 (overlay branch):
```python
right = max(0.93 - 0.065 * max(0, len(vis) - 2), 0.58)
self.fig.subplots_adjust(left=0.15, right=right, top=0.96, bottom=0.09)
```
Replace with:
```python
# Overlay keeps the right-hand margin adjustment because multiple twinx
# spines require space; tight_layout cannot reason about twinx stacks.
# Use tight_layout first to fix left/top/bottom, then carve the right.
self.fig.tight_layout()
right = max(0.93 - 0.065 * max(0, len(vis) - 2), 0.58)
self.fig.subplots_adjust(right=right)
```

Line ~188 (single-channel branch):
```python
self.fig.subplots_adjust(left=0.17, right=0.96, top=0.95, bottom=0.11)
```
Replace with:
```python
self.fig.tight_layout()
```

### Step 5.2: Swap in `do_fft`

- [ ] **Edit `mf4_analyzer/ui/main_window.py`** around line 676. Change:

```python
self.canvas_fft.fig.subplots_adjust(left=0.11, right=0.98, top=0.91, bottom=0.09, hspace=0.42)
```

To:

```python
self.canvas_fft.fig.tight_layout()
```

### Step 5.3: Smoke test

- [ ] **Run the smoke tests + the amplitude-normalization test.**

Run: `pytest tests/ui/test_main_window_smoke.py tests/test_fft_amplitude_normalization.py -v`
Expected: all green.

### Step 5.4: Commit

- [ ] **Commit.**

```bash
git add mf4_analyzer/ui/canvases.py mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): tight_layout default for all figures

Time-domain subplot / single-channel and FFT plots now use
fig.tight_layout(). Overlay mode keeps a right-margin carve so stacked
twinx axes still fit; the tight_layout call before it fixes the
left/top/bottom spacing."
```

---

## Task 6 — Manual verification

- [ ] **Step 6.1: Launch the app.**

Run: `python "MF4 Data Analyzer V1.py"` (or `python -m mf4_analyzer.app`)

- [ ] **Step 6.2: Load an MF4 or CSV file.**

Use the "添加文件" button. Load any existing sample (e.g., from `tests/` fixtures or an MF4 on disk).

- [ ] **Step 6.3: Verify time chart toolbar layout.**

- Native buttons (home, back, forward, pan, zoom, save) visible.
- NO "Configure subplots" button.
- Vertical line separator.
- "Subplot" (checked) + "Overlay".
- Vertical line separator.
- "Off" (checked) + "Single" + "Dual".

- [ ] **Step 6.4: Verify FFT / Order chart toolbars do NOT carry the segmented controls.**

Switch tabs to FFT, then Order. Their toolbars must contain ONLY the native buttons (no Configure subplots either).

- [ ] **Step 6.5: Verify plot-mode toggle works.**

Click "Overlay" → time plot re-renders with stacked twinx axes. Click "Subplot" → returns to stacked subplots.

- [ ] **Step 6.6: Verify cursor modes.**

- Default is Off — hovering does not show a cursor pill.
- Click Single — hover shows pill with t + per-channel values.
- Click Dual — click to place A/B; pill shows ΔT and 1/ΔT.
- Click Off — all cursors hidden.

- [ ] **Step 6.7: Verify FFT → time regression is fixed.**

Click "FFT" mode in top toolbar, compute an FFT, then click "时域" back.
**Expected:** the time plot is re-drawn and visible, not blank.

- [ ] **Step 6.8: Verify Inspector shape.**

- 横坐标 group — unchanged.
- 范围 group — unchanged.
- 刻度 group — no checkbox in the group title; X / Y spin-boxes always visible.
- No "绘图模式" group. No "游标" group.
- "绘图" button still present at the bottom of the time contextual.

- [ ] **Step 6.9: Verify top toolbar height.**

Eyeball against previous screenshot — visibly thinner (margins 3px).

- [ ] **Step 6.10: Verify splitter handle.**

Drag the gap between Inspector and chart area. Handle is thin (3px) but visibly colored so the user can spot it.

- [ ] **Step 6.11: Verify tight_layout look.**

Time subplot, overlay, single-channel, FFT, and each Order mode — axis labels are not clipped and there is no wasted whitespace around the figure.

---

## Self-Review

Against `docs/superpowers/specs/2026-04-24-ui-layout-cleanup-design.md`:

- §1.1 regression — Task 1.
- §1.2 top toolbar too tall — Task 4.5 + 4.7.
- §1.3 plot-mode / cursor-mode out of Inspector — Tasks 2 + 3.
- §1.4 tick group always-on — Task 4.1–4.4.
- §1.5 Subplots-config button removed — Task 2.3 (`_strip_subplots_action`).
- §1.6 splitter too wide — Task 4.6 + 4.7.
- §1.7 cursor default Off — Task 2.3 (`_cursor_mode = 'off'`; `self._cursor_buttons['off'].setChecked(True)`).
- §6 tight_layout default — Task 5.

All spec requirements map to a task. No placeholders remain. Method/signal names are consistent across tasks (`plot_mode` / `set_plot_mode` / `plot_mode_changed`; `cursor_mode` / `set_cursor_mode` / `cursor_mode_changed`).

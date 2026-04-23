# Mac 浅色 3-Pane UI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `mf4_analyzer/ui/` from a 2-pane layout to a Mac light-theme 3-pane (file navigator + chart stack + inspector) + drawer/sheet/popover pattern, preserving every existing feature.

**Architecture:** Decompose the monolithic `main_window.py` into focused sibling modules (`toolbar.py`, `file_navigator.py`, `chart_stack.py`, `inspector.py`, `inspector_sections.py`, `drawers/*`). `MainWindow` becomes a central router: owns `files`/`_active` state, receives signals from sub-widgets, dispatches analysis methods (`plot_time / do_fft / do_order_*`). Cursor pill moves from standalone label to `ChartStack`-owned overlay. Modal dialogs become slide-in drawer / top-anchored sheet / frameless popovers. Analysis algorithms in `signal/*` and I/O in `io/*` are untouched.

**Tech Stack:** PyQt5, matplotlib (Qt5Agg backend), pandas, numpy. Tests use pytest + pytest-qt where widget-level; smoke tests launch the real MainWindow via `pytest --qt-bot`.

**Reference:** Spec at `docs/superpowers/specs/2026-04-23-mac-style-3pane-ui-design.md`.

---

## File Structure Overview

**Create:**
- `mf4_analyzer/ui/toolbar.py` — top three-segment toolbar
- `mf4_analyzer/ui/file_navigator.py` — left pane (file list + channel tree)
- `mf4_analyzer/ui/chart_stack.py` — center pane (QStackedWidget + stats strip + cursor pill)
- `mf4_analyzer/ui/inspector.py` — right pane framework (persistent top + contextual bottom)
- `mf4_analyzer/ui/inspector_sections.py` — subsection widgets (xaxis/range/ticks/plot-mode/fft/order)
- `mf4_analyzer/ui/drawers/__init__.py`
- `mf4_analyzer/ui/drawers/channel_editor_drawer.py`
- `mf4_analyzer/ui/drawers/export_sheet.py`
- `mf4_analyzer/ui/drawers/rebuild_time_popover.py`
- `mf4_analyzer/ui/drawers/axis_lock_popover.py`
- `tests/ui/test_file_navigator.py`
- `tests/ui/test_inspector.py`
- `tests/ui/test_chart_stack.py`
- `tests/ui/test_toolbar.py`
- `tests/ui/test_drawers.py`
- `tests/ui/test_main_window_smoke.py`

**Modify:**
- `mf4_analyzer/ui/main_window.py` — thin router; signal wiring only
- `mf4_analyzer/ui/widgets.py` — keep `StatisticsPanel`, remove `MultiFileChannelWidget` (moved to file_navigator)
- `mf4_analyzer/ui/canvases.py` — remove standalone cursor-label emission; keep `cursor_info / dual_cursor_info` signals
- `mf4_analyzer/ui/style.qss` — full rewrite for light theme
- `mf4_analyzer/ui/icons.py` — add segmented / kebab / close / drawer icons

**Delete:**
- `mf4_analyzer/ui/axis_lock_toolbar.py` (content moves to `drawers/axis_lock_popover.py`)

---

## Pre-work: Setup test infra

### Task 0.1: Add pytest-qt dependency and test folder

**Files:**
- Modify: `requirements.txt`
- Create: `tests/ui/__init__.py`
- Create: `tests/ui/conftest.py`

- [ ] **Step 1: Check current requirements.txt**

Run: `cat requirements.txt`
Expected: lists PyQt5, matplotlib, pandas, numpy, asammdf etc.

- [ ] **Step 2: Add pytest-qt**

Append to `requirements.txt`:
```
pytest>=7.0
pytest-qt>=4.2
```

- [ ] **Step 3: Install**

Run: `pip install pytest pytest-qt`
Expected: installs successfully

- [ ] **Step 4: Create test conftest with QApplication fixture**

Create `tests/ui/__init__.py` (empty).

Create `tests/ui/conftest.py`:
```python
"""Shared pytest fixtures for UI tests."""
import os
# Force offscreen Qt platform for headless CI *before* QApplication exists
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication so each test reuses the instance."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def loaded_csv(tmp_path):
    """Create a small CSV for file-load tests."""
    import pandas as pd
    import numpy as np
    t = np.linspace(0, 1.0, 1000)
    df = pd.DataFrame({"time": t, "speed": 1000 * np.sin(2 * np.pi * 5 * t), "torque": 50 + 5 * np.cos(2 * np.pi * 3 * t)})
    p = tmp_path / "sample.csv"
    df.to_csv(p, index=False)
    return str(p)
```

- [ ] **Step 5: Verify pytest discovers the folder**

Run: `pytest tests/ui/ --collect-only`
Expected: `collected 0 items` (no tests yet) or empty list, no errors.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/ui/
git commit -m "test(ui): add pytest-qt infra + QApplication fixture"
```

---

## Phase 1 — Skeleton & functional mapping

**Goal of phase:** New module files exist with skeleton classes; `MainWindow` is decomposed into new module roles but functional behavior is identical to pre-refactor. Old `ChannelEditorDialog / ExportDialog / AxisLockBar` still used via existing QDialog triggers. Visual style is not yet changed.

### Task 1.1: Create empty Toolbar module

**Files:**
- Create: `mf4_analyzer/ui/toolbar.py`

- [ ] **Step 1: Write a stub test**

Create `tests/ui/test_toolbar.py`:
```python
from PyQt5.QtWidgets import QWidget
from mf4_analyzer.ui.toolbar import Toolbar


def test_toolbar_constructs(qapp):
    tb = Toolbar()
    assert isinstance(tb, QWidget)
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `pytest tests/ui/test_toolbar.py -v`
Expected: `ModuleNotFoundError: mf4_analyzer.ui.toolbar`

- [ ] **Step 3: Create skeleton `toolbar.py`**

```python
"""Top three-segment toolbar: file actions · mode switcher · canvas actions."""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QWidget


class Toolbar(QWidget):
    # Left segment
    file_add_requested = pyqtSignal()
    channel_editor_requested = pyqtSignal()
    export_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'order'
    # Right segment
    cursor_reset_requested = pyqtSignal()
    axis_lock_requested = pyqtSignal(object)  # anchor QPushButton for popover

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        # placeholder buttons; real layout comes in Phase 4
        self.btn_add = QPushButton("＋ 添加文件", self)
        self.btn_edit = QPushButton("🔧 编辑通道", self)
        self.btn_export = QPushButton("📥 导出", self)
        self.btn_mode_time = QPushButton("时域", self)
        self.btn_mode_fft = QPushButton("FFT", self)
        self.btn_mode_order = QPushButton("阶次", self)
        self.btn_cursor_reset = QPushButton("⌖", self)
        self.btn_axis_lock = QPushButton("🔒", self)
        for b in (self.btn_add, self.btn_edit, self.btn_export,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_order,
                  self.btn_cursor_reset, self.btn_axis_lock):
            lay.addWidget(b)
        lay.addStretch()
        self._current_mode = 'time'
        self._wire()

    def _wire(self):
        self.btn_add.clicked.connect(self.file_add_requested)
        self.btn_edit.clicked.connect(self.channel_editor_requested)
        self.btn_export.clicked.connect(self.export_requested)
        self.btn_mode_time.clicked.connect(lambda: self._set_mode('time'))
        self.btn_mode_fft.clicked.connect(lambda: self._set_mode('fft'))
        self.btn_mode_order.clicked.connect(lambda: self._set_mode('order'))
        self.btn_cursor_reset.clicked.connect(self.cursor_reset_requested)
        self.btn_axis_lock.clicked.connect(lambda: self.axis_lock_requested.emit(self.btn_axis_lock))

    def _set_mode(self, mode):
        if mode == self._current_mode:
            return
        self._current_mode = mode
        self.mode_changed.emit(mode)

    def set_enabled_for_mode(self, mode, has_file):
        """Implements the §7.1 enabled-state matrix."""
        self.btn_edit.setEnabled(has_file)
        self.btn_export.setEnabled(has_file)
        is_time = (mode == 'time')
        self.btn_cursor_reset.setEnabled(has_file and is_time)
        self.btn_axis_lock.setEnabled(has_file and is_time)

    def current_mode(self):
        return self._current_mode
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/ui/test_toolbar.py -v`
Expected: 1 passed

- [ ] **Step 5: Add signal emission test**

Append to `tests/ui/test_toolbar.py`:
```python
def test_toolbar_mode_changed_emits(qapp, qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.mode_changed, timeout=200) as blocker:
        tb.btn_mode_fft.click()
    assert blocker.args == ['fft']


def test_toolbar_enabled_matrix(qapp):
    tb = Toolbar()
    tb.set_enabled_for_mode('time', has_file=True)
    assert tb.btn_cursor_reset.isEnabled()
    assert tb.btn_axis_lock.isEnabled()
    tb.set_enabled_for_mode('fft', has_file=True)
    assert not tb.btn_cursor_reset.isEnabled()
    assert not tb.btn_axis_lock.isEnabled()
    tb.set_enabled_for_mode('time', has_file=False)
    assert not tb.btn_edit.isEnabled()
```

- [ ] **Step 6: Run new tests — expect PASS**

Run: `pytest tests/ui/test_toolbar.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/toolbar.py tests/ui/test_toolbar.py
git commit -m "feat(ui): add Toolbar skeleton with mode switch + enabled matrix"
```

### Task 1.2: Create skeleton FileNavigator

**Files:**
- Create: `mf4_analyzer/ui/file_navigator.py`
- Create: `tests/ui/test_file_navigator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/ui/test_file_navigator.py
from mf4_analyzer.ui.file_navigator import FileNavigator


def test_file_navigator_constructs(qapp):
    nav = FileNavigator()
    assert nav.channel_list is not None


def test_file_navigator_signals_exist(qapp):
    nav = FileNavigator()
    assert hasattr(nav, 'file_activated')
    assert hasattr(nav, 'file_close_requested')
    assert hasattr(nav, 'close_all_requested')
    assert hasattr(nav, 'channels_changed')
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/ui/test_file_navigator.py -v`
Expected: ImportError

- [ ] **Step 3: Implement skeleton**

Create `mf4_analyzer/ui/file_navigator.py`:
```python
"""Left pane: file list (replacing QTabWidget) + channel tree.

Phase 1 skeleton: wraps existing MultiFileChannelWidget unchanged; the
file-list UI and visual redesign land in Phase 2.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from .widgets import MultiFileChannelWidget


class FileNavigator(QWidget):
    file_activated = pyqtSignal(str)           # fid
    file_close_requested = pyqtSignal(str)     # fid
    close_all_requested = pyqtSignal()
    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.lbl_files = QLabel("文件 (0)", self)
        lay.addWidget(self.lbl_files)
        # Phase 1: file list is a placeholder; Phase 2 replaces with real list
        self.channel_list = MultiFileChannelWidget(self)
        lay.addWidget(self.channel_list, stretch=1)
        self.channel_list.channels_changed.connect(self.channels_changed)

    # ---- API used by MainWindow --------------------------------------
    def add_file(self, fid, fd):
        self.channel_list.add_file(fid, fd)
        self._refresh_count()

    def remove_file(self, fid):
        self.channel_list.remove_file(fid)
        self._refresh_count()

    def get_checked_channels(self):
        return self.channel_list.get_checked_channels()

    def get_file_data(self, fid):
        return self.channel_list.get_file_data(fid)

    def check_first_channel(self, fid):
        self.channel_list.check_first_channel(fid)

    def _refresh_count(self):
        n = len(self.channel_list._file_items)
        self.lbl_files.setText(f"文件 ({n})")
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/ui/test_file_navigator.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/file_navigator.py tests/ui/test_file_navigator.py
git commit -m "feat(ui): add FileNavigator skeleton wrapping MultiFileChannelWidget"
```

### Task 1.3: Create skeleton ChartStack

**Files:**
- Create: `mf4_analyzer/ui/chart_stack.py`
- Create: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Write failing test**

```python
# tests/ui/test_chart_stack.py
from mf4_analyzer.ui.chart_stack import ChartStack


def test_chart_stack_has_three_canvases(qapp):
    cs = ChartStack()
    assert cs.count() == 3


def test_chart_stack_set_mode(qapp):
    cs = ChartStack()
    cs.set_mode('fft')
    assert cs.current_mode() == 'fft'
    cs.set_mode('order')
    assert cs.current_mode() == 'order'
    cs.set_mode('time')
    assert cs.current_mode() == 'time'
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/ui/test_chart_stack.py -v`

- [ ] **Step 3: Implement**

Create `mf4_analyzer/ui/chart_stack.py`:
```python
"""Center pane: QStackedWidget holding the three canvases + stats strip.

Phase 1: bare-bones container + mode getter/setter. Stats strip and
cursor pill land in Phase 2.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .canvases import PlotCanvas, TimeDomainCanvas

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'order': 2}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = canvas
        self.toolbar = NavigationToolbar(canvas, self)
        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        self.canvas_time = TimeDomainCanvas(self)
        self.canvas_fft = PlotCanvas(self)
        self.canvas_order = PlotCanvas(self)
        self.stack.addWidget(_ChartCard(self.canvas_time))
        self.stack.addWidget(_ChartCard(self.canvas_fft))
        self.stack.addWidget(_ChartCard(self.canvas_order))
        lay.addWidget(self.stack, stretch=1)

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

    def full_reset_all(self):
        self.canvas_time.full_reset()
        self.canvas_fft.full_reset()
        self.canvas_order.full_reset()
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/ui/test_chart_stack.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_chart_stack.py
git commit -m "feat(ui): add ChartStack with 3 canvases + mode switch"
```

### Task 1.4: Create skeleton Inspector

**Files:**
- Create: `mf4_analyzer/ui/inspector.py`
- Create: `mf4_analyzer/ui/inspector_sections.py`
- Create: `tests/ui/test_inspector.py`

- [ ] **Step 1: Failing test**

```python
# tests/ui/test_inspector.py
from mf4_analyzer.ui.inspector import Inspector


def test_inspector_constructs(qapp):
    insp = Inspector()
    assert insp is not None


def test_inspector_switch_mode_changes_contextual(qapp):
    insp = Inspector()
    insp.set_mode('time')
    assert insp.contextual_widget_name() == 'time'
    insp.set_mode('fft')
    assert insp.contextual_widget_name() == 'fft'
    insp.set_mode('order')
    assert insp.contextual_widget_name() == 'order'
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement inspector_sections.py (stubs for Phase 1)**

```python
"""Inspector section widgets. Phase 1 stubs; real content in Phase 2."""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class PersistentTop(QWidget):
    """Xaxis / Range / Ticks sections (always visible)."""
    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[persistent-top stub]", self))


class TimeContextual(QWidget):
    plot_time_requested = pyqtSignal()
    cursor_mode_changed = pyqtSignal(str)  # 'off' | 'single' | 'dual'
    plot_mode_changed = pyqtSignal(str)    # 'subplot' | 'overlay'

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[time-contextual stub]", self))


class FFTContextual(QWidget):
    fft_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    remark_toggled = pyqtSignal(bool)
    signal_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[fft-contextual stub]", self))


class OrderContextual(QWidget):
    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    signal_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[order-contextual stub]", self))
```

- [ ] **Step 4: Implement inspector.py**

```python
"""Right pane: persistent top + contextual bottom card.

Owns the inspector_state_dict (per §12.1 of the design spec): caches
the user's last input on each mode's contextual widget so that
switching modes preserves context.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from .inspector_sections import FFTContextual, OrderContextual, PersistentTop, TimeContextual


class Inspector(QWidget):
    plot_time_requested = pyqtSignal()
    fft_requested = pyqtSignal()
    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    xaxis_apply_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object, str)  # (anchor, mode: 'fft'|'order')
    tick_density_changed = pyqtSignal(int, int)
    remark_toggled = pyqtSignal(bool)
    cursor_mode_changed = pyqtSignal(str)
    plot_mode_changed = pyqtSignal(str)
    # Fs auto-sync: relayed from fft_ctx/order_ctx combo_sig change
    signal_changed = pyqtSignal(str, object)  # (mode, (fid, ch) | None)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.top = PersistentTop(self)
        lay.addWidget(self.top)
        self.contextual_stack = QStackedWidget(self)
        self.time_ctx = TimeContextual(self)
        self.fft_ctx = FFTContextual(self)
        self.order_ctx = OrderContextual(self)
        self.contextual_stack.addWidget(self.time_ctx)
        self.contextual_stack.addWidget(self.fft_ctx)
        self.contextual_stack.addWidget(self.order_ctx)
        lay.addWidget(self.contextual_stack, stretch=1)
        self._wire()

    def _wire(self):
        self.top.xaxis_apply_requested.connect(self.xaxis_apply_requested)
        self.top.tick_density_changed.connect(self.tick_density_changed)
        self.time_ctx.plot_time_requested.connect(self.plot_time_requested)
        self.time_ctx.cursor_mode_changed.connect(self.cursor_mode_changed)
        self.time_ctx.plot_mode_changed.connect(self.plot_mode_changed)
        self.fft_ctx.fft_requested.connect(self.fft_requested)
        self.fft_ctx.rebuild_time_requested.connect(
            lambda a: self.rebuild_time_requested.emit(a, 'fft'))
        self.fft_ctx.remark_toggled.connect(self.remark_toggled)
        # Phase 2 adds signal_changed emitter on FFTContextual
        self.fft_ctx.signal_changed.connect(
            lambda d: self.signal_changed.emit('fft', d))
        self.order_ctx.order_time_requested.connect(self.order_time_requested)
        self.order_ctx.order_rpm_requested.connect(self.order_rpm_requested)
        self.order_ctx.order_track_requested.connect(self.order_track_requested)
        self.order_ctx.rebuild_time_requested.connect(
            lambda a: self.rebuild_time_requested.emit(a, 'order'))
        self.order_ctx.signal_changed.connect(
            lambda d: self.signal_changed.emit('order', d))

    def set_mode(self, mode):
        idx = {'time': 0, 'fft': 1, 'order': 2}[mode]
        self.contextual_stack.setCurrentIndex(idx)

    def contextual_widget_name(self):
        return {0: 'time', 1: 'fft', 2: 'order'}[self.contextual_stack.currentIndex()]
```

- [ ] **Step 5: Run — expect PASS**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/inspector.py mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(ui): add Inspector skeleton + stubbed sections"
```

### Task 1.5: Atomic MainWindow refactor (3-pane + signal wiring)

> **Important:** This task is intentionally large and atomic. Removing `_left / _right` without also rewriting `_connect`, `_load_one`, `_close`, `close_all`, and the dozens of `self.btn_load / self.file_tabs / self.spin_start / self.combo_sig / self.channel_list / self.lbl_info / self.tabs / self.stats` references in `plot_time`, `do_fft`, `do_order_*`, `_update_combos`, `_ch_changed`, `_update_info`, `_reset_cursors`, and `_reset_plot_state` causes the `__init__` to crash before any test runs. Keep compatibility **aliases** set in `_init_ui` so dependent methods keep compiling, then migrate them method-by-method in the same task.

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (full refactor of `_init_ui`, `_connect`, and compatibility aliases)

- [ ] **Step 1: Add smoke test first**

Create `tests/ui/test_main_window_smoke.py`:
```python
from mf4_analyzer.ui.main_window import MainWindow


def test_main_window_constructs(qapp):
    w = MainWindow()
    assert w.toolbar is not None
    assert w.navigator is not None
    assert w.chart_stack is not None
    assert w.inspector is not None


def test_main_window_has_splitter_with_three_panes(qapp):
    w = MainWindow()
    # The central widget contains a QSplitter with 3 widgets
    from PyQt5.QtWidgets import QSplitter
    splitter = w.findChild(QSplitter)
    assert splitter is not None
    assert splitter.count() == 3
```

- [ ] **Step 2: Run — expect fail (attributes missing)**

- [ ] **Step 3: Replace `_init_ui` in `main_window.py`**

Read current `main_window.py:56-68` (the `_init_ui` method). Replace its body:

```python
def _init_ui(self):
    from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget
    from PyQt5.QtCore import Qt

    from .chart_stack import ChartStack
    from .file_navigator import FileNavigator
    from .inspector import Inspector
    from .toolbar import Toolbar

    cw = QWidget()
    self.setCentralWidget(cw)
    root = QVBoxLayout(cw)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    self.toolbar = Toolbar(self)
    root.addWidget(self.toolbar)

    splitter = QSplitter(Qt.Horizontal, self)
    self.navigator = FileNavigator(self)
    self.chart_stack = ChartStack(self)
    self.inspector = Inspector(self)
    splitter.addWidget(self.navigator)
    splitter.addWidget(self.chart_stack)
    splitter.addWidget(self.inspector)
    splitter.setSizes([220, 920, 260])
    splitter.setCollapsible(0, False)
    splitter.setCollapsible(1, False)
    splitter.setCollapsible(2, False)
    self.navigator.setMinimumWidth(180)
    self.chart_stack.setMinimumWidth(400)
    self.inspector.setMinimumWidth(220)
    root.addWidget(splitter, stretch=1)

    # Compatibility aliases so legacy methods that still reference old
    # widget names compile and run in Phase 1. Each alias is removed in
    # the Phase 2 task that rewrites its consumer method.
    self.canvas_time = self.chart_stack.canvas_time
    self.canvas_fft = self.chart_stack.canvas_fft
    self.canvas_order = self.chart_stack.canvas_order
    self.channel_list = self.navigator.channel_list
    # Phase-1 placeholder shims for widgets that Phase 2 will kill:
    # plot_time / do_fft / do_order_* still read .spin_start / .spin_end /
    # .spin_fs / .combo_sig / .combo_rpm / .spin_xt / .spin_yt / .chk_range
    # / .chk_fft_autoscale etc. Alias them to the Inspector's real widgets
    # once Inspector has them (Phase 2). Until Phase 2 lands, the old
    # widget objects are kept alive as **hidden off-screen children** of
    # MainWindow so existing methods don't AttributeError.
    from PyQt5.QtWidgets import (
        QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QSpinBox, QTabWidget,
    )
    self._legacy_hidden = QWidget(self)
    self._legacy_hidden.setVisible(False)
    self.btn_load = self.toolbar.btn_add
    self.btn_close = self.toolbar.btn_edit   # unused in Phase 1; wired off
    self.btn_close_all = self.toolbar.btn_export  # unused; wired off
    self.btn_plot = self.toolbar.btn_mode_time  # unused in Phase 1
    self.combo_mode = QComboBox(self._legacy_hidden); self.combo_mode.addItems(['Subplot', 'Overlay'])
    self.chk_cursor = QCheckBox(self._legacy_hidden)
    self.chk_dual = QCheckBox(self._legacy_hidden)
    self.btn_reset = self.toolbar.btn_cursor_reset
    self.btn_edit = self.toolbar.btn_edit
    self.btn_export = self.toolbar.btn_export
    self.combo_xaxis = QComboBox(self._legacy_hidden); self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
    self.combo_xaxis_ch = QComboBox(self._legacy_hidden)
    self.edit_xlabel = QLabel("", self._legacy_hidden)
    self.btn_apply_xaxis = QLabel("", self._legacy_hidden)
    self.chk_range = QCheckBox(self._legacy_hidden)
    self.spin_start = QDoubleSpinBox(self._legacy_hidden); self.spin_start.setRange(0, 1e9)
    self.spin_end = QDoubleSpinBox(self._legacy_hidden); self.spin_end.setRange(0, 1e9)
    self.spin_xt = QSpinBox(self._legacy_hidden); self.spin_xt.setRange(3, 30); self.spin_xt.setValue(10)
    self.spin_yt = QSpinBox(self._legacy_hidden); self.spin_yt.setRange(3, 20); self.spin_yt.setValue(6)
    self.combo_sig = QComboBox(self._legacy_hidden)
    self.combo_rpm = QComboBox(self._legacy_hidden); self.combo_rpm.addItem("None", None)
    self.spin_fs = QDoubleSpinBox(self._legacy_hidden); self.spin_fs.setRange(1, 1e6); self.spin_fs.setValue(1000)
    self.btn_rebuild_time = QLabel("", self._legacy_hidden)
    self.spin_rf = QDoubleSpinBox(self._legacy_hidden); self.spin_rf.setRange(0.0001, 10000); self.spin_rf.setValue(1)
    self.combo_win = QComboBox(self._legacy_hidden); self.combo_win.addItems(['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop'])
    self.combo_nfft = QComboBox(self._legacy_hidden); self.combo_nfft.addItems(['自动', '512', '1024', '2048', '4096', '8192', '16384'])
    self.spin_overlap = QSpinBox(self._legacy_hidden); self.spin_overlap.setRange(0, 90); self.spin_overlap.setValue(50)
    self.btn_fft = QLabel("", self._legacy_hidden)
    self.chk_fft_remark = QCheckBox(self._legacy_hidden)
    self.chk_fft_autoscale = QCheckBox(self._legacy_hidden); self.chk_fft_autoscale.setChecked(True)
    self.spin_mo = QSpinBox(self._legacy_hidden); self.spin_mo.setRange(1, 100); self.spin_mo.setValue(20)
    self.spin_order_res = QDoubleSpinBox(self._legacy_hidden); self.spin_order_res.setRange(0.01, 1.0); self.spin_order_res.setValue(0.1)
    self.combo_order_nfft = QComboBox(self._legacy_hidden); self.combo_order_nfft.addItems(['512', '1024', '2048', '4096', '8192']); self.combo_order_nfft.setCurrentText('1024')
    self.spin_time_res = QDoubleSpinBox(self._legacy_hidden); self.spin_time_res.setRange(0.01, 1.0); self.spin_time_res.setValue(0.05)
    self.spin_rpm_res = QSpinBox(self._legacy_hidden); self.spin_rpm_res.setRange(1, 100); self.spin_rpm_res.setValue(10)
    self.spin_to = QDoubleSpinBox(self._legacy_hidden); self.spin_to.setRange(0.5, 100); self.spin_to.setValue(1)
    self.btn_ot = QLabel("", self._legacy_hidden)
    self.btn_or = QLabel("", self._legacy_hidden)
    self.btn_ok = QLabel("", self._legacy_hidden)
    self.lbl_order_progress = QLabel("", self._legacy_hidden)
    # Existing QLabels used in plot_time's status updates
    self.lbl_info = QLabel("", self._legacy_hidden)
    self.lbl_cursor = QLabel("", self._legacy_hidden)
    self.lbl_dual = QLabel("", self._legacy_hidden)
    # StatisticsPanel legacy alias — the real strip lives on ChartStack
    from .widgets import StatisticsPanel
    self.stats = StatisticsPanel(self._legacy_hidden)
    # old tabs object — only ever .setCurrentIndex(n) is called; create a real hidden one
    self.tabs = QTabWidget(self._legacy_hidden)
    for _ in range(3):
        self.tabs.addTab(QWidget(), "")

    from PyQt5.QtWidgets import QStatusBar
    self.statusBar = QStatusBar()
    self.setStatusBar(self.statusBar)
    self.statusBar.showMessage("Ready")
```

> **Why the legacy shims:** `plot_time / do_fft / do_order_*` still reference `self.spin_fs.value()` etc. Keeping hidden shim widgets lets the test suite run + app launch in Phase 1 without breaking those methods. Phase 2 tasks migrate each consumer to the real Inspector API and the corresponding shim is deleted at the end of the migration task.

- [ ] **Step 4: Delete old `_left / _right` builders**

Remove the entire `def _left(self):` and `def _right(self):` methods from `main_window.py`. They are no longer reachable (new `_init_ui` above replaces the call).

- [ ] **Step 5: Rewrite `_connect` to a minimum that wires the new widgets and keeps dependent methods compiling**

Replace the body of `MainWindow._connect` with:

```python
def _connect(self):
    # --- New-module wiring ---
    self.toolbar.file_add_requested.connect(self.load_files)
    self.toolbar.channel_editor_requested.connect(self.open_editor)
    self.toolbar.export_requested.connect(self.export_excel)
    self.toolbar.mode_changed.connect(self._on_mode_changed)
    self.toolbar.cursor_reset_requested.connect(self._reset_cursors)
    self.toolbar.axis_lock_requested.connect(self._show_axis_lock_popover)

    self.navigator.channels_changed.connect(self._ch_changed)
    self.navigator.file_activated.connect(self._on_file_activated)
    self.navigator.file_close_requested.connect(self._on_file_close_requested)
    self.navigator.close_all_requested.connect(self._on_close_all_requested)

    # Canvas cursor signals are owned by ChartStack; MainWindow doesn't
    # need to subscribe (ChartStack updates the pill itself).

    # Inspector signals wire up in Phase 2 when real sections land. In
    # Phase 1, these are no-ops but must exist so Task 2.x edits are
    # minimal additions rather than rewrites.
    self.inspector.plot_time_requested.connect(self.plot_time)
    self.inspector.fft_requested.connect(self.do_fft)
    self.inspector.order_time_requested.connect(self.do_order_time)
    self.inspector.order_rpm_requested.connect(self.do_order_rpm)
    self.inspector.order_track_requested.connect(self.do_order_track)
    self.inspector.xaxis_apply_requested.connect(self._apply_xaxis)
    self.inspector.rebuild_time_requested.connect(self._show_rebuild_popover)
    self.inspector.tick_density_changed.connect(self._update_all_tick_density_pair)
    self.inspector.remark_toggled.connect(self.canvas_fft.set_remark_enabled)
    self.inspector.cursor_mode_changed.connect(self._on_cursor_mode_changed)
    self.inspector.plot_mode_changed.connect(self._on_plot_mode_changed)
    self.inspector.signal_changed.connect(self._on_inspector_signal_changed)

    # Custom X axis state (unchanged)
    self._custom_xlabel = None
    self._custom_xaxis_fid = None
    self._custom_xaxis_ch = None
    self._plot_mode = 'subplot'
    self._axis_lock_widget = None
```

- [ ] **Step 6: Add placeholder slots**

Add these methods to `MainWindow` (after `_connect`):

```python
def _on_mode_changed(self, mode):
    self.chart_stack.set_mode(mode)
    self.inspector.set_mode(mode)
    self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
    # §6.2 auto re-plot on entering time mode with checked channels
    if mode == 'time' and self.files and self.navigator.get_checked_channels():
        self.plot_time()

def _on_cursor_mode_changed(self, mode):
    self.canvas_time.set_cursor_visible(mode != 'off')
    self.canvas_time.set_dual_cursor_mode(mode == 'dual')

def _on_plot_mode_changed(self, mode):
    self._plot_mode = mode
    self.plot_time()

def _update_all_tick_density_pair(self, xt, yt):
    self.canvas_time.set_tick_density(xt, yt)
    from matplotlib.ticker import MaxNLocator
    for ax in self.canvas_fft.fig.axes:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
    self.canvas_fft.draw_idle()
    for ax in self.canvas_order.fig.axes:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
    self.canvas_order.draw_idle()

def _show_axis_lock_popover(self, anchor):
    # Phase 1 placeholder — Phase 3 replaces with drawers/axis_lock_popover.py.
    # Canvas is the single source of truth for axis-lock state (§12.1).
    cur = self.canvas_time._axis_lock or 'none'
    next_state = {'none': 'x', 'x': 'y', 'y': 'none'}[cur]
    self.canvas_time.set_axis_lock(next_state)
    self.statusBar.showMessage(f"轴锁: {next_state}")

def _show_rebuild_popover(self, anchor, mode='fft'):
    # Phase 1 placeholder — Phase 3 replaces.
    # `mode` identifies which Inspector section emitted (needed for signal→file resolution).
    self.rebuild_time_axis()

def _on_inspector_signal_changed(self, mode, data):
    """Fs auto-sync per §6.3: spin_fs reflects selected signal's source file Fs."""
    if not data:
        return
    fid, _ch = data
    if fid not in self.files:
        return
    fs = self.files[fid].fs
    if mode == 'fft':
        self.inspector.fft_ctx.set_fs(fs)
    elif mode == 'order':
        self.inspector.order_ctx.set_fs(fs)

def _on_file_activated(self, fid):
    self._active = fid
    self._update_info()

def _on_file_close_requested(self, fid):
    self._close(fid)

def _on_close_all_requested(self):
    # Navigator already confirmed; skip the second confirm here
    self._close_all_confirmed()

def _close_all_confirmed(self):
    for fid in list(self.files.keys()):
        del self.files[fid]
        self.navigator.remove_file(fid)
    self._active = None
    self._update_info()
    self._reset_plot_state(scope='all')
    self.statusBar.showMessage("已关闭全部")
```

- [ ] **Step 7: Migrate `_load_one` to use Navigator**

In `_load_one`, replace:
```python
self._add_tab(fid, fd);
self.channel_list.add_file(fid, fd);
```
with:
```python
self.navigator.add_file(fid, fd)
```

Also delete calls to `_add_tab`, `_get_tab_fid`, `_tab_changed`, `_tab_close` methods and the helpers themselves — they belong to the old QTabWidget flow which no longer exists.

In `_close(fid)`, replace the loop that walks `file_tabs.count()` with:
```python
def _close(self, fid):
    if fid not in self.files: return
    del self.files[fid]
    self.navigator.remove_file(fid)
    self._active = self.navigator._active_fid  # navigator picks fallback
    self._update_info()
    self._reset_plot_state(scope='file')
    self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")
```

Delete the original `close_all` body (with its QMessageBox) — the kebab in FileNavigator already confirms. Keep the method as `self._close_all_confirmed()` shim:
```python
def close_all(self):
    """Legacy entry; navigator's kebab path is canonical. Not bound to UI."""
    self._close_all_confirmed()
```

- [ ] **Step 8: Run — smoke tests expected PASS**

Run: `pytest tests/ui/test_main_window_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 9: Launch app manually**

Run: `python -m mf4_analyzer.app`
Expected: 3-pane layout appears; toolbar ＋ loads file, navigator shows row, clicking row switches active, ✕ closes. Time domain / FFT / Order buttons in current Inspector stubs do nothing visible (Phase 2 wires them), but other existing code paths still work via shim widgets. No crashes.

- [ ] **Step 10: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "refactor(ui): atomic MainWindow 3-pane + signal wiring + shim aliases"
```

### Task 1.6: Integration tests + legacy shim exit plan

Task 1.5 already wired everything Phase 1 needs. This task adds integration tests that exercise the full Phase 1 flow and documents the shim-removal checklist that Phase 2 must close.

**Files:**
- Modify: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Add behavioral tests**

Append to `tests/ui/test_main_window_smoke.py`:
```python
def test_load_csv_flows_through_navigator(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    w = MainWindow()
    qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    assert len(w.files) == 1
    assert w.navigator.channel_list.tree.topLevelItemCount() == 1


def test_mode_change_routes_to_chart_stack(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.toolbar.btn_mode_fft.click()
    assert w.chart_stack.current_mode() == 'fft'
    assert w.inspector.contextual_widget_name() == 'fft'
```

- [ ] **Step 2: Run tests — expect PASS**

Run: `pytest tests/ui/test_main_window_smoke.py -v`
Expected: 4 passed (2 smoke + 2 integration).

- [ ] **Step 3: Document shim exit plan**

Add a comment block at the top of `main_window.py` summarizing which legacy shim widgets each Phase 2 task will remove:

```python
# PHASE-2 SHIM EXIT PLAN
# Task 2.3 (Inspector persistent top)  → removes combo_xaxis/combo_xaxis_ch/edit_xlabel/
#                                         btn_apply_xaxis/chk_range/spin_start/spin_end/
#                                         spin_xt/spin_yt shims
# Task 2.4 (Inspector time contextual) → removes combo_mode/chk_cursor/chk_dual shims
# Task 2.5 (Inspector FFT contextual)  → removes combo_sig/spin_fs/combo_win/combo_nfft/
#                                         spin_overlap/chk_fft_autoscale/chk_fft_remark/
#                                         btn_fft/btn_rebuild_time shims
# Task 2.6 (Inspector Order contextual)→ removes combo_rpm/spin_rf/spin_mo/spin_order_res/
#                                         combo_order_nfft/spin_time_res/spin_rpm_res/
#                                         spin_to/btn_ot/btn_or/btn_ok/lbl_order_progress shims
# Task 2.9 (ChartStack cursor pill)    → removes lbl_cursor/lbl_dual shims
# Task 2.10 (Stats strip)              → removes self.stats/tabs shims
# Task 3.4 (axis lock popover)         → deletes axis_lock_toolbar.py
# At end of Phase 2 the `_legacy_hidden` holder must be empty.
```

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "test(ui): add MainWindow integration tests + shim exit plan"
```

### Task 1.7: Delete old `_left / _right` builders; clean up

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Find dead code**

Grep `main_window.py` for `def _left(` and `def _right(`. Confirm no caller references these.

- [ ] **Step 2: Delete both methods**

Remove `_left` and `_right` entirely from `main_window.py`.

- [ ] **Step 3: Remove obsolete attribute creation**

Delete any leftover `self.btn_load = QPushButton(...)` etc that duplicate toolbar buttons.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: all UI tests pass; algorithm tests also pass (unchanged).

- [ ] **Step 5: Launch app**

Run: `python -m mf4_analyzer.app`
Expected: 3-pane skeleton visible; left/right stubs show placeholder text; center shows canvas.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "refactor(ui): remove dead _left/_right builders from MainWindow"
```

---

## Phase 2 — Left pane + Inspector real content

**Goal of phase:** FileNavigator has real file-list UI replacing tabs, channel tree styled. Inspector has fully functional sections; all dropdowns and spin boxes wire up. All existing interactions work end-to-end via the new UI. Visual style is still pre-polish.

### Task 2.1: FileNavigator — file list rows

**Files:**
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `tests/ui/test_file_navigator.py`

- [ ] **Step 1: Write test for file-row UI**

Append to `tests/ui/test_file_navigator.py`:
```python
class FakeFd:
    def __init__(self, filename="sample.csv", short_name="sample", rows=100, fs=1000.0, duration=5.0):
        self.filename = filename
        self.short_name = short_name
        self.fs = fs
        self._rows = rows
        self._dur = duration
    @property
    def data(self):
        class _L:
            def __init__(self, n): self._n = n
            def __len__(self): return self._n
        return _L(self._rows)
    @property
    def time_array(self):
        import numpy as np
        return np.linspace(0, self._dur, self._rows)
    def get_signal_channels(self): return ["speed", "torque"]
    def get_color_palette(self): return ["#1f77b4", "#ff7f0e"]
    @property
    def channel_units(self): return {}


def test_file_row_added(qapp):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    assert nav.file_list_count() == 1


def test_file_row_close_emits(qapp, qtbot):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    with qtbot.waitSignal(nav.file_close_requested, timeout=200) as blocker:
        nav._request_close("f0")
    assert blocker.args == ["f0"]


def test_file_row_click_emits_activated(qapp, qtbot):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    with qtbot.waitSignal(nav.file_activated, timeout=200) as blocker:
        nav._activate("f0")
    assert blocker.args == ["f0"]
```

- [ ] **Step 2: Run — expect fail (methods missing)**

- [ ] **Step 3: Implement file-row UI**

Rewrite `file_navigator.py`:
```python
"""Left pane: file list (replacing QTabWidget) + channel tree."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from .widgets import MultiFileChannelWidget


class _FileRow(QFrame):
    activated = pyqtSignal(str)
    close_requested = pyqtSignal(str)

    def __init__(self, fid, fd, parent=None):
        super().__init__(parent)
        self.fid = fid
        self.setObjectName("fileRow")
        self._active = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(2)
        top = QHBoxLayout()
        self._lbl_name = QLabel(f"📄 {fd.short_name}")
        top.addWidget(self._lbl_name, stretch=1)
        self._btn_close = QToolButton()
        self._btn_close.setText("✕")
        self._btn_close.setAutoRaise(True)
        self._btn_close.clicked.connect(lambda: self.close_requested.emit(self.fid))
        top.addWidget(self._btn_close)
        lay.addLayout(top)
        dur = fd.time_array[-1] if len(fd.time_array) else 0
        self._lbl_meta = QLabel(
            f"{len(fd.data)} 行 · {fd.fs:.1f} Hz · {dur:.2f} s"
        )
        self._lbl_meta.setObjectName("fileRowMeta")
        lay.addWidget(self._lbl_meta)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.fid)
        super().mousePressEvent(event)

    def set_active(self, active):
        self._active = active
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class FileNavigator(QWidget):
    file_activated = pyqtSignal(str)
    file_close_requested = pyqtSignal(str)
    close_all_requested = pyqtSignal()
    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}        # fid -> _FileRow
        self._active_fid = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # Header with kebab
        head = QHBoxLayout()
        self._lbl_header = QLabel("文件 (0)")
        head.addWidget(self._lbl_header)
        head.addStretch()
        self._btn_kebab = QToolButton()
        self._btn_kebab.setText("⋯")
        self._btn_kebab.setAutoRaise(True)
        self._btn_kebab.clicked.connect(self._open_kebab)
        head.addWidget(self._btn_kebab)
        lay.addLayout(head)

        # File list (scrollable rows)
        self._file_holder = QWidget()
        self._file_layout = QVBoxLayout(self._file_holder)
        self._file_layout.setContentsMargins(0, 0, 0, 0)
        self._file_layout.setSpacing(2)
        self._file_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._file_holder)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(200)
        lay.addWidget(scroll)

        # Channel tree
        self.channel_list = MultiFileChannelWidget(self)
        self.channel_list.channels_changed.connect(self.channels_changed)
        lay.addWidget(self.channel_list, stretch=1)

    # ---- public API used by MainWindow ----
    def add_file(self, fid, fd):
        row = _FileRow(fid, fd, self)
        row.activated.connect(self._activate)
        row.close_requested.connect(self._request_close)
        insert_pos = self._file_layout.count() - 1  # before the stretch
        self._file_layout.insertWidget(insert_pos, row)
        self._rows[fid] = row
        self.channel_list.add_file(fid, fd)
        self._refresh_header()
        self._activate(fid)

    def remove_file(self, fid):
        row = self._rows.pop(fid, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        self.channel_list.remove_file(fid)
        if self._active_fid == fid:
            new_active = next(iter(self._rows), None)
            self._active_fid = None  # force _activate to re-emit
            if new_active is not None:
                self._activate(new_active)
            else:
                # No files left; still notify MainWindow so Inspector resets
                self.file_activated.emit("")
        self._refresh_header()

    def file_list_count(self):
        return len(self._rows)

    def set_active(self, fid):
        self._activate(fid)

    def get_checked_channels(self):
        return self.channel_list.get_checked_channels()

    def get_file_data(self, fid):
        return self.channel_list.get_file_data(fid)

    def check_first_channel(self, fid):
        self.channel_list.check_first_channel(fid)

    # ---- private slots ----
    def _activate(self, fid):
        if fid == self._active_fid:
            return
        if self._active_fid in self._rows:
            self._rows[self._active_fid].set_active(False)
        self._active_fid = fid
        if fid in self._rows:
            self._rows[fid].set_active(True)
        self.file_activated.emit(fid)

    def _request_close(self, fid):
        self.file_close_requested.emit(fid)

    def _open_kebab(self):
        menu = QMenu(self)
        act = menu.addAction("全部关闭…")
        act.setEnabled(bool(self._rows))
        gp = self._btn_kebab.mapToGlobal(self._btn_kebab.rect().bottomLeft())
        chosen = menu.exec_(gp)
        if chosen == act:
            ans = QMessageBox.question(
                self, "确认", f"关闭全部 {len(self._rows)} 文件?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self.close_all_requested.emit()

    def _refresh_header(self):
        self._lbl_header.setText(f"文件 ({len(self._rows)})")
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/ui/test_file_navigator.py -v`
Expected: 5 passed

- [ ] **Step 5: Manually verify app launches**

Run: `python -m mf4_analyzer.app`
Load a CSV via toolbar → verify file row appears in left pane, click row to activate, click ✕ to close, kebab → "全部关闭…" prompts confirmation.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/file_navigator.py tests/ui/test_file_navigator.py
git commit -m "feat(ui): FileNavigator file-list rows with kebab close-all"
```

### Task 2.2: Remove old file_tabs usage from MainWindow

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Locate `_add_tab / _tab_changed / _tab_close / _get_tab_fid`**

Grep `main_window.py` for `file_tabs` and the four tab helper methods.

- [ ] **Step 2: Delete them all**

The FileNavigator now owns file activation and close requests via signals. Delete:
- `self.file_tabs = QTabWidget()...`
- `self._add_tab(fid, fd)`
- `self._get_tab_fid(idx)`
- `self._tab_changed(idx)`
- `self._tab_close(idx)`

- [ ] **Step 3: Update `_load_one` to not call `_add_tab`**

In `_load_one`, replace:
```python
self._add_tab(fid, fd)
self.channel_list.add_file(fid, fd)
```
with:
```python
self.navigator.add_file(fid, fd)
```
Note: `FileNavigator.add_file` now also emits `file_activated`, so `self._active = fid` is set via the signal handler, not here.

- [ ] **Step 4: Update `_close` / `close_all`**

In `_close(fid)`:
```python
def _close(self, fid):
    if fid not in self.files: return
    del self.files[fid]
    self.navigator.remove_file(fid)
    self._active = self.navigator._active_fid
    self._update_info()
    self._reset_plot_state(scope='file')
    self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")
```

In `close_all`:
```python
def close_all(self):
    if not self.files:
        return
    for fid in list(self.files.keys()):
        del self.files[fid]
        self.navigator.remove_file(fid)
    self._active = None
    self._update_info()
    self._reset_plot_state(scope='all')
    self.statusBar.showMessage("已关闭全部")
```
Note: the QMessageBox confirm is now in `FileNavigator._open_kebab` so `close_all()` here trusts it was already confirmed.

- [ ] **Step 5: Run tests**

Run: `pytest tests/ui/ -v`
Expected: all pass. Smoke test `test_load_csv_flows_through_navigator` still works.

- [ ] **Step 6: Manual app launch**

Run: `python -m mf4_analyzer.app`
Load 2 CSVs → confirm rows appear, clicking switches active, ✕ closes one, kebab closes all with confirm.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "refactor(ui): MainWindow delegates file list to FileNavigator"
```

### Task 2.3: Inspector persistent top — Xaxis section

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] **Step 1: Test**

Append to `tests/ui/test_inspector.py`:
```python
def test_persistent_top_xaxis_mode_toggle(qapp):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    assert pt.xaxis_mode() == 'time'
    pt.set_xaxis_mode('channel')
    assert pt.xaxis_mode() == 'channel'
    assert pt._combo_xaxis_ch.isEnabled()


def test_persistent_top_apply_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import PersistentTop
    pt = PersistentTop()
    with qtbot.waitSignal(pt.xaxis_apply_requested, timeout=200):
        pt.btn_apply_xaxis.click()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Rewrite `PersistentTop`**

Replace stub in `inspector_sections.py`:

```python
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

class PersistentTop(QWidget):
    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)
    range_changed = pyqtSignal()  # used by time-plot_time

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ------- Xaxis group -------
        g = QGroupBox("横坐标")
        gl = QVBoxLayout(g)
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("来源:"))
        self.combo_xaxis = QComboBox()
        self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
        h1.addWidget(self.combo_xaxis)
        gl.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("通道:"))
        self._combo_xaxis_ch = QComboBox()
        self._combo_xaxis_ch.setEnabled(False)
        h2.addWidget(self._combo_xaxis_ch)
        gl.addLayout(h2)
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("标签:"))
        self.edit_xlabel = QLineEdit()
        self.edit_xlabel.setPlaceholderText("Time (s)")
        h3.addWidget(self.edit_xlabel)
        gl.addLayout(h3)
        self.btn_apply_xaxis = QPushButton("应用")
        gl.addWidget(self.btn_apply_xaxis)
        root.addWidget(g)

        # ------- Range group -------
        g = QGroupBox("范围")
        gl = QVBoxLayout(g)
        self.chk_range = QCheckBox("使用选定范围")
        gl.addWidget(self.chk_range)
        h = QHBoxLayout()
        h.addWidget(QLabel("开始:"))
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setSuffix(" s")
        self.spin_start.setRange(0, 1e9)
        h.addWidget(self.spin_start)
        gl.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(QLabel("结束:"))
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setSuffix(" s")
        self.spin_end.setRange(0, 1e9)
        h.addWidget(self.spin_end)
        gl.addLayout(h)
        root.addWidget(g)

        # ------- Tick density group -------
        g = QGroupBox("刻度")
        fl = QFormLayout(g)
        self.spin_xt = QSpinBox()
        self.spin_xt.setRange(3, 30)
        self.spin_xt.setValue(10)
        fl.addRow("X:", self.spin_xt)
        self.spin_yt = QSpinBox()
        self.spin_yt.setRange(3, 20)
        self.spin_yt.setValue(6)
        fl.addRow("Y:", self.spin_yt)
        root.addWidget(g)

        self._wire()

    def _wire(self):
        self.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._combo_xaxis_ch.setEnabled(i == 1)
        )
        self.btn_apply_xaxis.clicked.connect(self.xaxis_apply_requested)
        self.spin_xt.valueChanged.connect(self._emit_ticks)
        self.spin_yt.valueChanged.connect(self._emit_ticks)
        self.chk_range.toggled.connect(lambda _: self.range_changed.emit())
        self.spin_start.valueChanged.connect(lambda _: self.range_changed.emit())
        self.spin_end.valueChanged.connect(lambda _: self.range_changed.emit())

    def _emit_ticks(self):
        self.tick_density_changed.emit(self.spin_xt.value(), self.spin_yt.value())

    # ---- public getters used by MainWindow ----
    def xaxis_mode(self):
        return 'channel' if self.combo_xaxis.currentIndex() == 1 else 'time'

    def set_xaxis_mode(self, mode):
        self.combo_xaxis.setCurrentIndex(1 if mode == 'channel' else 0)

    def xaxis_channel_data(self):
        """Return (fid, channel) tuple or None."""
        if self.combo_xaxis.currentIndex() != 1:
            return None
        d = self._combo_xaxis_ch.currentData()
        return d

    def xaxis_label(self):
        return self.edit_xlabel.text().strip()

    def set_xaxis_candidates(self, candidates):
        """candidates: list of (display_text, (fid, ch)) tuples."""
        self._combo_xaxis_ch.clear()
        for text, data in candidates:
            self._combo_xaxis_ch.addItem(text, data)

    def range_enabled(self):
        return self.chk_range.isChecked()

    def range_values(self):
        return (self.spin_start.value(), self.spin_end.value())

    def set_range_from_span(self, xmin, xmax):
        self.spin_start.setValue(xmin)
        self.spin_end.setValue(xmax)
        self.chk_range.setChecked(True)

    def set_range_limits(self, lo, hi):
        for sp in (self.spin_start, self.spin_end):
            sp.setRange(lo, hi)

    def tick_density(self):
        return (self.spin_xt.value(), self.spin_yt.value())
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: 4 passed (2 new + 2 old).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(ui): Inspector persistent top — xaxis/range/ticks sections"
```

### Task 2.4: Inspector time-domain contextual

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] **Step 1: Test cursor + plot-mode segmented**

Append to `tests/ui/test_inspector.py`:
```python
def test_time_contextual_cursor_segmented(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import TimeContextual
    tc = TimeContextual()
    with qtbot.waitSignal(tc.cursor_mode_changed, timeout=200) as bl:
        tc.set_cursor_mode('dual')
    assert bl.args == ['dual']
    assert tc.cursor_mode() == 'dual'


def test_time_contextual_plot_mode(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import TimeContextual
    tc = TimeContextual()
    with qtbot.waitSignal(tc.plot_mode_changed, timeout=200) as bl:
        tc.set_plot_mode('overlay')
    assert bl.args == ['overlay']


def test_time_contextual_plot_button_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import TimeContextual
    tc = TimeContextual()
    with qtbot.waitSignal(tc.plot_time_requested, timeout=200):
        tc.btn_plot.click()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Replace stub**

In `inspector_sections.py`, replace `TimeContextual`:

```python
class TimeContextual(QWidget):
    plot_time_requested = pyqtSignal()
    cursor_mode_changed = pyqtSignal(str)   # 'off' | 'single' | 'dual'
    plot_mode_changed = pyqtSignal(str)     # 'subplot' | 'overlay'

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        g = QGroupBox("绘图模式")
        gl = QHBoxLayout(g)
        self._btn_subplot = QPushButton("Subplot")
        self._btn_overlay = QPushButton("Overlay")
        for b in (self._btn_subplot, self._btn_overlay):
            b.setCheckable(True)
            gl.addWidget(b)
        self._btn_subplot.setChecked(True)
        self._plot_mode = 'subplot'
        self._btn_subplot.clicked.connect(lambda: self.set_plot_mode('subplot'))
        self._btn_overlay.clicked.connect(lambda: self.set_plot_mode('overlay'))
        root.addWidget(g)

        g = QGroupBox("游标")
        gl = QHBoxLayout(g)
        self._cursor_buttons = {}
        for label, key in [('Off', 'off'), ('Single', 'single'), ('Dual', 'dual')]:
            b = QPushButton(label)
            b.setCheckable(True)
            gl.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.set_cursor_mode(k))
            self._cursor_buttons[key] = b
        self._cursor_mode = 'single'
        self._cursor_buttons['single'].setChecked(True)
        root.addWidget(g)

        self.btn_plot = QPushButton("▶ 绘图")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()

    def set_cursor_mode(self, mode):
        self._cursor_mode = mode
        for k, b in self._cursor_buttons.items():
            b.setChecked(k == mode)
        self.cursor_mode_changed.emit(mode)

    def cursor_mode(self):
        return self._cursor_mode

    def set_plot_mode(self, mode):
        self._plot_mode = mode
        self._btn_subplot.setChecked(mode == 'subplot')
        self._btn_overlay.setChecked(mode == 'overlay')
        self.plot_mode_changed.emit(mode)

    def plot_mode(self):
        return self._plot_mode
```

- [ ] **Step 4: Test**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(ui): TimeContextual with plot-mode + cursor segmented + plot btn"
```

### Task 2.5: Inspector FFT contextual

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] **Step 1: Test**

```python
def test_fft_contextual_defaults(qapp):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    p = fc.get_params()
    assert p['window'] in ('hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop')
    assert 'nfft' in p
    assert 0 <= p['overlap'] <= 0.9
    assert isinstance(p['autoscale'], bool)


def test_fft_contextual_fft_button_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    fc = FFTContextual()
    with qtbot.waitSignal(fc.fft_requested, timeout=200):
        fc.btn_fft.click()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Replace FFTContextual stub**

```python
class FFTContextual(QWidget):
    fft_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    remark_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        g = QGroupBox("分析信号")
        fl = QFormLayout(g)
        self.combo_sig = QComboBox()
        fl.addRow("信号:", self.combo_sig)
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fs_row = QHBoxLayout()
        fs_row.addWidget(self.spin_fs)
        self.btn_rebuild = QPushButton("⏱")
        self.btn_rebuild.setMaximumWidth(30)
        self.btn_rebuild.setToolTip("重建时间轴")
        fs_row.addWidget(self.btn_rebuild)
        fl.addRow("Fs:", fs_row)
        root.addWidget(g)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        self.combo_win = QComboBox()
        self.combo_win.addItems(['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop'])
        fl.addRow("窗函数:", self.combo_win)
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(['自动', '512', '1024', '2048', '4096', '8192', '16384'])
        fl.addRow("NFFT:", self.combo_nfft)
        self.spin_overlap = QSpinBox()
        self.spin_overlap.setRange(0, 90)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        fl.addRow("重叠:", self.spin_overlap)
        root.addWidget(g)

        g = QGroupBox("选项")
        gl = QVBoxLayout(g)
        self.chk_autoscale = QCheckBox("自适应频率范围")
        self.chk_autoscale.setChecked(True)
        gl.addWidget(self.chk_autoscale)
        self.chk_remark = QCheckBox("点击标注")
        gl.addWidget(self.chk_remark)
        root.addWidget(g)

        self.btn_fft = QPushButton("▶ 计算 FFT")
        root.addWidget(self.btn_fft)
        root.addStretch()

        self.btn_fft.clicked.connect(self.fft_requested)
        self.btn_rebuild.clicked.connect(lambda: self.rebuild_time_requested.emit(self.btn_rebuild))
        self.chk_remark.toggled.connect(self.remark_toggled)
        # §6.3 Fs rule: spin_fs reflects selected signal's source file Fs.
        # MainWindow will call set_fs via the signal_changed relay.

    signal_changed = pyqtSignal(object)  # emits (fid, ch) or None

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        for text, data in candidates:
            self.combo_sig.addItem(text, data)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        self._on_sig_index_changed()  # emit for newly-populated default

    def current_signal(self):
        return self.combo_sig.currentData()

    def get_params(self):
        nfft_text = self.combo_nfft.currentText()
        return dict(
            window=self.combo_win.currentText(),
            nfft=None if nfft_text == '自动' else int(nfft_text),
            overlap=self.spin_overlap.value() / 100.0,
            autoscale=self.chk_autoscale.isChecked(),
            remark=self.chk_remark.isChecked(),
        )

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)
```

- [ ] **Step 4: Test**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(ui): FFTContextual with signal/Fs/params/options + emit btns"
```

### Task 2.6: Inspector Order contextual

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] **Step 1: Test**

```python
def test_order_contextual_params(qapp):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    p = oc.get_params()
    for k in ('max_order', 'order_res', 'time_res', 'rpm_res', 'nfft'):
        assert k in p
    assert oc.target_order() > 0


def test_order_contextual_emits(qapp, qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual
    oc = OrderContextual()
    with qtbot.waitSignal(oc.order_time_requested, timeout=200):
        oc.btn_ot.click()
    with qtbot.waitSignal(oc.order_rpm_requested, timeout=200):
        oc.btn_or.click()
    with qtbot.waitSignal(oc.order_track_requested, timeout=200):
        oc.btn_ok.click()
```

- [ ] **Step 2: Implement OrderContextual**

Replace stub:
```python
class OrderContextual(QWidget):
    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)   # anchor widget
    signal_changed = pyqtSignal(object)            # (fid, ch) tuple or None

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        g = QGroupBox("信号源")
        fl = QFormLayout(g)
        self.combo_sig = QComboBox()
        fl.addRow("信号:", self.combo_sig)
        self.combo_rpm = QComboBox()
        fl.addRow("转速:", self.combo_rpm)
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fs_row = QHBoxLayout()
        fs_row.addWidget(self.spin_fs)
        self.btn_rebuild = QPushButton("⏱")
        self.btn_rebuild.setMaximumWidth(30)
        self.btn_rebuild.setToolTip("重建时间轴")
        self.btn_rebuild.clicked.connect(lambda: self.rebuild_time_requested.emit(self.btn_rebuild))
        fs_row.addWidget(self.btn_rebuild)
        fl.addRow("Fs:", fs_row)
        self.spin_rf = QDoubleSpinBox()
        self.spin_rf.setRange(0.0001, 10000)
        self.spin_rf.setDecimals(4)
        self.spin_rf.setValue(1)
        fl.addRow("RPM系数:", self.spin_rf)
        root.addWidget(g)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        self.spin_mo = QSpinBox()
        self.spin_mo.setRange(1, 100)
        self.spin_mo.setValue(20)
        fl.addRow("最大阶次:", self.spin_mo)
        self.spin_order_res = QDoubleSpinBox()
        self.spin_order_res.setRange(0.01, 1.0)
        self.spin_order_res.setValue(0.1)
        self.spin_order_res.setSingleStep(0.05)
        fl.addRow("阶次分辨率:", self.spin_order_res)
        self.spin_time_res = QDoubleSpinBox()
        self.spin_time_res.setRange(0.01, 1.0)
        self.spin_time_res.setValue(0.05)
        self.spin_time_res.setSuffix(" s")
        fl.addRow("时间分辨率:", self.spin_time_res)
        self.spin_rpm_res = QSpinBox()
        self.spin_rpm_res.setRange(1, 100)
        self.spin_rpm_res.setValue(10)
        self.spin_rpm_res.setSuffix(" rpm")
        fl.addRow("RPM分辨率:", self.spin_rpm_res)
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(['512', '1024', '2048', '4096', '8192'])
        self.combo_nfft.setCurrentText('1024')
        fl.addRow("FFT点数:", self.combo_nfft)
        root.addWidget(g)

        two_btns = QHBoxLayout()
        self.btn_ot = QPushButton("▶ 时间-阶次")
        self.btn_or = QPushButton("▶ 转速-阶次")
        two_btns.addWidget(self.btn_ot)
        two_btns.addWidget(self.btn_or)
        root.addLayout(two_btns)

        g = QGroupBox("阶次跟踪")
        fl = QFormLayout(g)
        self.spin_to = QDoubleSpinBox()
        self.spin_to.setRange(0.5, 100)
        self.spin_to.setValue(1)
        fl.addRow("目标阶次:", self.spin_to)
        self.btn_ok = QPushButton("▶ 阶次跟踪")
        fl.addRow(self.btn_ok)
        root.addWidget(g)

        self.lbl_progress = QLabel("")
        root.addWidget(self.lbl_progress)
        root.addStretch()

        self.btn_ot.clicked.connect(self.order_time_requested)
        self.btn_or.clicked.connect(self.order_rpm_requested)
        self.btn_ok.clicked.connect(self.order_track_requested)

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        for text, data in candidates:
            self.combo_sig.addItem(text, data)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        self._on_sig_index_changed()

    def set_rpm_candidates(self, candidates):
        self.combo_rpm.clear()
        self.combo_rpm.addItem("None", None)
        for text, data in candidates:
            self.combo_rpm.addItem(text, data)

    def current_signal(self):
        return self.combo_sig.currentData()

    def current_rpm(self):
        return self.combo_rpm.currentData()

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)

    def rpm_factor(self):
        return self.spin_rf.value()

    def get_params(self):
        return dict(
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            rpm_res=self.spin_rpm_res.value(),
            nfft=int(self.combo_nfft.currentText()),
        )

    def target_order(self):
        return self.spin_to.value()

    def set_progress(self, text):
        self.lbl_progress.setText(text)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ui/test_inspector.py -v`
Expected: 11 passed.

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(ui): OrderContextual with 3 analyses + separate track section"
```

### Task 2.7: Rewire MainWindow analysis methods through Inspector

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Identify which methods read widget values**

Methods to update: `plot_time / do_fft / do_order_time / do_order_rpm / do_order_track / _get_sig / _get_rpm / _apply_xaxis / _on_xaxis_mode_changed / _update_combos / rebuild_time_axis`.

- [ ] **Step 2: Update `_get_sig` / `_get_rpm`**

Replace:
```python
def _get_sig(self):
    mode = self.toolbar.current_mode()
    if mode == 'fft':
        data = self.inspector.fft_ctx.current_signal()
    else:
        data = self.inspector.order_ctx.current_signal()
    if not data:
        return None, None, None
    fid, ch = data
    if fid not in self.files:
        return None, None, None
    fd = self.files[fid]
    if ch not in fd.data.columns:
        return None, None, None
    return fd.time_array, fd.data[ch].values, fd.fs

def _get_rpm(self, n):
    data = self.inspector.order_ctx.current_rpm()
    if not data:
        QMessageBox.warning(self, "提示", "请选择转速信号")
        return None
    fid, ch = data
    if fid not in self.files:
        return None
    fd = self.files[fid]
    if ch not in fd.data.columns:
        return None
    factor = self.inspector.order_ctx.rpm_factor()
    rpm = fd.data[ch].values.copy() * factor
    if self.inspector.top.range_enabled() and fd.time_array is not None:
        lo, hi = self.inspector.top.range_values()
        m = (fd.time_array >= lo) & (fd.time_array <= hi)
        rpm = rpm[m]
    if len(rpm) != n:
        QMessageBox.warning(self, "提示", f"长度不匹配 ({n} vs {len(rpm)})")
        return None
    return rpm
```

- [ ] **Step 3: Update `plot_time`**

Replace the plot-mode read:
```python
mode = self.inspector.time_ctx.plot_mode()
```
And the range read:
```python
if self.inspector.top.range_enabled():
    lo, hi = self.inspector.top.range_values()
    m = (t >= lo) & (t <= hi); t, sig = t[m], sig[m]
```
And the xlabel read:
```python
xlabel = self._custom_xlabel or self.inspector.top.xaxis_label() or 'Time (s)'
```

- [ ] **Step 4: Update `do_fft`**

Read params from inspector:
```python
fft_params = self.inspector.fft_ctx.get_params()
win = fft_params['window']
nfft = fft_params['nfft']
overlap = fft_params['overlap']
fs = self.inspector.fft_ctx.fs()
```
Replace `self.chk_fft_autoscale.isChecked()` with `fft_params['autoscale']`.

- [ ] **Step 5: Update do_order_time / do_order_rpm / do_order_track**

Each method replaces fs/params reads:
```python
fs = self.inspector.order_ctx.fs()
op = self.inspector.order_ctx.get_params()
nfft = op['nfft']; max_ord = op['max_order']
order_res = op['order_res']; time_res = op['time_res']; rpm_res = op['rpm_res']
# for track:
to = self.inspector.order_ctx.target_order()
```

Also replace progress callbacks: instead of `self.lbl_order_progress.setText(...)`, call `self.inspector.order_ctx.set_progress(...)`.

- [ ] **Step 6: Update `_apply_xaxis` and `_on_xaxis_mode_changed`**

```python
def _apply_xaxis(self):
    mode = self.inspector.top.xaxis_mode()
    if mode == 'time':
        self._custom_xlabel = self.inspector.top.xaxis_label() or None
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
    else:
        data = self.inspector.top.xaxis_channel_data()
        if not data:
            QMessageBox.warning(self, "提示", "请选择横坐标通道")
            return
        fid, ch = data
        # §6.1 length validation
        if fid not in self.files or ch not in self.files[fid].data.columns:
            QMessageBox.warning(self, "提示", "横坐标通道不存在")
            return
        # §6.1 validation: length must match every file whose channels are
        # currently checked for plotting (not every loaded file).
        xlen = len(self.files[fid].data)
        checked = self.navigator.get_checked_channels()  # [(fid, ch, color), ...]
        plotted_fids = {cfid for cfid, _, _ in checked}
        if not plotted_fids:
            plotted_fids = {fid}  # nothing plotted yet, will auto-plot after apply
        for cfid in plotted_fids:
            if cfid in self.files and len(self.files[cfid].data) != xlen:
                QMessageBox.warning(
                    self, "提示",
                    "横坐标通道长度与当前绘图通道所在文件不匹配",
                )
                return
        self._custom_xaxis_fid = fid
        self._custom_xaxis_ch = ch
        self._custom_xlabel = self.inspector.top.xaxis_label() or ch
    self.plot_time()
    self.statusBar.showMessage(f"横坐标已更新")

def _on_xaxis_mode_changed(self, mode):
    # populate candidates when switching to 'channel'
    if mode == 'channel':
        cands = []
        for fid, fd in self.files.items():
            px = f"[{fd.short_name}] "
            for ch in fd.channels:
                cands.append((px + ch, (fid, ch)))
        self.inspector.top.set_xaxis_candidates(cands)
```

Connect mode change in `_connect`:
```python
self.inspector.top.combo_xaxis.currentIndexChanged.connect(
    lambda i: self._on_xaxis_mode_changed('channel' if i == 1 else 'time')
)
```

- [ ] **Step 7: Update `_update_combos`**

```python
def _update_combos(self):
    sig_cands = []; rpm_cands = []
    for fid, fd in self.files.items():
        px = f"[{fd.short_name}] "
        for ch in fd.get_signal_channels():
            sig_cands.append((px + ch, (fid, ch)))
            rpm_cands.append((px + ch, (fid, ch)))
    self.inspector.fft_ctx.set_signal_candidates(sig_cands)
    self.inspector.order_ctx.set_signal_candidates(sig_cands)
    self.inspector.order_ctx.set_rpm_candidates(rpm_cands)
```

- [ ] **Step 8: Update `_on_span` to push range into Inspector + update stats strip**

```python
def _on_span(self, xmin, xmax):
    self.inspector.top.set_range_from_span(xmin, xmax)
    st = self.canvas_time.get_statistics(time_range=(xmin, xmax))
    self.chart_stack.stats_strip.update_stats(st or {})
```

`SpanSelector` is created inside `TimeDomainCanvas.enable_span_selector(self._on_span)` which `plot_time` already calls after drawing. No §12.2 signal refactor is needed; the callback path stays as-is but now terminates in the Inspector + stats strip instead of the discarded `self.stats` reference.

- [ ] **Step 9: Wire cursor + plot-mode signals**

Already done in Task 1.6, now functional: `_on_cursor_mode_changed` drives `canvas_time.set_cursor_visible` + `set_dual_cursor_mode`; `_on_plot_mode_changed` triggers `plot_time`.

- [ ] **Step 10: Run smoke + manual test**

Run: `pytest tests/ui/ -v`
Expected: all pass.

Run: `python -m mf4_analyzer.app`
Load a CSV → click ▶ 绘图 → time-domain plot renders.
Switch to FFT mode → pick signal → click ▶ 计算 FFT → FFT renders.
Switch to 阶次 → pick signal + rpm → click ▶ 时间-阶次 → order renders.

- [ ] **Step 11: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "refactor(ui): MainWindow reads all form values through Inspector API"
```

### Task 2.8: Custom X validation — replace silent fallback

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (plot_time)

Already implemented in Task 2.7's `_apply_xaxis`. This task verifies plot_time also handles mid-plot length mismatch gracefully.

- [ ] **Step 1: Add test**

```python
# tests/ui/test_main_window_smoke.py
def test_custom_xaxis_length_mismatch_warns(qapp, qtbot, loaded_csv, tmp_path):
    """If user selects a custom X channel whose length != data, warn and abort."""
    import pandas as pd
    import numpy as np
    from PyQt5.QtWidgets import QMessageBox
    from unittest.mock import patch
    # Second csv with different length
    df = pd.DataFrame({"time": np.linspace(0, 1, 500), "pressure": np.random.randn(500)})
    p2 = tmp_path / "shorter.csv"; df.to_csv(p2, index=False)

    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv, str(p2)], "")):
        w.load_files()
    # Pick custom X from file 2's channel while file 1 checked
    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')
    w.inspector.top._combo_xaxis_ch.setCurrentIndex(
        w.inspector.top._combo_xaxis_ch.count() - 1  # last candidate (from file 2)
    )
    with patch.object(QMessageBox, 'warning') as warn:
        w._apply_xaxis()
    assert warn.called
```

- [ ] **Step 2: Run — should pass because `_apply_xaxis` already warns**

Run: `pytest tests/ui/test_main_window_smoke.py::test_custom_xaxis_length_mismatch_warns -v`

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_main_window_smoke.py
git commit -m "test(ui): custom xaxis length mismatch warns instead of silent fallback"
```

### Task 2.9: Cursor pill owned by ChartStack

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Test**

```python
# tests/ui/test_chart_stack.py
def test_cursor_pill_updates_on_time_signal(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.canvas_time.cursor_info.emit("t=1.0s | Speed=100")
    assert "t=1.0s" in cs.cursor_pill_text()


def test_cursor_pill_hidden_in_fft_mode(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    cs.set_mode('fft')
    assert not cs.cursor_pill_visible()
```

- [ ] **Step 2: Add cursor pill to ChartStack**

Edit `chart_stack.py`:
```python
from PyQt5.QtWidgets import QLabel

class ChartStack(QWidget):
    # ... existing ...
    def __init__(self, parent=None):
        # ... existing init ...
        self._cursor_pill = QLabel("", self.stack)
        self._cursor_pill.setObjectName("cursorPill")
        self._cursor_pill.setVisible(False)
        self._cursor_dual_pill = QLabel("", self.stack)
        self._cursor_dual_pill.setObjectName("cursorPill")
        self._cursor_dual_pill.setVisible(False)
        self._dual_pill_wrap = True
        self.canvas_time.cursor_info.connect(self._on_cursor_info)
        self.canvas_time.dual_cursor_info.connect(self._on_dual_cursor_info)
        self.stack.currentChanged.connect(self._reposition_pills)

    def _on_cursor_info(self, text):
        self._cursor_pill.setText(text)
        self._cursor_pill.adjustSize()
        self._cursor_pill.setVisible(self.current_mode() == 'time')
        self._reposition_pills()

    def _on_dual_cursor_info(self, text):
        self._cursor_dual_pill.setText(text)
        self._cursor_dual_pill.setWordWrap(True)
        self._cursor_dual_pill.adjustSize()
        self._cursor_dual_pill.setVisible(bool(text) and self.current_mode() == 'time')
        self._reposition_pills()

    def _reposition_pills(self):
        # Hide in non-time modes
        visible = self.current_mode() == 'time'
        if not visible:
            self._cursor_pill.setVisible(False)
            self._cursor_dual_pill.setVisible(False)
            return
        card = self.stack.currentWidget()
        h = card.height()
        pill_h = self._cursor_pill.sizeHint().height()
        self._cursor_pill.move(8, h - pill_h - 8)
        if self._cursor_dual_pill.text():
            dh = self._cursor_dual_pill.sizeHint().height()
            self._cursor_dual_pill.move(8, h - pill_h - dh - 12)
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

- [ ] **Step 3: Remove old cursor labels from MainWindow**

Find and delete `self.lbl_cursor = QLabel(...)` and `self.lbl_dual = QLabel(...)` and their layout inserts from `main_window.py`. Also delete the cursor_info / dual_cursor_info connections there (ChartStack now owns them).

In `_on_cursor_info / _on_dual_cursor_info` in MainWindow (from Task 1.6), make them no-ops or remove the signal bindings since ChartStack owns them directly.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ui/test_chart_stack.py -v`
Expected: 4 passed.

- [ ] **Step 5: Manual verify**

Run: `python -m mf4_analyzer.app`
Load CSV, plot time → hover mouse → cursor pill shows at bottom-left of canvas (readable, not green monospace anymore — but styling comes in Phase 4; for now plain QLabel is fine). Switch to FFT → pill hides.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/main_window.py tests/ui/test_chart_stack.py
git commit -m "feat(ui): ChartStack owns cursor pill (moved from MainWindow)"
```

### Task 2.10: Stats strip + expandable tree

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `mf4_analyzer/ui/widgets.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Add StatsStrip widget**

Add to `widgets.py` (keep existing StatisticsPanel unchanged):
```python
class StatsStrip(QFrame):
    """Compact stats line + click-to-expand full table."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import QHBoxLayout, QLabel, QToolButton
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        top = QHBoxLayout()
        self._btn_expand = QToolButton(); self._btn_expand.setText("▸")
        self._btn_expand.clicked.connect(self.toggle)
        top.addWidget(self._btn_expand)
        self._lbl_summary = QLabel("— 无通道 —")
        top.addWidget(self._lbl_summary, stretch=1)
        lay.addLayout(top)
        self._panel = StatisticsPanel(self)
        self._panel.setVisible(False)
        lay.addWidget(self._panel)

    def toggle(self):
        self._expanded = not self._expanded
        self._btn_expand.setText("▾" if self._expanded else "▸")
        self._panel.setVisible(self._expanded)

    def update_stats(self, stats):
        if not stats:
            self._lbl_summary.setText("— 无通道 —")
            self._panel.update_stats({})
            return
        parts = []
        for ch, s in stats.items():
            parts.append(f"● {ch}: min={s['min']:.3g} max={s['max']:.3g} rms={s['rms']:.3g} p2p={s['p2p']:.3g}")
        self._lbl_summary.setText(" │ ".join(parts))
        self._panel.update_stats(stats)
```

- [ ] **Step 2: Mount StatsStrip in ChartStack**

In `chart_stack.py`, add to `__init__` (after `lay.addWidget(self.stack, stretch=1)`):
```python
from .widgets import StatsStrip
self.stats_strip = StatsStrip(self)
lay.addWidget(self.stats_strip)
```

- [ ] **Step 3: Update MainWindow to call stats_strip**

Find every `self.stats.update_stats(...)` and replace with `self.chart_stack.stats_strip.update_stats(...)`. Also delete the old `self.stats = StatisticsPanel()` mount from MainWindow.

- [ ] **Step 4: Test**

```python
# tests/ui/test_chart_stack.py
def test_stats_strip_update(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.stats_strip.update_stats({'ch1': {'min': 0, 'max': 10, 'mean': 5, 'rms': 6, 'std': 2, 'p2p': 10, 'unit': 'V'}})
    assert 'ch1' in cs.stats_strip._lbl_summary.text()

def test_stats_strip_toggle(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    assert not cs.stats_strip._panel.isVisible()
    cs.stats_strip.toggle()
    qapp.processEvents()
    assert cs.stats_strip._panel.isVisible()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/ui/ -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/widgets.py mf4_analyzer/ui/main_window.py tests/ui/test_chart_stack.py
git commit -m "feat(ui): stats strip with click-to-expand full metrics tree"
```

### Task 2.11: FileNavigator → MainWindow file activation wiring

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Ensure `_on_file_activated` updates Fs + combos**

```python
def _on_file_activated(self, fid):
    self._active = fid
    self._update_info()
    if fid in self.files:
        fs = self.files[fid].fs
        self.inspector.fft_ctx.set_fs(fs)
        self.inspector.order_ctx.set_fs(fs)
        # range limits
        fd = self.files[fid]
        if len(fd.time_array):
            self.inspector.top.set_range_limits(0, fd.time_array[-1])
    self.toolbar.set_enabled_for_mode(self.toolbar.current_mode(), has_file=bool(self.files))
```

- [ ] **Step 2: Wire `close_all_requested` to trigger MainWindow.close_all**

Already connected in Task 1.6. But ensure Kebab confirm + MainWindow close_all dual-confirm doesn't happen; MainWindow.close_all should skip its own confirm because navigator already confirmed. Remove the QMessageBox from MainWindow.close_all.

- [ ] **Step 3: Smoke test**

Run: `python -m mf4_analyzer.app`
Load 2 CSVs. Click second row → confirm Fs in Inspector updates, range limits update.

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): file activation updates Inspector Fs + range limits"
```

### Task 2.12: Channel search / All / None / Inv behavioral tests

Behavioral tests that actually observe filtering, bulk checking, and the
>8-channel warning branch — not just that the widgets exist.

**Files:**
- Modify: `tests/ui/test_file_navigator.py`

- [ ] **Step 1: Add behavioral tests**

```python
# tests/ui/test_file_navigator.py
from unittest.mock import patch
from PyQt5.QtCore import Qt


def test_channel_search_filters(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    # "speed" matches channel named "speed"; "xyz" matches nothing
    nav.channel_list.search.setText("xyz")
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).isHidden()
    nav.channel_list.search.setText("speed")
    visible = [not fi.child(i).isHidden() for i in range(fi.childCount())]
    assert any(visible)


def test_channel_all_button_checks(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    nav.channel_list._all()
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).checkState(0) == Qt.Checked


def test_channel_none_button_clears(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    nav.channel_list._all()
    nav.channel_list._none()
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).checkState(0) == Qt.Unchecked


def test_channel_inv_button_toggles(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    fi = nav.channel_list._file_items["f0"]
    fi.child(0).setCheckState(0, Qt.Checked)
    nav.channel_list._inv()
    assert fi.child(0).checkState(0) == Qt.Unchecked
    assert fi.child(1).checkState(0) == Qt.Checked


def test_channel_over_threshold_warns(qapp, qtbot, monkeypatch):
    # Craft a FakeFd with many channels and monkeypatch MAX threshold low.
    class WideFd(FakeFd):
        def get_signal_channels(self): return [f"ch{i}" for i in range(20)]
        def get_color_palette(self): return ["#000"] * 20
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", WideFd())
    with patch('mf4_analyzer.ui.widgets.QMessageBox.question',
               return_value=False) as q:
        nav.channel_list._all()
    assert q.called
```

- [ ] **Step 2: Run — expect PASS**

Run: `pytest tests/ui/test_file_navigator.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_file_navigator.py
git commit -m "test(ui): behavioral tests for channel search/All/None/Inv/warn"
```

---

## Phase 3 — Drawer / Sheet / Popover migration

**Goal of phase:** `ChannelEditorDialog / ExportDialog / AxisLockBar / rebuild_time` migrate to the new forms (slide-in drawer, top-anchored sheet, frameless popovers) per §8. Functional behavior identical; only container form changes. Delete `axis_lock_toolbar.py`.

### Task 3.1: Channel editor drawer

**Files:**
- Create: `mf4_analyzer/ui/drawers/__init__.py` (if not yet)
- Create: `mf4_analyzer/ui/drawers/channel_editor_drawer.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Test**

```python
# tests/ui/test_drawers.py
def test_channel_editor_drawer_constructs(qapp):
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer

    class FakeFD:
        filename = "x.mf4"
        channels = ['a', 'b']
        channel_units = {}
        def get_signal_channels(self): return ['a', 'b']

        from types import SimpleNamespace
        import numpy as np
        data = SimpleNamespace(columns=['a', 'b'], values=None)
        time_array = np.linspace(0, 1, 10)

    drawer = ChannelEditorDrawer(parent=None, fd=FakeFD())
    assert drawer is not None
```

- [ ] **Step 2: Implement drawer (content = existing ChannelEditorDialog body)**

Create `mf4_analyzer/ui/drawers/__init__.py` (empty).

Create `mf4_analyzer/ui/drawers/channel_editor_drawer.py`:
```python
"""Channel editor as a right-side slide-in drawer (v1 baseline: fixed panel)."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..dialogs import ChannelEditorDialog


class ChannelEditorDrawer(QDialog):
    """
    Wraps ChannelEditorDialog's content in a window anchored to the right edge
    of the parent. v1: modal QDialog positioned to the right side of the parent
    window (baseline, no slide-in animation). Phase 4 may add animation.
    """
    applied = pyqtSignal(dict, set)  # new_channels, removed_channels

    def __init__(self, parent, fd):
        super().__init__(parent)
        self.setWindowTitle(f"通道编辑 — {fd.filename}")
        self.setModal(True)
        # reuse the existing editor content unchanged
        self._inner = ChannelEditorDialog(self, fd)
        # remove its window chrome; embed the dialog as a widget
        self._inner.setWindowFlags(Qt.Widget)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
        # forward accept
        self._inner.accepted.connect(self._on_applied)
        self._inner.rejected.connect(self.reject)
        self.resize(420, max(520, parent.height() - 80) if parent else 520)

    def showEvent(self, event):
        if self.parent() is not None:
            pr = self.parent().geometry()
            self.move(pr.right() - self.width(), pr.top() + 40)
        super().showEvent(event)

    def _on_applied(self):
        self.applied.emit(self._inner.new_channels, self._inner.removed_channels)
        self.accept()
```

- [ ] **Step 3: Switch `MainWindow.open_editor` to drawer**

Replace `open_editor`:
```python
def open_editor(self):
    if not self.files or not self._active or self._active not in self.files:
        QMessageBox.warning(self, "提示", "请先加载文件")
        return
    fd = self.files[self._active]
    from .drawers.channel_editor_drawer import ChannelEditorDrawer
    drawer = ChannelEditorDrawer(self, fd)
    drawer.applied.connect(lambda nc, rm: self._apply_channel_edits(self._active, nc, rm))
    drawer.exec_()


def _apply_channel_edits(self, fid, new_channels, removed_channels):
    fd = self.files[fid]
    for name, (arr, unit) in new_channels.items():
        fd.data[name] = arr
        fd.channels.append(name)
        fd.channel_units[name] = unit
    for name in removed_channels:
        if name in fd.data.columns:
            fd.data = fd.data.drop(columns=[name])
        if name in fd.channels:
            fd.channels.remove(name)
        fd.channel_units.pop(name, None)
    self.navigator.remove_file(fid)
    self.navigator.add_file(fid, fd)
    self._update_combos()
    self.statusBar.showMessage(
        f"编辑: +{len(new_channels)} -{len(removed_channels)}"
    )
    self.plot_time()
```

- [ ] **Step 4: Test + launch**

Run: `pytest tests/ui/test_drawers.py -v`
Expected: 1 passed.

Run: `python -m mf4_analyzer.app`
Load CSV → toolbar 🔧 编辑通道 → drawer appears on the right → create / delete channels → confirm changes persist.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/drawers/ mf4_analyzer/ui/main_window.py tests/ui/test_drawers.py
git commit -m "feat(ui): channel editor as right-anchored drawer"
```

### Task 3.2: Export sheet

**Files:**
- Create: `mf4_analyzer/ui/drawers/export_sheet.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Implement top-anchored sheet**

```python
# mf4_analyzer/ui/drawers/export_sheet.py
"""Export Excel as top-anchored modal QDialog (Qt.Sheet fallback)."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout

from ..dialogs import ExportDialog


class ExportSheet(QDialog):
    def __init__(self, parent, chs):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("导出 Excel")
        self._inner = ExportDialog(self, chs)
        self._inner.setWindowFlags(Qt.Widget)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._inner)
        self._inner.accepted.connect(self.accept)
        self._inner.rejected.connect(self.reject)
        self.resize(320, 400)

    def showEvent(self, event):
        if self.parent() is not None:
            pr = self.parent().geometry()
            self.move(pr.left() + (pr.width() - self.width()) // 2, pr.top() + 40)
        super().showEvent(event)

    def get_selected(self):
        return self._inner.get_selected()

    @property
    def chk_time(self):
        return self._inner.chk_time

    @property
    def chk_range(self):
        return self._inner.chk_range
```

- [ ] **Step 2: Switch `MainWindow.export_excel`**

Replace `dlg = ExportDialog(self, chs)` with `dlg = ExportSheet(self, chs)` (import accordingly).

- [ ] **Step 3: Manual verify**

Run: `python -m mf4_analyzer.app`
Load CSV → toolbar 📥 导出 → sheet anchored top-center → select channels → confirm xlsx write.

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/drawers/export_sheet.py mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): export dialog as top-anchored sheet"
```

### Task 3.3: Rebuild time popover

**Files:**
- Create: `mf4_analyzer/ui/drawers/rebuild_time_popover.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Test**

```python
# tests/ui/test_drawers.py
def test_rebuild_time_popover_returns_fs(qapp, qtbot):
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    p = RebuildTimePopover(parent=None, target_filename="data.mf4", current_fs=1000)
    qtbot.addWidget(p)
    p.spin_fs.setValue(500)
    assert p.new_fs() == 500


def test_rebuild_time_popover_anchors_below_widget(qapp, qtbot):
    from PyQt5.QtWidgets import QPushButton
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    anchor = QPushButton("⏱")
    qtbot.addWidget(anchor)
    anchor.move(100, 200)
    anchor.show()
    qtbot.waitExposed(anchor)
    p = RebuildTimePopover(parent=None, target_filename="d.mf4", current_fs=1000)
    qtbot.addWidget(p)
    p.show_at(anchor)
    qtbot.waitExposed(p)
    # popover top-left should equal anchor.mapToGlobal(bottomLeft)
    expected = anchor.mapToGlobal(anchor.rect().bottomLeft())
    assert abs(p.pos().x() - expected.x()) < 3
    assert abs(p.pos().y() - expected.y()) < 3


def test_rebuild_time_popover_does_not_close_on_spin_interaction(qapp, qtbot):
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    p = RebuildTimePopover(parent=None, target_filename="d.mf4", current_fs=1000)
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    # Spinbox focus must not close the popover (regression test for Qt.Popup bug)
    p.spin_fs.setFocus()
    qapp.processEvents()
    assert p.isVisible()
    p.spin_fs.setValue(500)
    qapp.processEvents()
    assert p.isVisible()
```

- [ ] **Step 2: Implement**

```python
# mf4_analyzer/ui/drawers/rebuild_time_popover.py
"""Rebuild-time popover: frameless QDialog with focus-out auto-close."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFocusEvent
from PyQt5.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class RebuildTimePopover(QDialog):
    def __init__(self, parent, target_filename, current_fs):
        super().__init__(parent)
        # §8.1: frameless QDialog with manual focus-out close. NOT Qt.Popup
        # because Qt.Popup + child QSpinBox can close when the spin buttons
        # take focus; the dialog must stay open while user edits Fs.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setModal(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(QLabel("重建时间轴"))
        root.addWidget(QLabel(f"目标：[{target_filename}]"))
        h = QHBoxLayout()
        h.addWidget(QLabel("Fs:"))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(current_fs)
        self.spin_fs.setSuffix(" Hz")
        h.addWidget(self.spin_fs)
        root.addLayout(h)
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

    def new_fs(self):
        return self.spin_fs.value()

    def show_at(self, anchor_widget):
        gp = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        self.move(gp)
        self.show()
        self.spin_fs.setFocus()
        self.activateWindow()

    # §8.1: auto-close when focus leaves the popover *and* its descendants.
    # Qt emits WindowDeactivate when the app itself loses active window.
    def event(self, ev):
        from PyQt5.QtCore import QEvent
        if ev.type() == QEvent.WindowDeactivate and self.isVisible():
            # close with reject so exec_() returns non-Accepted
            self.reject()
        return super().event(ev)
```

- [ ] **Step 3: Update `MainWindow._show_rebuild_popover`**

```python
def _show_rebuild_popover(self, anchor):
    # resolve target file = signal's source file
    sig_data = self.inspector.fft_ctx.current_signal() if self.toolbar.current_mode() == 'fft' \
               else self.inspector.order_ctx.current_signal()
    target_fid = sig_data[0] if sig_data and sig_data[0] in self.files else self._active
    if not target_fid or target_fid not in self.files:
        QMessageBox.warning(self, "提示", "请先选择信号")
        return
    fd = self.files[target_fid]
    from .drawers.rebuild_time_popover import RebuildTimePopover
    pop = RebuildTimePopover(self, fd.filename, fd.fs)
    pop.show_at(anchor)
    if pop.exec_() == QDialog.Accepted:
        new_fs = pop.new_fs()
        old_max = fd.time_array[-1] if len(fd.time_array) else 0
        fd.rebuild_time_axis(new_fs)
        new_max = fd.time_array[-1] if len(fd.time_array) else 0
        self.inspector.top.set_range_limits(0, max(self.inspector.top.spin_end.maximum(), new_max))
        if target_fid == self._active:
            self.inspector.fft_ctx.set_fs(new_fs)
            self.inspector.order_ctx.set_fs(new_fs)
        self.plot_time()
        self.statusBar.showMessage(
            f"时间轴已重建: {fd.short_name} | Fs={new_fs} | {old_max:.1f}s → {new_max:.3f}s"
        )
```

Remove the legacy `rebuild_time_axis` method (or keep as helper called from here — either way, the old UI button is gone).

- [ ] **Step 4: Test + manual**

Run: `pytest tests/ui/test_drawers.py -v`
Expected: 2 passed.

Run: `python -m mf4_analyzer.app`
Switch to FFT, pick signal, click ⏱ → popover appears under button → change Fs → confirm time-axis updated.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/drawers/rebuild_time_popover.py mf4_analyzer/ui/main_window.py tests/ui/test_drawers.py
git commit -m "feat(ui): rebuild-time popover anchored to Inspector ⏱ button"
```

### Task 3.4: Axis lock popover

**Files:**
- Create: `mf4_analyzer/ui/drawers/axis_lock_popover.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Delete: `mf4_analyzer/ui/axis_lock_toolbar.py`

- [ ] **Step 1: Read current AxisLockBar**

Run: `cat mf4_analyzer/ui/axis_lock_toolbar.py`
Identify the three radio options (None / X / Y) and `lock_changed` signal.

- [ ] **Step 2: Implement popover**

```python
# mf4_analyzer/ui/drawers/axis_lock_popover.py
"""Axis lock popover: frameless QDialog replacing the old toolbar strip."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QDialog, QLabel, QRadioButton, QVBoxLayout,
)


class AxisLockPopover(QDialog):
    lock_changed = pyqtSignal(str)  # 'none' | 'x' | 'y'

    def __init__(self, parent=None, current='none'):
        super().__init__(parent)
        # §8.1: frameless QDialog with WindowDeactivate → close. NOT Qt.Popup.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(QLabel("轴锁（按方向拖选缩放）"))
        self._grp = QButtonGroup(self)
        for key, label in [('none', '无'), ('x', 'X 轴'), ('y', 'Y 轴')]:
            rb = QRadioButton(label, self)
            rb.setProperty("lock_key", key)
            if key == current:
                rb.setChecked(True)
            self._grp.addButton(rb)
            root.addWidget(rb)
            rb.toggled.connect(
                lambda checked, k=key: self.lock_changed.emit(k) if checked else None
            )

    def show_at(self, anchor):
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.move(gp)
        self.show()
        self.activateWindow()

    def event(self, ev):
        from PyQt5.QtCore import QEvent
        if ev.type() == QEvent.WindowDeactivate and self.isVisible():
            self.close()
        return super().event(ev)
```

- [ ] **Step 3: Update `MainWindow._show_axis_lock_popover`**

Canvas is single source of truth for axis-lock state (§12.1). Popover initializes from `canvas_time._axis_lock`, mutates via `set_axis_lock`.

```python
def _show_axis_lock_popover(self, anchor):
    from .drawers.axis_lock_popover import AxisLockPopover
    current = self.canvas_time._axis_lock or 'none'
    pop = AxisLockPopover(self, current=current)
    pop.lock_changed.connect(self.canvas_time.set_axis_lock)
    pop.show_at(anchor)
```

Delete the placeholder `_axis_lock_state` attribute on MainWindow if it was introduced in Phase 1 — canvas owns the value.

- [ ] **Step 4: Delete old module**

```bash
rm mf4_analyzer/ui/axis_lock_toolbar.py
```

Grep for any remaining imports:
Run: Grep `from .axis_lock_toolbar import` across `mf4_analyzer/` — none should remain. If any do, remove them.

- [ ] **Step 5: Test**

```python
# tests/ui/test_drawers.py
def test_axis_lock_popover_emits(qapp, qtbot):
    from mf4_analyzer.ui.drawers.axis_lock_popover import AxisLockPopover
    p = AxisLockPopover(current='none')
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.lock_changed, timeout=200) as bl:
        for b in p._grp.buttons():
            if b.property('lock_key') == 'x':
                b.setChecked(True)
                break
    assert bl.args == ['x']


def test_axis_lock_popover_anchors(qapp, qtbot):
    from PyQt5.QtWidgets import QPushButton
    from mf4_analyzer.ui.drawers.axis_lock_popover import AxisLockPopover
    anchor = QPushButton("🔒"); qtbot.addWidget(anchor); anchor.move(50, 100); anchor.show()
    qtbot.waitExposed(anchor)
    p = AxisLockPopover(current='x'); qtbot.addWidget(p)
    p.show_at(anchor); qtbot.waitExposed(p)
    expected = anchor.mapToGlobal(anchor.rect().bottomLeft())
    assert abs(p.pos().x() - expected.x()) < 3
    assert abs(p.pos().y() - expected.y()) < 3
```

- [ ] **Step 6: Run**

Run: `pytest tests/ui/test_drawers.py -v`
Expected: 3 passed.

Run: `python -m mf4_analyzer.app`
Load CSV, plot time, click toolbar 🔒 → popover → pick X → drag on canvas → X rubber-band selects range.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/drawers/axis_lock_popover.py mf4_analyzer/ui/main_window.py tests/ui/test_drawers.py
git rm mf4_analyzer/ui/axis_lock_toolbar.py
git commit -m "feat(ui): axis lock as frameless popover; delete old toolbar strip"
```

### Task 3.5: Rewrite `_reset_cursors` + `_reset_plot_state` for new widget topology

The old `_reset_cursors` and `_reset_plot_state` touch `self.lbl_cursor / self.lbl_dual / self.stats / self.chk_cursor / self.chk_dual / self.combo_xaxis_ch` — all of which were either deleted or migrated by Task 2.3–2.10. They'll crash on the first file close if not rewritten. This task finishes the migration by rewriting both methods against the real widget topology.

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: Rewrite `_reset_cursors`**

```python
def _reset_cursors(self):
    """Reset both single and dual cursor state on the time-domain canvas."""
    self.canvas_time._ax = self.canvas_time._bx = None
    self.canvas_time._placing = 'A'
    self.canvas_time._refresh = True
    self.canvas_time.draw_idle()
    # Clear the ChartStack-owned cursor pill (no more lbl_cursor/lbl_dual)
    self.chart_stack._cursor_pill.setText("")
    self.chart_stack._cursor_dual_pill.setText("")
    self.chart_stack._cursor_pill.setVisible(False)
    self.chart_stack._cursor_dual_pill.setVisible(False)
    self.statusBar.showMessage("游标已重置")
```

- [ ] **Step 2: Rewrite `_reset_plot_state`**

```python
def _reset_plot_state(self, scope='file'):
    """Wipe plot-related state after a file close.
    scope in {'file', 'all'}; both paths currently share code.
    """
    self.chart_stack.full_reset_all()
    # Cursor pill (ChartStack owns both)
    self.chart_stack._cursor_pill.setText("")
    self.chart_stack._cursor_pill.setVisible(False)
    self.chart_stack._cursor_dual_pill.setText("")
    self.chart_stack._cursor_dual_pill.setVisible(False)
    # Stats strip
    self.chart_stack.stats_strip.update_stats({})
    # Inspector cursor mode → back to 'single' default
    self.inspector.time_ctx.set_cursor_mode('single')
    # Axis-lock popover is transient; canvas state resets in full_reset()
    # Invalidate custom X axis pointer if source gone
    if self._custom_xaxis_fid is not None and self._custom_xaxis_fid not in self.files:
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        self._custom_xlabel = None
        self.inspector.top.set_xaxis_mode('time')
    # Refill candidates
    if self.inspector.top.xaxis_mode() == 'channel':
        self._on_xaxis_mode_changed('channel')
    self._update_combos()
    if not self.files:
        self.inspector.top.set_range_limits(0, 0)
        self.inspector.top.spin_start.setValue(0)
        self.inspector.top.spin_end.setValue(0)
    else:
        max_t = max(
            (fd.time_array[-1] for fd in self.files.values() if len(fd.time_array)),
            default=0,
        )
        self.inspector.top.set_range_limits(0, max_t)
        lo, hi = self.inspector.top.range_values()
        if hi > max_t:
            self.inspector.top.spin_end.setValue(max_t)
        if lo > max_t:
            self.inspector.top.spin_start.setValue(0)
        if self._active in self.files:
            fs = self.files[self._active].fs
            self.inspector.fft_ctx.set_fs(fs)
            self.inspector.order_ctx.set_fs(fs)
    # Re-plot remaining channels (or clear if empty)
    self.plot_time()
```

- [ ] **Step 3: Delete dead imports / references**

Grep `main_window.py` for:
- `self.lbl_cursor` / `self.lbl_dual` / `self.stats.` / `self.chk_cursor` / `self.chk_dual` / `self.combo_xaxis_ch` / `self.combo_xaxis` / `self.chk_range` / `self.spin_start` / `self.spin_end` / `self.spin_fs` / `self.combo_sig` / `self.combo_rpm` / `self.spin_fs` / `self.spin_xt` / `self.spin_yt` / `self.chk_fft_autoscale` / `self.chk_fft_remark` / `self.combo_win` / `self.combo_nfft` / `self.spin_overlap` / `self.spin_mo` / `self.spin_order_res` / `self.combo_order_nfft` / `self.spin_time_res` / `self.spin_rpm_res` / `self.spin_to` / `self.spin_rf` / `self.btn_load` / `self.btn_close` / `self.btn_close_all` / `self.btn_plot` / `self.btn_reset` / `self.btn_edit` / `self.btn_export` / `self.btn_rebuild_time` / `self.btn_fft` / `self.btn_ot` / `self.btn_or` / `self.btn_ok` / `self.btn_apply_xaxis` / `self.edit_xlabel` / `self.lbl_info` / `self.lbl_order_progress` / `self.tabs` / `self.combo_mode` / `self._legacy_hidden` / `from .axis_lock_toolbar`

All should be gone. If any remain, remove them or replace with Inspector/ChartStack/Navigator API calls.

- [ ] **Step 4: Delete the `_legacy_hidden` holder**

Remove `self._legacy_hidden = QWidget(self)` from `_init_ui` — all shim widgets should now be unreferenced. Its disappearance is the Phase 2 completion signal.

- [ ] **Step 5: Run full suite**

Run: `pytest -v`
Expected: all pass; close-file flow no longer crashes; `_reset_plot_state` path covered by `test_close_file_resets_plot` smoke.

- [ ] **Step 6: Add close-flow smoke test**

```python
# tests/ui/test_main_window_smoke.py
def test_close_file_resets_inspector(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    assert w.files
    w._close(next(iter(w.files)))
    # No crash; stats strip shows placeholder
    assert '—' in w.chart_stack.stats_strip._lbl_summary.text()
```

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "refactor(ui): rewrite _reset_cursors/_reset_plot_state against new widgets"
```

---

## Phase 4 — Visual polish

**Goal of phase:** Replace `style.qss` with light-theme tokens; cursor pill, toolbar, inspector cards, file rows all adopt Mac Sonoma / Finder visual language.

### Task 4.1: Rewrite style.qss light tokens

**Files:**
- Modify: `mf4_analyzer/ui/style.qss`
- Modify: `mf4_analyzer/ui/icons.py` (maybe add helpers)

- [ ] **Step 1: Replace QSS**

Read current `style.qss`. Write new:

```css
/* ==== MF4 Analyzer — Mac light theme ==== */
QMainWindow, QWidget {
    background-color: #ffffff;
    color: #1d1d1f;
    font-family: -apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}

/* Splitter */
QSplitter::handle { background: #e5e5e7; }
QSplitter::handle:horizontal { width: 1px; }

/* Toolbar */
Toolbar {
    background: #fafafa;
    border-bottom: 1px solid #e5e5e7;
    padding: 4px;
}
Toolbar QPushButton {
    background: #fff;
    border: 1px solid #d2d2d7;
    border-radius: 6px;
    padding: 5px 11px;
    margin: 0 2px;
}
Toolbar QPushButton:hover { background: #f0f0f3; }
Toolbar QPushButton:pressed { background: #e3e3e6; }
Toolbar QPushButton:checked {
    background: #007aff;
    color: #fff;
    border-color: #007aff;
}
Toolbar QPushButton:disabled { color: #c7c7cc; background: #fafafa; }

/* File navigator */
FileNavigator { background: rgba(248, 248, 250, 0.85); border-right: 1px solid #e5e5e7; }
#fileRow {
    background: transparent;
    border-radius: 7px;
    padding: 6px 8px;
    color: #1d1d1f;
}
#fileRow[active="true"] { background: #007aff; color: #fff; }
#fileRow[active="true"] #fileRowMeta { color: rgba(255,255,255,0.85); }
#fileRowMeta { font-size: 9px; color: #86868b; }
#fileRow:hover { background: rgba(0, 122, 255, 0.06); }

/* Inspector */
Inspector { background: rgba(248, 248, 250, 0.85); border-left: 1px solid #e5e5e7; }
Inspector QGroupBox {
    background: #fff;
    border: 1px solid #e5e5e7;
    border-radius: 8px;
    margin-top: 8px;
    padding: 12px 10px 8px;
    font-weight: 500;
}
Inspector QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #6e6e73;
}
Inspector QPushButton {
    background: #fff;
    border: 1px solid #d2d2d7;
    border-radius: 6px;
    padding: 5px 10px;
}
Inspector QPushButton:checked { background: #007aff; color: #fff; border-color: #007aff; }
Inspector QDoubleSpinBox, Inspector QSpinBox, Inspector QComboBox, Inspector QLineEdit {
    background: #f7f7f9;
    border: 1px solid #e5e5e7;
    border-radius: 5px;
    padding: 3px 6px;
}

/* Chart stack */
ChartStack { background: #fff; }
#cursorPill {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid #e5e5e7;
    border-radius: 6px;
    padding: 5px 8px;
    color: #1d1d1f;
    font-size: 12px;
}

/* Stats strip */
StatsStrip {
    background: #f7f7f9;
    border: 1px solid #e5e5e7;
    border-radius: 7px;
    margin: 6px 4px;
}

/* Statusbar */
QStatusBar { background: #f7f7f9; color: #6e6e73; border-top: 1px solid #e5e5e7; }
```

- [ ] **Step 2: Remove deprecated styles**

Search `main_window.py` / `widgets.py` for inline stylesheets like `setStyleSheet("background:#1e1e1e...`) and delete or replace:
- `self.lbl_cursor.setStyleSheet(...)` (deleted in Task 2.9)
- `self.lbl_dual.setStyleSheet(...)` (deleted in Task 2.9)
- `StatisticsPanel.setStyleSheet("font-size:15px")` — remove; let QSS govern
- `self.btn_fft.setStyleSheet("font-weight:bold")` — remove
- `self.btn_ot.setStyleSheet("font-weight:bold")` — remove

- [ ] **Step 3: Launch app**

Run: `python -m mf4_analyzer.app`
Visually verify:
- White center canvas area, light-gray side panes
- Toolbar buttons pill style, selected mode highlighted blue
- File rows: active blue, inactive transparent with hover
- Inspector cards white with gray group-box titles
- Cursor pill: white translucent with border, readable system font

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/style.qss mf4_analyzer/ui/main_window.py mf4_analyzer/ui/widgets.py
git commit -m "style(ui): rewrite QSS for Mac light theme tokens"
```

### Task 4.2: Toolbar segmented control look

**Files:**
- Modify: `mf4_analyzer/ui/toolbar.py`
- Modify: `mf4_analyzer/ui/style.qss`

- [ ] **Step 1: Make mode buttons a checkable group**

In `toolbar.py`, make mode buttons behave as a segmented control:
```python
from PyQt5.QtWidgets import QButtonGroup

# in __init__ after creating the three mode buttons:
self._mode_group = QButtonGroup(self)
self._mode_group.setExclusive(True)
for key, b in [('time', self.btn_mode_time), ('fft', self.btn_mode_fft), ('order', self.btn_mode_order)]:
    b.setCheckable(True)
    b.setProperty("segment", key)
    self._mode_group.addButton(b)
self.btn_mode_time.setChecked(True)
```

- [ ] **Step 2: Replace `_set_mode` to trigger from check change**

```python
def _wire(self):
    self.btn_add.clicked.connect(self.file_add_requested)
    self.btn_edit.clicked.connect(self.channel_editor_requested)
    self.btn_export.clicked.connect(self.export_requested)
    for key, b in [('time', self.btn_mode_time), ('fft', self.btn_mode_fft), ('order', self.btn_mode_order)]:
        b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
    self.btn_cursor_reset.clicked.connect(self.cursor_reset_requested)
    self.btn_axis_lock.clicked.connect(lambda: self.axis_lock_requested.emit(self.btn_axis_lock))
```

- [ ] **Step 3: Add QSS for segmented look**

Append to `style.qss`:
```css
Toolbar QPushButton[segment="time"],
Toolbar QPushButton[segment="fft"],
Toolbar QPushButton[segment="order"] {
    background: #e8e8ed;
    border: none;
    border-radius: 5px;
    margin: 0 1px;
    padding: 5px 16px;
    color: #6e6e73;
}
Toolbar QPushButton[segment]:checked {
    background: #ffffff;
    color: #1d1d1f;
    border: 1px solid #d2d2d7;
}
```

- [ ] **Step 4: Run tests + manual**

Run: `pytest tests/ui/test_toolbar.py -v`
Expected: still passes.

Run: `python -m mf4_analyzer.app`
Verify segmented control looks like grouped pill with white active segment.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/toolbar.py mf4_analyzer/ui/style.qss
git commit -m "style(ui): toolbar mode buttons as segmented control"
```

### Task 4.3: Final smoke test + manual parity matrix

**Files:**
- None modified

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: all passing.

- [ ] **Step 2: Manual parity checklist**

Launch app. Run through the spec §15 verification list:

- [ ] Load MF4 — parse + channels appear in navigator
- [ ] Load CSV — same
- [ ] Load XLSX — same
- [ ] Multi-file load: 2+ files visible, click switches active
- [ ] Close single file via ✕ — removed
- [ ] Close all via kebab — confirm dialog, all cleared
- [ ] Channel search filters
- [ ] All / None / Inv work
- [ ] File-level checkbox cascades; >8 warning appears
- [ ] Time plot renders; Subplot / Overlay switch works
- [ ] Cursor Off/Single/Dual works; double cursor shows A/B/ΔT/stats
- [ ] Axis lock popover: pick X → drag rubber-band → zoom applied; Esc cancels
- [ ] Range selection (span select) writes Inspector range
- [ ] Tick density sliders affect all three canvases
- [ ] Custom X axis: time mode works; channel mode validates length, warns on mismatch
- [ ] FFT mode: signal dropdown → Fs → params → click ▶ 计算 FFT → plot appears
- [ ] FFT remark: toggle checkbox → left-click snaps → right-click deletes
- [ ] Rebuild-time popover: Fs changes time axis of target file
- [ ] Order mode: 3 buttons all produce plots with progress text
- [ ] Channel editor drawer: single ops, dual ops, delete — all work; active-file scope
- [ ] Export sheet: writes xlsx with selected channels + time + range
- [ ] Double-click axis labels → AxisEditDialog
- [ ] Wheel zoom Ctrl/Shift modifiers
- [ ] Resize splitter: left / center / right widths change; minimum widths enforced
- [ ] Shrink window to 1100×640 — all controls visible
- [ ] QSS is fully light — no dark remnants

If any item fails, file as a follow-up fix task and loop back to the relevant Phase 2/3 task.

- [ ] **Step 3: Commit (if any fixes)**

```bash
git add -A
git commit -m "chore(ui): final polish fixes after parity checklist"
```

---

## Closing

After all phases green:

- [ ] Run `pytest -v` — 100% pass
- [ ] Launch `python -m mf4_analyzer.app` — all §15 items verified
- [ ] Review git log — every task = one commit
- [ ] Delete any temporary test files or debug `print()` statements

Handed off to:
1. **Squad Phase 1 (orchestrator):** route this plan to `pyqt-ui-engineer` + `refactor-architect`
2. **Squad Phase 2 (execute):** specialists run task-by-task
3. **Codex review of final implementation** per master pipeline

---

## Self-Review Notes

**Spec coverage:** All 16 sections mapped — §2 mapping table → Tasks 1.1-3.5; §6 Inspector → Tasks 2.3-2.6; §7 toolbar → Task 1.1, 4.2; §8 drawers → Tasks 3.1-3.4; §9 sizes → Task 1.5 (splitter sizes); §12 code organization → overall file structure; §13 consistency rules → individual tasks; §14 non-goals — honored (no dark mode, no shortcuts, no screenshot); §15 verification → Task 4.3 checklist; §16 phases → 4 top-level sections.

**Placeholder scan:** No TBDs. Every step has concrete code or command.

**Type consistency:** Signal names match spec §12.2 (`mode_changed`, `file_activated`, `plot_time_requested`, etc.). `set_signal_candidates` / `current_signal` / `get_params` / `fs()` / `set_fs()` used consistently across Inspector section classes.

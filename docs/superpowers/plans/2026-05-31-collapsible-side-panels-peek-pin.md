# Collapsible Side Panels (peek/pin) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is PyQt UI work — the repo's `pyqt-ui-engineer` specialist is the intended executor.

**Goal:** Make both side panels (navigator left, inspector right) collapsible with a HIDDEN/PEEK/PINNED state machine; a faint edge "strip" peeks a floating overlay on hover and pins a docked panel on click; remove the inspector toolbar button and move the Cockpit button into its slot.

**Architecture:** A pure, event-loop-free reducer (`reduce_panel`) owns the HIDDEN↔PEEK↔PINNED transitions and emits string effects. A thin Qt controller (`SidePanelController`) wires strip/overlay/splitter events into the reducer and executes effects (reparent panel, restore width, timers). The peek overlay is a **child widget** of the central widget (never a top-level frameless window) to avoid macOS native square shadows. Toolbar loses the inspector button; the strip replaces it; the Cockpit button moves to the right segment.

**Tech Stack:** PyQt5, pytest + pytest-qt (`qtbot`, offscreen), existing QSS template `mf4_analyzer/ui_kit/style.qss`.

**Spec:** `docs/superpowers/specs/2026-05-31-collapsible-side-panels-peek-pin-design.md`

---

## File Structure

- **Create** `mf4_analyzer/ui/side_panels.py` — `PanelState`, `Side`, event/effect constants, pure `reduce_panel`, `SidePanelStrip`, `PeekOverlay`, `SidePanelController`.
- **Create** `tests/ui/test_side_panel_reducer.py` — pure reducer unit tests (no Qt).
- **Create** `tests/ui/test_side_panel_widgets.py` — qtbot widget/controller tests.
- **Modify** `mf4_analyzer/ui/main_window.py` — wrap splitter with strips, collapsible flags, `splitterMoved`, controller wiring, reposition, generalize restore-width.
- **Modify** `mf4_analyzer/ui/toolbar.py` — remove inspector button chain; move Cockpit button to right segment.
- **Modify** `mf4_analyzer/ui_kit/style.qss` — `#sidePanelStrip` + `PeekOverlay` styling.

---

## Task 1: Pure state-machine reducer

**Files:**
- Create: `mf4_analyzer/ui/side_panels.py`
- Test: `tests/ui/test_side_panel_reducer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_side_panel_reducer.py
"""Pure (no-Qt) tests for the side-panel HIDDEN/PEEK/PINNED reducer."""
import pytest

from mf4_analyzer.ui.side_panels import (
    PanelState, Ev, Effect, reduce_panel, strip_visible_for,
)


def test_hidden_hover_enters_peek():
    state, effects = reduce_panel(PanelState.HIDDEN, Ev.HOVER)
    assert state == PanelState.PEEK
    assert effects == (Effect.ENTER_PEEK,)


def test_hidden_click_pins():
    state, effects = reduce_panel(PanelState.HIDDEN, Ev.CLICK)
    assert state == PanelState.PINNED
    assert effects == (Effect.DOCK,)


def test_peek_click_stops_timer_then_docks():
    state, effects = reduce_panel(PanelState.PEEK, Ev.CLICK)
    assert state == PanelState.PINNED
    assert effects == (Effect.STOP_TIMER, Effect.DOCK)


def test_peek_mouse_left_starts_collapse_timer():
    state, effects = reduce_panel(PanelState.PEEK, Ev.OVERLAY_LEFT)
    assert state == PanelState.PEEK
    assert effects == (Effect.START_TIMER,)


def test_peek_mouse_reentered_cancels_collapse():
    state, effects = reduce_panel(PanelState.PEEK, Ev.OVERLAY_ENTERED)
    assert state == PanelState.PEEK
    assert effects == (Effect.STOP_TIMER,)


def test_peek_timeout_collapses_to_hidden():
    state, effects = reduce_panel(PanelState.PEEK, Ev.COLLAPSE_TIMEOUT)
    assert state == PanelState.HIDDEN
    assert effects == (Effect.EXIT_PEEK,)


def test_pinned_drag_collapse_hides():
    state, effects = reduce_panel(PanelState.PINNED, Ev.DRAG_COLLAPSED)
    assert state == PanelState.HIDDEN
    assert effects == (Effect.COLLAPSE_PINNED,)


def test_irrelevant_events_are_noops():
    # hovering while already peeking, clicking while pinned, etc.
    assert reduce_panel(PanelState.PEEK, Ev.HOVER) == (PanelState.PEEK, ())
    assert reduce_panel(PanelState.PINNED, Ev.HOVER) == (PanelState.PINNED, ())
    assert reduce_panel(PanelState.HIDDEN, Ev.COLLAPSE_TIMEOUT) == (PanelState.HIDDEN, ())


def test_strip_visible_in_hidden_and_peek_only():
    assert strip_visible_for(PanelState.HIDDEN) is True
    assert strip_visible_for(PanelState.PEEK) is True
    assert strip_visible_for(PanelState.PINNED) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_reducer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mf4_analyzer.ui.side_panels'`.

- [ ] **Step 3: Write minimal implementation**

```python
# mf4_analyzer/ui/side_panels.py  (top of new file)
"""Collapsible side panels: HIDDEN/PEEK/PINNED state machine + widgets.

The reducer (``reduce_panel``) is intentionally Qt-free so the transition
logic is unit-testable without an event loop. ``SidePanelController`` (added
in a later task) executes the emitted effects against real Qt widgets.
"""
from enum import Enum, auto


class PanelState(Enum):
    HIDDEN = auto()   # splitter slot 0, panel invisible, strip visible
    PEEK = auto()     # panel reparented into a floating overlay, strip visible
    PINNED = auto()   # panel docked in splitter, pushes canvas, strip hidden


class Side(Enum):
    LEFT = auto()
    RIGHT = auto()


class Ev(Enum):
    HOVER = auto()            # mouse entered strip (after open debounce)
    CLICK = auto()            # strip left-clicked
    OVERLAY_LEFT = auto()     # mouse left (overlay ∪ strip)
    OVERLAY_ENTERED = auto()  # mouse re-entered (overlay ∪ strip)
    COLLAPSE_TIMEOUT = auto() # auto-hide timer fired
    DRAG_COLLAPSED = auto()   # splitter dragged to <= threshold while pinned


class Effect(Enum):
    ENTER_PEEK = auto()       # reparent panel -> overlay, size+position, show, raise
    EXIT_PEEK = auto()        # reparent panel -> splitter slot 0, setVisible(False)
    DOCK = auto()             # reparent -> splitter, restore width, show; (strip hidden via state)
    COLLAPSE_PINNED = auto()  # setVisible(False), slot -> 0 (panel already in splitter)
    START_TIMER = auto()
    STOP_TIMER = auto()


# (current_state, event) -> (next_state, effects tuple). Missing keys are no-ops.
_TRANSITIONS = {
    (PanelState.HIDDEN, Ev.HOVER): (PanelState.PEEK, (Effect.ENTER_PEEK,)),
    (PanelState.HIDDEN, Ev.CLICK): (PanelState.PINNED, (Effect.DOCK,)),
    (PanelState.PEEK, Ev.CLICK): (PanelState.PINNED, (Effect.STOP_TIMER, Effect.DOCK)),
    (PanelState.PEEK, Ev.OVERLAY_LEFT): (PanelState.PEEK, (Effect.START_TIMER,)),
    (PanelState.PEEK, Ev.OVERLAY_ENTERED): (PanelState.PEEK, (Effect.STOP_TIMER,)),
    (PanelState.PEEK, Ev.COLLAPSE_TIMEOUT): (PanelState.HIDDEN, (Effect.EXIT_PEEK,)),
    (PanelState.PINNED, Ev.DRAG_COLLAPSED): (PanelState.HIDDEN, (Effect.COLLAPSE_PINNED,)),
}


def reduce_panel(state, event):
    """Pure transition: returns ``(next_state, effects)``; no-op stays put."""
    return _TRANSITIONS.get((state, event), (state, ()))


def strip_visible_for(state):
    """Edge strip is shown only while the panel is HIDDEN or PEEK."""
    return state in (PanelState.HIDDEN, PanelState.PEEK)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_reducer.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/side_panels.py tests/ui/test_side_panel_reducer.py
git commit -m "feat(ui): pure HIDDEN/PEEK/PINNED side-panel reducer"
```

---

## Task 2: SidePanelStrip widget (faint rail)

**Files:**
- Modify: `mf4_analyzer/ui/side_panels.py`
- Test: `tests/ui/test_side_panel_widgets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_side_panel_widgets.py
"""qtbot widget/controller tests for collapsible side panels."""
import pytest
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QWidget, QSplitter
from PyQt5.QtTest import QTest

from mf4_analyzer.ui.side_panels import Side, SidePanelStrip


def test_strip_emits_pin_on_left_click(qtbot):
    strip = SidePanelStrip(Side.LEFT)
    qtbot.addWidget(strip)
    strip.resize(12, 200)
    with qtbot.waitSignal(strip.pin_requested, timeout=500) as blocker:
        QTest.mouseClick(strip, Qt.LeftButton, pos=QPoint(6, 100))
    assert blocker.args == [Side.LEFT]


def test_strip_emits_peek_after_hover_debounce(qtbot):
    strip = SidePanelStrip(Side.RIGHT, hover_delay_ms=10)
    qtbot.addWidget(strip)
    with qtbot.waitSignal(strip.peek_requested, timeout=500) as blocker:
        strip.enterEvent(None)  # simulate hover-in; debounce timer starts
    assert blocker.args == [Side.RIGHT]


def test_strip_hover_out_before_debounce_cancels(qtbot):
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=300)
    qtbot.addWidget(strip)
    fired = []
    strip.peek_requested.connect(lambda s: fired.append(s))
    strip.enterEvent(None)
    strip.leaveEvent(None)   # leaves before 300ms debounce elapses
    qtbot.wait(120)
    assert fired == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py -q`
Expected: FAIL — `ImportError: cannot import name 'SidePanelStrip'`.

- [ ] **Step 3: Write minimal implementation**

Append to `mf4_analyzer/ui/side_panels.py`:

```python
from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame


class SidePanelStrip(QFrame):
    """A thin, faint, clickable edge rail shown when its side is collapsed.

    Hover (after a short debounce) requests a peek; left-click requests a pin.
    """
    peek_requested = pyqtSignal(object)  # Side
    pin_requested = pyqtSignal(object)   # Side

    WIDTH_PX = 12

    def __init__(self, side, hover_delay_ms=150, parent=None):
        super().__init__(parent)
        self._side = side
        self.setObjectName("sidePanelStrip")
        self.setProperty("side", "left" if side == Side.LEFT else "right")
        self.setFixedWidth(self.WIDTH_PX)
        self.setCursor(Qt.PointingHandCursor)
        chevron = "‹" if side == Side.LEFT else "›"  # ‹ / ›  (points inward)
        self.setToolTip("文件 / 通道" if side == Side.LEFT else "Inspector")
        self._chevron = chevron
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(hover_delay_ms)
        self._hover_timer.timeout.connect(lambda: self.peek_requested.emit(self._side))

    def enterEvent(self, event):
        self._hover_timer.start()
        super().enterEvent(event) if event is not None else None

    def leaveEvent(self, event):
        self._hover_timer.stop()
        super().leaveEvent(event) if event is not None else None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._hover_timer.stop()
            self.pin_requested.emit(self._side)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        from PyQt5.QtGui import QPainter, QColor
        p = QPainter(self)
        p.setPen(QColor("#9aa3ad"))
        p.drawText(self.rect(), Qt.AlignCenter, self._chevron)
        p.end()
```

> Note: the tests call `enterEvent(None)`/`leaveEvent(None)` directly, so guard the
> `super()` call against `None` as shown.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/side_panels.py tests/ui/test_side_panel_widgets.py
git commit -m "feat(ui): SidePanelStrip faint edge rail (hover-peek / click-pin)"
```

---

## Task 3: PeekOverlay container

**Files:**
- Modify: `mf4_analyzer/ui/side_panels.py`
- Test: `tests/ui/test_side_panel_widgets.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_side_panel_widgets.py`:

```python
from mf4_analyzer.ui.side_panels import PeekOverlay


def test_overlay_emits_enter_and_leave(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    overlay = PeekOverlay(host)
    entered, left = [], []
    overlay.mouse_entered.connect(lambda: entered.append(1))
    overlay.mouse_left.connect(lambda: left.append(1))
    overlay.enterEvent(None)
    overlay.leaveEvent(None)
    assert entered == [1]
    assert left == [1]


def test_overlay_hosts_a_panel(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    overlay = PeekOverlay(host)
    panel = QWidget()
    overlay.set_panel(panel)
    assert panel.parent() is overlay
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py -q`
Expected: FAIL — `ImportError: cannot import name 'PeekOverlay'`.

- [ ] **Step 3: Write minimal implementation**

Append to `mf4_analyzer/ui/side_panels.py`:

```python
from PyQt5.QtWidgets import QVBoxLayout


class PeekOverlay(QFrame):
    """Floating container for the peeked panel.

    MUST be a child widget (parent = central widget), never a top-level
    frameless window, so macOS does not paint a native square shadow
    (see commit 44786538). Raised above the canvas via ``raise_()``.
    """
    mouse_entered = pyqtSignal()
    mouse_left = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("peekOverlay")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._panel = None
        self.hide()

    def set_panel(self, panel):
        """Reparent ``panel`` into this overlay (filling it)."""
        if self._panel is panel:
            return
        self._panel = panel
        panel.setParent(self)
        self._lay.addWidget(panel)
        panel.show()

    def take_panel(self):
        """Detach the current panel and return it (caller reparents it)."""
        panel = self._panel
        if panel is not None:
            self._lay.removeWidget(panel)
            self._panel = None
        return panel

    def enterEvent(self, event):
        self.mouse_entered.emit()
        super().enterEvent(event) if event is not None else None

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event) if event is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/side_panels.py tests/ui/test_side_panel_widgets.py
git commit -m "feat(ui): PeekOverlay child-widget host for peeked panels"
```

---

## Task 4: SidePanelController (Qt glue + effect executor)

**Files:**
- Modify: `mf4_analyzer/ui/side_panels.py`
- Test: `tests/ui/test_side_panel_widgets.py`

The controller manages ONE side: a `SidePanelStrip`, a `PeekOverlay`, the shared
horizontal `QSplitter`, the panel widget, its splitter index, and a memorized dock
width. It maps Qt events → `reduce_panel` → effect execution, and owns the collapse
`QTimer` (with a popup guard so an open context menu does not auto-collapse a peek).

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_side_panel_widgets.py`:

```python
from mf4_analyzer.ui.side_panels import (
    PanelState, SidePanelController,
)


def _make_controller(qtbot):
    host = QWidget()
    host.resize(900, 600)
    qtbot.addWidget(host)
    splitter = QSplitter(Qt.Horizontal, host)
    panel = QWidget()
    panel.setMinimumWidth(50)
    middle = QWidget()
    middle.setMinimumWidth(100)
    splitter.addWidget(panel)
    splitter.addWidget(middle)
    splitter.setSizes([250, 650])
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=10)
    overlay = PeekOverlay(host)
    ctrl = SidePanelController(
        side=Side.LEFT, splitter=splitter, panel=panel, panel_index=0,
        strip=strip, overlay=overlay, host=host,
        collapse_delay_ms=20, default_width=250,
    )
    return ctrl, splitter, panel, strip, overlay


def test_controller_starts_pinned_strip_hidden(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    assert ctrl.state == PanelState.PINNED
    assert strip.isVisible() is False


def test_drag_collapse_hides_panel_and_shows_strip(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900])          # user dragged handle to the edge
    ctrl.on_splitter_moved()
    assert ctrl.state == PanelState.HIDDEN
    assert strip.isVisible() is True
    assert panel.isVisible() is False


def test_click_strip_redocks_with_remembered_width(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.pin_requested.emit(Side.LEFT)                      # click
    assert ctrl.state == PanelState.PINNED
    assert splitter.sizes()[0] == 250                        # remembered
    assert strip.isVisible() is False


def test_hover_peeks_into_overlay_then_autohides(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.peek_requested.emit(Side.LEFT)                     # hover
    assert ctrl.state == PanelState.PEEK
    assert panel.parent() is overlay
    assert overlay.isVisible() is True
    overlay.mouse_left.emit()                                # mouse leaves
    qtbot.waitUntil(lambda: ctrl.state == PanelState.HIDDEN, timeout=500)
    assert overlay.isVisible() is False
    assert panel.isVisible() is False


def test_reentry_cancels_autohide(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()
    strip.peek_requested.emit(Side.LEFT)
    overlay.mouse_left.emit()                                # start timer
    overlay.mouse_entered.emit()                             # cancel within window
    qtbot.wait(60)
    assert ctrl.state == PanelState.PEEK                     # still peeking
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py -q`
Expected: FAIL — `ImportError: cannot import name 'SidePanelController'`.

- [ ] **Step 3: Write minimal implementation**

Append to `mf4_analyzer/ui/side_panels.py`:

```python
from PyQt5.QtWidgets import QApplication


class SidePanelController(QObject):
    """Drives one side's HIDDEN/PEEK/PINNED lifecycle against real widgets."""

    PEEK_EXTRA_PX = 24      # overlay is "a bit wider" than the docked width
    COLLAPSE_THRESHOLD = 24  # drag width <= this => collapsed

    def __init__(self, side, splitter, panel, panel_index, strip, overlay,
                 host, collapse_delay_ms=600, default_width=250, parent=None):
        super().__init__(parent)
        self._side = side
        self._splitter = splitter
        self._panel = panel
        self._index = panel_index
        self._strip = strip
        self._overlay = overlay
        self._host = host
        self._remembered_width = default_width
        self.state = PanelState.PINNED

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(collapse_delay_ms)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

        strip.peek_requested.connect(lambda _s: self._dispatch(Ev.HOVER))
        strip.pin_requested.connect(lambda _s: self._dispatch(Ev.CLICK))
        overlay.mouse_left.connect(lambda: self._dispatch(Ev.OVERLAY_LEFT))
        overlay.mouse_entered.connect(lambda: self._dispatch(Ev.OVERLAY_ENTERED))

        self._apply_strip_visibility()

    # ---- event entry points ----
    def on_splitter_moved(self):
        """Call from QSplitter.splitterMoved. Collapse if dragged to the edge."""
        if self.state == PanelState.PINNED:
            w = self._splitter.sizes()[self._index]
            if w <= self.COLLAPSE_THRESHOLD:
                self._dispatch(Ev.DRAG_COLLAPSED)

    def _on_collapse_timeout(self):
        # Popup guard: a context menu opened from inside the peeked panel makes
        # the mouse "leave" the overlay; don't auto-collapse while it's open.
        if QApplication.activePopupWidget() is not None:
            self._collapse_timer.start()  # re-arm; re-check shortly
            return
        self._dispatch(Ev.COLLAPSE_TIMEOUT)

    # ---- core dispatch ----
    def _dispatch(self, event):
        new_state, effects = reduce_panel(self.state, event)
        self.state = new_state
        for eff in effects:
            self._run_effect(eff)
        self._apply_strip_visibility()

    def _run_effect(self, eff):
        if eff == Effect.ENTER_PEEK:
            self._remember_width_if_docked()
            self._overlay.set_panel(self._panel)
            self._position_overlay()
            self._overlay.show()
            self._overlay.raise_()
        elif eff == Effect.EXIT_PEEK:
            self._overlay.take_panel()
            self._overlay.hide()
            self._dock_panel_into_splitter(width=0, visible=False)
        elif eff == Effect.DOCK:
            if self._overlay.isVisible():
                self._overlay.take_panel()
                self._overlay.hide()
            self._dock_panel_into_splitter(width=self._remembered_width, visible=True)
        elif eff == Effect.COLLAPSE_PINNED:
            self._remember_width_if_docked()
            self._panel.setVisible(False)
            self._set_slot_width(0)
        elif eff == Effect.START_TIMER:
            self._collapse_timer.start()
        elif eff == Effect.STOP_TIMER:
            self._collapse_timer.stop()

    # ---- helpers ----
    def _apply_strip_visibility(self):
        self._strip.setVisible(strip_visible_for(self.state))

    def _remember_width_if_docked(self):
        w = self._splitter.sizes()[self._index]
        if w > self.COLLAPSE_THRESHOLD:
            self._remembered_width = w

    def _dock_panel_into_splitter(self, width, visible):
        # Re-insert if the panel was reparented out (peek), else just resize.
        if self._panel.parent() is not self._splitter:
            self._splitter.insertWidget(self._index, self._panel)
        self._panel.setVisible(visible)
        self._set_slot_width(width if visible else 0)

    def _set_slot_width(self, width):
        sizes = self._splitter.sizes()
        if len(sizes) <= self._index:
            return
        total = sum(sizes)
        delta = width - sizes[self._index]
        sizes[self._index] = width
        # absorb the delta from the widest middle pane (the canvas)
        mid = max(range(len(sizes)), key=lambda i: sizes[i] if i != self._index else -1)
        sizes[mid] = max(0, sizes[mid] - delta)
        self._splitter.setSizes(sizes)

    def _position_overlay(self):
        w = self._remembered_width + self.PEEK_EXTRA_PX
        h = self._host.height()
        x = 0 if self._side == Side.LEFT else max(0, self._host.width() - w)
        self._overlay.setGeometry(x, 0, w, h)

    def reposition(self):
        """Call from MainWindow.resizeEvent / moveEvent while peeking."""
        if self.state == PanelState.PEEK:
            self._position_overlay()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py -q`
Expected: PASS (10 passed). If `test_hover_peeks...` flakes on timer timing, raise the test's `collapse_delay_ms` and `qtbot.waitUntil` timeout — do not weaken the assertions.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/side_panels.py tests/ui/test_side_panel_widgets.py
git commit -m "feat(ui): SidePanelController drives peek/pin against real widgets"
```

---

## Task 5: QSS styling for strip + overlay

**Files:**
- Modify: `mf4_analyzer/ui_kit/style.qss`

- [ ] **Step 1: Add styles** (append near the other `QFrame`/popup rules)

```css
/* Collapsible side panels: faint edge rail + peek overlay */
QFrame#sidePanelStrip {
    background-color: #f3f5f8;
    border: none;
    border-right: 1px solid #e2e6eb;
}
QFrame#sidePanelStrip[side="right"] {
    border-right: none;
    border-left: 1px solid #e2e6eb;
}
QFrame#sidePanelStrip:hover {
    background-color: #e7ecf2;
}
QFrame#peekOverlay {
    background-color: #ffffff;
    border: 1px solid #d3d8df;
    border-radius: 10px;
}
```

- [ ] **Step 2: Verify the stylesheet still loads**

Run: `QT_QPA_PLATFORM=offscreen python -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); from mf4_analyzer.ui_kit.stylesheet import load_stylesheet; load_stylesheet(app); print('qss ok')"`
Expected: prints `qss ok` with no traceback.

- [ ] **Step 3: Commit**

```bash
git add mf4_analyzer/ui_kit/style.qss
git commit -m "style(ui): faint side-panel strip + rounded peek overlay"
```

---

## Task 6: Wire controllers into MainWindow

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py:130-163` (splitter setup), `:190-193` (resizeEvent)

- [ ] **Step 1: Replace the splitter/strip layout block**

In `_init_ui`, replace the current `splitter` construction through `root.addWidget(splitter, stretch=1)` (`main_window.py:133-163`) with:

```python
        from PyQt5.QtWidgets import QHBoxLayout
        from .side_panels import Side, SidePanelStrip, PeekOverlay, SidePanelController

        splitter = QSplitter(Qt.Horizontal, self)
        self.splitter = splitter
        self.navigator = FileNavigator(self)
        self.chart_stack = ChartStack(self)
        self.inspector = Inspector(self)
        splitter.addWidget(self.navigator)
        splitter.addWidget(self.chart_stack)
        splitter.addWidget(self.inspector)
        splitter.setSizes([250, 900, 360])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        # Collapsible left/right so a handle-drag to the edge hides the panel;
        # the canvas (index 1) must never collapse.
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, True)
        splitter.setHandleWidth(3)
        self.navigator.setMinimumWidth(220)
        self.chart_stack.setMinimumWidth(400)
        self.inspector.setMinimumWidth(self.inspector.maximumWidth())

        # Edge strips flank the splitter; visible only while their side is hidden.
        self._strip_left = SidePanelStrip(Side.LEFT, self)
        self._strip_right = SidePanelStrip(Side.RIGHT, self)
        strip_row = QWidget(self)
        row = QHBoxLayout(strip_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._strip_left)
        row.addWidget(splitter, stretch=1)
        row.addWidget(self._strip_right)
        root.addWidget(strip_row, stretch=1)

        # Peek overlays parented to the central widget (NOT top-level windows).
        self._overlay_left = PeekOverlay(cw)
        self._overlay_right = PeekOverlay(cw)
        self._panel_ctrl_left = SidePanelController(
            side=Side.LEFT, splitter=splitter, panel=self.navigator, panel_index=0,
            strip=self._strip_left, overlay=self._overlay_left, host=cw,
            default_width=250, parent=self,
        )
        self._panel_ctrl_right = SidePanelController(
            side=Side.RIGHT, splitter=splitter, panel=self.inspector, panel_index=2,
            strip=self._strip_right, overlay=self._overlay_right, host=cw,
            default_width=360, parent=self,
        )
        splitter.splitterMoved.connect(
            lambda *_: (self._panel_ctrl_left.on_splitter_moved(),
                        self._panel_ctrl_right.on_splitter_moved())
        )
```

> The convenience aliases that follow (`self.canvas_time = ...` at `main_window.py:167-171`)
> stay unchanged.

- [ ] **Step 2: Reposition overlays on resize/move**

Replace `resizeEvent` (`main_window.py:190-193`) with:

```python
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, '_toast') and self._toast.isVisible():
            self._toast._reposition()
        if hasattr(self, '_panel_ctrl_left'):
            self._panel_ctrl_left.reposition()
            self._panel_ctrl_right.reposition()

    def moveEvent(self, e):
        super().moveEvent(e)
        if hasattr(self, '_panel_ctrl_left'):
            self._panel_ctrl_left.reposition()
            self._panel_ctrl_right.reposition()
```

- [ ] **Step 3: Run the app smoke import + existing UI tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/ -q`
Expected: PASS (existing UI tests + the new side-panel tests). No import errors from `main_window`.

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): wire collapsible navigator + inspector into MainWindow"
```

---

## Task 7: Remove inspector toolbar button; move Cockpit to right segment

**Files:**
- Modify: `mf4_analyzer/ui/toolbar.py`, `mf4_analyzer/ui/main_window.py:240`
- Test: `tests/ui/test_side_panel_widgets.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_side_panel_widgets.py`:

```python
def test_toolbar_has_no_inspector_button_and_cockpit_on_right(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    qtbot.addWidget(tb)
    assert not hasattr(tb, "btn_inspector")
    assert not hasattr(tb, "inspector_visibility_changed")
    # Cockpit button now lives in the right-segment host widget.
    assert tb.btn_acquisition_cockpit.parent() is tb._right_widget
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_side_panel_widgets.py::test_toolbar_has_no_inspector_button_and_cockpit_on_right -q`
Expected: FAIL — `btn_inspector` still exists / cockpit parent is `_left_widget`.

- [ ] **Step 3: Edit `toolbar.py`**

(a) Remove the `inspector_visibility_changed = pyqtSignal(bool)` line (`toolbar.py:18`).

(b) Remove the `btn_inspector` construction block (`toolbar.py:41-45`):
```python
        self.btn_inspector = QPushButton("Inspector", self)
        self.btn_inspector.setIcon(Icons.inspector(BLUE))
        self.btn_inspector.setCheckable(True)
        self.btn_inspector.setChecked(True)
        self.btn_inspector.setToolTip("显示或隐藏右侧 Inspector 面板")
```

(c) In the icon-size loop (`toolbar.py:57-61`), drop `self.btn_inspector` from the tuple so it reads:
```python
        for b in (self.btn_add, self.btn_edit, self.btn_export, self.btn_batch,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_fft_time,
                  self.btn_mode_order):
            b.setIconSize(QSize(16, 16))
```

(d) Remove `self.btn_acquisition_cockpit` from the LEFT layout loop (`toolbar.py:66-73`) so left contains only add/edit/export/batch:
```python
        for b in (
            self.btn_add,
            self.btn_edit,
            self.btn_export,
            self.btn_batch,
        ):
            left.addWidget(b)
```

(e) In the RIGHT layout (`toolbar.py:99-103`) replace `self.btn_inspector` with the cockpit button:
```python
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)
        right.addWidget(self.btn_acquisition_cockpit)
```

(f) In `_wire` (`toolbar.py:144`) remove `self.btn_inspector.clicked.connect(self._on_inspector_clicked)`. The cockpit connection at `toolbar.py:143` stays.

(g) Delete `_on_inspector_clicked` (`toolbar.py:175-177`) and `set_inspector_visible` (`toolbar.py:179-186`) entirely.

- [ ] **Step 4: Edit `main_window.py` `_connect`**

Remove the now-dangling connection (`main_window.py:240`):
```python
        self.toolbar.inspector_visibility_changed.connect(self.set_inspector_visible)
```
Leave the cockpit connection (`main_window.py:239`) and the `set_inspector_visible` method body in `main_window.py:195-231` in place (it is no longer called by the toolbar but is harmless; a follow-up may remove it once the strip/controller fully own visibility — out of scope here).

- [ ] **Step 5: Run tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/ -q`
Expected: PASS. Verify no other test references `btn_inspector` / `inspector_visibility_changed`:
Run: `grep -rn "btn_inspector\|inspector_visibility_changed\|set_inspector_visible\|_on_inspector_clicked" tests/ mf4_analyzer/ | grep -v "main_window.py:.*def set_inspector_visible"`
Expected: only the retained `main_window.set_inspector_visible` definition (no toolbar/test hits).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/toolbar.py mf4_analyzer/ui/main_window.py tests/ui/test_side_panel_widgets.py
git commit -m "feat(ui): drop inspector toolbar button; move Cockpit to right segment"
```

---

## Task 8: Manual + macOS render verification

**Files:** none (verification only)

- [ ] **Step 1: Launch the real app**

Run: `python -m mf4_analyzer.app` (or the project's normal entry). Load a sample file.

- [ ] **Step 2: Verify the interaction loop by hand**

- Drag the left handle to the edge → navigator collapses, a faint strip appears flush-left.
- Hover the strip → after ~150ms a panel floats over the canvas (canvas does NOT shrink), slightly wider than docked.
- Move mouse onto the channel tree, check a channel → plot updates (signal still wired); overlay stays.
- Open a channel right-click menu, move onto it → overlay does NOT auto-collapse.
- Move mouse off the overlay → after ~600ms it collapses back to the strip; re-enter within the window → it stays.
- Click the strip → panel re-docks, pushes the canvas, strip disappears.
- Repeat for the right (inspector) side.
- Confirm the toolbar shows no "Inspector" button and "Cockpit" sits on the right.

- [ ] **Step 3: macOS render check (REQUIRED — see lessons-learned)**

Capture a screenshot of a peeked overlay on macOS and confirm:
- the overlay has rounded corners + soft border (matches popups), and
- **no native square shadow** behind it (the bug class fixed in commit 44786538).

Per [[feedback-verify-ui-visually]], do not mark this done on "properties set + unit tests pass" — confirm against the actual rendered screenshot.

- [ ] **Step 4: Run the full suite once**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit any screenshot/notes if the repo tracks them**

```bash
git add -A
git commit -m "docs(ui): verification notes for collapsible side panels" || echo "nothing to commit"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** state machine §3 → Task 1; strip §4.1 → Task 2; overlay §4.1 (macOS child-widget rule) → Task 3; controller + timers + popup guard §4.1/§5/§7 → Task 4; QSS §4.5 → Task 5; main_window wrap/collapsible/splitterMoved/reposition §4.2 → Task 6; toolbar removal + Cockpit move §4.3/§4.4 → Task 7; testing §8 + macOS verify → Tasks 1–4, 8. Default params §6 → Tasks 2 & 4 constructor args. Out-of-scope items (persistence, header chevron) intentionally absent.
- **Placeholder scan:** none — every code/test step shows full content.
- **Type consistency:** `reduce_panel`, `PanelState`, `Ev`, `Effect`, `strip_visible_for`, `SidePanelStrip(side, hover_delay_ms)`, `PeekOverlay(parent)`/`set_panel`/`take_panel`, `SidePanelController(side, splitter, panel, panel_index, strip, overlay, host, collapse_delay_ms, default_width)`, `on_splitter_moved`, `reposition` used consistently across Tasks 1–7.

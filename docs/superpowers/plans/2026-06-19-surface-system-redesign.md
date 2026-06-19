# TraceLab Porcelain Surface Layering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved porcelain tray surface system: top/bottom rounded white floating bars, three rounded main panels, and selected inner floating surfaces, while preserving TraceLab behavior.

**Architecture:** Phase 1 fixes the shell owner widgets and bottom status-bar placement. Phase 2 applies the porcelain QSS surface tokens and inner-card ownership. Phase 3 cleans conflicting QSS overrides and verifies with tests plus rendered UI evidence. Keep the change UI-only.

**Tech Stack:** PyQt5, Qt Style Sheets, pyqtgraph/matplotlib UI shell, pytest.

**Spec:** `docs/superpowers/specs/2026-06-19-surface-system-redesign-design.md`
**Visual Reference:** `docs/surface-layering-options.html`

---

## Current Evidence

- `mf4_analyzer/ui/main_window/window.py:105-114` creates `QWidget#centralTray`, root margins `5px`, and root spacing currently `8px`.
- `mf4_analyzer/ui/main_window/window.py:225-230` creates `self.statusBar = QStatusBar()` and registers it through `setStatusBar`.
- `mf4_analyzer/ui/toolbar.py:67-84` defines `Toolbar(QWidget)` with no explicit `WA_StyledBackground`.
- `mf4_analyzer/ui_kit/style.qss:299-303` paints `Toolbar` as tray gray.
- `mf4_analyzer/ui_kit/style.qss:1249-1257` paints `#chartToolbar` white; user annotation says this row should not have card/border/radius treatment.
- `mf4_analyzer/ui_kit/style.qss:1632-1636`, `1811-1838`, `1893-1899` contain duplicate/tail status/hint/tray rules that can override earlier rules.
- Tests directly rely on `self.statusBar` being a real `QStatusBar`: `tests/ui/test_view_switch_integration.py:100-101`, many `currentMessage()` and `showMessage()` call sites.

## Non-Negotiable Boundaries

- Do not change plotting, FFT, FFT-vs-Time, Order, cache, file-load, or numeric code.
- Do not change splitter sizes `[250, 900, 288]`, splitter handle width `3`, panel min widths, or `_INSPECTOR_CONTENT_MAX_WIDTH = 272`.
- Do not revert or absorb unrelated dirty worktree files.
- Do not commit unless the user explicitly asks. Use checkpoints and list changed paths instead.
- Preserve `self.statusBar` as a `QStatusBar` instance.
- The preserved API is this app's existing `self.statusBar` attribute API. `MainWindow.statusBar()` callable compatibility is not promised because the attribute already shadows the inherited `QMainWindow.statusBar` method.

## Agent Execution Model

Use one implementation agent per task, sequentially. Do not run multiple code-writing agents in parallel because Tasks 2-6 all touch `style.qss` or adjacent shell widgets. After each task:

1. Implementer reports changed paths and test output.
2. Main Codex reviews spec compliance.
3. Main Codex runs or requests the next focused test bundle.
4. Only then dispatch the next implementation task.

---

## Task 0: Baseline And Stale-Selector Audit

**Files:** none modified.

- [ ] **Step 1: Record current dirty scope**

Run:

```bash
git status --short
```

Expected: note unrelated dirty/untracked files. Do not clean them.

- [ ] **Step 2: Record current surface selectors**

Run:

```bash
rg -n "centralTray|Toolbar|QStatusBar|chartHintBar|viewTabBar|chartToolbar|FileNavigator|ChartStack|Inspector|e8ecf2|d3dbe6" \
  mf4_analyzer/ui_kit/style.qss \
  mf4_analyzer/ui/main_window/window.py \
  mf4_analyzer/ui/toolbar.py \
  mf4_analyzer/ui/file_navigator.py \
  mf4_analyzer/ui/widgets/__init__.py \
  tests/ui
```

Expected: use this as the before map. Do not edit yet.

- [ ] **Step 3: Run focused baseline tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_toolbar.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_switch_integration.py \
  -q
```

Expected: record pass/fail count. If baseline fails, stop and report exact failing tests before implementation.

---

## Task 1: Add Surface-Layering Regression Tests First

**Files:**
- Create or update: `tests/ui/test_surface_layering.py`
- Modify only if necessary: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Create or reconcile `tests/ui/test_surface_layering.py`**

If the file already exists or is untracked, inspect it first and update it in place. Do not overwrite unrelated local edits.

Add:

```python
from pathlib import Path
import re

from PyQt5.QtWidgets import QStatusBar

from mf4_analyzer.ui.main_window import MainWindow


QSS_PATH = Path("mf4_analyzer/ui_kit/style.qss")


def _apply_app_qss(qapp):
    old = qapp.styleSheet()
    qapp.setStyleSheet(QSS_PATH.read_text(encoding="utf-8"))
    return old


def test_surface_shell_uses_porcelain_tray_and_real_statusbar(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        root = win.centralWidget().layout()
        assert win.centralWidget().objectName() == "centralTray"
        assert root.contentsMargins().left() == 5
        assert root.contentsMargins().top() == 5
        assert root.spacing() == 5

        assert win.toolbar.objectName() == "surfaceTopBar"
        assert win.toolbar.minimumHeight() == 50
        assert win.toolbar.maximumHeight() == 50

        assert isinstance(win.statusBar, QStatusBar)
        assert win.statusBar.objectName() == "surfaceStatusBar"
        assert win.statusBar.parentWidget() is win.centralWidget()
        assert win.statusBar.minimumHeight() == 40
        assert win.statusBar.maximumHeight() == 40
        assert win.findChildren(QStatusBar).count(win.statusBar) == 1

        win.statusBar.clearMessage()
        win.statusBar.showMessage("surface ok")
        assert win.statusBar.currentMessage() == "surface ok"
    finally:
        qapp.setStyleSheet(old)


def test_surface_qss_contract_has_porcelain_bars_and_flat_chart_toolbar():
    qss = QSS_PATH.read_text(encoding="utf-8")

    assert "QMainWindow { background-color: #f2f4f7;" in qss
    assert "QWidget#centralTray { background-color: #f2f4f7;" in qss
    assert "Toolbar#surfaceTopBar" in qss
    assert "QStatusBar#surfaceStatusBar" in qss

    match = re.search(
        r"QToolBar#chartToolbar,\s*"
        r"QWidget#chartToolbar,\s*"
        r"NavigationToolbar2QT#chartToolbar,\s*"
        r"NavigationToolbar2QT\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.S,
    )
    assert match is not None
    toolbar_block = match.group("body")
    assert "background-color: transparent;" in toolbar_block
    assert "border: none;" in toolbar_block
    assert "border-radius" not in toolbar_block

    assert "background-color: #e8ecf2;" not in qss
```

- [ ] **Step 2: Update the existing chart toolbar spacer test**

In `tests/ui/test_chart_stack.py`, change `test_time_controls_spacer_has_toolbar_background_rule` so it expects the spacer selector to exist and use transparent background:

```python
def test_time_controls_spacer_has_toolbar_background_rule():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    match = re.search(
        r"QWidget#chartToolbar QWidget#chartTimeControlsSpacer\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.S,
    )
    assert match is not None
    assert "background-color: transparent;" in match.group("body")
```

- [ ] **Step 3: Run the new tests and confirm they fail for the right reason**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_chart_stack.py::test_time_controls_spacer_has_toolbar_background_rule \
  -q
```

Expected before implementation: failures mention `surfaceTopBar`, `surfaceStatusBar`, `root.spacing() == 5`, porcelain tokens, or transparent chart toolbar.

---

## Task 2: Phase 1 Shell Owner Widgets

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/toolbar.py`

- [ ] **Step 1: Add a compatible status-bar class**

In `mf4_analyzer/ui/main_window/window.py`, change the QtCore import:

```python
from PyQt5.QtCore import QTimer, QThread, Qt
```

Add this class above `class MainWindow`:

```python
class SurfaceStatusBar(QStatusBar):
    """QStatusBar API, displayed as the bottom rounded surface inside the tray."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("surfaceStatusBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(40)
```

- [ ] **Step 2: Make the toolbar an owned surface widget**

In `mf4_analyzer/ui/toolbar.py`, inside `Toolbar.__init__` immediately after `super().__init__(parent)`:

```python
self.setObjectName("surfaceTopBar")
self.setAttribute(Qt.WA_StyledBackground, True)
self.setFixedHeight(50)
```

`Qt` is already imported in this file.

- [ ] **Step 3: Tighten shell vertical rhythm**

In `MainWindow._init_ui`, keep root margins at `5, 5, 5, 5`, but change:

```python
root.setSpacing(8)
```

to:

```python
root.setSpacing(5)
```

- [ ] **Step 4: Move status bar into the central tray layout**

Intentional API decision: keep `self.statusBar` as the app API and move that same `QStatusBar` into the central tray. Do not add a second native QMainWindow status bar, and do not introduce code that calls `win.statusBar()`.

Replace:

```python
self.statusBar = QStatusBar()
self.setStatusBar(self.statusBar)
```

with:

```python
self.statusBar = SurfaceStatusBar(self)
root.addWidget(self.statusBar)
```

Leave the following status-hint/update wiring unchanged:

```python
self._status_hint_bar = None
self._install_status_hint_bar(self.chart_stack.current_mode())
self.chart_stack.mode_changed.connect(self._install_status_hint_bar)
self.statusBar.showMessage("Ready")
self._install_update_indicator()
```

- [ ] **Step 5: Verify shell API and dimensions**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py::test_surface_shell_uses_porcelain_tray_and_real_statusbar \
  tests/ui/test_view_switch_integration.py::test_main_window_mounts_view_tabbar \
  tests/ui/test_main_window_smoke.py::test_fft_time_cached_status_message_persists_on_view_switch \
  -q
```

Expected: tests fail only on QSS contract until Task 3, or pass if Task 3 is already done. They must not fail on the `self.statusBar` attribute API or create a second `QStatusBar`.

---

## Task 3: Phase 1 QSS Porcelain Tray + Top/Bottom Bars

**Files:**
- Modify: `mf4_analyzer/ui_kit/style.qss`

- [ ] **Step 1: Update the palette header and global shell backgrounds**

Replace the opening global block with this shape:

```css
/* ==== MF4 Analyzer -- Porcelain surface layering ====
 * tray       #f2f4f7   QMainWindow, central tray, splitter gaps
 * panel      #ffffff   topbar, bottombar, three main panels, inner cards
 * panel-soft #fafbfc   inner panel bodies where white cards need contrast
 * edge       #dbe2eb   topbar/bottombar/panel/card outlines
 * hairline   #eef2f7   soft separators inside a surface
 * accent #1769e0  ·  accent-wash #e8efff   (interaction only)
 */

QMainWindow { background-color: #f2f4f7; }

QWidget {
    background-color: #ffffff;
    color: #111827;
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", "SF Pro Text", sans-serif;
    font-size: 12px;
}
```

Keep `QWidget:disabled`, `QFrame`, `QGroupBox`, and `QLabel` rules after this.

- [ ] **Step 2: Recolor splitter and central tray**

Use:

```css
QSplitter::handle { margin: 0; background-color: #f2f4f7; }
```

At the tail rule, use:

```css
QWidget#centralTray { background-color: #f2f4f7; }
```

- [ ] **Step 3: Style top and bottom shell bars**

Replace the `Toolbar` block with:

```css
Toolbar#surfaceTopBar {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 13px;
}
```

Replace all generic `QStatusBar { ... }` duplicates with one specific rule:

```css
QStatusBar#surfaceStatusBar {
    background-color: #ffffff;
    color: #64748b;
    border: 1px solid #dbe2eb;
    border-radius: 13px;
}
```

Keep `QStatusBar QLabel#versionTag` but do not let it set a background.

- [ ] **Step 4: Verify no old tray gray remains**

Run:

```bash
rg -n "#e8ecf2|QStatusBar \\{|QWidget#centralTray|Toolbar#surfaceTopBar|QStatusBar#surfaceStatusBar" mf4_analyzer/ui_kit/style.qss
```

Expected: no `#e8ecf2`; one `Toolbar#surfaceTopBar`; one `QStatusBar#surfaceStatusBar`; one tail `QWidget#centralTray`.

- [ ] **Step 5: Run shell QSS tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_surface_layering.py -q
```

Expected: pass, except failures intentionally deferred to inner surface tasks.

---

## Task 4: Phase 2 Left Panel Inner Surfaces

**Files:**
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `mf4_analyzer/ui/widgets/__init__.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify or add focused assertions in: `tests/ui/test_surface_layering.py`

- [ ] **Step 1: Make file scroll paint as an inner card**

In `FileNavigator.__init__`, after:

```python
scroll.setObjectName("fileScroll")
```

add:

```python
scroll.setAttribute(Qt.WA_StyledBackground, True)
```

Set the file area body margins to create the inner card gap. Replace:

```python
file_lay.setContentsMargins(0, 0, 0, 0)
```

with:

```python
file_lay.setContentsMargins(8, 0, 8, 8)
```

- [ ] **Step 2: Make channel list paint as an inner card**

In `MultiFileChannelWidget.__init__`, immediately after `super().__init__(parent)`:

```python
self.setObjectName("channelCard")
self.setAttribute(Qt.WA_StyledBackground, True)
```

Change:

```python
layout.setContentsMargins(0, 0, 0, 0);
layout.setSpacing(2)
```

to:

```python
layout.setContentsMargins(8, 8, 8, 8)
layout.setSpacing(6)
```

- [ ] **Step 3: Add QSS for left inner cards**

In the left navigator section:

```css
FileNavigator {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 10px;
}

QWidget#fileArea { background-color: #fafbfc; }

QScrollArea#fileScroll,
QWidget#channelCard {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 11px;
}

QScrollArea#fileScroll > QWidget > QWidget {
    background-color: #ffffff;
}
```

Keep `QTreeWidget#channelTree` as a table surface inside the channel card.

- [ ] **Step 4: Extend the surface test**

Add assertions to `test_surface_shell_uses_porcelain_tray_and_real_statusbar`:

```python
assert win.navigator.channel_list.objectName() == "channelCard"
assert win.navigator.channel_list.testAttribute(Qt.WA_StyledBackground)
```

Import `Qt` from `PyQt5.QtCore`.

- [ ] **Step 5: Verify**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_channel_widget.py \
  -q
```

Expected: pass.

---

## Task 5: Phase 2 Chart And Inspector Inner Surface Rules

**Files:**
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Keep main panels white with porcelain edges**

Use these main panel rules:

```css
Inspector,
FileNavigator,
ChartStack {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 10px;
}
```

If keeping selectors separate for local readability, each selector must use the same values.

- [ ] **Step 2: Make Inspector body soft and cards white**

Use:

```css
QScrollArea#inspectorScroll {
    border: none;
    background-color: #fafbfc;
}
QScrollArea#inspectorScroll > QWidget > QWidget {
    background-color: #fafbfc;
}
Inspector QFrame#fftSignalCard,
Inspector QFrame#orderSignalCard,
Inspector QFrame#fftTimeSignalCard,
Inspector QFrame#fftParamsCard,
Inspector QFrame#fftTimeParamsCard,
Inspector QFrame#orderParamsCard {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
}
```

Keep existing radius values: signal cards `8px`, params cards `10px`. Do not restore green `#effaf4` or blue `#eef4ff`.

- [ ] **Step 3: Flatten chart toolbar**

Replace the `QToolBar#chartToolbar` / `QWidget#chartToolbar` block with:

```css
QToolBar#chartToolbar,
QWidget#chartToolbar,
NavigationToolbar2QT#chartToolbar,
NavigationToolbar2QT {
    background-color: transparent;
    border: none;
    spacing: 1px;
    padding: 1px;
}
```

Do not add `border-radius` to the chart toolbar block.

Set:

```css
QWidget#chartToolbar QWidget#chartTimeControlsSpacer {
    background-color: transparent;
}
```

- [ ] **Step 4: Keep chart choice selected state visible**

Do not change the existing checked choice token:

```css
QWidget#chartToolbar QPushButton[role="chart-choice"]:checked {
    background-color: #e8efff;
    border-color: #2563eb;
    color: #2563eb;
}
```

This preserves `tests/ui/test_chart_stack.py::test_chart_choice_checked_qss_uses_visible_blue_selection_tokens`.

- [ ] **Step 5: Verify**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_chart_choice_checked_qss_uses_visible_blue_selection_tokens \
  tests/ui/test_chart_stack.py::test_time_controls_spacer_has_toolbar_background_rule \
  tests/ui/test_inspector.py \
  tests/ui/test_surface_layering.py \
  -q
```

Expected: pass.

---

## Task 6: Phase 3 QSS Cleanup And Rounded-Corner Render Probe

**Files:**
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify if rounded-corner probe fails: `mf4_analyzer/ui/toolbar.py`, `mf4_analyzer/ui/main_window/window.py`, `mf4_analyzer/ui/file_navigator.py`, `mf4_analyzer/ui/chart_stack/stack.py`, `mf4_analyzer/ui/inspector.py`
- Modify: `tests/ui/test_surface_layering.py`

- [ ] **Step 1: Remove duplicate tail overrides**

After the implementation, this command must show only intentional specific selectors:

```bash
rg -n "QStatusBar|QFrame#chartHintBar|QWidget#viewTabBar|QWidget#centralTray|#e8ecf2" mf4_analyzer/ui_kit/style.qss
```

Expected:

- No `#e8ecf2`.
- No generic `QStatusBar { ... }` block.
- `QStatusBar#surfaceStatusBar` exists once.
- `QWidget#centralTray` exists once.
- `QWidget#viewTabBar` remains shared, not scoped only under `#timeViewBottomDock`.

- [ ] **Step 2: Add a rendered-corner test**

Append to `tests/ui/test_surface_layering.py`:

```python
from PyQt5.QtGui import QColor, QImage, QPainter


def _corner_alphas(widget):
    img = QImage(widget.width(), widget.height(), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    widget.render(painter)
    painter.end()
    w = img.width() - 1
    h = img.height() - 1
    return [
        QColor(img.pixelColor(0, 0)).alpha(),
        QColor(img.pixelColor(w, 0)).alpha(),
        QColor(img.pixelColor(0, h)).alpha(),
        QColor(img.pixelColor(w, h)).alpha(),
    ]


def test_surface_top_bottom_and_panels_render_rounded_corners(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(1450, 850)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        for widget in (win.toolbar, win.statusBar, win.navigator, win.chart_stack, win.inspector):
            alphas = _corner_alphas(widget)
            assert max(alphas) < 12, f"{widget.objectName() or type(widget).__name__} has opaque corner pixels: {alphas}"
    finally:
        qapp.setStyleSheet(old)
```

If this fails for a QWidget that still visually needs rounded transparent corners, first remember that `FileNavigator`, `ChartStack`, and `Inspector` already set `WA_StyledBackground`; the likely fix is a transparent shell/rendering adjustment or parent backing cleanup, not merely adding that attribute again. For this surface system, the concrete fix is to combine `WA_TranslucentBackground`, `WA_NoSystemBackground`, `setAutoFillBackground(False)`, and, where child content covers a rounded edge, a minimal 1px content inset. Do not delete the test.

- [ ] **Step 3: Verify shared ViewTabBar chrome**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_view_switch_integration.py \
  -q
```

Expected: pass.

---

## Task 7: Rendered App Verification

**Files:**
- Create/update: `docs/surface-redesign-after/`

- [ ] **Step 1: Launch TraceLab with the real stylesheet**

Use the repo venv and normal app entrypoint. If launching from `~/Downloads` hits macOS TCC / `Operation not permitted`, report that exact blocker and do not debug parser code.

Recommended command:

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"
```

- [ ] **Step 2: Capture four mode screenshots**

Save:

```text
docs/surface-redesign-after/1-time.png
docs/surface-redesign-after/2-fft.png
docs/surface-redesign-after/3-fft_time.png
docs/surface-redesign-after/4-order.png
```

The screenshots must show:

- porcelain tray behind rounded top/bottom/main panels;
- top and bottom long white rounded bars;
- chart toolbar flat, no card frame;
- no old gray strip at the bottom;
- no square backing behind rounded corners.

- [ ] **Step 3: Run final focused suite**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_channel_widget.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_switch_integration.py \
  -q
```

Expected: pass.

- [ ] **Step 4: Invariant diff audit**

Run:

```bash
git diff -- mf4_analyzer tests | rg -n "setSizes|setHandleWidth|setMinimumWidth|_INSPECTOR_CONTENT_MAX_WIDTH|compute_fft|compute_psd|plot_result|cache_key" || true
```

Expected: only allowed shell/layout changes. No numeric or analysis logic changes.

---

## Done Definition

The work is complete only when:

- Spec acceptance criteria are checked against the live rendered app.
- New `test_surface_layering.py` passes.
- Existing focused UI tests pass.
- `rg "#e8ecf2"` finds no stale old tray token in `style.qss`.
- Agent summary lists changed paths and explicitly states no unrelated files were reverted.
- No commit was created unless the user explicitly asked for one.

## Self-Review

- **Spec coverage:** Phase 1 maps to Tasks 2-3; Phase 2 maps to Tasks 4-5; Phase 3 maps to Tasks 6-7.
- **Known risks covered:** status-bar API, duplicate QSS overrides, rounded-corner pixel proof, shared ViewTabBar selector, dirty worktree.
- **No stale direction:** The old snow/flush plan is replaced by porcelain tray + top/bottom white floating surface direction.

# TraceLab Surface Radius Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the porcelain surface system so radii are smaller, borders are not covered by child widgets, outer panel layers remain visibly rounded, and the `v7.0` affordance becomes transparent icon + text.

**Architecture:** Treat this as a surface-layer ownership fix, not a one-off QSS patch. Tests first capture the compact radius tokens, child inset/transparent-shell invariants, and version-button contract; implementation then updates QSS, widget attributes, layout insets, and the custom topbar painter in tightly scoped passes.

**Tech Stack:** PyQt5, Qt Style Sheets, pytest, offscreen Qt screenshots.

**Spec:** `docs/superpowers/specs/2026-06-19-surface-radius-alignment-design.md`

---

## Current Evidence

- `mf4_analyzer/ui_kit/style.qss:301-305` sets `Toolbar#surfaceTopBar` radius to `13px`.
- `mf4_analyzer/ui/toolbar.py:221-228` also custom-paints the topbar with radius `13`.
- `mf4_analyzer/ui_kit/style.qss:794-804` sets FileNavigator radius `10px` and its inner cards `11px`.
- `mf4_analyzer/ui_kit/style.qss:891-898` sets Inspector radius `10px`, while `inspectorScroll` paints an edge-to-edge soft body.
- `mf4_analyzer/ui_kit/style.qss:1172-1186` sets ChartStack radius `10px` and chart cards `12px`.
- `mf4_analyzer/ui/main_window/window.py:265-278` creates the update affordance as a styled `QToolButton` with inline padding and no stable object name.
- `mf4_analyzer/ui/chart_stack/stack.py:55-57` uses `ChartStack` margins `0,4,0,0`; a previous left/right margin experiment disturbed toolbar geometry, so the center fix must be localized and verified against `tests/ui/test_chart_stack.py`.

## Non-Negotiable Boundaries

- Do not touch FFT, FFT-vs-Time, Order, pyqtgraph numeric logic, cache keys, file-load behavior, or splitter sizes.
- Do not change `self.statusBar` from a `QStatusBar` instance.
- Do not add broad shadows or a new visual theme.
- Do not run multiple implementation agents in parallel; Tasks 1-3 touch overlapping QSS and shell widgets.
- Do not revert unrelated dirty worktree files.

## Task 0: Add Radius And Alignment Regression Tests

**Files:**
- Modify: `tests/ui/test_surface_layering.py`
- Modify only if necessary: `tests/ui/test_update_indicator.py`

- [ ] **Step 1: Add QSS block helper**

Append this helper near the existing `_corner_alphas` helper in
`tests/ui/test_surface_layering.py`:

```python
def _qss_block(qss, selector):
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}"
    match = re.search(pattern, qss, flags=re.S)
    assert match is not None, f"missing QSS block for {selector}"
    return match.group("body")
```

- [ ] **Step 2: Add compact radius token test**

Add:

```python
def test_surface_qss_uses_compact_radius_scale():
    qss = QSS_PATH.read_text(encoding="utf-8")

    topbar_block = _qss_block(qss, "QWidget#surfaceTopBar")
    status_block = _qss_block(qss, "QStatusBar#surfaceStatusBar")
    file_block = _qss_block(qss, "FileNavigator")
    inspector_block = _qss_block(qss, "Inspector")
    chart_match = re.search(r"ChartStack\s*\{(?P<body>[^}]*)\}", qss, flags=re.S)
    assert chart_match is not None
    chart_block = chart_match.group("body")

    assert "border-radius: 8px;" in topbar_block
    assert "border-radius: 8px;" in status_block
    assert "border-radius: 7px;" in file_block
    assert "border-radius: 7px;" in chart_block
    assert "border-radius: 7px;" in inspector_block

    assert "border-radius: 13px;" not in topbar_block
    assert "border-radius: 13px;" not in status_block
    assert "border-radius: 10px;" not in file_block
    assert "border-radius: 10px;" not in chart_block
    assert "border-radius: 10px;" not in inspector_block
```

- [ ] **Step 3: Add version affordance test**

Add:

```python
def test_surface_version_affordance_is_transparent_icon_text(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        btn = win._update_btn
        assert btn.objectName() == "surfaceVersionButton"
        assert btn.autoRaise()
        assert btn.text() == "v7.0"
        assert btn.styleSheet() == ""

        qss = QSS_PATH.read_text(encoding="utf-8")
        block = _qss_block(qss, "QStatusBar#surfaceStatusBar QToolButton#surfaceVersionButton")
        assert "background-color: transparent;" in block
        assert "border: none;" in block
        assert "border-radius: 5px;" in block

        btn_rect = btn.geometry()
        bar_rect = win.statusBar.rect()
        assert bar_rect.right() - btn_rect.right() >= 4
        assert bar_rect.bottom() - btn_rect.bottom() >= 2
    finally:
        qapp.setStyleSheet(old)
```

- [ ] **Step 4: Add panel content inset test**

Add:

```python
def test_surface_panel_children_leave_outer_shell_visible(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(1450, 850)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        nav_margins = win.navigator.layout().contentsMargins()
        assert nav_margins.left() >= 3
        assert nav_margins.right() >= 3
        assert nav_margins.bottom() >= 3

        inspector_margins = win.inspector.layout().contentsMargins()
        assert inspector_margins.left() >= 3
        assert inspector_margins.right() >= 3
        assert inspector_margins.bottom() >= 3

        scroll = win.inspector.findChild(type(win.inspector._scroll), "inspectorScroll")
        assert scroll is win.inspector._scroll
        assert not scroll.autoFillBackground()
        assert not scroll.viewport().autoFillBackground()
    finally:
        qapp.setStyleSheet(old)
```

- [ ] **Step 5: Run tests and confirm expected failure**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_update_indicator.py \
  -q
```

Expected: failures for radius tokens, version button object name/style, and
inspector/panel inset until Tasks 1-3 are implemented.

## Task 1: Compact Radius Tokens And Topbar Painter

**Files:**
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `mf4_analyzer/ui/toolbar.py`
- Modify: `mf4_analyzer/ui/main_window/window.py` comments only if stale radius comments need correction

- [ ] **Step 1: Update surface QSS radii**

Change only the surface-system blocks:

```css
Toolbar#surfaceTopBar,
QWidget#surfaceTopBar {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 8px;
}

FileNavigator {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 7px;
}

QScrollArea#fileScroll,
QWidget#channelCard {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 6px;
}

Inspector {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 7px;
}

Inspector QFrame#fftSignalCard,
Inspector QFrame#orderSignalCard,
Inspector QFrame#fftTimeSignalCard,
Inspector QFrame#fftParamsCard,
Inspector QFrame#fftTimeParamsCard,
Inspector QFrame#orderParamsCard {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 6px;
}

ChartStack {
    background-color: #ffffff;
    border: 1px solid #dbe2eb;
    border-radius: 7px;
}

QWidget#chartCard {
    border: 1px solid #d3dbe6;
    border-radius: 6px;
    background-color: #ffffff;
}

QWidget#chartCard[focused="true"] {
    border-radius: 6px;
    background-color: #ffffff;
}

QStatusBar#surfaceStatusBar {
    background-color: #ffffff;
    color: #64748b;
    border: 1px solid #dbe2eb;
    border-radius: 8px;
}
```

Do not mass-replace every radius in the file. Popup/menu/acquisition/editor
rules are out of scope.

- [ ] **Step 2: Update `Toolbar.paintEvent` radius**

In `mf4_analyzer/ui/toolbar.py`, change:

```python
painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 13, 13)
```

to:

```python
painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
```

- [ ] **Step 3: Update stale comment**

If `mf4_analyzer/ui/main_window/window.py` still says panel corner radius
`10px`, update that comment to `7px`. Do not change splitter sizes.

- [ ] **Step 4: Run radius tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py::test_surface_qss_uses_compact_radius_scale \
  tests/ui/test_surface_layering.py::test_surface_top_bottom_and_panels_render_rounded_corners \
  -q
```

Expected: both tests pass.

## Task 2: Prevent Child Widgets From Covering Outer Panel Shells

**Files:**
- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `mf4_analyzer/ui/inspector.py`
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`

- [ ] **Step 1: Inset left and right panel content**

Set `FileNavigator` and `Inspector` outer layout margins to at least `3px` on
all sides that can expose the rounded shell:

```python
lay.setContentsMargins(3, 3, 3, 3)
```

For FileNavigator, keep internal spacing compact. If top spacing makes the
header too low, use `3, 2, 3, 3`, but left/right/bottom must be at least `3`.

- [ ] **Step 2: Make scroll viewports transparent**

For `fileScroll` in `mf4_analyzer/ui/file_navigator.py`, after constructing the
scroll area and before adding it to the layout, set:

```python
scroll.setAutoFillBackground(False)
scroll.viewport().setAutoFillBackground(False)
scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
scroll.viewport().setAttribute(Qt.WA_NoSystemBackground, True)
self._file_holder.setAutoFillBackground(False)
self._file_holder.setAttribute(Qt.WA_TranslucentBackground, True)
self._file_holder.setAttribute(Qt.WA_NoSystemBackground, True)
```

For `inspectorScroll` in `mf4_analyzer/ui/inspector.py`, after creating
`self._scroll`, set:

```python
self._scroll.setAutoFillBackground(False)
self._scroll.viewport().setAutoFillBackground(False)
self._scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
self._scroll.viewport().setAttribute(Qt.WA_NoSystemBackground, True)
```

For Inspector `host` and `self._scroll_body`, keep the host transparent and let
the named body own the soft internal fill:

```python
host.setAutoFillBackground(False)
host.setAttribute(Qt.WA_TranslucentBackground, True)
host.setAttribute(Qt.WA_NoSystemBackground, True)

self._scroll_body.setObjectName("inspectorScrollBody")
self._scroll_body.setAttribute(Qt.WA_StyledBackground, True)
```

- [ ] **Step 3: Localize ChartStack edge fixes**

Keep `ChartStack` toolbar geometry stable. Do not add left/right margins to the
main ChartStack layout unless the toolbar geometry tests still pass.

Instead, prefer QSS/background ownership:

```css
QWidget#timeDomainPage {
    background-color: transparent;
}

QFrame#timeViewBottomDock {
    background-color: transparent;
    border-top: 1px solid #dbe3ee;
}

QWidget#viewTabBar {
    background-color: transparent;
    border: none;
}
```

If a rendered probe still shows center panel bottom corners covered, add a
localized bottom inset by putting the view tab bar/hint host inside the already
transparent bottom dock rather than changing chart toolbar placement.

- [ ] **Step 4: Remove or neutralize edge-covering child QSS**

Review and adjust only these selectors:

```css
QWidget#fileArea
QScrollArea#fileScroll > QWidget > QWidget
QScrollArea#inspectorScroll
QScrollArea#inspectorScroll > QWidget > QWidget
QWidget#timeDomainPage
QFrame#timeViewBottomDock
QFrame#chartHintBar
QWidget#viewTabBar
```

Target behavior:
- parent shells stay visible at corners and borders;
- internal bodies can be `#fafbfc` only when inset or not touching a rounded edge;
- no edge-to-edge rectangular child fill over a rounded parent.

- [ ] **Step 5: Run layout and chart tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_channel_widget.py \
  tests/ui/test_chart_stack.py::test_time_toolbar_has_no_loc_label_to_jostle_right_controls \
  tests/ui/test_chart_stack.py::test_time_toolbar_controls_fit_when_inspector_narrows_chart \
  tests/ui/test_inspector.py \
  -q
```

Expected: all selected tests pass.

## Task 3: Convert `v7.0` To Transparent Icon + Text

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Modify: `tests/ui/test_update_indicator.py` only if it needs to assert the new object name

- [ ] **Step 1: Give update button a stable object name and remove inline style**

In `_install_update_indicator`, after constructing `self._update_btn`, add:

```python
self._update_btn.setObjectName("surfaceVersionButton")
```

Remove:

```python
self._update_btn.setStyleSheet(
    "QToolButton { padding: 2px 6px; }"
)
```

Keep `setAutoRaise(True)`, tooltip, icon, text, cursor, and click behavior.

- [ ] **Step 2: Add scoped QSS**

Add a QSS block near `QStatusBar#surfaceStatusBar`:

```css
QStatusBar#surfaceStatusBar QToolButton#surfaceVersionButton {
    min-height: 22px;
    padding: 1px 7px;
    background-color: transparent;
    border: none;
    border-radius: 5px;
    color: #111827;
    font-weight: 700;
}

QStatusBar#surfaceStatusBar QToolButton#surfaceVersionButton:hover {
    background-color: #f5f7fb;
}

QStatusBar#surfaceStatusBar QToolButton#surfaceVersionButton:pressed {
    background-color: #eef2f7;
}
```

- [ ] **Step 3: Ensure it is inset from status surface edges**

If geometry test fails because the button touches the status-bar contents rect,
set `SurfaceStatusBar` contents margins in `mf4_analyzer/ui/main_window/window.py`:

```python
self.setContentsMargins(8, 2, 8, 2)
```

Do not make the bottom bar taller.

- [ ] **Step 4: Run update indicator tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py::test_surface_version_affordance_is_transparent_icon_text \
  tests/ui/test_update_indicator.py \
  -q
```

Expected: all pass.

## Task 4: Final Verification And Screenshot Evidence

**Files:**
- Generated/updated: `docs/surface-redesign-after/*.png`
- Modify: `progress.md`

- [ ] **Step 1: Run focused UI suite**

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
  tests/ui/test_update_indicator.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run diff hygiene and scope audit**

Run:

```bash
git diff --check -- mf4_analyzer tests docs/superpowers progress.md
git diff -- mf4_analyzer tests | rg -n "setSizes|setHandleWidth|_INSPECTOR_CONTENT_MAX_WIDTH|compute_fft|compute_psd|plot_result|cache_key" || true
```

Expected: no whitespace errors; no numeric/cache/splitter implementation changes.

- [ ] **Step 3: Regenerate screenshots**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python - <<'PY'
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from mf4_analyzer.ui.main_window.window import MainWindow

out_dir = Path("docs/surface-redesign-after")
out_dir.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
qss_path = Path("mf4_analyzer/ui_kit/style.qss")
app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
win = MainWindow()
win.resize(1450, 850)
win.show()
app.processEvents()
for index, (mode, suffix) in enumerate(
    [("time", "time"), ("fft", "fft"), ("fft_time", "fft_time"), ("order", "order")],
    start=1,
):
    win._on_mode_changed(mode)
    app.processEvents()
    path = out_dir / f"{index}-{suffix}.png"
    if not win.grab().save(str(path)):
        raise SystemExit(f"failed to save {path}")
    print(path)
win.close()
PY
```

Expected: four screenshots saved. Inspect `4-order.png` against the user's
annotated screenshot because that is the failure reference.

- [ ] **Step 4: Update progress**

Append to `progress.md`:

```markdown
- Surface radius alignment pass completed: compact radii `8/7/6/5`, transparent version affordance, shell/child backing fixes, focused UI tests passed, and screenshots regenerated.
```

## Agent Execution Order

Use sequential agents:

1. **Task 0 agent:** tests only.
2. **Task 1 agent:** QSS radius + topbar painter.
3. **Task 2 agent:** child backing/inset fixes.
4. **Task 3 agent:** version affordance.
5. **Task 4 agent:** final verification, screenshots, progress update.

After each implementation task, the main Codex must review the diff before
dispatching the next agent.

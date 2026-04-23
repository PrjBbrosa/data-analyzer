# MF4 Analyzer UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three user-reported UI defects in the MF4 Analyzer (state leak on file close, missing axis-locked zoom, overlay channels collapse into a single Y axis) and opportunistically modernise the chrome with macOS-style icons and a global stylesheet.

**Architecture:** Route B — structured refactor. Introduces two new `ui/` modules (`icons.py`, `axis_lock_toolbar.py`) and a stylesheet (`style.qss`). Extends `canvases.py` with `full_reset()` contract + axis-lock state machine + twin-Y overlay. Rewrites `MainWindow._close/close_all` to go through a single `_reset_plot_state()` helper. Touches only `mf4_analyzer/ui/**` and `mf4_analyzer/app.py`.

**Tech Stack:** PyQt5, matplotlib (Qt5Agg backend), numpy, pandas. No new dependencies.

**Spec reference:** `docs/superpowers/specs/2026-04-23-plot-state-cleanup-and-axis-ux-design.md`

**Testing note:** This is pure UI/UX work. No unit tests exist for the UI layer in this project. Each task ends with **manual verification steps** against a running app, plus a `python -c "import mf4_analyzer"` import-smoke-check where relevant. The signal-processing tests under `tests/` must continue to pass unchanged — any task that breaks them is a regression.

---

## File Structure

**New files:**
- `mf4_analyzer/ui/icons.py` — `Icons` class, programmatic `QIcon` factories (≈150 lines)
- `mf4_analyzer/ui/axis_lock_toolbar.py` — `AxisLockBar` QWidget (≈40 lines)
- `mf4_analyzer/ui/style.qss` — global QSS

**Modified files:**
- `mf4_analyzer/ui/canvases.py` — `full_reset()` on both canvases, axis-lock state + rubber-band on `TimeDomainCanvas`, overlay twin-Y rewrite, cursor-readout units
- `mf4_analyzer/ui/main_window.py` — `_reset_plot_state()`, `_close/close_all` rewrite, axis-lock wiring, icon usage on 6 buttons, overlay-warning dialog, subplot unit labels
- `mf4_analyzer/app.py` — load `style.qss` at startup

**Not touched:** `mf4_analyzer/signal/**`, `mf4_analyzer/io/**`, `tests/**`, `ui/dialogs.py`, `ui/widgets.py`.

---

## Task 1: Add `full_reset()` to canvases

Introduce the clearing contract used by `_reset_plot_state()`. Pure
addition; no existing behaviour changes.

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`

- [ ] **Step 1.1: Add `full_reset()` to `TimeDomainCanvas`**

Insert after the existing `clear()` method (~line 46-57):

```python
def full_reset(self):
    """Clear figure AND all cursor/dual-cursor/background state.
    Use this on file close; use clear() for redraws within a session."""
    self.clear()
    self._bg = None
    self._cursor_artists = []
    self._a_artists = []
    self._b_artists = []
    self._ax = None
    self._bx = None
    self._placing = 'A'
    self._cursor_visible = False
    self._dual = False
    self.span_selector = None
    self.draw_idle()
```

- [ ] **Step 1.2: Add `full_reset()` to `PlotCanvas`**

Insert after `PlotCanvas.clear()` (~line 266-269):

```python
def full_reset(self):
    """Clear figure AND remarks/stored-line-data."""
    self.clear()
    self.draw_idle()
```

(`clear()` already zeroes `_remarks` and `_line_data`; `full_reset` just
adds the explicit `draw_idle()` and is the public contract hook.)

- [ ] **Step 1.3: Import-smoke-check**

Run:
```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -c "from mf4_analyzer.ui.canvases import TimeDomainCanvas, PlotCanvas; print('ok')"
```
Expected: `ok`. If `ImportError`, stop and fix.

- [ ] **Step 1.4: Run signal tests**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m pytest tests/ -x -q 2>&1 | tail -20
```
Expected: all existing tests still pass.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/canvases.py
git commit -m "feat(ui): add full_reset() to canvases — cleanup contract hook"
```

---

## Task 2: `_reset_plot_state()` + rewrite `_close/close_all`

Single-source-of-truth cleanup helper; rewrite the two call-sites.

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 2.1: Add `_reset_plot_state()` method**

Insert in `MainWindow` class after `_update_info()` (~line 566):

```python
def _reset_plot_state(self, scope='file'):
    """Wipe plot-related state after a file close. scope in {'file', 'all'}.
    Kept scope-parameterised for future divergence; today both paths share code."""
    self.canvas_time.full_reset()
    self.canvas_fft.full_reset()
    self.canvas_order.full_reset()
    self.stats.update_stats({})
    self.lbl_cursor.setText("")
    self.lbl_dual.setText("")
    self.lbl_dual.setVisible(False)
    self.chk_cursor.blockSignals(True); self.chk_cursor.setChecked(False); self.chk_cursor.blockSignals(False)
    self.chk_dual.blockSignals(True); self.chk_dual.setChecked(False); self.chk_dual.blockSignals(False)

    # Invalidate custom X axis pointer if the source file is gone
    if self._custom_xaxis_fid is not None and self._custom_xaxis_fid not in self.files:
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        self._custom_xlabel = None
        self.combo_xaxis.blockSignals(True)
        self.combo_xaxis.setCurrentIndex(0)
        self.combo_xaxis.blockSignals(False)
        self.combo_xaxis_ch.setEnabled(False)

    self.combo_xaxis_ch.clear()
    self._update_combos()  # rebuilds combo_sig/combo_rpm from current self.files

    if not self.files:
        self.spin_start.blockSignals(True); self.spin_start.setValue(0); self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(True); self.spin_end.setValue(0); self.spin_end.blockSignals(False)
        self.spin_fs.blockSignals(True); self.spin_fs.setValue(1000); self.spin_fs.blockSignals(False)
    else:
        max_t = max((fd.time_array[-1] for fd in self.files.values() if len(fd.time_array) > 0), default=0)
        if self.spin_end.value() > max_t: self.spin_end.setValue(max_t)
        if self.spin_start.value() > max_t: self.spin_start.setValue(0)
        if self._active in self.files:
            self.spin_fs.blockSignals(True); self.spin_fs.setValue(self.files[self._active].fs); self.spin_fs.blockSignals(False)

    # re-fill combo_xaxis_ch if still in channel mode
    if self.combo_xaxis.currentIndex() == 1:
        self._on_xaxis_mode_changed(1)

    self.plot_time()  # re-renders remaining channels or clears if empty
```

- [ ] **Step 2.2: Rewrite `_close()`**

Replace the body (~line 541-551) with:

```python
def _close(self, fid):
    if fid not in self.files: return
    del self.files[fid]
    self.channel_list.remove_file(fid)
    for i in range(self.file_tabs.count()):
        if self._get_tab_fid(i) == fid: self.file_tabs.removeTab(i); break
    self._active = list(self.files.keys())[0] if self.files else None
    self._update_info()
    self._reset_plot_state(scope='file')
    self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")
```

- [ ] **Step 2.3: Rewrite `close_all()`**

Replace the body (~line 553-560) with:

```python
def close_all(self):
    if not self.files: return
    if QMessageBox.question(self, "确认", f"关闭全部 {len(self.files)} 文件?",
                            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
    for fid in list(self.files.keys()):
        del self.files[fid]
        self.channel_list.remove_file(fid)
    while self.file_tabs.count():
        self.file_tabs.removeTab(0)
    self._active = None
    self._update_info()
    self._reset_plot_state(scope='all')
    self.statusBar.showMessage("已关闭全部")
```

- [ ] **Step 2.4: Import-smoke-check**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -c "from mf4_analyzer.ui.main_window import MainWindow; print('ok')"
```
Expected: `ok`.

- [ ] **Step 2.5: Manual verification**

Run:
```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m mf4_analyzer.app
```

Checklist (confirm all):
1. Load a `.csv` or `.mf4` file → plot → go to FFT tab → run FFT → go to Order tab → run Time-Order → back to time tab → enable cursor.
2. Click 关闭 → time/FFT/Order tabs all empty; 通道选择 tree empty; 统计 empty; 游标 checkbox unchecked; lbl_cursor text gone; combo_sig / combo_rpm empty; combo_xaxis_ch empty; combo_xaxis back to "自动(时间)"; spin_start/spin_end = 0; spin_fs = 1000.
3. Load two files A and B → plot 1 channel from each in overlay → 关闭 A → B's channel re-renders automatically.
4. Load A → 横坐标 → 指定通道 → pick a channel in A → 应用 → close A → combo_xaxis returns to "自动(时间)".
5. Load 3 files → 全部 button → confirm → all empty.

- [ ] **Step 2.6: Run signal tests**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m pytest tests/ -x -q 2>&1 | tail -20
```
Expected: still pass.

- [ ] **Step 2.7: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/main_window.py
git commit -m "fix(ui): centralise file-close cleanup via _reset_plot_state()"
```

---

## Task 3: Create `ui/icons.py`

Programmatic macOS-style icons. Six icons for this pass plus the two
axis-lock icons.

**Files:**
- Create: `mf4_analyzer/ui/icons.py`

- [ ] **Step 3.1: Write the module**

Create the file with this exact content:

```python
"""macOS-style QIcon factories. All icons drawn programmatically via QPainter.
No external image assets. Icons render at 2x DPR for Retina sharpness."""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QPainterPath

BLUE = QColor('#007AFF')
GRAY = QColor('#48484A')
RED = QColor('#FF3B30')
GREEN = QColor('#34C759')


def _canvas(size=20):
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    return pix, p


def _pen(color, w=1.5):
    pen = QPen(color, w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _padlock(p, color):
    """Draw a small padlock at ~(4..16, 6..16). Shared body for lock_x/lock_y."""
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.NoBrush)
    # shackle (top U)
    p.drawArc(QRectF(6, 3, 8, 8), 0 * 16, 180 * 16)
    # body (rounded rect)
    p.setBrush(QBrush(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(4, 8, 12, 9), 1.5, 1.5)


def _axis_letter(p, letter, color=QColor('white')):
    """Overlay a single letter on the lock body."""
    f = QFont()
    f.setPointSizeF(6.5)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QPen(color))
    p.drawText(QRectF(4, 8, 12, 9), Qt.AlignCenter, letter)


class Icons:
    @classmethod
    def lock_x(cls):
        pix, p = _canvas(20)
        _padlock(p, BLUE)
        _axis_letter(p, 'X')
        p.end()
        return QIcon(pix)

    @classmethod
    def lock_y(cls):
        pix, p = _canvas(20)
        _padlock(p, BLUE)
        _axis_letter(p, 'Y')
        p.end()
        return QIcon(pix)

    @classmethod
    def add_file(cls):
        pix, p = _canvas(20)
        # circle outline
        p.setPen(_pen(BLUE, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(3, 3, 14, 14))
        # plus
        p.drawLine(QPointF(10, 6), QPointF(10, 14))
        p.drawLine(QPointF(6, 10), QPointF(14, 10))
        p.end()
        return QIcon(pix)

    @classmethod
    def close_file(cls):
        pix, p = _canvas(20)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(RED))
        p.drawRoundedRect(QRectF(3, 3, 14, 14), 4, 4)
        p.setPen(_pen(QColor('white'), 1.8))
        p.drawLine(QPointF(7, 7), QPointF(13, 13))
        p.drawLine(QPointF(13, 7), QPointF(7, 13))
        p.end()
        return QIcon(pix)

    @classmethod
    def close_all(cls):
        pix, p = _canvas(20)
        p.setPen(Qt.NoPen)
        # two stacked red squares
        p.setBrush(QBrush(QColor(255, 59, 48, 110)))
        p.drawRoundedRect(QRectF(1, 5, 13, 13), 3, 3)
        p.setBrush(QBrush(RED))
        p.drawRoundedRect(QRectF(6, 2, 13, 13), 3, 3)
        p.setPen(_pen(QColor('white'), 1.6))
        p.drawLine(QPointF(10, 6), QPointF(15, 11))
        p.drawLine(QPointF(15, 6), QPointF(10, 11))
        p.end()
        return QIcon(pix)

    @classmethod
    def plot(cls):
        pix, p = _canvas(20)
        p.setPen(_pen(BLUE, 1.6))
        path = QPainterPath()
        path.moveTo(3, 15)
        path.lineTo(7, 9)
        path.lineTo(11, 12)
        path.lineTo(17, 4)
        p.drawPath(path)
        # axis baseline
        p.setPen(_pen(GRAY, 1.0))
        p.drawLine(QPointF(3, 17), QPointF(17, 17))
        p.drawLine(QPointF(3, 17), QPointF(3, 4))
        p.end()
        return QIcon(pix)

    @classmethod
    def rebuild_time(cls):
        pix, p = _canvas(20)
        p.setPen(_pen(BLUE, 1.5))
        p.setBrush(Qt.NoBrush)
        # circular arrow
        p.drawArc(QRectF(3, 3, 14, 14), 30 * 16, 270 * 16)
        # arrowhead
        path = QPainterPath()
        path.moveTo(14, 2)
        path.lineTo(17, 5)
        path.lineTo(12, 6)
        path.closeSubpath()
        p.setBrush(QBrush(BLUE))
        p.setPen(Qt.NoPen)
        p.drawPath(path)
        # clock hand
        p.setPen(_pen(BLUE, 1.3))
        p.drawLine(QPointF(10, 10), QPointF(10, 6))
        p.drawLine(QPointF(10, 10), QPointF(13, 10))
        p.end()
        return QIcon(pix)
```

- [ ] **Step 3.2: Import-smoke-check**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -c "from mf4_analyzer.ui.icons import Icons; print('ok')"
```
Expected: `ok`.

Note: `QIcon` instantiation needs a `QApplication`, so we don't call
the factory methods in the smoke check — only import-level checks. The
real visual verification happens in Task 7.

- [ ] **Step 3.3: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/icons.py
git commit -m "feat(ui): add Icons module — programmatic macOS-style QIcons"
```

---

## Task 4: Create `ui/style.qss` + load in `app.py`

Global stylesheet; install at QApplication boot.

**Files:**
- Create: `mf4_analyzer/ui/style.qss`
- Modify: `mf4_analyzer/app.py`

- [ ] **Step 4.1: Create the stylesheet**

Create `mf4_analyzer/ui/style.qss` with exactly:

```css
/* MF4 Analyzer — macOS-style global QSS */

QWidget { font-family: -apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif; }

QPushButton, QToolButton {
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    padding: 4px 10px;
    background: #FFFFFF;
    color: #1C1C1E;
}
QPushButton:hover, QToolButton:hover { background: #F2F2F7; }
QPushButton:pressed, QToolButton:pressed { background: #E5E5EA; }
QPushButton:disabled, QToolButton:disabled { color: #8E8E93; background: #F9F9FB; }

QPushButton#primary {
    background: #007AFF; color: white; border: 1px solid #007AFF;
    font-weight: 600;
}
QPushButton#primary:hover { background: #0A84FF; border-color: #0A84FF; }
QPushButton#primary:pressed { background: #0060DF; }

QPushButton#danger {
    background: #FF3B30; color: white; border: 1px solid #FF3B30;
}
QPushButton#danger:hover { background: #FF453A; border-color: #FF453A; }
QPushButton#danger:pressed { background: #D9201A; }

QPushButton#accent {
    background: #FF9500; color: white; border: 1px solid #FF9500;
}
QPushButton#accent:hover { background: #FFA01F; }

QPushButton#success {
    background: #34C759; color: white; border: 1px solid #34C759;
}
QPushButton#success:hover { background: #3BD86A; }

QToolButton#axisLock {
    padding: 3px 6px;
}
QToolButton#axisLock:checked {
    background: #007AFF; border-color: #007AFF;
}

QGroupBox {
    border: 1px solid #E5E5EA;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: 600;
    color: #1C1C1E;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    background: transparent;
}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    border: 1px solid #D1D1D6;
    border-radius: 5px;
    padding: 2px 6px;
    background: #FFFFFF;
    selection-background-color: #007AFF;
    selection-color: white;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
    border-color: #007AFF;
}

QTabWidget::pane { border: 1px solid #E5E5EA; border-radius: 4px; }
QTabBar::tab {
    background: transparent;
    border: 1px solid transparent;
    padding: 5px 12px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
}
QTabBar::tab:selected { background: #FFFFFF; border-color: #E5E5EA; border-bottom-color: #FFFFFF; }
QTabBar::tab:hover:!selected { background: #F2F2F7; }

QScrollBar:vertical {
    width: 9px; background: transparent; margin: 0;
}
QScrollBar::handle:vertical {
    background: #C7C7CC; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #AEAEB2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 9px; background: transparent; }
QScrollBar::handle:horizontal { background: #C7C7CC; border-radius: 4px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #C7C7CC; border-radius: 3px; background: white;
}
QCheckBox::indicator:checked {
    background: #007AFF; border-color: #007AFF;
    image: none;
}

QTreeWidget {
    border: 1px solid #E5E5EA;
    border-radius: 5px;
    background: #FFFFFF;
}
QHeaderView::section {
    background: #F2F2F7;
    padding: 3px 6px;
    border: none;
    border-right: 1px solid #E5E5EA;
    font-weight: 600;
}

QStatusBar { background: #F2F2F7; color: #48484A; }
```

- [ ] **Step 4.2: Wire the stylesheet into `app.py`**

The existing `app.py` has this `main()` body (verified):
```python
def main():
    bootstrap_pyqt5 = _import_symbol("_qt_bootstrap", "bootstrap_pyqt5")
    bootstrap_pyqt5()
    import matplotlib
    matplotlib.use("Qt5Agg", force=True)
    from PyQt5.QtWidgets import QApplication
    MainWindow = _import_symbol("ui", "MainWindow")
    setup_chinese_font = _import_symbol("_fonts", "setup_chinese_font")
    setup_chinese_font()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
```

Apply **two edits** via the Edit tool. **Do not rewrite the file.**

**Edit A** — insert the `_load_stylesheet` helper **before** `def main():`. Replace:
```python
def main():
    bootstrap_pyqt5 = _import_symbol("_qt_bootstrap", "bootstrap_pyqt5")
```
with:
```python
def _load_stylesheet(app):
    qss = Path(__file__).resolve().parent / "ui" / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))


def main():
    bootstrap_pyqt5 = _import_symbol("_qt_bootstrap", "bootstrap_pyqt5")
```

**Edit B** — insert the load call after `app.setStyle('Fusion')`. Replace:
```python
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
```
with:
```python
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    _load_stylesheet(app)
    window = MainWindow()
```

Do NOT delete `app.setStyle('Fusion')` — Fusion + QSS coexist; Fusion
provides the widget baseline and QSS overrides chrome.

- [ ] **Step 4.3: Smoke-launch**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m mf4_analyzer.app
```
Expected: app launches, buttons show rounded corners, hover shows light gray. Close the window.

If `QApplication` errors about invalid QSS property, read the error line number from stderr and fix the offending CSS rule (most commonly a missing `;` or a property PyQt5's QSS parser doesn't accept).

- [ ] **Step 4.4: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/style.qss mf4_analyzer/app.py
git commit -m "feat(ui): add global macOS-style QSS loaded at app boot"
```

---

## Task 5: Axis-lock toolbar + rubber-band on `TimeDomainCanvas`

Pure addition: two toggle buttons in a new widget, plus state machine in
the time canvas. Zero impact when both toggles are off.

**Files:**
- Create: `mf4_analyzer/ui/axis_lock_toolbar.py`
- Modify: `mf4_analyzer/ui/canvases.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 5.1: Create `axis_lock_toolbar.py`**

Exact contents:

```python
"""Toggle bar with mutually-exclusive 🔒X / 🔒Y buttons.
Emits lock_changed(mode) where mode in {'x', 'y', 'none'}."""
from PyQt5.QtCore import pyqtSignal, QSize
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QToolButton

from .icons import Icons


class AxisLockBar(QWidget):
    lock_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.btn_x = self._make_btn(Icons.lock_x(), "仅缩放 X 轴（左键拖动框选）")
        self.btn_y = self._make_btn(Icons.lock_y(), "仅缩放 Y 轴（左键拖动框选）")
        lay.addWidget(self.btn_x)
        lay.addWidget(self.btn_y)
        lay.addStretch()
        self.btn_x.toggled.connect(lambda v: self._on_toggle('x', v))
        self.btn_y.toggled.connect(lambda v: self._on_toggle('y', v))

    def _make_btn(self, icon, tip):
        b = QToolButton()
        b.setIcon(icon)
        b.setIconSize(QSize(18, 18))
        b.setCheckable(True)
        b.setToolTip(tip)
        b.setObjectName("axisLock")
        return b

    def _on_toggle(self, which, checked):
        if checked:
            other = self.btn_y if which == 'x' else self.btn_x
            if other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
            self.lock_changed.emit(which)
        else:
            if not self.btn_x.isChecked() and not self.btn_y.isChecked():
                self.lock_changed.emit('none')
```

- [ ] **Step 5.2: Add axis-lock state to `TimeDomainCanvas`**

In `mf4_analyzer/ui/canvases.py`, inside `TimeDomainCanvas.__init__` add
these lines at the end (after `self.setFocusPolicy(Qt.StrongFocus)`):

```python
self._axis_lock = None     # None | 'x' | 'y'
self._rb_start = None      # (x, y) at press
self._rb_ax = None
self._rb_patch = None
self.mpl_connect('button_release_event', self._on_release)
self.mpl_connect('key_press_event', self._on_key)
```

Also add `Rectangle` import if not present. At the top of the file, add:

```python
from matplotlib.patches import Rectangle
```

- [ ] **Step 5.3: Add axis-lock methods to `TimeDomainCanvas`**

Insert these methods anywhere in `TimeDomainCanvas` (suggest after
`_reset_cursors`'s analog or at the end of the class):

```python
def set_axis_lock(self, mode):
    """mode in {'x', 'y', 'none'}."""
    self._axis_lock = None if mode == 'none' else mode
    if self.span_selector is not None:
        self.span_selector.set_active(self._axis_lock is None)
    self._cancel_rb()

def _cancel_rb(self):
    if self._rb_patch is not None:
        try: self._rb_patch.remove()
        except Exception: pass
    self._rb_patch = None
    self._rb_start = None
    self._rb_ax = None
    self.draw_idle()

def _on_release(self, e):
    if self._axis_lock is None or self._rb_start is None or self._rb_ax is None:
        return
    if e.inaxes is not self._rb_ax or e.xdata is None or e.ydata is None:
        self._cancel_rb(); return
    x0, y0 = self._rb_start
    x1, y1 = e.xdata, e.ydata
    ax = self._rb_ax
    if self._axis_lock == 'x' and abs(x1 - x0) > 1e-9:
        ax.set_xlim(min(x0, x1), max(x0, x1))
    elif self._axis_lock == 'y' and abs(y1 - y0) > 1e-9:
        ax.set_ylim(min(y0, y1), max(y0, y1))
    self._cancel_rb()
    self._refresh = True

def _on_key(self, e):
    if e.key == 'escape':
        self._cancel_rb()
```

- [ ] **Step 5.4: Patch `_on_click` to start the rubber-band**

Locate `_on_click` in `TimeDomainCanvas` (~line 164). Replace it with:

```python
def _on_click(self, e):
    # Axis-lock mode short-circuits dual-cursor and initiates rubber-band
    if self._axis_lock is not None and e.button == 1 and e.inaxes is not None \
            and e.xdata is not None and e.ydata is not None:
        self._rb_start = (e.xdata, e.ydata)
        self._rb_ax = e.inaxes
        xlo, xhi = e.inaxes.get_xlim()
        ylo, yhi = e.inaxes.get_ylim()
        if self._axis_lock == 'x':
            self._rb_patch = Rectangle((e.xdata, ylo), 0, yhi - ylo,
                                       facecolor='#007AFF', alpha=0.18, edgecolor='#007AFF', lw=0.8)
        else:
            self._rb_patch = Rectangle((xlo, e.ydata), xhi - xlo, 0,
                                       facecolor='#007AFF', alpha=0.18, edgecolor='#007AFF', lw=0.8)
        e.inaxes.add_patch(self._rb_patch)
        self.draw_idle()
        return
    if not self._dual or not self._cursor_visible or e.inaxes is None or e.xdata is None or e.button != 1:
        return
    if self._placing == 'A':
        self._ax = e.xdata; self._placing = 'B'
    else:
        self._bx = e.xdata; self._placing = 'A'
    self._update_dual()
```

- [ ] **Step 5.5: Patch `_on_move` to update the rubber-band**

Locate `_on_move` (~line 172). Replace with:

```python
def _on_move(self, e):
    # Rubber-band update has priority
    if self._rb_start is not None and self._rb_patch is not None and e.inaxes is self._rb_ax \
            and e.xdata is not None and e.ydata is not None:
        x0, y0 = self._rb_start
        if self._axis_lock == 'x':
            self._rb_patch.set_x(min(x0, e.xdata))
            self._rb_patch.set_width(abs(e.xdata - x0))
        else:
            self._rb_patch.set_y(min(y0, e.ydata))
            self._rb_patch.set_height(abs(e.ydata - y0))
        self.draw_idle()
        return
    if not self._cursor_visible or e.inaxes is None or e.xdata is None: return
    now = _time.monotonic() * 1000
    if now - self._last_t < 33: return
    self._last_t = now
    if self._dual:
        self._update_dual(hover=e.xdata)
    else:
        self._update_single(e.xdata)
```

- [ ] **Step 5.6: Wire the bar into `main_window.py`**

In `_right()`, locate where `self.toolbar_time = NavigationToolbar(...)`
is created (~line 234). Change the layout so the toolbar and the new
`AxisLockBar` sit side-by-side:

```python
from .axis_lock_toolbar import AxisLockBar
```
(add to imports at top of file)

Replace the lines that currently add the toolbar and labels to `tl`:

Before:
```python
self.toolbar_time = NavigationToolbar(self.canvas_time, self)
...
tl.addWidget(self.toolbar_time);
tl.addWidget(self.lbl_cursor);
tl.addWidget(self.lbl_dual);
tl.addWidget(self.canvas_time, stretch=1)
```

After:
```python
self.toolbar_time = NavigationToolbar(self.canvas_time, self)
self.axis_lock = AxisLockBar(self)
tb_row = QHBoxLayout()
tb_row.addWidget(self.toolbar_time, stretch=1)
tb_row.addWidget(self.axis_lock)
tl.addLayout(tb_row)
tl.addWidget(self.lbl_cursor)
tl.addWidget(self.lbl_dual)
tl.addWidget(self.canvas_time, stretch=1)
```

In `_connect()`, add one line after the existing cursor_info connect:
```python
self.axis_lock.lock_changed.connect(self.canvas_time.set_axis_lock)
```

- [ ] **Step 5.7: Import-smoke-check**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -c "from mf4_analyzer.ui.main_window import MainWindow; print('ok')"
```
Expected: `ok`.

- [ ] **Step 5.8: Manual verification**

Launch:
```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m mf4_analyzer.app
```

Checklist:
1. Load a file, plot a channel.
2. Click 🔒X. Left-drag horizontally across plot → blue vertical band follows cursor → release → X-axis zooms to dragged range; Y axis unchanged.
3. Click 🔒X again to turn off → left-drag does nothing special (cursor / native behaviour).
4. Click 🔒Y. Left-drag vertically → blue horizontal band → release → Y-axis zooms; X unchanged.
5. Click 🔒X, start a drag, press `Esc` → band disappears; nothing zooms.
6. Click 🔒X, click 🔒Y → 🔒X auto-deselects (mutual exclusion).
7. Click native matplotlib zoom in toolbar → still works as before.
8. With both locks off and dual-cursor checked, click the plot → A/B cursors still work.

- [ ] **Step 5.9: Run signal tests**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m pytest tests/ -x -q 2>&1 | tail -20
```
Expected: pass.

- [ ] **Step 5.10: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/axis_lock_toolbar.py mf4_analyzer/ui/canvases.py mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): add axis-lock rubber-band zoom for time-domain canvas"
```

---

## Task 6: Overlay per-channel twin-Y + subplot unit + cursor units + warn dialog

Rewrites the overlay branch of `plot_channels`, adds unit to subplot
Y-labels, appends unit to cursor readouts, and adds the >5-channel
confirmation dialog in `MainWindow.plot_time()`.

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 6.1: Rewrite `TimeDomainCanvas.plot_channels` overlay branch**

Locate `plot_channels` (~line 59). Replace the whole method with:

```python
def plot_channels(self, ch_list, mode='overlay', xlabel='Time (s)'):
    self.clear()
    vis = [(n, t, s, c, u) for n, v, t, s, c, u in ch_list if v]
    if not vis: self.draw(); return
    if mode == 'subplot' and len(vis) > 1:
        n = len(vis); first = None
        for i, (name, t, sig, color, unit) in enumerate(vis):
            ax = self.fig.add_subplot(n, 1, i + 1, sharex=first) if i > 0 else self.fig.add_subplot(n, 1, 1)
            if i == 0: first = ax
            self.axes_list.append(ax)
            td, sd = self._ds(t, sig)
            ax.plot(td, sd, color=color, lw=0.8)
            self.channel_data[name] = (t, sig, color, unit)
            label = f"{name[:22]} ({unit})" if unit else name[:22]
            ax.set_ylabel(label, fontsize=8, color=color)
            ax.tick_params(axis='y', colors=color, labelsize=7)
            ax.spines['left'].set_color(color); ax.spines['left'].set_linewidth(2)
            ax.grid(True, alpha=0.25, ls='--')
            if i < n - 1:
                ax.tick_params(axis='x', labelbottom=False)
            else:
                ax.set_xlabel(xlabel, fontsize=9)
        self.fig.subplots_adjust(hspace=0.05, left=0.12, right=0.96, top=0.97, bottom=0.07)
    elif mode == 'overlay' and len(vis) >= 2:
        # Per-channel twin-Y axes
        ax0 = self.fig.add_subplot(1, 1, 1); self.axes_list.append(ax0)
        twins = []
        for i in range(1, len(vis)):
            tw = ax0.twinx(); self.axes_list.append(tw); twins.append(tw)
            if i >= 2:
                tw.spines['right'].set_position(('outward', 60 * (i - 1)))
        for ax, (name, t, sig, color, unit) in zip(self.axes_list, vis):
            td, sd = self._ds(t, sig)
            ax.plot(td, sd, color=color, lw=0.8)
            self.channel_data[name] = (t, sig, color, unit)
            label = f"{name[:18]} ({unit})" if unit else name[:18]
            ax.set_ylabel(label, color=color, fontsize=8)
            ax.tick_params(axis='y', colors=color, labelsize=7)
            side = 'left' if ax is ax0 else 'right'
            ax.spines[side].set_color(color); ax.spines[side].set_linewidth(1.5)
        ax0.set_xlabel(xlabel, fontsize=9)
        ax0.grid(True, alpha=0.25, ls='--')
        right = max(0.95 - 0.06 * max(0, len(vis) - 2), 0.60)
        self.fig.subplots_adjust(left=0.08, right=right, top=0.97, bottom=0.08)
    else:
        # single channel
        ax = self.fig.add_subplot(1, 1, 1); self.axes_list.append(ax)
        name, t, sig, color, unit = vis[0]
        td, sd = self._ds(t, sig)
        ax.plot(td, sd, color=color, lw=0.8)
        self.channel_data[name] = (t, sig, color, unit)
        label = f"{name[:22]} ({unit})" if unit else name[:22]
        ax.set_ylabel(label, fontsize=8, color=color)
        ax.tick_params(axis='y', colors=color, labelsize=7)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.grid(True, alpha=0.25, ls='--')
        self.fig.tight_layout(pad=0.5)
    for ax in self.axes_list:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=10, min_n_ticks=3))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=3))
    self.draw(); self._refresh = True
```

- [ ] **Step 6.2: Append units in cursor readouts**

In `TimeDomainCanvas._update_single`, replace the info-building loop:

Before:
```python
for ch, (tf, sf, _, _) in self.channel_data.items():
    if len(tf): idx = min(np.searchsorted(tf, x), len(sf) - 1); info.append(f"{ch[:18]}={sf[idx]:.4g}")
```

After:
```python
for ch, (tf, sf, _, u) in self.channel_data.items():
    if len(tf):
        idx = min(np.searchsorted(tf, x), len(sf) - 1)
        unit_s = f" {u}" if u else ""
        info.append(f"{ch[:18]}={sf[idx]:.4g}{unit_s}")
```

In `TimeDomainCanvas._update_dual`, replace the dual-stats loop. Before:
```python
for ch, (tf, sf, _, _) in self.channel_data.items():
    if len(tf): m = (tf >= xlo) & (tf <= xhi); seg = sf[m]
    if len(seg): dual.append(f"{ch[:20]}:Min={np.min(seg):.4g} Max={np.max(seg):.4g}  Avg={np.mean(seg):.4g} RMS={np.sqrt(np.mean(seg ** 2)):.4g}")
```

After:
```python
for ch, (tf, sf, _, u) in self.channel_data.items():
    if not len(tf): continue
    m = (tf >= xlo) & (tf <= xhi); seg = sf[m]
    if not len(seg): continue
    unit_s = f" {u}" if u else ""
    dual.append(
        f"{ch[:20]}:Min={np.min(seg):.4g}{unit_s} Max={np.max(seg):.4g}{unit_s} "
        f"Avg={np.mean(seg):.4g}{unit_s} RMS={np.sqrt(np.mean(seg ** 2)):.4g}{unit_s}"
    )
```

Note: The original used a buggy outer `if len(tf): m = ...; seg = sf[m]`
followed by an unindented `if len(seg):` — `seg` would be undefined
when `tf` was empty. The replacement fixes the indentation/scope bug
while adding units.

- [ ] **Step 6.3: Add >5-channel confirmation dialog in `plot_time()`**

In `MainWindow.plot_time()` (~line 588), after `checked = self.channel_list.get_checked_channels()` and its early-return, but before the data-building loop, insert:

Before the line `data = []; st = {}`:
```python
mode = 'subplot' if self.combo_mode.currentIndex() == 0 else 'overlay'
if mode == 'overlay' and len(checked) > 5:
    ans = QMessageBox.question(
        self, "确认",
        f"overlay 下 {len(checked)} 个通道会产生 {len(checked)} 根 Y 轴，右侧可能拥挤。继续？",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    if ans != QMessageBox.Yes:
        return
```

Then REMOVE the redundant `mode = ...` line that currently appears later
in `plot_time()` (~line 624):

```python
mode = 'subplot' if self.combo_mode.currentIndex() == 0 else 'overlay'
```

(It's now computed above. Keep the `xlabel = ...` and
`self.canvas_time.plot_channels(data, mode, xlabel=xlabel)` lines.)

- [ ] **Step 6.4: Import-smoke-check**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -c "from mf4_analyzer.ui.main_window import MainWindow; print('ok')"
```
Expected: `ok`.

- [ ] **Step 6.5: Manual verification**

Launch:
```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m mf4_analyzer.app
```

Checklist:
1. Load a file with at least 3 channels of different units (e.g., `°C`, `rpm`, `Nm`). If not available, any MF4 with distinct-unit channels works.
2. Select Overlay, check 2 channels with different units, 绘图 → two distinct Y axes (left & right), each labelled `name (unit)` with matching colours on spines and ticks.
3. Check a 3rd channel → three Y axes; third one offset to the right by ~60px.
4. Check 6 channels → confirmation dialog appears; choose No → no plot; choose Yes → six Y axes rendered (right side crowded but visible).
5. Select Subplot, 2 channels → each subplot's Y label shows `(unit)`.
6. Enable 游标 → readout row format `channel=value unit`; 双游标 → stats line shows values with unit suffix.
7. Single channel overlay → single Y axis, no warning.

- [ ] **Step 6.6: Run signal tests**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m pytest tests/ -x -q 2>&1 | tail -20
```
Expected: pass.

- [ ] **Step 6.7: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/canvases.py mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): overlay per-channel twin-Y with unit labels; subplot/cursor units"
```

---

## Task 7: Replace emoji buttons with icons + QSS object names

Six buttons switch to `Icons` calls; `objectName`s unlock the primary /
danger QSS rules.

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 7.1: Import Icons**

At top of `mf4_analyzer/ui/main_window.py` add:
```python
from .icons import Icons
```

- [ ] **Step 7.2: Replace the six buttons' construction**

In `_left()`, locate and replace:

Before:
```python
self.btn_load = QPushButton("➕ 添加");
self.btn_load.setStyleSheet("font-weight:bold;background:#2196F3;color:white;");
br.addWidget(self.btn_load)
self.btn_close = QPushButton("✖ 关闭");
self.btn_close.setStyleSheet("background:#f44336;color:white;");
br.addWidget(self.btn_close)
self.btn_close_all = QPushButton("全部");
self.btn_close_all.setMaximumWidth(50);
br.addWidget(self.btn_close_all)
```

After:
```python
self.btn_load = QPushButton(" 添加")
self.btn_load.setIcon(Icons.add_file())
self.btn_load.setObjectName("primary")
br.addWidget(self.btn_load)
self.btn_close = QPushButton(" 关闭")
self.btn_close.setIcon(Icons.close_file())
self.btn_close.setObjectName("danger")
br.addWidget(self.btn_close)
self.btn_close_all = QPushButton("全部")
self.btn_close_all.setIcon(Icons.close_all())
self.btn_close_all.setObjectName("danger")
self.btn_close_all.setMaximumWidth(70)
br.addWidget(self.btn_close_all)
```

Before:
```python
self.btn_plot = QPushButton("📈 绘图");
self.btn_plot.setStyleSheet("font-weight:bold;");
gl.addWidget(self.btn_plot)
```

After:
```python
self.btn_plot = QPushButton(" 绘图")
self.btn_plot.setIcon(Icons.plot())
self.btn_plot.setObjectName("primary")
gl.addWidget(self.btn_plot)
```

Before:
```python
self.btn_rebuild_time = QPushButton("🔄 重建时间轴");
self.btn_rebuild_time.setToolTip("根据Fs重新生成当前文件的时间轴")
```

After:
```python
self.btn_rebuild_time = QPushButton(" 重建时间轴")
self.btn_rebuild_time.setIcon(Icons.rebuild_time())
self.btn_rebuild_time.setToolTip("根据Fs重新生成当前文件的时间轴")
```

Leave all other emoji-prefixed buttons (`🔧 编辑`, `📥 导出`, `▶ FFT`, `▶
时间-阶次`, `▶ 转速-阶次`, `▶ 阶次跟踪`) untouched — QSS still restyles their
chrome. Remove their inline `setStyleSheet("...color:white;")` calls so
that QSS takes over their look:

Before (in `_left()`):
```python
self.btn_edit = QPushButton("🔧 编辑");
self.btn_edit.setStyleSheet("background:#FF9800;color:white;");
bh.addWidget(self.btn_edit)
self.btn_export = QPushButton("📥 导出");
self.btn_export.setStyleSheet("background:#4CAF50;color:white;");
bh.addWidget(self.btn_export)
```

After:
```python
self.btn_edit = QPushButton("🔧 编辑")
self.btn_edit.setObjectName("accent")
bh.addWidget(self.btn_edit)
self.btn_export = QPushButton("📥 导出")
self.btn_export.setObjectName("success")
bh.addWidget(self.btn_export)
```

(QSS rules for `#accent` and `#success` are already in `style.qss` from Task 4.)

- [ ] **Step 7.3: Smoke-launch**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m mf4_analyzer.app
```

Checklist:
1. Left panel buttons render with crisp blue/red icons (not emoji).
2. `添加` button has blue background, `关闭` red, `全部` red, `绘图` blue.
3. `编辑` orange, `导出` green.
4. Axis-lock bar in right panel shows two padlock icons (with X/Y letters).
5. Hover on each button → background lightens slightly.
6. No visual regression elsewhere.

- [ ] **Step 7.4: Run signal tests**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m pytest tests/ -x -q 2>&1 | tail -20
```
Expected: pass.

- [ ] **Step 7.5: Commit**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
git add mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): swap emoji buttons for macOS-style icons; QSS object names"
```

---

## Task 8: End-to-end regression pass

Final integrated check; no code changes.

- [ ] **Step 8.1: Launch app**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m mf4_analyzer.app
```

- [ ] **Step 8.2: Full flow checklist**

Run through every feature in one session:
1. Load 2 files A (small CSV) and B (MF4 or another CSV).
2. Overlay plot 3 channels from A → 3 Y axes, units present.
3. Enable 游标 → readouts include units.
4. Enable 双游标 → A/B cursors + stats with units.
5. Zoom: `🔒X` drag → X-only zoom; `🔒Y` drag → Y-only zoom; both off; native toolbar zoom still works.
6. Switch to FFT tab → run FFT → add remark → double-click Y axis to edit.
7. Switch to Order tab → run time-order → run rpm-order → run order tracking.
8. Select custom X axis: 指定通道 → pick a channel in B → 应用 → time plot re-renders.
9. Close A → FFT/Order canvases clear; stats clear; custom X remains if it pointed to B, otherwise resets; remaining B channel re-renders.
10. Close all → everything empty; spin_fs = 1000; status bar "已关闭全部".
11. Confirm no Python exceptions on stderr.

- [ ] **Step 8.3: Run full test suite one last time**

```bash
cd /Users/donghang/Documents/Codex/mf4_project/data-analyzer-fresh
python -m pytest tests/ -q 2>&1 | tail -30
```
Expected: all green.

- [ ] **Step 8.4: Push branch (user decision)**

Ask the user whether to push the branch `claude/fft-remarks-chart-ui-sJ410`
and open a PR; do not push without confirmation.

---

## Risk Log

- **QSS parser rejects a property** → error shows line number; fix the
  offending rule inline; do not try to mass-rewrite the QSS.
- **Icon painter coords look off at other DPRs** → adjust `_canvas(size=...)`
  and related QRectF values; Retina (2x) is the calibration target.
- **Overlay twin-Y right margin too tight at n=6** → `right = max(..., 0.60)`
  floor prevents sub-0.6; if users complain, raise floor to 0.55.
- **Rubber-band conflicts with double-click axis edit on PlotCanvas** →
  irrelevant here: `PlotCanvas` (FFT/Order) has no axis-lock; only
  `TimeDomainCanvas` gets it.
- **`_reset_plot_state` fires during a live FFT/Order computation** → not
  possible: those run synchronously on the GUI thread; user can't click
  close until they return.

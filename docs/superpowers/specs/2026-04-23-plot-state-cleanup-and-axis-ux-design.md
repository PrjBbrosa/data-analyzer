# MF4 Analyzer UI Polish — Design Spec

**Date:** 2026-04-23
**Branch:** `claude/fft-remarks-chart-ui-sJ410`
**Scope:** Three UI issues + opportunistic icon / stylesheet modernization.

## 1. Problem Statement

Three defects surfaced during usage:

1. **State leak on file close.** Closing a file leaves stale channel, cursor,
   remark, statistics, and combo-box data from the closed file visible. Some
   panels (FFT, Order) are never cleared.
2. **No axis-locked zoom.** Users can only zoom via scroll modifiers
   (Ctrl=X, Shift=Y). No visible toggle, no rubber-band-with-axis-lock
   interaction.
3. **Overlay plots collapse channels with different units.** All channels
   share a single Y axis in overlay mode; no unit annotation; channels of
   very different scales become unreadable.

Additional opportunistic improvement: the app currently uses emoji labels
and ad-hoc inline stylesheets. Users asked for a macOS-style, modernised
look.

## 2. Solution Overview — Route B (approved)

Four independently testable changes:

| ID | Change | Files touched |
|----|--------|---------------|
| R1 | `MainWindow._reset_plot_state(scope)` cleanup contract | `ui/main_window.py`, `ui/canvases.py` |
| R2 | Axis-lock toolbar + rubber-band selector on `TimeDomainCanvas` | `ui/axis_lock_toolbar.py` (new), `ui/canvases.py`, `ui/main_window.py` |
| R3 | Overlay per-channel twin-Y with unit labels | `ui/canvases.py`, `ui/main_window.py` |
| R4 | Icon system + global stylesheet | `ui/icons.py` (new), `ui/style.qss` (new), `app.py`, `ui/main_window.py` |

No signal-processing code is touched. No tests for numeric algorithms are
affected. All diffs are `ui/` and `app.py`.

## 3. R1 — Cleanup Contract

### Goal
Single source of truth for "what to wipe when a file closes." Both
`_close(fid)` and `close_all()` go through it. `plot_time()` stays
authoritative for "re-render after state changes."

### API additions

**`ui/canvases.py`**

```python
class TimeDomainCanvas(FigureCanvas):
    def full_reset(self):
        """Clear figure AND cursor/dual-cursor/background state."""
        self.clear()                       # existing
        self._bg = None
        self._cursor_artists = []
        self._a_artists, self._b_artists = [], []
        self._ax = self._bx = None
        self._placing = 'A'
        self._cursor_visible = False
        self._dual = False
        self.draw_idle()

class PlotCanvas(FigureCanvas):
    def full_reset(self):
        """Clear figure AND remarks/stored-line-data."""
        self.clear()                       # existing
        self.draw_idle()
```

`clear()` keeps its current semantics (figure + minimal state). Internal
callers (`plot_channels`, `do_fft`, etc.) keep calling `clear()`.
`full_reset()` is the new contract for file-close / close-all.

### `MainWindow._reset_plot_state(scope: str)`

`scope ∈ {'file', 'all'}` — identical behaviour today, kept as a parameter
for future divergence.

Order of operations:

1. `canvas_time.full_reset()`, `canvas_fft.full_reset()`, `canvas_order.full_reset()`
2. `stats.update_stats({})`
3. `lbl_cursor.setText("")`, `lbl_dual.setText("")`, `lbl_dual.setVisible(False)`
4. `chk_cursor.setChecked(False)`, `chk_dual.setChecked(False)`
5. If `_custom_xaxis_fid not in self.files`:
   `_custom_xaxis_fid = _custom_xaxis_ch = _custom_xlabel = None`;
   `combo_xaxis.setCurrentIndex(0)` (temporarily block signals to avoid re-filling)
6. `combo_xaxis_ch.clear()`
7. `_update_combos()` (existing — handles `combo_sig`, `combo_rpm`)
8. If `self.files` empty: `spin_start.setValue(0)`, `spin_end.setValue(0)`,
   `spin_fs.setValue(1000)`. Else clip `spin_start/spin_end` to
   `max(fd.time_array[-1] for fd in files)` and set `spin_fs` to active file's fs.
9. Call `self.plot_time()` — it early-returns (clearing time canvas) if
   nothing is selected.

### Call sites

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

def close_all(self):
    if not self.files: return
    if QMessageBox.question(...) != Yes: return
    for fid in list(self.files.keys()):
        del self.files[fid]
        self.channel_list.remove_file(fid)
    while self.file_tabs.count(): self.file_tabs.removeTab(0)
    self._active = None
    self._update_info()
    self._reset_plot_state(scope='all')
    self.statusBar.showMessage("已关闭全部")
```

Note: previous `close_all` called `_close` in a loop which was O(n²) on
tab lookups; the rewrite closes bookkeeping directly and finishes with a
single `_reset_plot_state('all')`.

### Acceptance

- Load file A → plot → FFT → add remark → close A → FFT canvas empty,
  statistics empty, cursor checkbox off, X-axis combo back to "自动(时间)".
- Load A + B → plot overlay → close A → remaining B channels re-render
  automatically (no blank canvas).

## 4. R2 — Axis-Lock Rubber-Band Zoom

### Goal
Add a Mac-style toggle pair next to the time-domain toolbar. When `🔒X` is
active, left-drag on the plot draws a vertical band and only `set_xlim`
zooms on release. When `🔒Y` is active, left-drag draws a horizontal band
and only `set_ylim` zooms. Selecting one toggle un-selects the other.

### New module `ui/axis_lock_toolbar.py`

```python
from PyQt5.QtCore import pyqtSignal, QSize
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QToolButton
from .icons import Icons

class AxisLockBar(QWidget):
    lock_changed = pyqtSignal(str)  # 'x' | 'y' | 'none'

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        self.btn_x = self._make_btn(Icons.lock_x(), "仅缩放 X 轴\n左键拖动框选")
        self.btn_y = self._make_btn(Icons.lock_y(), "仅缩放 Y 轴\n左键拖动框选")
        lay.addWidget(self.btn_x); lay.addWidget(self.btn_y); lay.addStretch()
        self.btn_x.toggled.connect(lambda v: self._on_toggle('x', v))
        self.btn_y.toggled.connect(lambda v: self._on_toggle('y', v))

    def _make_btn(self, icon, tip):
        b = QToolButton(); b.setIcon(icon); b.setIconSize(QSize(20,20))
        b.setCheckable(True); b.setToolTip(tip)
        b.setObjectName("axisLock")
        return b

    def _on_toggle(self, which, checked):
        if checked:
            # mutually exclusive
            other = self.btn_y if which == 'x' else self.btn_x
            if other.isChecked():
                other.blockSignals(True); other.setChecked(False); other.blockSignals(False)
            self.lock_changed.emit(which)
        else:
            # if both off, emit 'none'
            if not self.btn_x.isChecked() and not self.btn_y.isChecked():
                self.lock_changed.emit('none')
```

### `TimeDomainCanvas` additions

State:
```python
self._axis_lock = None          # None | 'x' | 'y'
self._rb_start = None           # (x_data, y_data) at press time
self._rb_patch = None           # AxVSpan / AxHSpan artist
self._rb_ax    = None           # axes the drag started in
```

API:
```python
def set_axis_lock(self, mode):
    """mode ∈ {'x', 'y', 'none'}. Disables span_selector while active."""
    self._axis_lock = None if mode == 'none' else mode
    if self.span_selector is not None:
        self.span_selector.set_active(mode == 'none')
    self._cancel_rb()
```

Event handlers — integrate into existing `_on_click` / new
`_on_release` / extended `_on_move`:

- **press (button 1)** with `_axis_lock` set: record `_rb_start` and
  `_rb_ax`; create `axvspan(x0, x0, alpha=0.2, color='#007AFF')` or
  `axhspan(y0, y0, ...)`; **return before** the existing dual-cursor
  click logic (dual cursor disabled while locked).
- **motion** while `_rb_start` is set: update the patch's right/top edge.
- **release (button 1)** while `_rb_start` is set: compute
  `[min, max]`; if width > ε, call `ax.set_xlim` or `ax.set_ylim` and
  `draw_idle()`. Remove the patch.
- **Key `Escape`**: `_cancel_rb()` — remove patch, clear `_rb_start`.

Priority: when `_axis_lock` is set, we short-circuit dual-cursor click
handling and SpanSelector is disabled. The matplotlib NavigationToolbar's
native zoom button is unaffected (users can still use it).

### Layout wiring

`ui/main_window.py` `_right()`:

```python
from .axis_lock_toolbar import AxisLockBar
...
self.toolbar_time = NavigationToolbar(self.canvas_time, self)
self.axis_lock = AxisLockBar(self)
tb_row = QHBoxLayout()
tb_row.addWidget(self.toolbar_time)
tb_row.addWidget(self.axis_lock)
tl.addLayout(tb_row)
...
# in _connect:
self.axis_lock.lock_changed.connect(self.canvas_time.set_axis_lock)
```

### Acceptance

- Toggle 🔒X → drag-select range on time plot → only X range zooms; Y
  untouched; cursor label unaffected.
- Toggle 🔒X off → drag no longer creates a band; dual-cursor click works
  again; `SpanSelector` re-enabled.
- Native matplotlib zoom button still works independently.

## 5. R3 — Overlay Per-Channel Twin-Y

### Goal
In overlay mode, give each selected channel its own Y axis labelled
`name (unit)`, with tick colour tracking the channel colour. Warn when
`n > 5`. Subplot mode also gains unit in labels. No legend.

### `TimeDomainCanvas.plot_channels` overlay branch

Replace existing overlay block:

```python
else:  # overlay
    n = len(vis)
    ax0 = self.fig.add_subplot(1, 1, 1); self.axes_list = [ax0]
    for i in range(1, n):
        tw = ax0.twinx(); self.axes_list.append(tw)
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
    # shrink right margin as twin axes multiply
    right = max(0.95 - 0.06 * max(0, n - 2), 0.60)
    self.fig.subplots_adjust(left=0.08, right=right, top=0.97, bottom=0.08)
```

No legend call. `self.channel_data` continues to feed cursor readout.

### Subplot branch — unit label

One-line change:
```python
ax.set_ylabel(f"{name[:22]} ({unit})" if unit else name[:22], fontsize=8, color=color)
```

### Warn on >5 overlay channels — `MainWindow.plot_time()`

After `checked = self.channel_list.get_checked_channels()` and before
computing `data`:

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

### Cursor readout — include unit

In `_update_single` and `_update_dual`, the per-channel info line becomes:
```python
unit_str = f" {u}" if u else ""
info.append(f"{ch[:18]}={sf[idx]:.4g}{unit_str}")
```
(`_update_dual` dual readout — min/max/avg/rms — also appends `unit_str`
to each stat line.) `channel_data[ch]` already stores `(t, sig, color, unit)`.

### Acceptance

- Overlay 3 channels with units `°C`, `rpm`, `Nm` → three distinct Y
  axes, labelled, with coloured ticks and spines; X axis shared.
- Overlay 6 channels → confirmation dialog; proceeding draws but users
  can see it's crowded.
- Subplot 2 channels with units `°C`, `rpm` → each subplot's Y label
  shows unit.
- Cursor readout shows `ch1=23.4 °C │ ch2=1800 rpm`.

## 6. R4 — Icons + Global Stylesheet

### `ui/icons.py`

Programmatic icon rendering via `QPainter`. No external image assets.

```python
from PyQt5.QtCore import Qt, QSize, QRect
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QPainterPath

BLUE = QColor('#007AFF')
GRAY = QColor('#8E8E93')
RED  = QColor('#FF3B30')

class Icons:
    @staticmethod
    def _canvas(size=20):
        pix = QPixmap(size*2, size*2); pix.setDevicePixelRatio(2); pix.fill(Qt.transparent)
        p = QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
        return pix, p

    @classmethod
    def lock_x(cls):        ...  # padlock + "X"
    @classmethod
    def lock_y(cls):        ...
    @classmethod
    def add_file(cls):      ...  # ⊕ circle
    @classmethod
    def close_file(cls):    ...  # × in rounded square
    @classmethod
    def plot(cls):          ...  # sparkline polyline
    @classmethod
    def rebuild_time(cls):  ...  # circular arrow + clock hand
```

Each method returns a `QIcon`. Internally they build a `QPainterPath`,
use `QPen(BLUE, 1.5)`, rounded joins/caps, and draw on a
2× DPR pixmap for retina sharpness.

Usage in `main_window.py`:
```python
from .icons import Icons
self.btn_load = QPushButton("添加"); self.btn_load.setIcon(Icons.add_file())
self.btn_load.setObjectName("primary")
# ...drop the emoji prefix and the inline setStyleSheet colour, QSS handles it
```

### `ui/style.qss`

Global QSS applied at `app.py` boot via
`QApplication.instance().setStyleSheet(qss_text)`.

Highlights (full content to be generated during implementation):

```css
QPushButton, QToolButton {
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    padding: 4px 10px;
    background: #FFFFFF;
}
QPushButton:hover, QToolButton:hover { background: #F2F2F7; }
QPushButton:pressed, QToolButton:pressed { background: #E5E5EA; }
QToolButton#axisLock:checked {
    background: #007AFF; border-color: #007AFF;
}
QPushButton#primary {
    background: #007AFF; color: white; border-color: #007AFF;
}
QPushButton#primary:hover { background: #0A84FF; }
QPushButton#danger {
    background: #FF3B30; color: white; border-color: #FF3B30;
}
QPushButton#danger:hover { background: #FF453A; }
QGroupBox {
    border: 1px solid #E5E5EA; border-radius: 6px;
    margin-top: 10px; padding-top: 6px; font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px;
    color: #1C1C1E;
}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    border: 1px solid #D1D1D6; border-radius: 5px; padding: 2px 6px;
    background: #FFFFFF;
}
QTabWidget::pane { border: 1px solid #E5E5EA; border-radius: 4px; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #C7C7CC; border-radius: 4px; min-height: 20px; }
```

`StatisticsPanel`'s dark monospace label keeps its inline style — intentional.

### `app.py` loader

```python
from pathlib import Path
from PyQt5.QtWidgets import QApplication
...
def main():
    app = QApplication(sys.argv)
    qss_path = Path(__file__).parent / 'ui' / 'style.qss'
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding='utf-8'))
    ...
```

### Scope

Six buttons are re-iconed in this pass:
`btn_load`, `btn_close`, `btn_close_all`, `btn_plot`, `btn_rebuild_time`,
plus the two `AxisLockBar` buttons. Remaining emoji-labeled buttons
(`📊 FFT`, `🔄 阶次`, `🔧 编辑`, `📥 导出`, `▶ FFT`, `▶ 时间-阶次`, etc.)
are left untouched for this iteration to bound the diff; the QSS
still restyles their chrome.

## 7. Out of Scope

- Any signal-processing changes (`mf4_analyzer/signal/**`)
- Replacing matplotlib with pyqtgraph
- Per-channel zoom on twin-Y axes (axis-lock only zooms the primary ax's
  X or the scroll-targeted ax's Y — documented limitation)
- Full icon replacement for every emoji-labeled control
- Theme switching (light/dark); initial pass ships light only

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Rubber-band patch conflicts with dual-cursor `mpl_connect` handlers | Short-circuit dual-cursor when `_axis_lock` is set; test both ON/OFF transitions |
| Twin-Y layout squeezes axes off-screen when n≥5 | `right` margin floor at 0.60 + user-facing warning dialog |
| QSS breaks matplotlib Figure's internal Qt widgets | QSS only targets top-level `QPushButton/QToolButton/QGroupBox/QComboBox/etc.`; matplotlib canvas has no QPushButton children |
| `_reset_plot_state` fires during partial load failure | Called only from `_close`/`close_all`; `_load_one` failures don't invoke it |
| Programmatic icons look mediocre at high DPR | Use `devicePixelRatio(2)`; Qt antialiasing; test on Retina |

## 9. Testing Plan

Manual UI testing checklist (no unit tests for this pass — pure UI).

1. **Cleanup**
   - Load 1 file, plot, FFT, add remark, close file → verify all panels clear and combos empty.
   - Load 2 files, overlay-plot channels from both, close one → remaining channels re-render.
   - Custom X axis pointing to file A, close A → combo returns to "自动(时间)".
2. **Axis lock**
   - Toggle 🔒X, drag, release → only X zooms.
   - Toggle 🔒Y, drag, release → only Y zooms.
   - Toggle both off → native behaviour restored.
   - Mid-drag `Esc` → patch disappears.
3. **Overlay multi-Y**
   - 2-channel overlay, different units → two Y axes.
   - 6-channel overlay → confirmation dialog; proceeding draws.
   - Subplot 2 channels → Y labels include unit.
   - Cursor readouts include units.
4. **Icons / QSS**
   - Buttons render crisply on 1x and 2x DPR.
   - Hover / pressed / checked states all render.
   - No regression in existing layouts.

## 10. File Map

```
mf4_analyzer/
├── app.py                    # modified: load style.qss
└── ui/
    ├── main_window.py        # modified: _reset_plot_state, icons, axis_lock wiring
    ├── canvases.py           # modified: full_reset, axis lock, overlay twin-Y, cursor units
    ├── axis_lock_toolbar.py  # NEW
    ├── icons.py              # NEW
    └── style.qss             # NEW
```

No deletions. No moves. No changes under `mf4_analyzer/signal/` or
`mf4_analyzer/io/`.

# 时域滤波叠加 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在时域面板对已勾选通道做 FFT 频域低/高/带通/带阻滤波，把滤波结果叠加到对应时域图，可勾选切换显示原始/滤波后。

**Architecture:** 纯 numpy FFT 频域滤波（`signal/filters.py`，无状态、零相位）；时域绘图路径 `_plot_time_on_canvas` 对每个勾选通道追加一条滤波叠加曲线；面板新增滤波控件，时间范围+滤波合并为一张卡、单个「绘图」统一提交，横坐标拆为独立卡。仅显示叠加，不改 `channel_data`、不进通道树。

**Tech Stack:** Python 3.12, numpy, PyQt5, pyqtgraph, pytest-qt。解释器 `.venv/bin/python`。

## Global Constraints

- **不用 scipy**（主代码零 scipy 依赖；Windows 打包排除）。滤波只用 numpy。
- **不改 `channel_data` 原始样本**；滤波是显示层叠加。
- **滤波控件透明背景**——禁止默认灰底（QSS `background: transparent`，必要处 `WA_TranslucentBackground` + `paintEvent` 兜底）。真机渲染专项核此条。
- **零相位固有**——FFT 频域法天然零相位，UI 无「零相位」勾选。
- **不破坏 `self.inspector.top.range_values()/range_enabled()/xaxis_*`** 的语义/可读性（FFT/阶次取信号依赖）。
- 真机渲染验收用 `QT_QPA_PLATFORM=offscreen` + `.venv/bin/python` + `widget.grab()`（项目既有方式），临时脚本用完即删。
- EPS 领域措辞（电机转速/转向角），勿用 engine。

---

### Task 1: `signal/filters.py` — FFT 频域滤波核心

**Files:**
- Create: `mf4_analyzer/signal/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Produces:
  - `FilterSpec(kind: str, order: int=4, cutoff: float=0.0, cutoff_lo: float=0.0, cutoff_hi: float=0.0)` — frozen dataclass, `kind ∈ {'low','high','band','bandstop'}`，可 hash。
  - `butter_magnitude(freqs: np.ndarray, spec: FilterSpec) -> np.ndarray` — 实数非负频域掩码。
  - `nyquist_guard(spec: FilterSpec, fs: float) -> tuple[FilterSpec, str|None]` — 钳制+提示；带通 lo≥hi 抛 `ValueError`。
  - `apply(sig: np.ndarray, spec: FilterSpec, fs: float) -> np.ndarray` — 零相位滤波，输出与输入等长；保留 NaN 位置。

- [ ] **Step 1: 写失败测试**

`tests/test_filters.py`:

```python
import numpy as np
import pytest
from mf4_analyzer.signal.filters import (
    FilterSpec, butter_magnitude, nyquist_guard, apply,
)


def test_lowpass_magnitude_is_3db_at_cutoff():
    f = np.array([0.0, 100.0, 1e9])
    m = butter_magnitude(f, FilterSpec('low', order=4, cutoff=100.0))
    assert m[0] == pytest.approx(1.0, abs=1e-6)          # DC passes
    assert m[1] == pytest.approx(1.0 / np.sqrt(2), abs=1e-6)  # -3 dB at fc
    assert m[2] < 1e-6                                    # far above cut → ~0


def test_highpass_is_lowpass_complement_at_cutoff():
    f = np.array([0.0, 100.0, 1e9])
    m = butter_magnitude(f, FilterSpec('high', order=4, cutoff=100.0))
    assert m[0] == pytest.approx(0.0, abs=1e-9)           # DC blocked
    assert m[1] == pytest.approx(1.0 / np.sqrt(2), abs=1e-6)
    assert m[2] == pytest.approx(1.0, abs=1e-3)


def test_lowpass_attenuates_high_keeps_low():
    fs = 2000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    low = np.sin(2 * np.pi * 10 * t)
    high = np.sin(2 * np.pi * 400 * t)
    y = apply(low + high, FilterSpec('low', order=6, cutoff=50.0), fs)
    # low component preserved, high component crushed
    assert np.corrcoef(y, low)[0, 1] > 0.99
    assert np.std(y - low) < 0.15


def test_bandpass_passes_mid_rejects_out():
    fs = 4000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    spec = FilterSpec('band', order=6, cutoff_lo=80.0, cutoff_hi=300.0)
    mid = apply(np.sin(2 * np.pi * 150 * t), spec, fs)
    lo = apply(np.sin(2 * np.pi * 10 * t), spec, fs)
    hi = apply(np.sin(2 * np.pi * 900 * t), spec, fs)
    assert np.std(mid) > 0.6
    assert np.std(lo) < 0.1 and np.std(hi) < 0.1


def test_bandstop_rejects_mid():
    fs = 4000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    spec = FilterSpec('bandstop', order=6, cutoff_lo=80.0, cutoff_hi=300.0)
    assert np.std(apply(np.sin(2 * np.pi * 150 * t), spec, fs)) < 0.1


def test_zero_phase_no_time_shift():
    fs = 2000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    x = np.sin(2 * np.pi * 5 * t)
    y = apply(x, FilterSpec('low', order=4, cutoff=50.0), fs)
    # cross-correlation peak at lag 0 → no phase shift
    xc = np.correlate(y - y.mean(), x - x.mean(), mode='same')
    assert abs(np.argmax(xc) - len(x) // 2) <= 1


def test_multirate_uses_channel_fs():
    spec = FilterSpec('low', order=4, cutoff=1000.0)
    for fs in (5400.0, 129500.0):
        t = np.arange(0, 0.5, 1.0 / fs)
        y = apply(np.sin(2 * np.pi * 100 * t), spec, fs)  # 100 Hz << 1 kHz
        assert np.std(y) > 0.6  # low tone passes at both rates


def test_nyquist_guard_clamps_and_messages():
    spec = FilterSpec('low', order=4, cutoff=9999.0)
    clamped, msg = nyquist_guard(spec, fs=1000.0)
    assert clamped.cutoff < 500.0 and msg is not None


def test_band_lo_ge_hi_raises():
    with pytest.raises(ValueError):
        nyquist_guard(FilterSpec('band', cutoff_lo=300.0, cutoff_hi=100.0), fs=4000.0)


def test_nan_positions_preserved():
    fs = 1000.0
    t = np.arange(0, 1.0, 1.0 / fs)
    x = np.sin(2 * np.pi * 5 * t)
    x[100:110] = np.nan
    y = apply(x, FilterSpec('low', order=4, cutoff=50.0), fs)
    assert np.all(np.isnan(y[100:110]))
    assert np.isfinite(y[0]) and np.isfinite(y[-1])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_filters.py -q`
Expected: FAIL（`ModuleNotFoundError: mf4_analyzer.signal.filters`）。

- [ ] **Step 3: 实现 `signal/filters.py`**

```python
"""Pure-numpy FFT-domain filtering (low/high/band/bandstop), zero-phase, no
scipy. See docs/superpowers/specs/2026-06-22-timedomain-filter-overlay-design.md.

Why FFT-domain not IIR: pure-numpy sosfilt over 1M+ samples × many channels is
seconds-slow; FFT-domain is O(N log N) C-backed (numpy.fft) → ms, numerically
robust (no poles/stability), and zero-phase by construction (real even mask).
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class FilterSpec:
    kind: str            # 'low' | 'high' | 'band' | 'bandstop'
    order: int = 4
    cutoff: float = 0.0       # low/high (Hz)
    cutoff_lo: float = 0.0    # band/bandstop (Hz)
    cutoff_hi: float = 0.0    # band/bandstop (Hz)


def _lp_mag(f, fc, n):
    if fc <= 0:
        return np.zeros_like(f)
    return 1.0 / np.sqrt(1.0 + (f / fc) ** (2 * n))


def _hp_mag(f, fc, n):
    m = np.zeros_like(f)
    pos = f > 0
    m[pos] = 1.0 / np.sqrt(1.0 + (fc / f[pos]) ** (2 * n))
    return m


def butter_magnitude(freqs, spec):
    """Real, non-negative Butterworth-shaped magnitude mask. `freqs` in Hz."""
    f = np.abs(np.asarray(freqs, dtype=float))
    n = int(spec.order)
    if spec.kind == 'low':
        return _lp_mag(f, float(spec.cutoff), n)
    if spec.kind == 'high':
        return _hp_mag(f, float(spec.cutoff), n)
    if spec.kind == 'band':
        return _hp_mag(f, float(spec.cutoff_lo), n) * _lp_mag(f, float(spec.cutoff_hi), n)
    if spec.kind == 'bandstop':
        band = _hp_mag(f, float(spec.cutoff_lo), n) * _lp_mag(f, float(spec.cutoff_hi), n)
        return 1.0 - band
    raise ValueError(f"unknown filter kind: {spec.kind!r}")


def nyquist_guard(spec, fs):
    """Clamp cutoffs into (0, nyquist). Returns (clamped_spec, message|None).
    Raises ValueError if band lo >= hi."""
    nyq = 0.5 * float(fs)
    eps = nyq * 1e-3

    def clamp(v):
        return min(max(float(v), eps), nyq - eps)

    if spec.kind in ('low', 'high'):
        c = clamp(spec.cutoff)
        msg = None if c == spec.cutoff else f"截止频率超出范围，已钳制到 {c:.3g} Hz"
        return FilterSpec(spec.kind, spec.order, cutoff=c), msg

    if float(spec.cutoff_lo) >= float(spec.cutoff_hi):
        raise ValueError("带通/带阻：下限必须小于上限")
    lo, hi = clamp(spec.cutoff_lo), clamp(spec.cutoff_hi)
    msg = (None if (lo, hi) == (spec.cutoff_lo, spec.cutoff_hi)
           else f"截止频率超出范围，已钳制到 {lo:.3g}–{hi:.3g} Hz")
    return FilterSpec(spec.kind, spec.order, cutoff_lo=lo, cutoff_hi=hi), msg


def apply(sig, spec, fs):
    """Zero-phase FFT-domain filter. Output same length as `sig`. NaN positions
    in the input are interpolated for filtering, then restored as NaN."""
    x = np.asarray(sig, dtype=float)
    n0 = x.size
    if n0 < 4 or float(fs) <= 0:
        return x.copy()

    nan_mask = ~np.isfinite(x)
    if nan_mask.all():
        return x.copy()
    xf = x.copy()
    if nan_mask.any():
        idx = np.arange(n0)
        xf[nan_mask] = np.interp(idx[nan_mask], idx[~nan_mask], x[~nan_mask])

    # odd-reflection pad to soften circular-convolution edge wrap
    pad = min(n0 - 1, max(16, n0 // 10))
    left = 2 * xf[0] - xf[pad:0:-1]
    right = 2 * xf[-1] - xf[-2:-pad - 2:-1]
    xp = np.concatenate([left, xf, right])
    N = xp.size

    freqs = np.fft.rfftfreq(N, d=1.0 / float(fs))
    mask = butter_magnitude(freqs, spec)
    yp = np.fft.irfft(np.fft.rfft(xp) * mask, n=N)
    y = yp[pad:pad + n0]

    if nan_mask.any():
        y[nan_mask] = np.nan
    return y
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_filters.py -q`
Expected: 10 passed。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/signal/filters.py tests/test_filters.py
git commit -m "feat(signal): FFT 频域滤波核心 (LP/HP/BP/BS, 零相位, 无 scipy)"
```

---

### Task 2: `FilterPanel` 控件

**Files:**
- Create: `mf4_analyzer/ui/inspector_sections/time_filter.py`
- Test: `tests/ui/test_time_filter_panel.py`

**Interfaces:**
- Consumes: `FilterSpec`（Task 1）。
- Produces: `class FilterPanel(QWidget)`:
  - signal `filter_changed = pyqtSignal()`（任一控件变动时发，供宿主决定是否重绘）。
  - `filter_spec() -> FilterSpec`（按当前类型读 cutoff 或 lo/hi）。
  - `show_original() -> bool` / `show_filtered() -> bool`。
  - 内部：类型下拉切到 band/bandstop 时显示双截止行、否则单截止行。

- [ ] **Step 1: 写失败测试**

`tests/ui/test_time_filter_panel.py`:

```python
import pytest
from mf4_analyzer.ui.inspector_sections.time_filter import FilterPanel
from mf4_analyzer.signal.filters import FilterSpec


def test_lowpass_spec(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    p.set_kind("低通"); p.set_cutoff(120.0); p.set_order(6)
    s = p.filter_spec()
    assert s.kind == "low" and s.cutoff == 120.0 and s.order == 6


def test_bandpass_uses_two_cutoffs(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    p.set_kind("带通"); p.set_band(100.0, 2000.0)
    s = p.filter_spec()
    assert s.kind == "band" and s.cutoff_lo == 100.0 and s.cutoff_hi == 2000.0
    # the dual-cutoff row is visible, single-cutoff row hidden
    assert p._band_row.isVisible() and not p._single_row.isVisible()


def test_show_flags_default_on(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    assert p.show_original() is True and p.show_filtered() is True


def test_no_zero_phase_control(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    assert not hasattr(p, "chk_zero_phase")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_time_filter_panel.py -q`
Expected: FAIL（`ImportError`）。

- [ ] **Step 3: 实现 `time_filter.py`**

样式参照现有 `_helpers.py`（`_no_buttons`/`_fit_field`/`_pair_field`）与 `CompactDoubleSpinBox`；容器透明。

```python
"""时域滤波控件。FFT 频域滤波参数 + 显示原始/滤波后开关。透明背景。"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox, QCheckBox,
)
from .._helpers_import import *  # noqa  (see note: use real import below)
from .compact_imports import CompactDoubleSpinBox  # placeholder; see Step 3 note
from ...signal.filters import FilterSpec

_KIND_MAP = {"低通": "low", "高通": "high", "带通": "band", "带阻": "bandstop"}


class FilterPanel(QWidget):
    filter_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeFilterPanel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("#timeFilterPanel{background:transparent;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(4)

        title = QLabel("滤波")
        title.setStyleSheet("font-weight:600; color:#1f2d3d; background:transparent;")
        root.addWidget(title)

        fl = QFormLayout(); fl.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.setHorizontalSpacing(6); fl.setVerticalSpacing(4)
        fl.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.combo_kind = QComboBox(); self.combo_kind.addItems(list(_KIND_MAP))
        fl.addRow("类型:", _fit_field(self.combo_kind))

        self.spin_cut = _no_buttons(CompactDoubleSpinBox())
        self.spin_cut.setDecimals(1); self.spin_cut.setRange(0.0, 1e6)
        self.spin_cut.setSuffix(" Hz"); self.spin_cut.setValue(100.0)
        self._single_row = _fit_field(self.spin_cut, max_width=120)
        fl.addRow("截止:", self._single_row)

        self.spin_lo = _no_buttons(CompactDoubleSpinBox())
        self.spin_lo.setDecimals(1); self.spin_lo.setRange(0.0, 1e6)
        self.spin_lo.setSuffix(" Hz"); self.spin_lo.setValue(100.0)
        self.spin_hi = _no_buttons(CompactDoubleSpinBox())
        self.spin_hi.setDecimals(1); self.spin_hi.setRange(0.0, 1e6)
        self.spin_hi.setSuffix(" Hz"); self.spin_hi.setValue(2000.0)
        self._band_row = _pair_field(self.spin_lo, "– 上限", self.spin_hi)
        fl.addRow("下限:", self._band_row)

        self.combo_order = QComboBox(); self.combo_order.addItems(["2", "4", "6", "8"])
        self.combo_order.setCurrentText("4")
        fl.addRow("阶数:", _fit_field(self.combo_order, max_width=120))
        root.addLayout(fl)

        row = QHBoxLayout(); row.setContentsMargins(0, 2, 0, 2); row.setSpacing(14)
        self.chk_orig = QCheckBox("显示原始"); self.chk_orig.setChecked(True)
        self.chk_filt = QCheckBox("显示滤波后"); self.chk_filt.setChecked(True)
        for c in (self.chk_orig, self.chk_filt):
            c.setStyleSheet("background:transparent;")
        row.addWidget(self.chk_orig); row.addWidget(self.chk_filt); row.addStretch()
        root.addLayout(row)

        self._sync_rows()
        self.combo_kind.currentTextChanged.connect(self._sync_rows)
        for w in (self.combo_kind, self.combo_order):
            w.currentTextChanged.connect(lambda *_: self.filter_changed.emit())
        for s in (self.spin_cut, self.spin_lo, self.spin_hi):
            s.valueChanged.connect(lambda *_: self.filter_changed.emit())
        for c in (self.chk_orig, self.chk_filt):
            c.toggled.connect(lambda *_: self.filter_changed.emit())

    # --- row visibility ------------------------------------------------
    def _is_band(self):
        return _KIND_MAP[self.combo_kind.currentText()] in ("band", "bandstop")

    def _sync_rows(self, *_):
        band = self._is_band()
        self._single_row.setVisible(not band)
        self._band_row.setVisible(band)
        self.filter_changed.emit()

    # --- programmatic setters (tests / presets) ------------------------
    def set_kind(self, label): self.combo_kind.setCurrentText(label)
    def set_cutoff(self, hz): self.spin_cut.setValue(float(hz))
    def set_band(self, lo, hi): self.spin_lo.setValue(float(lo)); self.spin_hi.setValue(float(hi))
    def set_order(self, n): self.combo_order.setCurrentText(str(int(n)))

    # --- getters -------------------------------------------------------
    def filter_spec(self):
        kind = _KIND_MAP[self.combo_kind.currentText()]
        order = int(self.combo_order.currentText())
        if kind in ("band", "bandstop"):
            return FilterSpec(kind, order=order,
                              cutoff_lo=self.spin_lo.value(),
                              cutoff_hi=self.spin_hi.value())
        return FilterSpec(kind, order=order, cutoff=self.spin_cut.value())

    def show_original(self): return self.chk_orig.isChecked()
    def show_filtered(self): return self.chk_filt.isChecked()
```

**Step 3 note（实现者必读）**：上面 `_fit_field/_no_buttons/_pair_field` 来自
`mf4_analyzer/ui/inspector_sections/_helpers.py`，`CompactDoubleSpinBox` 来自
`mf4_analyzer/ui/widgets/compact_spinbox.py`。把顶部两行占位 import 换成真实导入：
```python
from ._helpers import _no_buttons, _fit_field, _pair_field
from ..widgets.compact_spinbox import CompactDoubleSpinBox
```
`_fit_field` 返回的是包裹后的字段 widget（可 `setVisible`）；若它返回的是布局而非
widget，则改用一个 `QWidget` 容器包住单/双截止行再 `setVisible`（保持 `_single_row`/
`_band_row` 为可见性可控的 QWidget）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_time_filter_panel.py -q`
Expected: 4 passed。

- [ ] **Step 5: 真机渲染核灰底**

写临时脚本 `scripts/_probe_filter_panel.py`（用完删）：`QT_QPA_PLATFORM=offscreen` +
`load_stylesheet(app)`，把 `FilterPanel` 放在 `#f2f4f7` 托盘上 `grab()` 存 PNG；
肉眼确认控件/标签**无灰底**（透明）、单/双截止切换正确。报告 PNG 路径，确认后删脚本+图。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/inspector_sections/time_filter.py tests/ui/test_time_filter_panel.py
git commit -m "feat(ui): 时域滤波控件 FilterPanel (透明背景, 动态单/双截止)"
```

---

### Task 3: 绘图接入 — 滤波叠加曲线

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`（`_plot_time_on_canvas`，约 :1769-1798 组装 `data` 处）
- Modify: `mf4_analyzer/ui/inspector.py`（暴露 `self.inspector.filter_panel` 引用——Task 4 挂载后即可用；本任务先允许 `getattr` 容错）
- Test: `tests/ui/test_time_filter_overlay.py`

**Interfaces:**
- Consumes: `FilterPanel.filter_spec()/show_original()/show_filtered()`（Task 2）；`filters.apply`、`filters.nyquist_guard`（Task 1）。
- Produces: 时域 `data` 列表中，每个勾选通道在「显示滤波后」开启且滤波启用时多一条
  `(name+" ("+后缀+")", show_filtered, x, filtered, color, unit, fid)`，原始那条的 `visible` = `show_original`。

- [ ] **Step 1: 写失败测试**

`tests/ui/test_time_filter_overlay.py`（用既有 MainWindow smoke 夹具风格；若无现成夹具，
参照 `tests/ui/test_pg_timedomain_canvas.py` 的 `_pg_canvas` + 直接测 `_build_time_plot_data`
辅助函数）：

```python
import numpy as np
from mf4_analyzer.signal.filters import FilterSpec


def test_filtered_trace_appended_and_attenuated(time_window_with_two_high_low_channels):
    w = time_window_with_two_high_low_channels  # fixture: loads sig=low+high
    w.inspector.filter_panel.set_kind("低通")
    w.inspector.filter_panel.set_cutoff(50.0)
    w.inspector.filter_panel.set_order(6)
    data = w._build_time_plot_data()  # extracted pure helper (see Step 3)
    names = [d[0] for d in data]
    # one original + one filtered per channel
    assert any("(" in n and "Hz" in n for n in names)
    # filtered series has smaller high-freq energy than original
    orig = next(d for d in data if "(" not in d[0])
    filt = next(d for d in data if "Hz)" in d[0])
    assert np.std(filt[3]) < np.std(orig[3])


def test_uncheck_show_filtered_hides_trace(time_window_with_two_high_low_channels):
    w = time_window_with_two_high_low_channels
    w.inspector.filter_panel.chk_filt.setChecked(False)
    data = w._build_time_plot_data()
    # filtered traces present but visible=False (so cancel = just hide)
    filt = [d for d in data if "Hz)" in d[0]]
    assert filt and all(d[1] is False for d in filt)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_time_filter_overlay.py -q`
Expected: FAIL（无 `_build_time_plot_data` / `filter_panel`）。

- [ ] **Step 3: 抽出 `_build_time_plot_data` 并加滤波叠加**

把 `_plot_time_on_canvas` 中组装 `data`（:1769-1798）的纯逻辑抽成
`_build_time_plot_data(self) -> list[tuple]`（无副作用、可单测），并在每个通道处追加滤波叠加：

```python
def _build_time_plot_data(self):
    """组装时域绘图 data=[(name, visible, x, sig, color, unit, fid), ...]，
    含可选的滤波叠加曲线（显示层，不改 channel_data）。"""
    from ...signal import filters as _filters  # 相对路径按文件实际层级
    fp = getattr(self.inspector, "filter_panel", None)
    spec = None
    show_orig, show_filt = True, True
    if fp is not None:
        spec = fp.filter_spec()
        show_orig, show_filt = fp.show_original(), fp.show_filtered()
        filt_enabled = (spec.cutoff > 0) or (spec.cutoff_lo > 0 and spec.cutoff_hi > 0)
    else:
        filt_enabled = False

    range_enabled = self.inspector.top.range_enabled()
    range_lo, range_hi = self.inspector.top.range_values()
    checked = self.navigator.get_checked_channels()
    custom_x = self._current_custom_x_array()  # 既有取自定义横坐标的逻辑，按现状

    data = []
    for fid, ch, color in checked:
        fd = self.channel_list.get_file_data(fid)
        if fd is None or ch not in fd.data.columns:
            continue
        time_axis = fd.time_array
        x_axis = custom_x if (custom_x is not None and len(custom_x) == len(fd.data)) else time_axis
        sig = fd.data[ch].to_numpy(copy=False)
        unit = fd.channel_units.get(ch, '')
        name = fd.get_prefixed_channel(ch)
        if range_enabled:
            m = (time_axis >= range_lo) & (time_axis <= range_hi)
            x_axis, sig = x_axis[m], sig[m]
        if len(sig) == 0:
            continue
        data.append((name, show_orig, x_axis, sig, color, unit, fid))

        if filt_enabled:
            fs = float(getattr(fd, "fs", 0.0)) or self._estimate_fs(time_axis)
            try:
                gspec, _msg = _filters.nyquist_guard(spec, fs)
            except ValueError:
                continue  # band lo>=hi → 只画原始
            filtered = _filters.apply(sig, gspec, fs)
            suffix = self._filter_suffix(gspec)  # e.g. "LP 50Hz" / "BP 100–2000Hz"
            data.append((f"{name} ({suffix})", show_filt, x_axis, filtered,
                         color, unit, fid))
    return data
```

新增小辅助：

```python
def _filter_suffix(self, spec):
    tag = {"low": "LP", "high": "HP", "band": "BP", "bandstop": "BS"}[spec.kind]
    if spec.kind in ("band", "bandstop"):
        return f"{tag} {spec.cutoff_lo:g}–{spec.cutoff_hi:g}Hz"
    return f"{tag} {spec.cutoff:g}Hz"

def _estimate_fs(self, t):
    t = np.asarray(t, dtype=float)
    if t.size < 2:
        return 0.0
    dt = np.median(np.diff(t))
    return float(1.0 / dt) if dt > 0 else 0.0
```

`_plot_time_on_canvas` 改为调用 `data = self._build_time_plot_data()`（替换原内联组装段），
其余（stats、`plot_channels`、空判断）不变。**stats 仍只用原始曲线**：统计循环改为只在
原始那条上算（`for name, vis, x, sig, color, unit, fid in data if "(" not in name 末尾 Hz)`
不可靠——改为在 `_build_time_plot_data` 内对原始 append 时同时收 stats，或对 `filt_enabled`
分支跳过 stats）。简洁做法：stats 在上面循环里紧跟原始 `data.append` 后用 `sig` 计算（与现状一致）。

滤波叠加曲线样式（虚线）：在 `plot_channels`/canvas 侧按"名字含 `Hz)` 后缀"或新增可选
`style` 字段区分。**最小改动**：给 `data` 元组保持 7 元不变，名字后缀already区分；虚线样式
在 Task 4 真机渲染时确认是否需要（若 canvas 不支持按条设虚线，可先用同色细线 + 名字区分，
并在 Task 4 评估加 `dash`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_time_filter_overlay.py -q`
Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/main_window/window.py tests/ui/test_time_filter_overlay.py
git commit -m "feat(ui): 时域绘图叠加滤波曲线 (显示层, 前后对比开关)"
```

---

### Task 4: 面板挂载 + 卡片重组 + 真机验收

**Files:**
- Modify: `mf4_analyzer/ui/inspector.py`（挂载 `FilterPanel`，暴露 `self.filter_panel`，`filter_changed` 不强制触发绘图——绘图由「绘图」按钮统一提交）
- Modify: `mf4_analyzer/ui/inspector_sections/persistent_top.py`（把现有"横坐标"group 与"时间范围"group 分成两张卡；滤波放进时间范围卡）
- Test: `tests/ui/test_time_filter_panel.py`（追加挂载/重组结构断言）

**Interfaces:**
- Consumes: `FilterPanel`（Task 2）。
- Produces: `inspector.filter_panel`（Task 3 已 `getattr` 兼容，挂载后即生效）；
  时域 inspector 呈现为两卡：①横坐标(含「应用」) ②时间范围+滤波(底部单「绘图」)。

- [ ] **Step 1: 写失败/结构测试**

追加到 `tests/ui/test_time_filter_panel.py`：

```python
def test_inspector_mounts_filter_panel_in_time_card(qtbot, make_inspector):
    insp = make_inspector()  # 既有 inspector 构造夹具；无则最小构造 Inspector()
    qtbot.addWidget(insp)
    assert hasattr(insp, "filter_panel")
    # 横坐标卡与 时间范围+滤波卡 是两个独立容器
    assert insp._xaxis_card is not insp._range_filter_card
    # 滤波控件在 时间范围+滤波 卡内
    assert insp.filter_panel.parent() is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_time_filter_panel.py -q`
Expected: 新增用例 FAIL。

- [ ] **Step 3: 重组卡片 + 挂载**

在 `persistent_top.py`：把当前 `body_lay` 里依次 add 的"横坐标 group"和"时间范围 group"
分别放进两个 `QFrame` 卡（objectName 复用现有卡样式或新建透明卡 + 白底圆角，见 Global
Constraints 灰底约束），暴露 `xaxis_card()` / `range_card()` / `range_card_layout()`。
在 `inspector.py`：构造 `self.filter_panel = FilterPanel(...)`，加入"时间范围"卡的 layout
（时间范围下方），记 `self._xaxis_card` / `self._range_filter_card` / `self.filter_panel`。
「绘图」按钮（TimeContextual）与「应用」(横坐标) 行为不变；滤波**无独立按钮**，绘图时由
Task 3 的 `_build_time_plot_data` 读取。`filter_changed` 不接重绘（避免每次改参即重算）。

**勿破坏**：`range_values()/range_enabled()/xaxis_*` 等 getter 签名与可读性保持，
FFT/阶次取信号不受影响（跑全量回归确认）。

- [ ] **Step 4: 跑测试 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ui/test_time_filter_panel.py tests/ui/test_pg_timedomain_canvas.py -q`
然后 `.venv/bin/python -m pytest -q`
Expected: 新增通过；全量零回归。

- [ ] **Step 5: 真机渲染验收**

临时脚本 `scripts/_probe_filter_e2e.py`（用完删）：`offscreen` + `load_stylesheet`，
构造 MainWindow、加载 `testdoc/260417-ripple-PK2C-电机加热-1.hdf`、勾两个通道、进时域、
设低通、点绘图 → `grab()` 存 PNG。肉眼核：①两卡布局（横坐标独立 / 时间范围+滤波合并 +
单「绘图」）②滤波控件**无灰底** ③图上原始+滤波叠加可见、取消「显示滤波后」后滤波曲线消失、
原始仍在。报告 PNG，确认后删脚本+图。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/inspector.py mf4_analyzer/ui/inspector_sections/persistent_top.py tests/ui/test_time_filter_panel.py
git commit -m "feat(ui): 时域面板挂载滤波 + 横坐标/时间范围+滤波 卡片重组"
```

---

## Self-Review 记录

- **Spec 覆盖**：FFT 频域滤波(Task1) · 面板控件+透明背景(Task2) · 叠加+前后开关+取消(Task3) ·
  卡片重组+单绘图提交(Task4)。LP/HP/BP/BS、多速率 fs、Nyquist 守卫、NaN 保留均有测试。
- **占位**：无 TBD；Task2 Step3 顶部占位 import 已在 Step3 note 显式给出真实导入与回退方案。
- **类型一致**：`FilterSpec(kind, order, cutoff/cutoff_lo/cutoff_hi)`、`apply(sig, spec, fs)`、
  `nyquist_guard -> (spec, msg)`、`FilterPanel.filter_spec()/show_original()/show_filtered()`
  全计划一致。
- **风险点**：`persistent_top` 卡片重组勿破坏共享 getter（Task4 Step4 全量回归把关）；
  虚线样式按 canvas 能力在 Task4 真机阶段定（名字后缀已能区分，虚线为增强项）。

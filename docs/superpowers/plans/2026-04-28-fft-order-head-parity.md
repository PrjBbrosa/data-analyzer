# FFT / Order Analysis · HEAD Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the FFT and Order analysis views to feature parity with HEAD acoustics' typical behavior — Welch averaging, dB rendering with reasonable defaults, sub-bin pseudo-order floor, Computed Order Tracking — and add searchable channel dropdowns across the app.

**Architecture:** Four independent sub-projects. SP1 (searchable combos) is widget-level. SP2 (FFT averaging + linear/dB) and SP3 (order heatmap dB) are UI + display. SP4 (COT) adds a new DSP module and wires it through the order inspector. Each sub-project ships independently.

**Tech Stack:** PyQt5, matplotlib, numpy, scipy, qtawesome, pytest, pytest-qt. Existing test patterns: offscreen Qt + numerical assertions.

**Reference spec:** `docs/superpowers/specs/2026-04-28-fft-order-head-parity-design.md`

---

## Wave 1 — SP1: Searchable Channel Dropdowns

### Task 1.1: SearchableComboBox widget + tests

**Files:**
- Create: `mf4_analyzer/ui/widgets/searchable_combo.py`
- Create: `tests/ui/test_searchable_combo.py`

- [ ] **Step 1.1.1: Write the failing tests**

```python
# tests/ui/test_searchable_combo.py
from PyQt5.QtCore import Qt
from mf4_analyzer.ui.widgets.searchable_combo import SearchableComboBox


def test_basic_construction(qapp):
    cb = SearchableComboBox()
    cb.addItems(["Speed", "Torque", "Rte_RPS_nRotorSpeed_xds16"])
    assert cb.count() == 3
    assert cb.isEditable()
    assert cb.completer() is not None


def test_completer_is_substring_caseinsensitive(qapp):
    cb = SearchableComboBox()
    cb.addItems(["Rte_TAS_mTorsionBarTorque_xds16",
                 "Rte_RPS_nRotorSpeed_xds16",
                 "Speed_command"])
    comp = cb.completer()
    assert comp.filterMode() == Qt.MatchContains
    assert comp.caseSensitivity() == Qt.CaseInsensitive


def test_completer_model_rebinds_after_addItems(qapp):
    cb = SearchableComboBox()
    cb.addItems(["A", "B"])
    first_model = cb.completer().model()
    cb.clear()
    cb.addItems(["C", "D", "E"])
    assert cb.count() == 3
    assert cb.completer().model() is cb.model()
    assert first_model is not None  # original kept alive but unused


def test_currentIndexChanged_signal_still_fires(qapp, qtbot):
    cb = SearchableComboBox()
    cb.addItems(["A", "B", "C"])
    captured = []
    cb.currentIndexChanged.connect(lambda i: captured.append(i))
    cb.setCurrentIndex(2)
    assert captured == [2]


def test_drop_in_compatible_setCurrentText(qapp):
    cb = SearchableComboBox()
    cb.addItems(["alpha", "beta", "gamma"])
    cb.setCurrentText("beta")
    assert cb.currentText() == "beta"
    assert cb.currentIndex() == 1
```

- [ ] **Step 1.1.2: Run tests to verify they fail**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_searchable_combo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mf4_analyzer.ui.widgets.searchable_combo'`

- [ ] **Step 1.1.3: Create the widgets package init if missing**

```bash
test -d mf4_analyzer/ui/widgets || mkdir -p mf4_analyzer/ui/widgets
test -f mf4_analyzer/ui/widgets/__init__.py || touch mf4_analyzer/ui/widgets/__init__.py
```

- [ ] **Step 1.1.4: Implement `SearchableComboBox`**

```python
# mf4_analyzer/ui/widgets/searchable_combo.py
"""Drop-in replacement for QComboBox that supports type-to-filter search.

Usage:
    cb = SearchableComboBox(parent)
    cb.addItems(channel_names)

The completer matches anywhere in the string (substring), case-insensitive.
After every model change (addItem, addItems, clear, insertItem) the completer
is re-bound to the live model so its filter stays correct.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QCompleter


class SearchableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(self)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)
        self._rebind_completer_model()

    def _rebind_completer_model(self):
        c = self.completer()
        if c is not None:
            c.setModel(self.model())

    # Methods that mutate the item set: re-bind after each.
    def addItem(self, *args, **kwargs):
        super().addItem(*args, **kwargs)
        self._rebind_completer_model()

    def addItems(self, items):
        super().addItems(items)
        self._rebind_completer_model()

    def insertItem(self, *args, **kwargs):
        super().insertItem(*args, **kwargs)
        self._rebind_completer_model()

    def insertItems(self, *args, **kwargs):
        super().insertItems(*args, **kwargs)
        self._rebind_completer_model()

    def clear(self):
        super().clear()
        self._rebind_completer_model()
```

- [ ] **Step 1.1.5: Run tests to verify they pass**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_searchable_combo.py -v`
Expected: 5 passed

- [ ] **Step 1.1.6: Commit**

```bash
git add mf4_analyzer/ui/widgets/__init__.py mf4_analyzer/ui/widgets/searchable_combo.py tests/ui/test_searchable_combo.py
git commit -m "feat(ui): add SearchableComboBox with substring case-insensitive completer

Drop-in replacement for QComboBox. Re-binds completer model on every
addItem/addItems/clear/insert to keep the filter live as items change."
```

### Task 1.2: Replace channel-pick QComboBox call sites

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` — `TimeContextual`, `FFTContextual`, `OrderContextual`, `FFTTimeContextual` channel combos
- Modify: any batch dialog file under `mf4_analyzer/ui/` that uses channel combos
- Modify: edit-channels dialog file

- [ ] **Step 1.2.1: Locate every channel-pick QComboBox (two-pass)**

First pass — known channel names:
```bash
cd "/Users/donghang/Downloads/data analyzer" && grep -rn "QComboBox" mf4_analyzer/ui/ | grep -iE "channel|signal|chan|combo_sig|combo_rpm|combo_src"
```

Second pass — every QComboBox instantiation, judge per-line whether it holds channels:
```bash
cd "/Users/donghang/Downloads/data analyzer" && grep -rn "= QComboBox(" mf4_analyzer/ui/
```

Skip non-channel combos: `combo_window`, `combo_amp_mode`, `combo_dynamic`, `combo_avg_mode`, `combo_amp_y`, `combo_psd_y`, `combo_algorithm`. Record only channel-pick combo paths + line numbers.

- [ ] **Step 1.2.2: For each match site, swap import + instantiation**

For each file in the previous step output, change two things:

(a) Add to import block:
```python
from mf4_analyzer.ui.widgets.searchable_combo import SearchableComboBox
```

(b) Change every `QComboBox()` that is assigned to a channel-pick attribute to `SearchableComboBox()`. Do NOT change non-channel combos (e.g. `combo_amp_mode`, `combo_window`, `combo_dynamic`).

Concrete example for `inspector_sections.py:830` block (FFTContextual):

```python
# BEFORE
self.combo_sig = QComboBox()
# AFTER
self.combo_sig = SearchableComboBox()
```

- [ ] **Step 1.2.3: Write a smoke test**

```python
# Append to tests/ui/test_searchable_combo.py
from mf4_analyzer.ui.inspector_sections import (
    TimeContextual, FFTContextual, OrderContextual, FFTTimeContextual,
)
from mf4_analyzer.ui.widgets.searchable_combo import SearchableComboBox


def test_inspector_channel_combos_are_searchable(qapp):
    # FFTContextual.combo_sig
    fft = FFTContextual()
    assert isinstance(fft.combo_sig, SearchableComboBox), \
        "FFTContextual.combo_sig must be SearchableComboBox"
    # OrderContextual.combo_sig and combo_rpm
    order = OrderContextual()
    assert isinstance(order.combo_sig, SearchableComboBox)
    assert isinstance(order.combo_rpm, SearchableComboBox)
    # FFTTimeContextual.combo_sig
    fftt = FFTTimeContextual()
    assert isinstance(fftt.combo_sig, SearchableComboBox)
```

- [ ] **Step 1.2.4: Run the smoke test**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_searchable_combo.py -v`
Expected: all tests pass including the new one.

- [ ] **Step 1.2.5: Run full suite to catch regressions**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS (existing 339 + 6 new from this task = 345)

- [ ] **Step 1.2.6: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_searchable_combo.py
# add any other modified files from step 1.2.1
git commit -m "feat(ui): use SearchableComboBox for all channel-pick dropdowns

Replaces QComboBox at every channel-selection site (FFT/Order/FFT-vs-Time
inspectors plus batch and edit-channel dialogs) with the searchable
variant. Non-channel combos (window/mode/dynamic-range) are untouched."
```

---

## Wave 2 — SP2: FFT 1D Welch Averaging + Linear/dB Toggles

### Task 2.1: Add averaging mode toggle + overlap to FFTContextual

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` — `FFTContextual.__init__` (around line 830-1014)
- Modify: `mf4_analyzer/ui/inspector_sections.py` — `current_params()` and `apply_params()` of `FFTContextual`
- Test: `tests/ui/test_inspector.py` — append new tests

- [ ] **Step 2.1.1: Locate `FFTContextual.__init__` end of "calc params" group and `current_params()`**

Run:
```bash
cd "/Users/donghang/Downloads/data analyzer" && grep -n "class FFTContextual\|def current_params\|def apply_params" mf4_analyzer/ui/inspector_sections.py | head -20
```
Record line ranges for `FFTContextual` (start ~830, ends before `class OrderContextual` ~1015).

- [ ] **Step 2.1.2: Write failing tests for avg-mode + overlap**

```python
# tests/ui/test_inspector.py — append
from mf4_analyzer.ui.inspector_sections import FFTContextual


def test_fft_contextual_has_avg_mode_combo(qapp):
    w = FFTContextual()
    assert hasattr(w, 'combo_avg_mode')
    items = [w.combo_avg_mode.itemText(i) for i in range(w.combo_avg_mode.count())]
    assert items == ['单帧', '线性平均', '峰值保持']
    assert w.combo_avg_mode.currentText() == '单帧'


def test_fft_contextual_has_overlap_spin(qapp):
    w = FFTContextual()
    assert hasattr(w, 'spin_avg_overlap')
    assert w.spin_avg_overlap.minimum() == 0
    assert w.spin_avg_overlap.maximum() == 95
    assert w.spin_avg_overlap.value() == 50


def test_fft_contextual_overlap_disabled_in_single_frame_mode(qapp):
    w = FFTContextual()
    # default avg_mode = '单帧'
    assert w.spin_avg_overlap.isEnabled() is False
    w.combo_avg_mode.setCurrentText('线性平均')
    assert w.spin_avg_overlap.isEnabled() is True
    w.combo_avg_mode.setCurrentText('单帧')
    assert w.spin_avg_overlap.isEnabled() is False


def test_fft_contextual_avg_mode_in_current_params(qapp):
    w = FFTContextual()
    w.combo_avg_mode.setCurrentText('线性平均')
    w.spin_avg_overlap.setValue(75)
    p = w.current_params()
    assert p.get('avg_mode') == '线性平均'
    assert p.get('avg_overlap') == 75


def test_fft_contextual_apply_params_restores_avg(qapp):
    w = FFTContextual()
    w.apply_params({'avg_mode': '峰值保持', 'avg_overlap': 88})
    assert w.combo_avg_mode.currentText() == '峰值保持'
    assert w.spin_avg_overlap.value() == 88
```

- [ ] **Step 2.1.3: Run tests to verify they fail**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_inspector.py -k "avg_mode or overlap_disabled or avg_overlap or apply_params_restores_avg" -v`
Expected: FAILED with "AttributeError: 'FFTContextual' object has no attribute 'combo_avg_mode'" (or similar)

- [ ] **Step 2.1.4: Add the widgets to `FFTContextual.__init__`**

Find the existing FFT compute-params group (look for `combo_window`, `spin_nfft`). After the last existing form row in that group, add:

```python
# --- Averaging (Welch / peak-hold) ---
self.combo_avg_mode = QComboBox()
self.combo_avg_mode.addItems(['单帧', '线性平均', '峰值保持'])
self.combo_avg_mode.setCurrentText('单帧')
self.combo_avg_mode.setToolTip(
    "单帧：单次 FFT 快照；线性平均：Welch 多段平均（降噪）；"
    "峰值保持：每个频率取多段最大值（保留瞬态）。"
)
fl.addRow("平均模式:", _fit_field(self.combo_avg_mode, max_width=_SHORT_FIELD_MAX_WIDTH))

self.spin_avg_overlap = QSpinBox()
self.spin_avg_overlap.setRange(0, 95)
self.spin_avg_overlap.setValue(50)
self.spin_avg_overlap.setSuffix(' %')
self.spin_avg_overlap.setEnabled(False)
self.spin_avg_overlap.setToolTip("仅在平均/峰值保持模式下生效")
fl.addRow("重叠率:", _fit_field(self.spin_avg_overlap, max_width=_SHORT_FIELD_MAX_WIDTH))

self.combo_avg_mode.currentTextChanged.connect(
    lambda txt: self.spin_avg_overlap.setEnabled(txt != '单帧')
)
```

(Use the `fl` variable name from the existing code; if the form layout is named differently in `FFTContextual`, match that name.)

- [ ] **Step 2.1.5: Update `current_params()` and `apply_params()`**

In `FFTContextual.current_params()` add to the returned dict:
```python
'avg_mode':    self.combo_avg_mode.currentText(),
'avg_overlap': int(self.spin_avg_overlap.value()),
```

In `FFTContextual.apply_params(d)` add:
```python
if 'avg_mode' in d:
    i = self.combo_avg_mode.findText(str(d['avg_mode']))
    if i >= 0:
        self.combo_avg_mode.setCurrentIndex(i)
if 'avg_overlap' in d:
    self.spin_avg_overlap.setValue(int(d['avg_overlap']))
```

- [ ] **Step 2.1.6: Run tests to verify pass**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_inspector.py -v`
Expected: all new tests pass.

- [ ] **Step 2.1.7: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(fft-ui): add Welch averaging mode + overlap to FFTContextual

New combo: 单帧/线性平均/峰值保持. Overlap spin (0-95%, default 50)
gates on non-single-frame modes. Persisted via current_params/apply_params."
```

### Task 2.2: Wire averaging modes through main_window FFT render

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` — FFT render block (around line 1220-1250)
- Test: extend `tests/ui/test_inspector.py` or new integration test

- [ ] **Step 2.2.1: Read current FFT render path**

Run:
```bash
cd "/Users/donghang/Downloads/data analyzer" && sed -n '1190,1260p' mf4_analyzer/ui/main_window.py
```
Identify where `freq, amp = compute_fft(...)` is called and where `psd_db = 10*np.log10(...)` is computed.

- [ ] **Step 2.2.2: Write a behavioral test**

```python
# tests/ui/test_inspector.py — append
import numpy as np
from mf4_analyzer.signal.fft import FFTAnalyzer


def test_welch_average_lowers_noise_floor():
    """Stationary noisy 10Hz tone → Welch averaging produces lower noise std
    than single frame (sanity check that the wired-up code path is correct)."""
    rng = np.random.default_rng(42)
    fs = 1000.0
    n = 10 * fs  # 10 seconds
    t = np.arange(int(n)) / fs
    sig = np.sin(2 * np.pi * 10 * t) + 0.3 * rng.standard_normal(int(n))

    # single frame (full nfft window of length 4096)
    seg = sig[:4096]
    from mf4_analyzer.signal.fft import one_sided_amplitude
    f1, a1 = one_sided_amplitude(seg, fs, win='hanning', nfft=4096)

    # welch averaging
    f2, a2, _ = FFTAnalyzer.compute_averaged_fft(sig, fs, win='hanning',
                                                  nfft=4096, overlap=0.5)
    # Outside the 10Hz peak (drop bins near 10Hz), welch noise std should be lower.
    mask = np.abs(f1 - 10.0) > 2.0
    assert a2[mask].std() < a1[mask].std() * 0.85, \
        "Welch averaging should reduce out-of-peak std by at least 15%"
```

- [ ] **Step 2.2.3: Run that test (it should already pass — the function exists)**

Run: `cd "/Users/donghang/Downloads/data analyzer" && .venv/bin/python -m pytest tests/ui/test_inspector.py::test_welch_average_lowers_noise_floor -v`
Expected: PASS (the math is already correct in `compute_averaged_fft`).

- [ ] **Step 2.2.4: Modify `_render_fft` (or wherever the FFT rendering happens) to dispatch on `avg_mode`**

Find the block around `main_window.py:1228` that computes `amp` from `compute_fft`. Replace with:

```python
avg_mode = fft_params.get('avg_mode', '单帧')
overlap_pct = int(fft_params.get('avg_overlap', 50))
overlap = max(0.0, min(0.95, overlap_pct / 100.0))

if avg_mode == '线性平均':
    freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
        sig, fs, win=win, nfft=nfft or 1024, overlap=overlap)
elif avg_mode == '峰值保持':
    freq, amp = FFTAnalyzer.compute_peak_hold_fft(
        sig, fs, win=win, nfft=nfft or 1024, overlap=overlap)
    psd = amp ** 2
else:  # 单帧
    freq, amp = FFTAnalyzer.compute_fft(sig, fs, win=win, nfft=nfft)
    psd = amp ** 2
```

- [ ] **Step 2.2.5: Add the `compute_peak_hold_fft` helper to `mf4_analyzer/signal/fft.py`**

DSP helpers belong with `compute_averaged_fft` in the signal module, not in main_window. Add as a `@staticmethod` of `FFTAnalyzer`:

```python
@staticmethod
def compute_peak_hold_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5):
    """Per-frequency max across overlapping FFT segments (peak-hold)."""
    n = len(sig)
    hop = max(int(nfft * (1 - overlap)), 1)
    n_seg = max((n - nfft) // hop + 1, 1)
    peak = None
    freq = None
    for i in range(n_seg):
        s = i * hop
        if s + nfft > n:
            break
        f, a = one_sided_amplitude(sig[s:s + nfft], fs, win=win, nfft=nfft)
        if peak is None:
            peak = a.copy()
            freq = f
        else:
            np.maximum(peak, a, out=peak)
    if peak is None:
        freq, peak = one_sided_amplitude(sig, fs, win=win, nfft=nfft)
    return freq, peak
```

In `main_window.py`, import it where the FFT render block lives:
```python
from mf4_analyzer.signal.fft import FFTAnalyzer
# usage: FFTAnalyzer.compute_peak_hold_fft(...)
```

- [ ] **Step 2.2.6: Update `current_params()` consumer in `main_window.py` FFT path to read `avg_mode`/`avg_overlap`**

Find where `fft_params = self.inspector.fft_ctx.current_params()` (or equivalent) is gathered. Confirm `avg_mode` and `avg_overlap` propagate through. If `current_params` is not the source, find the actual source and add the keys.

- [ ] **Step 2.2.7: Run full FFT test suite**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 2.2.8: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py
git commit -m "feat(fft-ui): wire averaging modes to FFT render path

Single-frame keeps current behaviour. Linear-average dispatches to
compute_averaged_fft. Peak-hold uses np.maximum across overlapping segments."
```

### Task 2.3: Per-axis linear/dB toggle for FFT 1D

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` — `FFTContextual` add `combo_amp_y` + `combo_psd_y`
- Modify: `mf4_analyzer/ui/main_window.py` — FFT render reads the toggles
- Test: `tests/ui/test_inspector.py`

- [ ] **Step 2.3.1: Tests first**

```python
# tests/ui/test_inspector.py — append
def test_fft_contextual_has_axis_toggles(qapp):
    w = FFTContextual()
    assert hasattr(w, 'combo_amp_y')
    assert hasattr(w, 'combo_psd_y')
    assert w.combo_amp_y.currentText() == 'Linear'
    assert w.combo_psd_y.currentText() == 'dB'


def test_fft_contextual_axis_toggles_in_params(qapp):
    w = FFTContextual()
    w.combo_amp_y.setCurrentText('dB')
    w.combo_psd_y.setCurrentText('Linear')
    p = w.current_params()
    assert p.get('amp_y') == 'dB'
    assert p.get('psd_y') == 'Linear'
    w.apply_params({'amp_y': 'Linear', 'psd_y': 'dB'})
    assert w.combo_amp_y.currentText() == 'Linear'
    assert w.combo_psd_y.currentText() == 'dB'
```

- [ ] **Step 2.3.2: Run tests to verify failure**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_inspector.py -k "axis_toggles" -v`
Expected: FAIL.

- [ ] **Step 2.3.3: Add the combos in `FFTContextual.__init__`**

After the avg-mode block from Task 2.1:

```python
# --- Y-axis scale per subplot ---
self.combo_amp_y = QComboBox()
self.combo_amp_y.addItems(['Linear', 'dB'])
self.combo_amp_y.setCurrentText('Linear')
fl.addRow("Amplitude 轴:", _fit_field(self.combo_amp_y, max_width=_SHORT_FIELD_MAX_WIDTH))

self.combo_psd_y = QComboBox()
self.combo_psd_y.addItems(['Linear', 'dB'])
self.combo_psd_y.setCurrentText('dB')
fl.addRow("PSD 轴:", _fit_field(self.combo_psd_y, max_width=_SHORT_FIELD_MAX_WIDTH))
```

Update `current_params()`:
```python
'amp_y': self.combo_amp_y.currentText(),
'psd_y': self.combo_psd_y.currentText(),
```

Update `apply_params()`:
```python
for k, combo in [('amp_y', self.combo_amp_y), ('psd_y', self.combo_psd_y)]:
    if k in d:
        i = combo.findText(str(d[k]))
        if i >= 0:
            combo.setCurrentIndex(i)
```

- [ ] **Step 2.3.4: Wire toggles into render path in `main_window.py`**

Around the render block in `_render_fft`:
```python
amp_y = fft_params.get('amp_y', 'Linear')
psd_y = fft_params.get('psd_y', 'dB')

amp_disp = 20 * np.log10(np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12)) if amp_y == 'dB' else amp
psd_disp = 10 * np.log10(psd + 1e-12) if psd_y == 'dB' else psd

ax1.plot(freq, amp_disp, '#2563eb', lw=1.0)
ax1.set_ylabel('Amplitude (dB)' if amp_y == 'dB' else 'Amplitude', labelpad=10)
# … similar for ax2 with psd_disp
ax2.plot(freq, psd_disp, '#dc2626', lw=1.0)
ax2.set_ylabel('PSD (dB)' if psd_y == 'dB' else 'PSD', labelpad=10)
```

- [ ] **Step 2.3.5: Run full test suite**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 2.3.6: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py
git commit -m "feat(fft-ui): per-subplot linear/dB toggle for FFT 1D view"
```

---

## Wave 3 — SP3: Order Heatmap dB Rendering + Sub-bin Floor

### Task 3.1: Add `amplitude_mode` and `dynamic` params to `plot_or_update_heatmap`

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py` — `PlotCanvas.plot_or_update_heatmap`
- Test: `tests/ui/test_canvases.py` (create if absent)

- [ ] **Step 3.1.1: Locate the function (canvases.py:1566+)**

Run: `cd "/Users/donghang/Downloads/data analyzer" && sed -n '1560,1645p' mf4_analyzer/ui/canvases.py`

- [ ] **Step 3.1.2: Write tests**

```python
# tests/ui/test_canvases.py
import numpy as np
import pytest
from mf4_analyzer.ui.canvases import PlotCanvas


def test_heatmap_db_mode_with_30db_clamps_to_minus30_zero(qapp):
    canvas = PlotCanvas()
    # Synthesize a matrix with a 100x dynamic range
    m = np.array([[1.0, 0.5, 0.1, 0.001]] * 4)
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude_db', dynamic='30 dB',
    )
    im = canvas._heatmap_im
    assert im is not None
    arr = im.get_array()
    assert arr.max() == pytest.approx(0.0, abs=0.5)
    assert arr.min() >= -30.0


def test_heatmap_linear_mode_passes_through(qapp):
    canvas = PlotCanvas()
    m = np.array([[2.0, 1.0], [0.5, 0.1]])
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude', dynamic='Auto',
    )
    arr = canvas._heatmap_im.get_array()
    assert arr.max() == pytest.approx(2.0)
    assert arr.min() == pytest.approx(0.1)


def test_heatmap_db_50db_dynamic(qapp):
    canvas = PlotCanvas()
    m = np.array([[1.0, 1e-3, 1e-5, 1e-7]])
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude_db', dynamic='50 dB',
    )
    arr = canvas._heatmap_im.get_array()
    assert arr.min() >= -50.0
```

- [ ] **Step 3.1.3: Run tests, expect FAIL**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_canvases.py -v`
Expected: FAIL with `TypeError: plot_or_update_heatmap() got an unexpected keyword argument 'amplitude_mode'`

- [ ] **Step 3.1.4: Add `amplitude_mode` and `dynamic` params, dB conversion**

Modify `plot_or_update_heatmap` signature:

```python
def plot_or_update_heatmap(self, *, matrix, x_extent, y_extent,
                            x_label, y_label, title,
                            cmap='turbo', interp='bilinear',
                            vmin=None, vmax=None,
                            cbar_label='Amplitude',
                            amplitude_mode='amplitude',
                            dynamic='Auto'):
```

Right after `m = np.asarray(matrix, dtype=float)`:

```python
# dB conversion if requested. Reference = current matrix peak.
if amplitude_mode == 'amplitude_db':
    ref = float(np.nanmax(m))
    if ref <= 0:
        m_disp = np.full_like(m, fill_value=-100.0)
    else:
        with np.errstate(divide='ignore'):
            m_disp = 20.0 * np.log10(np.clip(m, 1e-12, None) / ref)
    if dynamic == '30 dB':
        m_disp = np.clip(m_disp, -30.0, 0.0)
    elif dynamic == '50 dB':
        m_disp = np.clip(m_disp, -50.0, 0.0)
    elif dynamic == '80 dB':
        m_disp = np.clip(m_disp, -80.0, 0.0)
    # 'Auto' = no clip
    m = m_disp
    if vmin is None:
        vmin = float(np.nanmin(m))
    if vmax is None:
        vmax = 0.0
    if 'dB' not in cbar_label:
        cbar_label = f"{cbar_label} (dB)"
else:
    if vmin is None:
        vmin = float(np.nanmin(m))
    if vmax is None:
        vmax = float(np.nanmax(m))
```

- [ ] **Step 3.1.5: Run tests, expect PASS**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_canvases.py -v`
Expected: 3 passed.

- [ ] **Step 3.1.6: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_canvases.py
git commit -m "feat(canvas): add amplitude_mode + dynamic dB params to heatmap

Reuses dB conversion pattern from SpectrogramCanvas. Default behaviour
unchanged (amplitude_mode='amplitude', dynamic='Auto')."
```

### Task 3.2: Add display controls to OrderContextual

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` — `OrderContextual.__init__`
- Modify: `mf4_analyzer/ui/main_window.py` — `_render_order_time` reads new params
- Test: `tests/ui/test_inspector.py`

- [ ] **Step 3.2.1: Tests first**

```python
# tests/ui/test_inspector.py — append
def test_order_contextual_has_dB_controls(qapp):
    w = OrderContextual()
    assert hasattr(w, 'combo_amp_mode')
    assert hasattr(w, 'combo_dynamic')
    assert w.combo_amp_mode.currentText() == 'Amplitude dB'
    assert w.combo_dynamic.currentText() == '30 dB'


def test_order_contextual_dynamic_disabled_in_linear(qapp):
    w = OrderContextual()
    w.combo_amp_mode.setCurrentText('Amplitude')
    assert w.combo_dynamic.isEnabled() is False
    w.combo_amp_mode.setCurrentText('Amplitude dB')
    assert w.combo_dynamic.isEnabled() is True


def test_order_contextual_amp_mode_in_params(qapp):
    w = OrderContextual()
    w.combo_amp_mode.setCurrentText('Amplitude')
    p = w.current_params()
    assert p.get('amplitude_mode') == 'Amplitude'
    w.apply_params({'amplitude_mode': 'Amplitude dB', 'dynamic': '50 dB'})
    assert w.combo_amp_mode.currentText() == 'Amplitude dB'
    assert w.combo_dynamic.currentText() == '50 dB'
```

- [ ] **Step 3.2.2: Run tests, expect FAIL**

- [ ] **Step 3.2.3: Add controls in `OrderContextual.__init__`**

Locate `OrderContextual` (line ~1015). Add after the existing param block:

```python
# --- Display ---
self.combo_amp_mode = QComboBox()
self.combo_amp_mode.addItems(['Amplitude dB', 'Amplitude'])
self.combo_amp_mode.setCurrentText('Amplitude dB')
fl.addRow("模式:", _fit_field(self.combo_amp_mode, max_width=_SHORT_FIELD_MAX_WIDTH))

self.combo_dynamic = QComboBox()
self.combo_dynamic.addItems(['30 dB', '50 dB', '80 dB', 'Auto'])
self.combo_dynamic.setCurrentText('30 dB')
fl.addRow("动态范围:", _fit_field(self.combo_dynamic, max_width=_SHORT_FIELD_MAX_WIDTH))

self.combo_amp_mode.currentTextChanged.connect(
    lambda txt: self.combo_dynamic.setEnabled(txt == 'Amplitude dB')
)
```

Update `current_params()`:
```python
'amplitude_mode': self.combo_amp_mode.currentText(),
'dynamic':        self.combo_dynamic.currentText(),
```

Update `apply_params()`:
```python
for k, combo in [('amplitude_mode', self.combo_amp_mode), ('dynamic', self.combo_dynamic)]:
    if k in d:
        i = combo.findText(str(d[k]))
        if i >= 0:
            combo.setCurrentIndex(i)
```

- [ ] **Step 3.2.4: Pipe through `_render_order_time` in main_window.py**

Find `_render_order_time` (line ~1425). Modify its `plot_or_update_heatmap` call to pass the params from the order context:

```python
ctx = self.inspector.order_ctx
order_params = ctx.current_params() if hasattr(ctx, 'current_params') else {}
self.canvas_order.plot_or_update_heatmap(
    matrix=result.amplitude.T,
    x_extent=(result.times[0], result.times[-1]),
    y_extent=(result.orders[0], result.orders[-1]),
    x_label='Time (s)',
    y_label='Order',
    title='Order vs Time',
    cmap='turbo',
    interp='bilinear',
    cbar_label='Amplitude',
    amplitude_mode='amplitude_db' if order_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB' else 'amplitude',
    dynamic=order_params.get('dynamic', '30 dB'),
)
```

- [ ] **Step 3.2.5: Run tests + full suite**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 3.2.6: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py
git commit -m "feat(order-ui): dB rendering with 30/50/80dB dynamic range, default 30dB"
```

### Task 3.3: Sub-bin pseudo-order floor in `_orders`

**Files:**
- Modify: `mf4_analyzer/signal/order.py` — `_orders` and call sites
- Test: `tests/signal/test_order.py` (extend if exists, create otherwise)

- [ ] **Step 3.3.1: Tests first**

```python
# tests/signal/test_order.py — extend
import numpy as np
from mf4_analyzer.signal.order import OrderAnalyzer


def test_orders_legacy_call_unchanged():
    """Legacy two-arg call must keep returning the full grid."""
    o = OrderAnalyzer._orders(20.0, 0.1)
    assert len(o) == 200
    assert np.isclose(o[0], 0.1)
    assert np.isclose(o[-1], 20.0)


def test_orders_with_subbin_floor_drops_low_orders():
    """At fs=100, nfft=1024, max|RPM|=10 → df·60/RPM = 0.0977·60/10 = 0.586;
    so the floor must drop orders 0.1, 0.2, 0.3, 0.4, 0.5."""
    rpm = np.array([0, 10, 10, 10])  # max|RPM|=10 → floor = 0.586
    o = OrderAnalyzer._orders(20.0, 0.1, fs=100.0, nfft=1024, rpm=rpm)
    assert o[0] >= 0.5, f"floor failed; first order is {o[0]} (expected >= 0.5)"
    assert o[0] >= 0.586 - 1e-9
    assert o[-1] == 20.0


def test_orders_with_high_rpm_no_floor_kicks_in():
    """At max|RPM|=600 → df·60/RPM = 0.0098, below order_res 0.1, so no
    floor is applied."""
    rpm = np.array([0, 600, 600])
    o = OrderAnalyzer._orders(20.0, 0.1, fs=100.0, nfft=1024, rpm=rpm)
    assert np.isclose(o[0], 0.1)
```

- [ ] **Step 3.3.2: Run, expect FAIL on the floored variants**

- [ ] **Step 3.3.3: Modify `_orders` signature and add floor logic**

```python
@staticmethod
def _orders(max_order, order_res, fs=None, nfft=None, rpm=None):
    max_order = float(max_order)
    order_res = float(order_res)
    if max_order <= 0:
        raise ValueError("max_order must be positive")
    if order_res <= 0:
        raise ValueError("order_res must be positive")
    base = np.arange(order_res, max_order + order_res * 0.5, order_res)
    if fs is None or nfft is None or rpm is None:
        return base
    rpm_arr = np.asarray(rpm, dtype=float)
    rpm_max = float(np.nanmax(np.abs(rpm_arr))) if rpm_arr.size else 0.0
    if rpm_max <= 0:
        return base
    df = float(fs) / float(nfft)
    min_order = max(order_res, df * 60.0 / rpm_max)
    return base[base >= min_order]
```

- [ ] **Step 3.3.4: Update call sites to pass fs/nfft/rpm**

In `compute_time_order_result` (line 217):
```python
orders = OrderAnalyzer._orders(params.max_order, params.order_res,
                                fs=fs, nfft=nfft, rpm=rpm)
```

In `extract_order_track_result` — leave as-is (single-target track is unaffected).

- [ ] **Step 3.3.5: Run full test suite**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 3.3.6: Commit**

```bash
git add mf4_analyzer/signal/order.py tests/signal/test_order.py
git commit -m "fix(order): floor pseudo-orders below FFT bin resolution

When df·60/max|RPM| > order_res, lower 'orders' fall below FFT bin
width and accumulate DC drift. Skip them in the output grid. Legacy
two-arg call signature preserved for backwards compatibility."
```

---

## Wave 4 — SP4: Computed Order Tracking (COT)

### Task 4.1: New `order_cot.py` module + analyzer class

**Files:**
- Create: `mf4_analyzer/signal/order_cot.py`
- Create: `tests/signal/test_order_cot.py`

- [ ] **Step 4.1.1: Write the synthetic-signal verification tests first**

```python
# tests/signal/test_order_cot.py
import numpy as np
from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def _synth_constant_rpm_with_2nd_order(fs=1000.0, dur=10.0, rpm_const=600.0,
                                        order_amp=1.0, noise=0.05):
    """Build a signal with constant RPM and a pure 2nd-order ripple."""
    rng = np.random.default_rng(0)
    t = np.arange(int(fs * dur)) / fs
    rpm = np.full_like(t, rpm_const)
    fpo = rpm_const / 60.0
    f_order2 = 2 * fpo  # 20Hz at 600RPM
    sig = order_amp * np.sin(2 * np.pi * f_order2 * t) + noise * rng.standard_normal(len(t))
    return t, sig, rpm


def test_cot_constant_rpm_resolves_order_2_cleanly():
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)

    # Find order 2 column
    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o2_col = res.amplitude[:, o2_idx]
    o15_col = res.amplitude[:, int(np.argmin(np.abs(res.orders - 1.5)))]
    o25_col = res.amplitude[:, int(np.argmin(np.abs(res.orders - 2.5)))]

    # Order 2 should be at least 10x larger than neighbors at order 1.5 / 2.5
    assert o2_col.mean() > 10 * o15_col.mean(), \
        f"COT failed to isolate order 2: o2={o2_col.mean():.4f} o15={o15_col.mean():.4f}"
    assert o2_col.mean() > 10 * o25_col.mean()


def _synth_swept_rpm_with_2nd_order(fs=1000.0, dur=10.0, rpm_lo=300.0, rpm_hi=900.0,
                                     order_amp=1.0, noise=0.05):
    """Linearly sweeping RPM with a true 2nd-order ripple riding on top."""
    rng = np.random.default_rng(0)
    t = np.arange(int(fs * dur)) / fs
    rpm = rpm_lo + (rpm_hi - rpm_lo) * (t / dur)
    omega = 2 * np.pi * rpm / 60.0  # rad/s instantaneous shaft frequency
    # 2nd order means phase = 2 * cumtrapz(omega)
    phase2 = 2 * np.concatenate([[0.0], np.cumsum(omega[:-1]) * (t[1] - t[0])])
    sig = order_amp * np.sin(phase2) + noise * rng.standard_normal(len(t))
    return t, sig, rpm


def test_cot_swept_rpm_still_isolates_order_2():
    t, sig, rpm = _synth_swept_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)

    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o2_col = res.amplitude[:, o2_idx]
    # Order 2 should still dominate after sweep (the whole point of COT)
    assert o2_col.mean() > 0.3, \
        f"Sweep COT failed: order 2 mean={o2_col.mean():.4f}"
    # And dominate over neighbors
    o15 = res.amplitude[:, int(np.argmin(np.abs(res.orders - 1.5)))].mean()
    assert o2_col.mean() > 5 * o15


def test_cot_returns_orders_starting_at_order_res():
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=8.0,
                  order_res=0.1, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert np.isclose(res.orders[0], 0.1)
    assert res.orders[-1] <= 8.0


def test_cot_handles_zero_rpm_segment():
    """Signal with a 1-second flat-zero RPM segment should not crash and
    should not produce NaN amplitudes."""
    t, sig, rpm = _synth_constant_rpm_with_2nd_order(dur=5.0)
    rpm[1000:2000] = 0.0  # 1 second of zero RPM
    p = COTParams(samples_per_rev=256, nfft=512, max_order=10.0,
                  order_res=0.1, time_res=0.5, min_rpm_floor=10.0)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert np.all(np.isfinite(res.amplitude))


def test_cot_params_validation():
    import pytest
    with pytest.raises(ValueError):
        COTParams(samples_per_rev=0, nfft=1024, max_order=10.0,
                  order_res=0.1, time_res=0.5)
    with pytest.raises(ValueError):
        COTParams(samples_per_rev=256, nfft=0, max_order=10.0,
                  order_res=0.1, time_res=0.5)
```

- [ ] **Step 4.1.2: Run, expect FAIL**

Run: `cd "/Users/donghang/Downloads/data analyzer" && .venv/bin/python -m pytest tests/signal/test_order_cot.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 4.1.3: Implement `order_cot.py`**

```python
"""Computed Order Tracking (COT) — angle-domain order analysis.

Pipeline:
    1. abs_rpm = |RPM(t)|; ω(t) = abs_rpm · 2π / 60   (rad/s)
    2. θ(t) = ∫ω(t) dt                                (cumulative angle, rad)
    3. resample s(t) onto uniform-Δθ grid s(θ)        (np.interp)
    4. windowed FFT of s(θ) per-frame → orders direct  (k → k * samples_per_rev / nfft)

Edge cases:
    - RPM=0 segments collapse θ → degenerate interp. We zero out frames
      whose mean |RPM| < min_rpm_floor.
    - Forward/reverse rotation aliased onto same orders by |RPM|.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .windowing import get_analysis_window


@dataclass(frozen=True)
class COTParams:
    samples_per_rev: int = 256
    nfft: int = 1024
    window: str = 'hanning'
    max_order: float = 20.0
    order_res: float = 0.05
    time_res: float = 0.05      # in seconds, hop in time domain (mapped to angle)
    min_rpm_floor: float = 10.0  # frames whose mean |rpm| below this are zeroed

    def __post_init__(self):
        if self.samples_per_rev <= 0:
            raise ValueError("samples_per_rev must be > 0")
        if self.nfft <= 0:
            raise ValueError("nfft must be > 0")
        if self.max_order <= 0:
            raise ValueError("max_order must be > 0")
        if self.order_res <= 0:
            raise ValueError("order_res must be > 0")


@dataclass
class COTResult:
    times: np.ndarray             # frame center times in seconds
    orders: np.ndarray            # order axis (interpolated to user grid)
    amplitude: np.ndarray         # shape (frames, orders)
    params: COTParams
    metadata: dict = field(default_factory=dict)


class COTOrderAnalyzer:
    @staticmethod
    def _validate(sig, rpm, t):
        sig = np.asarray(sig, dtype=float)
        rpm = np.asarray(rpm, dtype=float)
        t   = np.asarray(t, dtype=float)
        if sig.ndim != 1 or rpm.ndim != 1 or t.ndim != 1:
            raise ValueError("sig, rpm, t must be 1-D")
        if not (len(sig) == len(rpm) == len(t)):
            raise ValueError(f"length mismatch: sig={len(sig)} rpm={len(rpm)} t={len(t)}")
        if len(sig) < 16:
            raise ValueError("signal too short")
        if np.any(np.diff(t) <= 0):
            raise ValueError("time vector must be strictly monotonically increasing")
        return sig, rpm, t

    @staticmethod
    def compute(sig, rpm, t, params: COTParams,
                progress_callback=None, cancel_token=None) -> COTResult:
        sig, rpm, t = COTOrderAnalyzer._validate(sig, rpm, t)

        abs_rpm = np.abs(rpm)
        omega = abs_rpm * 2.0 * np.pi / 60.0           # rad/s
        # cumulative angle via trapezoidal integration
        dt = np.diff(t)
        # midpoint-trapezoid: θ_i = θ_{i-1} + (ω_{i-1} + ω_i)/2 * dt_{i-1}
        theta = np.zeros_like(t)
        theta[1:] = np.cumsum(0.5 * (omega[:-1] + omega[1:]) * dt)
        theta_max = float(theta[-1])

        if theta_max <= 0:
            raise ValueError("RPM is zero throughout the signal — COT cannot resolve orders")

        # uniform angle grid
        dtheta = 2.0 * np.pi / params.samples_per_rev
        theta_uniform = np.arange(0.0, theta_max, dtheta)
        if len(theta_uniform) < params.nfft:
            raise ValueError(
                f"signal covers only {theta_max / (2*np.pi):.2f} revolutions; "
                f"need at least {params.nfft / params.samples_per_rev:.2f} for nfft={params.nfft}")

        # angle-domain signal
        s_theta = np.interp(theta_uniform, theta, sig)

        # angle-domain time map: t_uniform = interp(theta_uniform, theta, t)
        t_uniform = np.interp(theta_uniform, theta, t)
        rpm_uniform = np.interp(theta_uniform, theta, abs_rpm)

        # frame layout in angle domain
        nfft = int(params.nfft)
        # hop in samples = time_res * (samples_per_rev * mean_rps) seconds-equivalent
        # but in angle domain we just hop by a fixed fraction of nfft.
        hop_angle = max(int(nfft * 0.25), 1)            # 75% overlap default
        starts = np.arange(0, len(s_theta) - nfft + 1, hop_angle)
        n_frames = len(starts)
        if n_frames == 0:
            raise ValueError("not enough angle-domain samples for one frame")

        w = get_analysis_window(params.window, nfft)
        w_sum = float(np.sum(w))

        # raw bin-orders: bin k → k * samples_per_rev / nfft
        raw_orders = np.arange(nfft // 2 + 1) * (params.samples_per_rev / nfft)

        # user-facing order grid (dropping below first raw order, capped at max_order)
        out_orders = np.arange(params.order_res,
                               params.max_order + params.order_res * 0.5,
                               params.order_res)
        amp_matrix = np.zeros((n_frames, len(out_orders)), dtype=float)
        times_arr = np.zeros(n_frames, dtype=float)

        def _check_cancel():
            if cancel_token is not None and cancel_token():
                raise RuntimeError("COT cancelled")

        for idx, start in enumerate(starts):
            _check_cancel()
            frame = s_theta[start:start + nfft]
            mean_rpm_frame = float(np.mean(rpm_uniform[start:start + nfft]))
            times_arr[idx] = float(t_uniform[start + nfft // 2])

            if mean_rpm_frame < params.min_rpm_floor:
                # zero-out low-RPM frames; angle integration unreliable
                continue

            spec = np.fft.rfft((frame - frame.mean()) * w)
            amp_raw = np.abs(spec) / w_sum * 2.0
            amp_raw[0] /= 2.0
            if (nfft % 2) == 0:
                amp_raw[-1] /= 2.0

            # interpolate raw_orders → out_orders
            amp_matrix[idx, :] = np.interp(out_orders, raw_orders, amp_raw,
                                            left=0.0, right=0.0)

            if progress_callback is not None:
                progress_callback(idx + 1, n_frames)

        if progress_callback is not None:
            progress_callback(n_frames, n_frames)

        return COTResult(
            times=times_arr,
            orders=out_orders,
            amplitude=amp_matrix,
            params=params,
            metadata={
                'frames': n_frames,
                'samples_per_rev': params.samples_per_rev,
                'theta_max_rev': theta_max / (2 * np.pi),
                'angle_samples': len(s_theta),
            },
        )
```

- [ ] **Step 4.1.4: Run tests, expect PASS**

Run: `cd "/Users/donghang/Downloads/data analyzer" && .venv/bin/python -m pytest tests/signal/test_order_cot.py -v`
Expected: 6 passed.

- [ ] **Step 4.1.5: Commit**

```bash
git add mf4_analyzer/signal/order_cot.py tests/signal/test_order_cot.py
git commit -m "feat(signal): add Computed Order Tracking (COT) analyzer

Angle-domain analyzer that resamples s(t) → s(θ) at uniform Δθ then
performs FFT in angle. Orders stay stationary regardless of RPM
variation. Edge cases handled: zero-RPM frames zeroed via min_rpm_floor;
signum collapsed via |RPM| (forward/reverse aliased)."
```

### Task 4.2: Wire COT into OrderContextual + main_window

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py` — `OrderContextual` add algorithm picker + samples_per_rev spin
- Modify: `mf4_analyzer/ui/main_window.py` — order compute path branches on algorithm

- [ ] **Step 4.2.1: Tests first**

```python
# tests/ui/test_inspector.py — append
def test_order_contextual_has_algorithm_combo(qapp):
    w = OrderContextual()
    assert hasattr(w, 'combo_algorithm')
    items = [w.combo_algorithm.itemText(i) for i in range(w.combo_algorithm.count())]
    assert items == ['频域映射', 'COT (角域重采样)']
    assert w.combo_algorithm.currentText() == '频域映射'  # default keeps existing


def test_order_contextual_samples_per_rev_visible_only_for_cot(qapp):
    w = OrderContextual()
    assert hasattr(w, 'spin_samples_per_rev')
    assert w.spin_samples_per_rev.value() == 256
    # default = freq-mapped → spin disabled
    assert w.spin_samples_per_rev.isEnabled() is False
    w.combo_algorithm.setCurrentText('COT (角域重采样)')
    assert w.spin_samples_per_rev.isEnabled() is True


def test_order_contextual_algorithm_in_params(qapp):
    w = OrderContextual()
    w.combo_algorithm.setCurrentText('COT (角域重采样)')
    w.spin_samples_per_rev.setValue(512)
    p = w.current_params()
    assert p.get('algorithm') == 'cot'
    assert p.get('samples_per_rev') == 512
    w.apply_params({'algorithm': '频域映射', 'samples_per_rev': 256})
    assert w.combo_algorithm.currentText() == '频域映射'
```

- [ ] **Step 4.2.2: Run, expect FAIL**

- [ ] **Step 4.2.3: Add controls in `OrderContextual.__init__`**

After the dB controls from Task 3.2:

```python
# --- Algorithm ---
self.combo_algorithm = QComboBox()
self.combo_algorithm.addItems(['频域映射', 'COT (角域重采样)'])
self.combo_algorithm.setCurrentText('频域映射')
self.combo_algorithm.setToolTip(
    "频域映射：时间域 FFT 后按平均 RPM 把频率换成阶次（变 RPM 会涂抹）。\n"
    "COT：先把信号重采样到等角度域再 FFT，变 RPM 不涂抹。"
)
fl.addRow("跟踪算法:", _fit_field(self.combo_algorithm, max_width=_SHORT_FIELD_MAX_WIDTH))

self.spin_samples_per_rev = QSpinBox()
self.spin_samples_per_rev.setRange(64, 2048)
self.spin_samples_per_rev.setValue(256)
self.spin_samples_per_rev.setEnabled(False)
self.spin_samples_per_rev.setToolTip("每转角度采样数（仅 COT 启用）")
fl.addRow("每转样本数:", _fit_field(self.spin_samples_per_rev, max_width=_SHORT_FIELD_MAX_WIDTH))

def _on_algo_changed(txt):
    self.spin_samples_per_rev.setEnabled('COT' in txt)
self.combo_algorithm.currentTextChanged.connect(_on_algo_changed)
```

Update `current_params()`:
```python
algo_txt = self.combo_algorithm.currentText()
'algorithm':       'cot' if 'COT' in algo_txt else 'frequency',
'samples_per_rev': int(self.spin_samples_per_rev.value()),
```

Update `apply_params(d)`:
```python
if 'algorithm' in d:
    val = str(d['algorithm'])
    target = 'COT (角域重采样)' if val == 'cot' or 'COT' in val else '频域映射'
    i = self.combo_algorithm.findText(target)
    if i >= 0:
        self.combo_algorithm.setCurrentIndex(i)
if 'samples_per_rev' in d:
    self.spin_samples_per_rev.setValue(int(d['samples_per_rev']))
```

- [ ] **Step 4.2.4: Pipe into the order compute path in `main_window.py`**

Find where `OrderAnalyzer.compute_time_order_result` is called (line ~1304 from earlier grep). Add branching:

```python
order_params = self.inspector.order_ctx.current_params()
algorithm = order_params.get('algorithm', 'frequency')

if algorithm == 'cot':
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams
    p = COTParams(
        samples_per_rev=int(order_params.get('samples_per_rev', 256)),
        nfft=int(order_params.get('nfft', 1024)),
        window=order_params.get('window', 'hanning'),
        max_order=float(order_params.get('max_order', 20.0)),
        order_res=float(order_params.get('order_res', 0.05)),
        time_res=float(order_params.get('time_res', 0.05)),
    )
    result = COTOrderAnalyzer.compute(sig_arr, rpm_arr, t_arr, p)
else:
    p = OrderAnalysisParams(
        fs=fs,
        nfft=int(order_params.get('nfft', 1024)),
        window=order_params.get('window', 'hanning'),
        max_order=float(order_params.get('max_order', 20.0)),
        order_res=float(order_params.get('order_res', 0.1)),
        time_res=float(order_params.get('time_res', 0.05)),
    )
    result = OrderAnalyzer.compute_time_order_result(sig_arr, rpm_arr, t_arr, p)
```

`COTResult` and `OrderTimeResult` have compatible `.times`, `.orders`, `.amplitude` shapes, so `_render_order_time` works for both.

- [ ] **Step 4.2.5: Run all tests**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 4.2.6: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py
git commit -m "feat(order-ui): algorithm picker + samples_per_rev for COT mode"
```

---

## Wave 5 — Final Integration Verification

### Task 5.1: End-to-end smoke test on T08 file

**Files:**
- Create: `tests/integration/test_t08_order_cot_e2e.py`
- (No source changes)

- [ ] **Step 5.1.1: Write the e2e test**

```python
# tests/integration/test_t08_order_cot_e2e.py
import os
import numpy as np
import pytest

T08 = "/Users/donghang/Downloads/data analyzer/testdoc/T08_YuanDi_FOC_CurrentMode_0-1-2_Ripple.MF4"


@pytest.mark.skipif(not os.path.exists(T08), reason="T08 reference file missing")
def test_cot_resolves_order_2_on_T08():
    from asammdf import MDF
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams

    mdf = MDF(T08)
    sig = mdf.get('Rte_TAS_mTorsionBarTorque_xds16')
    rpm = mdf.get('Rte_RPS_nRotorSpeed_xds16')
    t = sig.timestamps
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.05)
    res = COTOrderAnalyzer.compute(sig.samples.astype(float),
                                    rpm.samples.astype(float), t, p)

    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o15_idx = int(np.argmin(np.abs(res.orders - 1.5)))
    o25_idx = int(np.argmin(np.abs(res.orders - 2.5)))

    o2 = res.amplitude[:, o2_idx].mean()
    o15 = res.amplitude[:, o15_idx].mean()
    o25 = res.amplitude[:, o25_idx].mean()

    # On T08 the ripple is around order 2; demand order 2 dominate the
    # neighborhood by at least 2x — strict enough to fail if smearing returns.
    assert o2 > 2.0 * o15, f"order2={o2:.4f} order1.5={o15:.4f} — COT smeared"
    assert o2 > 2.0 * o25, f"order2={o2:.4f} order2.5={o25:.4f} — COT smeared"
```

- [ ] **Step 5.1.2: Run and verify it passes**

Run: `cd "/Users/donghang/Downloads/data analyzer" && .venv/bin/python -m pytest tests/integration/test_t08_order_cot_e2e.py -v`
Expected: PASS (or SKIP if T08 not present in CI).

- [ ] **Step 5.1.3: Final full suite**

Run: `cd "/Users/donghang/Downloads/data analyzer" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 5.1.4: Commit**

```bash
git add tests/integration/test_t08_order_cot_e2e.py
git commit -m "test(integration): COT resolves order 2 ridge on T08 reference file"
```

---

## Self-review checklist

Run through this after writing the plan:

1. **Spec coverage:** every section of the spec maps to a wave / task above ✓
2. **No placeholders:** every step has executable code or shell commands ✓
3. **Type consistency:** `COTParams.samples_per_rev` named identically across spec, `order_cot.py`, `OrderContextual`, `apply_params`, e2e test ✓
4. **TDD ordering:** every implementation task has a failing test before the impl step ✓
5. **Backwards compatibility:** legacy callers of `OrderAnalyzer._orders` still work (Task 3.3) ✓
6. **Frequent commits:** every wave commits 2-4 times — every task ends with `git commit` ✓

## Execution

Subagent-driven. Each task = one fresh `pyqt-ui-engineer` or `signal-processing-expert` dispatch. Code-review-skill review at end of each wave before moving on.

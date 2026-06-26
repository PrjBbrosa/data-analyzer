# Batch TimeDomain + Filter Preprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a TimeDomain batch method and batch-level filter preprocessing that can be configured from the batch dialog and filled from the current TimeDomain view.

**Architecture:** Keep filtering as an input preprocessing stage owned by batch params, then feed the prepared signal into the existing FFT / FFT-vs-Time / Order compute paths. Add `time` as a first-class BatchRunner method with long-table export and pyqtgraph line PNG export, while keeping UI changes localized to the batch drawer panels.

**Tech Stack:** Python, PyQt5, pyqtgraph, pandas, numpy, pytest, pytest-qt, existing `mf4_analyzer.signal.filters` helpers.

---

## File Structure

- Modify `mf4_analyzer/batch.py`
  - Add `time` to `SUPPORTED_METHODS`.
  - Add filter preprocessing helpers.
  - Add time-domain dataframe and image rendering.
  - Apply preprocessing before FFT / FFT-vs-Time / Order compute.
- Create `mf4_analyzer/ui/drawers/batch/filter_panel.py`
  - Batch-scoped filter UI using the existing `FilterSpec` schema.
  - Exposes `get_filter_params()`, `apply_filter_params()`, and `set_method()`.
- Modify `mf4_analyzer/ui/drawers/batch/input_panel.py`
  - Embed `BatchFilterPanel` below the time range row.
  - Include filter params in `InputPanel` accessors and preset apply path.
- Modify `mf4_analyzer/ui/drawers/batch/sheet.py`
  - Merge input-owned filter params into `AnalysisPreset.params`.
  - Apply preset filter params into the InputPanel.
  - Route method changes into the filter panel.
- Modify `mf4_analyzer/ui/drawers/batch/method_buttons.py`
  - Add `time` method key and user label `时域`.
  - Hide analysis parameter rows for `time`.
  - Rename visible `order_time` button label to `阶次`.
- Modify `mf4_analyzer/ui/drawers/batch/output_panel.py`
  - Add `time` axis context.
  - Hide or disable Z controls for line methods where they are not used.
- Modify `mf4_analyzer/ui/main_window/window.py`
  - Add time-mode branch in `_build_current_batch_preset()`.
- Tests:
  - `tests/test_batch_runner.py`
  - `tests/ui/test_batch_input_panel.py`
  - `tests/ui/test_batch_method_buttons.py`
  - `tests/ui/test_batch_toolbar.py`
  - `tests/ui/test_batch_smoke.py`

---

### Task 1: BatchRunner TimeDomain Core

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

- [ ] **Step 1: Write failing tests for `time` method support and long-table export**

Append tests to `tests/test_batch_runner.py`:

```python
def test_batch_supported_methods_include_time():
    from mf4_analyzer.batch import BatchRunner

    assert "time" in BatchRunner.SUPPORTED_METHODS


def test_batch_time_dataframe_exports_original_series(tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.io import FileData

    t = np.arange(5, dtype=float) / 10.0
    df = pd.DataFrame({"Time": t, "sig": np.array([0.0, 1.0, 0.0, -1.0, 0.0])})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=10.0)
    preset = AnalysisPreset.from_current_single(
        name="time",
        method="time",
        signal=(0, "sig"),
        params={},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    out = pd.read_csv(result.items[0].data_path)
    assert list(out.columns) == ["time_s", "series", "value"]
    assert out["series"].tolist() == ["original"] * 5
    np.testing.assert_allclose(out["time_s"].to_numpy(), t)
    np.testing.assert_allclose(out["value"].to_numpy(), df["sig"].to_numpy())
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py::test_batch_supported_methods_include_time \
  tests/test_batch_runner.py::test_batch_time_dataframe_exports_original_series -q
```

Expected: first test fails because `time` is not in `SUPPORTED_METHODS`, or second fails with `unsupported method: time`.

- [ ] **Step 3: Implement minimal TimeDomain method**

In `mf4_analyzer/batch.py`, update the method set:

```python
SUPPORTED_METHODS = {'time', 'fft', 'order_time', 'fft_time'}
```

Add a helper near `_compute_fft_dataframe`:

```python
@staticmethod
def _time_axis_or_fallback(time, fs, n_samples):
    if time is not None:
        arr = np.asarray(time, dtype=float)
        if arr.size == int(n_samples):
            return arr
    fs = float(fs)
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError("缺少有效采样率")
    return np.arange(int(n_samples), dtype=float) / fs

@classmethod
def _compute_time_dataframe(cls, sig, time, fs, params):
    x = cls._time_axis_or_fallback(time, fs, len(sig))
    return pd.DataFrame({
        "time_s": x,
        "series": ["original"] * len(sig),
        "value": np.asarray(sig, dtype=float),
    })
```

In `_run_one()`, add a first branch before `fft`:

```python
if method == 'time':
    sig, time, _ = self._apply_time_range(sig, time, preset.params)
    time_df = self._compute_time_dataframe(sig, time, fs, preset.params)
    image_payload = ('time', time_df)
elif method == 'fft':
    ...
```

Initialize `time_df = None` before the branch, and in the export block use it:

```python
if time_df is not None:
    export_df = time_df
elif fft_df is not None:
    export_df = fft_df
else:
    export_df = spectro.to_long_dataframe()
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same command from Step 2.

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): add time-domain export core"
```

---

### Task 2: Batch Filter Preprocessing

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

- [ ] **Step 1: Write failing tests for filter params**

Append tests:

```python
def test_batch_time_dataframe_exports_original_and_filtered_series(tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.io import FileData

    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    sig = np.sin(2 * np.pi * 5 * t) + 0.5 * np.sin(2 * np.pi * 60 * t)
    df = pd.DataFrame({"Time": t, "sig": sig})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=fs)
    preset = AnalysisPreset.from_current_single(
        name="time filtered",
        method="time",
        signal=(0, "sig"),
        params={
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
                "show_original": True,
                "show_filtered": True,
            }
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    out = pd.read_csv(result.items[0].data_path)
    assert set(out["series"]) == {"original", "filtered"}
    original = out[out["series"] == "original"]["value"].to_numpy()
    filtered = out[out["series"] == "filtered"]["value"].to_numpy()
    assert len(original) == len(filtered) == len(sig)
    assert np.std(filtered - np.sin(2 * np.pi * 5 * t)) < np.std(original - np.sin(2 * np.pi * 5 * t))


def test_batch_time_blocks_when_filter_hides_both_series(tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.io import FileData

    t = np.arange(8, dtype=float) / 10.0
    df = pd.DataFrame({"Time": t, "sig": np.ones_like(t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=10.0)
    preset = AnalysisPreset.from_current_single(
        name="hidden",
        method="time",
        signal=(0, "sig"),
        params={
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 3.0},
                "show_original": False,
                "show_filtered": False,
            }
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "至少需要原始或滤波后一项" in result.blocked[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py::test_batch_time_dataframe_exports_original_and_filtered_series \
  tests/test_batch_runner.py::test_batch_time_blocks_when_filter_hides_both_series -q
```

Expected: first test only exports original, second does not block.

- [ ] **Step 3: Implement filter helpers and time-series rules**

In `mf4_analyzer/batch.py`, add helpers:

```python
@staticmethod
def _filter_state(params):
    state = params.get("filter") or {}
    return state if isinstance(state, dict) else {}

@classmethod
def _filter_enabled(cls, params):
    return bool(cls._filter_state(params).get("enabled", False))

@classmethod
def _filter_spec_from_params(cls, params):
    if not cls._filter_enabled(params):
        return None
    from .signal.filters import FilterSpec

    return FilterSpec.from_dict(cls._filter_state(params).get("spec") or {})

@classmethod
def _apply_filter_if_enabled(cls, sig, fs, params):
    spec = cls._filter_spec_from_params(params)
    if spec is None:
        return np.asarray(sig, dtype=float), None
    from .signal import filters as _filters

    guarded, _msg = _filters.nyquist_guard(spec, fs)
    return _filters.apply(sig, guarded, fs), guarded
```

Update `_compute_time_dataframe()`:

```python
@classmethod
def _compute_time_dataframe(cls, sig, time, fs, params):
    x = cls._time_axis_or_fallback(time, fs, len(sig))
    filter_state = cls._filter_state(params)
    if not cls._filter_enabled(params):
        return pd.DataFrame({
            "time_s": x,
            "series": ["original"] * len(sig),
            "value": np.asarray(sig, dtype=float),
        })

    show_original = bool(filter_state.get("show_original", True))
    show_filtered = bool(filter_state.get("show_filtered", True))
    if not show_original and not show_filtered:
        raise ValueError("时域导出至少需要原始或滤波后一项")

    frames = []
    if show_original:
        frames.append(pd.DataFrame({
            "time_s": x,
            "series": ["original"] * len(sig),
            "value": np.asarray(sig, dtype=float),
        }))
    if show_filtered:
        filtered, _spec = cls._apply_filter_if_enabled(sig, fs, params)
        frames.append(pd.DataFrame({
            "time_s": x,
            "series": ["filtered"] * len(filtered),
            "value": filtered,
        }))
    return pd.concat(frames, ignore_index=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same command from Step 2.

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): add filter preprocessing params"
```

---

### Task 3: Apply Filtering to FFT, FFT-vs-Time, and Order

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

- [ ] **Step 1: Write failing tests for compute-path preprocessing**

Append tests:

```python
def test_batch_fft_uses_filtered_signal_when_filter_enabled(monkeypatch):
    import numpy as np
    from mf4_analyzer.batch import BatchRunner

    captured = {}

    def fake_compute_fft(sig, fs, win="hanning", nfft=None, weighting="None"):
        captured["std"] = float(np.std(sig))
        return np.array([0.0]), np.array([1.0])

    monkeypatch.setattr("mf4_analyzer.batch.FFTAnalyzer.compute_fft", fake_compute_fft)
    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    sig = np.sin(2 * np.pi * 5 * t) + 0.5 * np.sin(2 * np.pi * 60 * t)

    BatchRunner._compute_fft_dataframe(
        sig,
        fs,
        {
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
            }
        },
    )

    assert captured["std"] < float(np.std(sig))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py::test_batch_fft_uses_filtered_signal_when_filter_enabled -q
```

Expected: fails because `_compute_fft_dataframe()` still receives raw `sig`.

- [ ] **Step 3: Apply filter inside compute wrappers**

At the top of `_compute_fft_dataframe()`:

```python
sig, _spec = BatchRunner._apply_filter_if_enabled(sig, fs, params)
```

At the top of `_compute_fft_time_spectro()` before uniform time-axis compute:

```python
sig, _spec = cls._apply_filter_if_enabled(sig, fs, params)
```

At the top of `_compute_order_time_spectro()` before COT params:

```python
sig, _spec = cls._apply_filter_if_enabled(sig, fs, params)
```

Do not apply this helper to RPM values in `_rpm_values()`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py::test_batch_fft_uses_filtered_signal_when_filter_enabled \
  tests/test_batch_runner.py::test_batch_time_dataframe_exports_original_and_filtered_series -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): filter signals before analysis"
```

---

### Task 4: TimeDomain PNG Export

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

- [ ] **Step 1: Write failing test for time image scene**

Append:

```python
def test_batch_time_export_scene_renders_line_series():
    import pandas as pd
    from mf4_analyzer.batch import BatchRunner

    df = pd.DataFrame({
        "time_s": [0.0, 0.1, 0.0, 0.1],
        "series": ["original", "original", "filtered", "filtered"],
        "value": [0.0, 1.0, 0.0, 0.5],
    })

    _widget, info = BatchRunner._build_export_scene(("time", df), {
        "x_auto": False,
        "x_min": 0.0,
        "x_max": 0.1,
        "y_auto": False,
        "y_min": -1.0,
        "y_max": 1.0,
    })

    assert info["line_count"] == 2
    assert info["x_range"] == (0.0, 0.1)
    assert info["y_range"] == (-1.0, 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py::test_batch_time_export_scene_renders_line_series -q
```

Expected: fails because `_build_export_scene()` has no `time` branch.

- [ ] **Step 3: Add time line-plot branch**

In `_build_export_scene()` before the `kind == 'fft'` branch:

```python
if kind == 'time':
    df = data
    line_count = 0
    for series, group in df.groupby("series", sort=False):
        x = group["time_s"].to_numpy(dtype=float)
        y = group["value"].to_numpy(dtype=float)
        pen = pg.mkPen("w", width=1.5)
        if str(series) == "filtered":
            pen = pg.mkPen("c", width=1.5, style=Qt.DashLine)
        plot.plot(x, y, pen=pen, name=str(series))
        line_count += 1
    plot.setLabel("bottom", "Time (s)")
    plot.setLabel("left", "Amplitude")
    if not x_auto and x_max > x_min:
        plot.setXRange(x_min, x_max, padding=0)
        info["x_range"] = (x_min, x_max)
    if not y_auto and y_max > y_min:
        plot.setYRange(y_min, y_max, padding=0)
        info["y_range"] = (y_min, y_max)
    info["line_count"] = line_count
    return widget, info
```

Add `Qt` to the existing import in `_build_export_scene()`:

```python
from PyQt5.QtCore import Qt, QRectF
```

- [ ] **Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): render time-domain batch images"
```

---

### Task 5: Batch Filter UI Panel

**Files:**
- Create: `mf4_analyzer/ui/drawers/batch/filter_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Test: `tests/ui/test_batch_input_panel.py`

- [ ] **Step 1: Write failing UI round-trip tests**

Append:

```python
def test_batch_input_filter_params_round_trip(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel(None, files={})
    qtbot.addWidget(panel)
    params = {
        "enabled": True,
        "spec": {
            "kind": "band",
            "order": 6,
            "cutoff_lo": 20.0,
            "cutoff_hi": 80.0,
        },
        "show_original": False,
        "show_filtered": True,
    }

    panel.apply_filter_params(params)

    got = panel.filter_params()
    assert got["enabled"] is True
    assert got["spec"]["kind"] == "band"
    assert got["spec"]["order"] == 6
    assert got["spec"]["cutoff_lo"] == 20.0
    assert got["spec"]["cutoff_hi"] == 80.0
    assert got["show_original"] is False
    assert got["show_filtered"] is True


def test_batch_filter_time_output_toggles_only_visible_for_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel(None, files={})
    qtbot.addWidget(panel)

    panel.set_method("fft")
    assert panel._filter_panel.time_output_options_visible() is False

    panel.set_method("time")
    assert panel._filter_panel.time_output_options_visible() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_input_panel.py::test_batch_input_filter_params_round_trip \
  tests/ui/test_batch_input_panel.py::test_batch_filter_time_output_toggles_only_visible_for_time -q
```

Expected: fails because `InputPanel` has no filter API.

- [ ] **Step 3: Create `BatchFilterPanel`**

Create `mf4_analyzer/ui/drawers/batch/filter_panel.py` with a compact widget that mirrors `FilterPanel` APIs:

```python
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ....signal.filters import FilterSpec
from ...widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons

_LABEL_TO_KIND = {"低通": "low", "高通": "high", "带通": "band", "带阻": "bandstop"}
_KIND_TO_LABEL = {v: k for k, v in _LABEL_TO_KIND.items()}


class BatchFilterPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(6)

        self.chk_enabled = QCheckBox("滤波", self)
        self._root.addWidget(self.chk_enabled)

        self._settings = QWidget(self)
        form = QFormLayout(self._settings)
        form.setContentsMargins(0, 0, 0, 0)
        self.combo_kind = QComboBox(self._settings)
        self.combo_kind.addItems(list(_LABEL_TO_KIND))
        form.addRow("类型", self.combo_kind)

        self.spin_cut = no_buttons(CompactDoubleSpinBox(self._settings))
        self.spin_cut.setRange(0.0, 1e6)
        self.spin_cut.setDecimals(1)
        self.spin_cut.setValue(100.0)
        self._single_label = QLabel("截止", self._settings)
        form.addRow(self._single_label, self.spin_cut)

        self._band_host = QWidget(self._settings)
        band_lay = QHBoxLayout(self._band_host)
        band_lay.setContentsMargins(0, 0, 0, 0)
        self.spin_lo = no_buttons(CompactDoubleSpinBox(self._band_host))
        self.spin_hi = no_buttons(CompactDoubleSpinBox(self._band_host))
        for spin, value in ((self.spin_lo, 100.0), (self.spin_hi, 2000.0)):
            spin.setRange(0.0, 1e6)
            spin.setDecimals(1)
            spin.setValue(value)
            band_lay.addWidget(spin)
        self._band_label = QLabel("范围", self._settings)
        form.addRow(self._band_label, self._band_host)

        self.combo_order = QComboBox(self._settings)
        self.combo_order.addItems(["2", "4", "6", "8"])
        self.combo_order.setCurrentText("4")
        form.addRow("阶数", self.combo_order)
        self._root.addWidget(self._settings)

        self._time_options = QWidget(self)
        time_lay = QHBoxLayout(self._time_options)
        time_lay.setContentsMargins(0, 0, 0, 0)
        self.chk_original = QCheckBox("原始", self._time_options)
        self.chk_filtered = QCheckBox("滤波后", self._time_options)
        self.chk_original.setChecked(True)
        self.chk_filtered.setChecked(True)
        time_lay.addWidget(self.chk_original)
        time_lay.addWidget(self.chk_filtered)
        time_lay.addStretch(1)
        self._root.addWidget(self._time_options)

        self.chk_enabled.toggled.connect(self._sync_enabled)
        self.combo_kind.currentTextChanged.connect(self._sync_kind)
        for widget in (
            self.chk_enabled, self.combo_kind, self.spin_cut, self.spin_lo,
            self.spin_hi, self.combo_order, self.chk_original, self.chk_filtered,
        ):
            signal = getattr(widget, "toggled", None) or getattr(widget, "currentTextChanged", None) or getattr(widget, "valueChanged")
            signal.connect(lambda *_: self.changed.emit())
        self._sync_enabled()
        self._sync_kind()
        self.set_method("fft")

    def _sync_enabled(self):
        self._settings.setEnabled(self.chk_enabled.isChecked())

    def _sync_kind(self):
        is_band = _LABEL_TO_KIND[self.combo_kind.currentText()] in {"band", "bandstop"}
        self._single_label.setVisible(not is_band)
        self.spin_cut.setVisible(not is_band)
        self._band_label.setVisible(is_band)
        self._band_host.setVisible(is_band)

    def set_method(self, method: str):
        self._time_options.setVisible(str(method) == "time")

    def time_output_options_visible(self) -> bool:
        return not self._time_options.isHidden()

    def filter_params(self) -> dict:
        spec = self.filter_spec().to_dict()
        return {
            "enabled": bool(self.chk_enabled.isChecked()),
            "spec": spec,
            "show_original": bool(self.chk_original.isChecked()),
            "show_filtered": bool(self.chk_filtered.isChecked()),
        }

    def filter_spec(self) -> FilterSpec:
        kind = _LABEL_TO_KIND[self.combo_kind.currentText()]
        order = int(self.combo_order.currentText())
        if kind in {"band", "bandstop"}:
            return FilterSpec(kind, order=order, cutoff_lo=self.spin_lo.value(), cutoff_hi=self.spin_hi.value())
        return FilterSpec(kind, order=order, cutoff=self.spin_cut.value())

    def apply_filter_params(self, params: dict | None):
        params = params or {}
        spec = FilterSpec.from_dict(params.get("spec") or {})
        self.chk_enabled.setChecked(bool(params.get("enabled", False)))
        self.combo_kind.setCurrentText(_KIND_TO_LABEL.get(spec.kind, "低通"))
        self.combo_order.setCurrentText(str(int(spec.order)))
        self.spin_cut.setValue(float(spec.cutoff))
        self.spin_lo.setValue(float(spec.cutoff_lo))
        self.spin_hi.setValue(float(spec.cutoff_hi))
        self.chk_original.setChecked(bool(params.get("show_original", True)))
        self.chk_filtered.setChecked(bool(params.get("show_filtered", True)))
        self._sync_kind()
        self._sync_enabled()
```

- [ ] **Step 4: Wire InputPanel and BatchSheet**

In `InputPanel.__init__`, after the time range row:

```python
from .filter_panel import BatchFilterPanel

self._filter_panel = BatchFilterPanel(form_host)
form.addRow("预处理", self._filter_panel)
self._filter_panel.changed.connect(lambda *_: self.changed.emit())
```

Add methods to `InputPanel`:

```python
def filter_params(self) -> dict:
    return self._filter_panel.filter_params()

def apply_filter_params(self, params: dict | None) -> None:
    self._filter_panel.apply_filter_params(params)
```

In `InputPanel.set_method()` add:

```python
self._filter_panel.set_method(method)
```

In `BatchSheet.get_preset()` add:

```python
params["filter"] = self._input_panel.filter_params()
```

In `BatchSheet.apply_preset()` after params are available:

```python
self._input_panel.apply_filter_params(dict(preset.params).get("filter"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run the same command from Step 2.

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/filter_panel.py mf4_analyzer/ui/drawers/batch/input_panel.py mf4_analyzer/ui/drawers/batch/sheet.py tests/ui/test_batch_input_panel.py
git commit -m "feat(batch): add filter preprocessing controls"
```

---

### Task 6: Batch UI Method and Output Context

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Test: `tests/ui/test_batch_method_buttons.py`
- Test: `tests/ui/test_batch_input_panel.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_batch_method_buttons_include_time_and_user_labels(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    group = MethodButtonGroup()
    qtbot.addWidget(group)

    assert set(group._buttons) == {"time", "fft", "fft_time", "order_time"}
    assert group._buttons["time"].text() == "时域"
    assert group._buttons["order_time"].text() == "阶次"


def test_batch_time_method_has_no_analysis_fields(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)

    form.set_method("time")

    assert form.visible_field_names() == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_method_buttons.py::test_batch_method_buttons_include_time_and_user_labels \
  tests/ui/test_batch_method_buttons.py::test_batch_time_method_has_no_analysis_fields -q
```

Expected: fails because method buttons do not include `time`.

- [ ] **Step 3: Update method metadata**

In `method_buttons.py`:

```python
_METHODS: tuple[tuple[str, str], ...] = (
    ("time", "时域"),
    ("fft", "FFT"),
    ("fft_time", "FFT vs Time"),
    ("order_time", "阶次"),
)
```

Update `_METHOD_FIELDS`:

```python
_METHOD_FIELDS: dict[str, tuple[str, ...]] = {
    "time": (),
    "fft": ("window", "nfft", "weighting"),
    "fft_time": ("window", "nfft", "overlap", "remove_mean", "weighting"),
    "order_time": (
        "window", "nfft", "max_order", "order_res", "time_res", "weighting",
    ),
}
```

In `input_panel.py`, keep RPM scoped only to order:

```python
_RPM_USING_METHODS = frozenset({"order_time"})
```

In `output_panel.py`, add context:

```python
"time": {
    "x_label": "时间 (X):",
    "x_unit": "s",
    "x_summary": "全时段",
    "y_label": "幅值 (Y):",
    "y_unit": "",
    "y_summary": "自动范围",
},
```

- [ ] **Step 4: Run UI tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/method_buttons.py mf4_analyzer/ui/drawers/batch/output_panel.py mf4_analyzer/ui/drawers/batch/input_panel.py tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py
git commit -m "feat(batch): add time-domain method controls"
```

---

### Task 7: Fill Batch From Current TimeDomain View

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Test: `tests/ui/test_batch_toolbar.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_build_current_batch_preset_supports_time_domain(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "time")
    monkeypatch.setattr(
        win.channel_list,
        "get_checked_channels",
        lambda: [("f1", "sig_a", "#ff0000"), ("f1", "sig_b", "#00ff00")],
    )
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: True)
    monkeypatch.setattr(win.inspector.top, "range_values", lambda: (1.0, 2.0))
    fp = win.inspector.filter_panel
    fp.set_enabled(True)
    fp.set_kind("低通")
    fp.set_cutoff(50.0)
    fp.set_order(6)
    fp.chk_orig.setChecked(False)
    fp.chk_filt.setChecked(True)

    preset = win._build_current_batch_preset()

    assert preset.source == "free_config"
    assert preset.method == "time"
    assert preset.target_signals == ("sig_a", "sig_b")
    assert preset.file_ids == ("f1",)
    assert preset.params["time_range"] == (1.0, 2.0)
    assert preset.params["filter"]["enabled"] is True
    assert preset.params["filter"]["spec"]["kind"] == "low"
    assert preset.params["filter"]["spec"]["cutoff"] == 50.0
    assert preset.params["filter"]["show_original"] is False
    assert preset.params["filter"]["show_filtered"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_toolbar.py::test_build_current_batch_preset_supports_time_domain -q
```

Expected: fails because `_build_current_batch_preset()` returns `None` in time mode.

- [ ] **Step 3: Implement time branch**

In `window.py`, import `dataclasses.replace` locally in `_build_current_batch_preset()` time branch:

```python
if mode == 'time':
    import dataclasses

    checked = self.channel_list.get_checked_channels()
    if not checked:
        return None
    file_ids = tuple(dict.fromkeys(fid for fid, _ch, _color in checked))
    target_signals = tuple(sorted({ch for _fid, ch, _color in checked}))
    params = {}
    if self.inspector.top.range_enabled():
        params['time_range'] = self.inspector.top.range_values()
    fp = getattr(self.inspector, "filter_panel", None)
    if fp is not None:
        params["filter"] = {
            "enabled": bool(fp.is_enabled()),
            "spec": fp.filter_spec().to_dict(),
            "show_original": bool(fp.show_original()),
            "show_filtered": bool(fp.show_filtered()),
        }
    preset = AnalysisPreset.free_config(
        name="当前时域",
        method="time",
        target_signals=target_signals,
        params=params,
    )
    return dataclasses.replace(preset, file_ids=file_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window/window.py tests/ui/test_batch_toolbar.py
git commit -m "feat(batch): fill from current time-domain view"
```

---

### Task 8: End-to-End Batch Smoke and Offscreen Screenshots

**Files:**
- Modify: `tests/ui/test_batch_smoke.py`
- Create: `.state/screenshots/batch-timedomain-filter/` artifacts during verification

- [ ] **Step 1: Write smoke test for full dialog preset**

Append:

```python
def test_batch_sheet_time_filter_preset_round_trip(qtbot, tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    t = np.arange(64, dtype=float) / 64.0
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 5 * t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=64.0)
    sheet = BatchSheet(None, files={0: fd})
    qtbot.addWidget(sheet)
    preset = AnalysisPreset.free_config(
        name="time",
        method="time",
        target_signals=("sig",),
        params={
            "time_range": (0.1, 0.5),
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 10.0},
                "show_original": True,
                "show_filtered": True,
            },
        },
    )

    sheet.apply_preset(preset)
    got = sheet.get_preset()

    assert got.method == "time"
    assert got.params["time_range"] == (0.1, 0.5)
    assert got.params["filter"]["enabled"] is True
    assert got.params["filter"]["spec"]["kind"] == "low"
    assert got.params["filter"]["show_filtered"] is True
```

- [ ] **Step 2: Run smoke test**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_batch_smoke.py::test_batch_sheet_time_filter_preset_round_trip -q
```

Expected: `1 passed`.

- [ ] **Step 3: Generate offscreen screenshots**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python - <<'PY'
from pathlib import Path
import sys
from PyQt5.QtWidgets import QApplication
from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font
from mf4_analyzer.ui.drawers.batch import BatchSheet

out_dir = Path(".state/screenshots/batch-timedomain-filter")
out_dir.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication(sys.argv)
setup_chinese_font()
load_stylesheet(app)
sheet = BatchSheet(None, files={})
sheet.resize(1080, 760)
for method in ("time", "fft", "fft_time", "order_time"):
    sheet.apply_method(method)
    sheet.show()
    for _ in range(10):
        app.processEvents()
    path = out_dir / f"batch-{method}.png"
    assert sheet.grab().save(str(path)), path
    print(path)
sheet.close()
PY
```

Expected: four PNG paths printed and non-empty files under `.state/screenshots/batch-timedomain-filter/`.

- [ ] **Step 4: Run focused verification**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py \
  tests/test_filters.py \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_toolbar.py \
  tests/ui/test_batch_smoke.py -q
git diff --check
```

Expected: pytest passes; `git diff --check` prints no output.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_batch_smoke.py
git commit -m "test(batch): cover time filter dialog workflow"
```

Do not commit `.state/screenshots/...` unless the user explicitly asks for screenshot artifacts in git.

---

## Self-Review Checklist

- Spec requirement coverage:
  - `time` method core: Task 1.
  - `time` PNG: Task 4.
  - Filter params and preprocessing: Tasks 2 and 3.
  - Batch UI filter panel: Task 5.
  - Method labels and axis context: Task 6.
  - Fill from current TimeDomain view: Task 7.
  - Offscreen rendered proof: Task 8.
- Placeholder scan: no unresolved placeholder text is intentionally left in this plan.
- Type consistency:
  - Batch method key is always `time`.
  - Filter params always live under `params["filter"]`.
  - Time data columns are always `time_s`, `series`, `value`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-batch-timedomain-filter-preprocessing.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.

# FFT vs Time 2D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Revised 2026-04-25** after the first review found a class of "looks
> done but UI controls don't actually do anything" bugs. The major fixes
> live in Tasks 3, 5, 6, and the new Task 7 (worker) and Task 8 (cache
> invalidation). Read §"Plan v2 changes" at the bottom before executing.

**Goal:** Add a precise, offline, single-channel FFT vs Time 2D spectrogram mode with bottom time-slice FFT, hover/click readouts, dynamic-range and frequency-range controls that actually take effect, caching, presets, export, worker-thread compute, and validation.

**Architecture:** Add a GUI-free signal-processing layer for spectrogram computation, then wire a fourth UI mode through Toolbar, ChartStack, Inspector, and MainWindow. Keep computation and plotting separate: `SpectrogramAnalyzer` returns arrays and metadata; UI classes render, cache, export, and handle cursor selection.

**Tech Stack:** PyQt5, matplotlib, numpy, scipy>=1.10 (load-bearing — window helper delegates to `scipy.signal.get_window`), pandas/asammdf/openpyxl loaders, pytest, pytest-qt.

---

## Reference Documents

- Design spec: `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md` (revised 2026-04-25)
- Brainstorm record: `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-brainstorm.md`
- UI demo: `docs/fft-vs-time-ui-demo.html`
- Existing FFT code: `mf4_analyzer/signal/fft.py`
- Existing UI topology: `mf4_analyzer/ui/toolbar.py`, `mf4_analyzer/ui/chart_stack.py`, `mf4_analyzer/ui/inspector.py`, `mf4_analyzer/ui/inspector_sections.py`, `mf4_analyzer/ui/canvases.py`, `mf4_analyzer/ui/main_window.py`

## File Map

- Modify `requirements.txt`: add `scipy>=1.10`.
- Modify `mf4_analyzer/signal/fft.py`: add shared window/amplitude helpers backed by `scipy.signal.get_window`; `FFTAnalyzer.compute_fft` delegates. **Behavior change:** DC and Nyquist bins are no longer doubled (the legacy 2× was a single-sided amplitude mistake — see Task 1 audit).
- Create `mf4_analyzer/signal/spectrogram.py`: dataclasses and `SpectrogramAnalyzer`.
- Modify `mf4_analyzer/signal/__init__.py`: export `SpectrogramAnalyzer`, `SpectrogramParams`, `SpectrogramResult`.
- Create `tests/test_spectrogram.py`: algorithm tests.
- Modify `tests/test_signal_no_gui_import.py`: include new signal module.
- Modify `mf4_analyzer/ui/icons.py`: add FFT vs Time icon.
- Modify `mf4_analyzer/ui/toolbar.py`: add fourth top mode.
- Modify `mf4_analyzer/ui/chart_stack.py`: add fourth card.
- Modify `mf4_analyzer/ui/canvases.py`: add `SpectrogramCanvas` (cursor_info signal, hover, click, dynamic-range, freq-range).
- Modify `mf4_analyzer/ui/inspector_sections.py`: add `FFTTimeContextual`.
- Modify `mf4_analyzer/ui/inspector.py`: add fourth contextual panel and relay signals.
- Modify `mf4_analyzer/ui/main_window.py`: add `do_fft_time`, cache, worker, export wiring, and the cache-invalidation hooks listed in Task 8.
- Modify/add UI tests under `tests/ui/`: toolbar, chart stack, inspector, smoke, and worker.
- Create `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`: validation report.

---

### Task 1: Add scipy and Shared FFT Math Helpers

**Files:**
- Modify: `requirements.txt`
- Modify: `mf4_analyzer/signal/fft.py`
- Reference: `tests/test_fft_amplitude_normalization.py`, `tests/test_signal_no_gui_import.py`

- [ ] **Step 1: Audit existing `compute_fft` for the DC/Nyquist scaling mistake**

The current implementation does `amp = 2 * |FFT|/n/mean(w)` over the
entire half-spectrum, which double-counts the DC bin and (when `nfft`
is even) the Nyquist bin. The mathematically correct one-sided
amplitude doubles only the interior bins.

Run:

```bash
grep -n "compute_fft\|amp\[0\]\|amp\[-1\]\|nyquist" tests/test_fft_amplitude_normalization.py tests/test_signal_no_gui_import.py
```

Expected: existing tests use a bin-aligned tone at `k=200` of `n=4096`
(`fs=1000`), well away from DC and Nyquist, plus a DC-offset test that
relies on `compute_fft` subtracting the mean. **None of them inspect
`amp[0]` or `amp[-1]`**, so the scaling correction is safe with
respect to the current test suite. Record this audit in the task
summary.

If a test in `tests/test_fft_amplitude_normalization.py` is later
edited to inspect `amp[0]` / `amp[-1]`, it must use the corrected
single-amplitude values (no implicit 2×).

- [ ] **Step 2: Add scipy dependency**

Edit `requirements.txt` so it includes:

```text
numpy
pandas
PyQt5
matplotlib
scipy>=1.10
asammdf
openpyxl
pytest>=7.0
pytest-qt>=4.2
```

- [ ] **Step 3: Add the shared, scipy-backed window and amplitude helpers**

In `mf4_analyzer/signal/fft.py`, add module-level helpers above
`class FFTAnalyzer`:

```python
import numpy as np
from scipy.signal import get_window as _scipy_get_window


# App-owned alias normalization. Keeps "hann" and "hanning" pointing at
# the same definition and forces our `kaiser` beta default.
_WINDOW_ALIASES = {
    'hann': 'hanning',
}


def get_analysis_window(name, n):
    """Return the app's symmetric analysis window of length n.

    Single source of truth for FFT and spectrogram code so both paths
    use identical amplitude normalization. Implementation delegates to
    `scipy.signal.get_window` but keeps app ownership of:

      - alias resolution (`hann` -> `hanning`)
      - the `kaiser` beta default (14)
      - the symmetric (fftbins=False) policy
    """
    key = (name or 'hanning').lower()
    key = _WINDOW_ALIASES.get(key, key)
    if key == 'kaiser':
        spec = ('kaiser', 14)
    elif key == 'hanning':
        spec = 'hann'  # scipy uses 'hann'; we map our public 'hanning' to it
    else:
        spec = key
    return _scipy_get_window(spec, n, fftbins=False).astype(float, copy=False)


def one_sided_amplitude(frame, fs, win='hanning', nfft=None, remove_mean=True):
    """One-sided amplitude spectrum with coherent-gain correction.

    Returns (freq, amp) where amp doubles the *interior* bins only;
    DC (amp[0]) and, for even nfft, Nyquist (amp[-1]) are NOT doubled.
    This is the mathematically correct single-sided amplitude.
    """
    frame = np.asarray(frame, dtype=float)
    n = len(frame)
    if nfft is None or nfft <= 0:
        nfft = n
    if nfft < n:
        work = frame[:nfft].copy()
        n = nfft
    else:
        work = frame.copy()
    if remove_mean:
        work = work - np.mean(work)
    w = get_analysis_window(win, n)
    padded = np.zeros(nfft, dtype=float)
    padded[:n] = work[:n] * w
    fft_r = np.fft.rfft(padded)
    freq = np.fft.rfftfreq(nfft, 1.0 / fs)
    amp = np.abs(fft_r) / n / np.mean(w)
    if amp.size > 2:
        # Double interior bins. For even nfft the last bin is Nyquist
        # and stays single; for odd nfft the last bin is interior and
        # should be doubled.
        if nfft % 2 == 0:
            amp[1:-1] *= 2.0
        else:
            amp[1:] *= 2.0
    return freq, amp
```

- [ ] **Step 4: Rewrite `FFTAnalyzer.get_window` and `compute_fft` to delegate**

```python
class FFTAnalyzer:
    @staticmethod
    def get_window(name, n):
        return get_analysis_window(name, n)

    @staticmethod
    def compute_fft(sig, fs, win='hanning', nfft=None):
        # Preserve historical contract: returns nfft//2 bins (drops Nyquist
        # for even nfft) with frequencies from np.fft.fftfreq's first half.
        sig = np.asarray(sig, dtype=float)
        n = len(sig)
        if nfft is None or nfft <= 0:
            nfft = n
        nfft = int(nfft)
        freq, amp = one_sided_amplitude(sig, fs, win=win, nfft=nfft, remove_mean=True)
        nh = nfft // 2
        return freq[:nh], amp[:nh]
```

Keep `compute_psd` and `compute_averaged_fft` public signatures
unchanged. **Note:** `compute_averaged_fft` should also be updated
to call `get_analysis_window` instead of building its own window so
the shared helper actually owns window construction across the
module.

- [ ] **Step 5: Run existing FFT tests**

```bash
pytest tests/test_fft_amplitude_normalization.py -v
```

Expected: all tests pass (the audit in Step 1 confirmed they don't
touch DC/Nyquist).

- [ ] **Step 6: Run signal no-GUI guard**

```bash
pytest tests/test_signal_no_gui_import.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

If this directory is a git repo:

```bash
git add requirements.txt mf4_analyzer/signal/fft.py
git commit -m "feat: share FFT window and amplitude helpers via scipy"
```

If not a git repo, record changed files in the task summary.

---

### Task 2: Add SpectrogramAnalyzer with TDD

**Files:**
- Create: `mf4_analyzer/signal/spectrogram.py`
- Modify: `mf4_analyzer/signal/__init__.py`
- Create: `tests/test_spectrogram.py`
- Modify: `tests/test_signal_no_gui_import.py`

- [ ] **Step 1: Write failing algorithm tests**

Create `tests/test_spectrogram.py`:

```python
from __future__ import annotations

import unittest

import numpy as np

from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams


class SpectrogramAnalyzerTests(unittest.TestCase):
    def test_bin_aligned_tone_amplitude(self):
        fs = 1000.0
        nfft = 1024
        t = np.arange(4096) / fs
        freq_hz = 125.0  # bin-aligned: k=128 of nfft=1024 at fs=1000
        amp_true = 2.5
        sig = amp_true * np.sin(2 * np.pi * freq_hz * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='tone', unit='V')

        peak_idx = int(np.argmax(result.amplitude[:, 0]))
        self.assertAlmostEqual(result.frequencies[peak_idx], freq_hz, places=6)
        self.assertLess(abs(result.amplitude[peak_idx, 0] - amp_true) / amp_true, 0.03)

    def test_two_tone_frequency_bins(self):
        fs = 1024.0
        nfft = 1024
        t = np.arange(4096) / fs
        sig = 1.0 * np.sin(2 * np.pi * 64 * t) + 0.5 * np.sin(2 * np.pi * 192 * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='two', unit='V')

        peaks = np.argsort(result.amplitude[:, 0])[-2:]
        peak_freqs = sorted(round(float(result.frequencies[i])) for i in peaks)
        self.assertEqual(peak_freqs, [64, 192])

    def test_burst_time_localization(self):
        # Burst from t=2.0s to t=3.0s, fs=1000, nfft=500, hop=250.
        # Frame centers fall at t[start] + (nfft-1)/(2*fs) = t[start] + 0.2495.
        # Frames straddling the burst boundary contain ~half the burst,
        # so threshold at 25% of peak energy is a robust separator
        # between "frame fully inside burst", "frame straddling boundary",
        # and "frame entirely outside burst".
        fs = 1000.0
        nfft = 500
        t = np.arange(5000) / fs
        sig = np.zeros_like(t)
        active = (t >= 2.0) & (t < 3.0)
        sig[active] = np.sin(2 * np.pi * 80 * t[active])
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='burst', unit='V')

        freq_idx = int(np.argmin(np.abs(result.frequencies - 80)))
        energy = result.amplitude[freq_idx, :]
        active_frames = result.times[energy > 0.25 * np.max(energy)]
        self.assertGreaterEqual(float(active_frames.min()), 1.75)
        self.assertLessEqual(float(active_frames.max()), 3.25)

    def test_db_conversion(self):
        amp = np.array([[1.0, 10.0]])
        db = SpectrogramAnalyzer.amplitude_to_db(amp, reference=1.0)
        self.assertAlmostEqual(float(db[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(db[0, 1]), 20.0, places=6)

    def test_frame_center_times(self):
        fs = 100.0
        nfft = 20
        t = np.arange(100) / fs
        sig = np.sin(2 * np.pi * 5 * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='time', unit='')

        self.assertAlmostEqual(float(result.times[0]), (nfft - 1) / (2 * fs), places=9)
        self.assertAlmostEqual(float(result.times[1] - result.times[0]), 0.1, places=9)

    def test_rejects_signal_shorter_than_nfft(self):
        params = SpectrogramParams(fs=1000.0, nfft=1024, window='hanning', overlap=0.5)
        with self.assertRaisesRegex(ValueError, 'shorter than nfft'):
            SpectrogramAnalyzer.compute(np.ones(100), np.arange(100) / 1000.0, params, 'short', '')

    def test_rejects_nonuniform_time_axis(self):
        fs = 1000.0
        t = np.arange(2048) / fs
        t[1000] += 0.01
        sig = np.sin(2 * np.pi * 100 * t)
        params = SpectrogramParams(fs=fs, nfft=512, window='hanning', overlap=0.5)
        with self.assertRaisesRegex(ValueError, 'non-uniform'):
            SpectrogramAnalyzer.compute(sig, t, params, 'jitter', '')

    def test_window_preset_hann_and_flattop(self):
        # Lock both presets so a future scipy upgrade or an accidental
        # alias rewrite cannot silently change normalization.
        fs = 1000.0
        nfft = 1024
        t = np.arange(4096) / fs
        amp_true = 1.7
        # Bin-aligned: hann reaches ~1% of true amp at the bin.
        bin_aligned = 200 * fs / nfft  # 195.3125 Hz
        sig = amp_true * np.sin(2 * np.pi * bin_aligned * t)

        for win, tol in (('hanning', 0.02), ('flattop', 0.01)):
            params = SpectrogramParams(fs=fs, nfft=nfft, window=win, overlap=0.5)
            result = SpectrogramAnalyzer.compute(sig, t, params, 'tone', 'V')
            peak = float(np.max(result.amplitude[:, 0]))
            self.assertLess(abs(peak - amp_true) / amp_true, tol, msg=f'window={win}')

    def test_memory_ceiling_blocks_oversized_request(self):
        # Construct a request that would build a > 64 MB float32 matrix
        # (e.g. nfft=8192, overlap=0.99, signal length ~= 5e6 samples).
        nfft = 8192
        n = 5_000_000
        fs = 50_000.0
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.99)
        sig = np.zeros(n, dtype=float)
        t = np.arange(n) / fs
        with self.assertRaisesRegex(ValueError, 'memory ceiling'):
            SpectrogramAnalyzer.compute(sig, t, params, 'huge', '')
```

- [ ] **Step 2: Run tests and verify failure**

```bash
pytest tests/test_spectrogram.py -v
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement spectrogram module**

Create `mf4_analyzer/signal/spectrogram.py`:

```python
"""2D FFT-vs-time spectrogram analysis without GUI dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .fft import one_sided_amplitude


# Hard ceiling on the rendered float32 amplitude matrix size.
# 64 MB ~ 16 M cells, e.g. 4097-bin x 4096-frame.
_MAX_AMPLITUDE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SpectrogramParams:
    fs: float
    nfft: int
    window: str = 'hanning'
    overlap: float = 0.5
    remove_mean: bool = True
    db_reference: float = 1.0


@dataclass
class SpectrogramResult:
    times: np.ndarray
    frequencies: np.ndarray
    amplitude: np.ndarray            # float32, shape (freq_bins, frames)
    params: SpectrogramParams
    channel_name: str
    unit: str = ''
    metadata: dict = field(default_factory=dict)


class SpectrogramAnalyzer:
    @staticmethod
    def amplitude_to_db(amplitude, reference=1.0):
        ref = float(reference)
        if ref <= 0:
            raise ValueError('db_reference must be > 0')
        amp = np.asarray(amplitude, dtype=float)
        eps = np.finfo(float).tiny
        return 20.0 * np.log10(np.maximum(amp, eps) / ref)

    @staticmethod
    def _validate_time_axis(t, fs, tolerance):
        arr = np.asarray(t, dtype=float)
        if arr.ndim != 1:
            raise ValueError('time axis must be one-dimensional')
        if arr.size < 2:
            raise ValueError('time axis is too short')
        nominal_dt = 1.0 / float(fs)
        dt = np.diff(arr)
        if np.any(dt <= 0):
            raise ValueError('time axis must be strictly increasing')
        relative_jitter = float(np.max(np.abs(dt - nominal_dt)) / nominal_dt)
        if relative_jitter > tolerance:
            raise ValueError(
                f'non-uniform time axis: relative_jitter={relative_jitter:.3g} '
                f'exceeds tolerance={tolerance:.3g}'
            )
        return arr

    @staticmethod
    def compute(
        signal,
        time,
        params: SpectrogramParams,
        channel_name,
        unit='',
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_token: Callable[[], bool] | None = None,
        time_jitter_tolerance: float = 1e-3,
        max_amplitude_bytes: int = _MAX_AMPLITUDE_BYTES,
    ):
        fs = float(params.fs)
        if fs <= 0:
            raise ValueError('fs must be > 0')
        nfft = int(params.nfft)
        if nfft <= 1:
            raise ValueError('nfft must be > 1')
        if not (0 <= float(params.overlap) < 1):
            raise ValueError('overlap must be >= 0 and < 1')

        sig = np.asarray(signal, dtype=float)
        t = SpectrogramAnalyzer._validate_time_axis(time, fs, time_jitter_tolerance)
        if sig.ndim != 1:
            raise ValueError('signal must be one-dimensional')
        if sig.size != t.size:
            raise ValueError('signal and time must have the same length')
        if sig.size < nfft:
            raise ValueError('signal is shorter than nfft')

        hop = int(nfft * (1.0 - float(params.overlap)))
        if hop <= 0:
            raise ValueError('overlap leaves no positive hop size')
        starts = np.arange(0, sig.size - nfft + 1, hop, dtype=int)
        total = int(starts.size)
        if total <= 0:
            raise ValueError('no complete spectrogram frames')

        freq_bins = nfft // 2 + 1
        estimated_bytes = freq_bins * total * 4  # float32
        if estimated_bytes > int(max_amplitude_bytes):
            raise ValueError(
                f'memory ceiling exceeded: '
                f'{freq_bins} bins x {total} frames ~= '
                f'{estimated_bytes / (1024 * 1024):.1f} MB '
                f'(ceiling {max_amplitude_bytes / (1024 * 1024):.0f} MB). '
                f'Reduce nfft, overlap, or selected time range.'
            )

        amplitude = np.empty((freq_bins, total), dtype=np.float32)
        times = np.empty(total, dtype=float)
        freq = None
        # Throttle progress callbacks to ~50 emissions over the run.
        progress_step = max(1, total // 50)
        for i, start in enumerate(starts):
            if cancel_token is not None and cancel_token():
                raise RuntimeError('spectrogram computation cancelled')
            frame = sig[start:start + nfft]
            f, amp = one_sided_amplitude(
                frame,
                fs,
                win=params.window,
                nfft=nfft,
                remove_mean=params.remove_mean,
            )
            if freq is None:
                freq = f
            amplitude[:, i] = amp.astype(np.float32, copy=False)
            times[i] = t[start] + (nfft - 1) / (2.0 * fs)
            if progress_callback is not None and (
                (i + 1) % progress_step == 0 or (i + 1) == total
            ):
                progress_callback(i + 1, total)

        return SpectrogramResult(
            times=times,
            frequencies=np.asarray(freq, dtype=float),
            amplitude=amplitude,
            params=params,
            channel_name=str(channel_name),
            unit=str(unit or ''),
            metadata={'frames': total, 'hop': hop, 'freq_bins': freq_bins},
        )
```

- [ ] **Step 4: Export new classes**

Modify `mf4_analyzer/signal/__init__.py`:

```python
from .fft import FFTAnalyzer
from .order import OrderAnalyzer
from .spectrogram import SpectrogramAnalyzer, SpectrogramParams, SpectrogramResult
```

- [ ] **Step 5: Add no-GUI import guard**

Update `tests/test_signal_no_gui_import.py` to import:

```python
import mf4_analyzer.signal.spectrogram
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_spectrogram.py tests/test_signal_no_gui_import.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/signal/__init__.py mf4_analyzer/signal/spectrogram.py tests/test_spectrogram.py tests/test_signal_no_gui_import.py
git commit -m "feat: add spectrogram analyzer"
```

If no `.git` directory exists, record changed files in the task summary.

---

### Task 3: Add FFT vs Time Mode Plumbing

**Files:**
- Modify: `mf4_analyzer/ui/toolbar.py`
- Modify: `mf4_analyzer/ui/icons.py`
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `mf4_analyzer/ui/canvases.py` (skeleton only — Task 5 fleshes it out)
- Modify: `mf4_analyzer/ui/inspector.py`
- Modify: `mf4_analyzer/ui/inspector_sections.py`
- Modify: `mf4_analyzer/ui/main_window.py` (canvas promotion + mode wiring)
- Test: `tests/ui/test_toolbar.py`, `tests/ui/test_chart_stack.py`, `tests/ui/test_inspector.py`, `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Add failing toolbar test**

In `tests/ui/test_toolbar.py`:

```python
def test_toolbar_exposes_fft_time_mode(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar

    tb = Toolbar()
    qtbot.addWidget(tb)
    seen = []
    tb.mode_changed.connect(seen.append)
    tb.btn_mode_fft_time.click()

    assert tb.current_mode() == 'fft_time'
    assert seen[-1] == 'fft_time'
    assert tb.btn_mode_fft_time.text() == 'FFT vs Time'
```

```bash
pytest tests/ui/test_toolbar.py::test_toolbar_exposes_fft_time_mode -v
```

Expected: fail.

- [ ] **Step 2: Add icon and toolbar button**

In `mf4_analyzer/ui/icons.py` add a `mode_fft_time()` method following
the existing icon-helper style (no emoji, no external assets — match
the line/pixmap style used by neighbors like `mode_fft`).

In `mf4_analyzer/ui/toolbar.py`:

```python
self.btn_mode_fft_time = QPushButton("FFT vs Time", self)
self.btn_mode_fft_time.setIcon(Icons.mode_fft_time())
```

Add it to icon-size loops, the `_mode_group`, the `(key, button)`
mapping (key `'fft_time'`), and `_wire()` / `_set_mode()` switch
mappings.

- [ ] **Step 3: Run toolbar test → pass**

- [ ] **Step 4: Add failing ChartStack test**

In `tests/ui/test_chart_stack.py`:

```python
def test_chart_stack_exposes_fft_time_card(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.set_mode('fft_time')

    assert stack.current_mode() == 'fft_time'
    assert stack.canvas_fft_time is not None
    assert stack.stack.currentWidget() is stack._fft_time_card
```

- [ ] **Step 5: Add SpectrogramCanvas skeleton and fourth ChartStack card**

In `mf4_analyzer/ui/canvases.py`, add a minimal class — full rendering
lands in Task 5. The skeleton **must** declare the public surface
Task 5 will fill so chart_stack/main_window can wire signals now:

```python
class SpectrogramCanvas(FigureCanvas):
    cursor_info = pyqtSignal(str)

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(12, 8), dpi=100, facecolor=CHART_FACE)
        super().__init__(self.fig)
        self.setParent(parent)
        self._result = None
        self._selected_index = None
        self._amplitude_mode = 'amplitude_db'
        self._cmap = 'turbo'
        self._dynamic = '80 dB'
        self._freq_range = None
        self._db_cache = None  # (id(result), db_reference) -> ndarray

    def clear(self):
        self._result = None
        self._selected_index = None
        self._db_cache = None
        self.fig.clear()
        self.fig.set_facecolor(CHART_FACE)

    def full_reset(self):
        self.clear()
        self.draw_idle()

    def selected_index(self):
        return self._selected_index

    def has_result(self):
        return self._result is not None
```

In `mf4_analyzer/ui/chart_stack.py`:

```python
from .canvases import PlotCanvas, SpectrogramCanvas, TimeDomainCanvas
```

```python
self.canvas_fft_time = SpectrogramCanvas(self)
self._fft_time_card = _ChartCard(self.canvas_fft_time)
self.stack.addWidget(self._fft_time_card)
```

Update mappings:

```python
_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}
```

Include `canvas_fft_time` in `full_reset_all()` and any copy-image
plumbing.

- [ ] **Step 6: Run ChartStack test → pass**

- [ ] **Step 7: Add failing Inspector test**

In `tests/ui/test_inspector.py`:

```python
def test_inspector_exposes_fft_time_context(qtbot):
    from mf4_analyzer.ui.inspector import Inspector

    inspector = Inspector()
    qtbot.addWidget(inspector)
    inspector.set_mode('fft_time')

    assert inspector.current_mode() == 'fft_time'
    assert hasattr(inspector, 'fft_time_ctx')
```

- [ ] **Step 8: Add minimal FFTTimeContextual + inspector wiring**

In `mf4_analyzer/ui/inspector_sections.py`, add a *minimal*
FFTTimeContextual — Task 4 expands it. It must already expose
`fft_time_requested = pyqtSignal()` and a `btn_compute` so MainWindow
can wire it now:

```python
class FFTTimeContextual(QWidget):
    fft_time_requested = pyqtSignal()
    force_recompute_requested = pyqtSignal()
    export_full_requested = pyqtSignal()
    export_main_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fftTimeContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        self.btn_compute = QPushButton("计算时频图")
        self.btn_compute.setProperty("role", "primary")
        self.btn_compute.setEnabled(False)  # disabled until a signal candidate is set
        root.addWidget(self.btn_compute)
        root.addStretch()
        self.btn_compute.clicked.connect(self.fft_time_requested)

    def set_signal_candidates(self, candidates):
        # Real implementation lands in Task 4.
        self.btn_compute.setEnabled(bool(candidates))
```

In `mf4_analyzer/ui/inspector.py`:

- create `self.fft_time_ctx = FFTTimeContextual()`
- add to the contextual stack
- add mode index mapping for `'fft_time'`
- relay signals: `fft_time_requested`, `fft_time_force_requested`,
  `fft_time_export_full_requested`, `fft_time_export_main_requested`.

- [ ] **Step 9: Promote canvas onto MainWindow and wire mode**

In `mf4_analyzer/ui/main_window.py`, **after** the existing canvas
promotion lines (around `self.canvas_time = self.chart_stack.canvas_time`
etc.), add:

```python
self.canvas_fft_time = self.chart_stack.canvas_fft_time
```

This is the gap that broke the first plan revision — without it,
`do_fft_time` would AttributeError on first invocation.

Add a smoke test at `tests/ui/test_main_window_smoke.py`:

```python
def test_main_window_promotes_fft_time_canvas(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    win = MainWindow()
    qtbot.addWidget(win)

    assert isinstance(win.canvas_fft_time, SpectrogramCanvas)
    assert win.canvas_fft_time is win.chart_stack.canvas_fft_time
```

- [ ] **Step 10: Run UI plumbing tests**

```bash
pytest tests/ui/test_toolbar.py tests/ui/test_chart_stack.py tests/ui/test_inspector.py tests/ui/test_main_window_smoke.py::test_main_window_promotes_fft_time_canvas -v
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add mf4_analyzer/ui/icons.py mf4_analyzer/ui/toolbar.py mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/canvases.py mf4_analyzer/ui/inspector.py mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/main_window.py tests/ui/
git commit -m "feat: add fft vs time mode plumbing"
```

---

### Task 4: Build FFTTimeContextual Parameters and Presets

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`
- Modify: `mf4_analyzer/ui/inspector.py`
- Test: `tests/ui/test_inspector.py`

- [ ] **Step 1: Add failing parameter-getter test**

```python
def test_fft_time_context_returns_params(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.set_signal_candidates([("file:ch", ("f1", "ch"))])

    ctx.combo_nfft.setCurrentText('2048')
    ctx.combo_win.setCurrentText('hanning')
    ctx.spin_overlap.setValue(75)
    ctx.combo_amp_mode.setCurrentText('Amplitude dB')
    ctx.chk_freq_auto.setChecked(False)
    ctx.spin_freq_min.setValue(50.0)
    ctx.spin_freq_max.setValue(2400.0)
    ctx.combo_dynamic.setCurrentText('80 dB')

    params = ctx.get_params()

    assert params['nfft'] == 2048
    assert params['window'] == 'hanning'
    assert params['overlap'] == 0.75
    assert params['amplitude_mode'] == 'amplitude_db'
    assert params['freq_auto'] is False
    assert params['freq_min'] == 50.0
    assert params['freq_max'] == 2400.0
    assert params['dynamic'] == '80 dB'
```

- [ ] **Step 2: Replace skeleton FFTTimeContextual body with real controls**

Add controls following the design §6.2 panel groups. Key bits:

```python
self.combo_sig = QComboBox()
self.spin_fs = QDoubleSpinBox()
self.spin_fs.setRange(1, 1e6)
self.spin_fs.setValue(1000)
self.spin_fs.setSuffix(" Hz")
self.combo_nfft = QComboBox()
self.combo_nfft.addItems(['512', '1024', '2048', '4096', '8192'])
self.combo_nfft.setCurrentText('2048')
self.combo_win = QComboBox()
self.combo_win.addItems(['hanning', 'flattop', 'hamming', 'blackman', 'kaiser', 'bartlett'])
self.spin_overlap = QSpinBox()
self.spin_overlap.setRange(0, 90)
self.spin_overlap.setValue(75)
self.spin_overlap.setSuffix(" %")
self.chk_remove_mean = QCheckBox("去均值")
self.chk_remove_mean.setChecked(True)
self.combo_amp_mode = QComboBox()
self.combo_amp_mode.addItems(['Amplitude dB', 'Amplitude'])
self.combo_dynamic = QComboBox()
self.combo_dynamic.addItems(['80 dB', '60 dB', 'Auto'])
self.combo_cmap = QComboBox()
self.combo_cmap.addItems(['turbo', 'viridis', 'gray'])
self.chk_freq_auto = QCheckBox("自动频率范围")
self.chk_freq_auto.setChecked(True)
self.spin_freq_min = QDoubleSpinBox(); self.spin_freq_min.setRange(0, 1e9)
self.spin_freq_max = QDoubleSpinBox(); self.spin_freq_max.setRange(0, 1e9)
self.spin_freq_max.setValue(0.0)  # 0.0 means "use Nyquist"
self.btn_force = QPushButton("强制重算")
self.btn_export_full = QPushButton("导出完整视图")
self.btn_export_main = QPushButton("导出主图")
```

Implement getters and signal wiring:

```python
def get_params(self):
    mode = self.combo_amp_mode.currentText()
    return dict(
        signal=self.combo_sig.currentData(),
        fs=self.spin_fs.value(),
        nfft=int(self.combo_nfft.currentText()),
        window=self.combo_win.currentText(),
        overlap=self.spin_overlap.value() / 100.0,
        remove_mean=self.chk_remove_mean.isChecked(),
        amplitude_mode='amplitude_db' if 'dB' in mode else 'amplitude',
        db_reference=1.0,
        freq_auto=self.chk_freq_auto.isChecked(),
        freq_min=self.spin_freq_min.value(),
        freq_max=self.spin_freq_max.value(),
        dynamic=self.combo_dynamic.currentText(),
        cmap=self.combo_cmap.currentText(),
    )

def set_signal_candidates(self, candidates):
    # Preserve previous selection if still present.
    prev = self.combo_sig.currentData()
    self.combo_sig.blockSignals(True)
    self.combo_sig.clear()
    keep_idx = -1
    for i, (text, data) in enumerate(candidates):
        self.combo_sig.addItem(text, data)
        if data == prev:
            keep_idx = i
    if keep_idx >= 0:
        self.combo_sig.setCurrentIndex(keep_idx)
    self.combo_sig.blockSignals(False)
    # Compute is enabled iff there is a valid candidate.
    self.btn_compute.setEnabled(self.combo_sig.count() > 0)

def current_signal(self):
    return self.combo_sig.currentData()

def set_fs(self, fs):
    self.spin_fs.blockSignals(True)
    self.spin_fs.setValue(float(fs))
    self.spin_fs.blockSignals(False)
```

Wire the existing button signals (`force_recompute_requested`,
`export_full_requested`, `export_main_requested`) to the new buttons.

- [ ] **Step 3: Add disabled-button test**

```python
def test_fft_time_compute_button_tracks_signal_candidates(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    assert ctx.btn_compute.isEnabled() is False

    ctx.set_signal_candidates([("file:ch", ("f1", "ch"))])
    assert ctx.btn_compute.isEnabled() is True

    ctx.set_signal_candidates([])
    assert ctx.btn_compute.isEnabled() is False
```

- [ ] **Step 4: Add candidate-preservation test**

```python
def test_fft_time_signal_candidates_preserve_selection(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.set_signal_candidates([
        ("file:a", ("f1", "a")),
        ("file:b", ("f1", "b")),
    ])
    ctx.combo_sig.setCurrentIndex(1)
    assert ctx.current_signal() == ("f1", "b")

    # Re-supply candidates (e.g. opening another file). The previously
    # selected ("f1", "b") is still available and must remain selected.
    ctx.set_signal_candidates([
        ("file:a", ("f1", "a")),
        ("file:b", ("f1", "b")),
        ("file:c", ("f2", "c")),
    ])
    assert ctx.current_signal() == ("f1", "b")
```

- [ ] **Step 5: Add preset test and implementation**

```python
def test_fft_time_context_builtin_presets(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual

    ctx = FFTTimeContextual()
    qtbot.addWidget(ctx)
    ctx.apply_builtin_preset('amplitude_accuracy')
    params = ctx.get_params()

    assert params['window'] == 'flattop'
    assert params['nfft'] == 4096
    assert params['amplitude_mode'] == 'amplitude'
```

Implementation per design §7. Three presets: `diagnostic`,
`amplitude_accuracy`, `high_frequency`.

- [ ] **Step 6: Run inspector tests**

```bash
pytest tests/ui/test_inspector.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/inspector.py mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat: add fft vs time inspector controls and presets"
```

---

### Task 5: Implement SpectrogramCanvas Rendering, Cursor, Hover

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Add failing render test**

```python
def test_spectrogram_canvas_plots_main_and_slice(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2, 0.3]),
        frequencies=np.array([10.0, 20.0, 30.0]),
        amplitude=np.array([[1, 2, 3], [2, 4, 6], [1, 3, 5]], dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8, window='hanning', overlap=0.5),
        channel_name='demo',
        unit='V',
    )

    canvas.plot_result(result, amplitude_mode='amplitude', cmap='viridis')

    assert len(canvas.fig.axes) >= 2
    assert canvas.selected_index() == 0
```

- [ ] **Step 2: Add failing dynamic-range / freq-range test**

```python
def test_spectrogram_canvas_applies_dynamic_and_freq_range(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    # Magnitudes spanning ~120 dB.
    amp = np.array([[1e-6, 1e-3], [1e-3, 1.0], [1.0, 0.1]], dtype=np.float32)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2]),
        frequencies=np.array([10.0, 100.0, 200.0]),
        amplitude=amp,
        params=SpectrogramParams(fs=400.0, nfft=8, db_reference=1.0),
        channel_name='demo',
    )

    canvas.plot_result(
        result,
        amplitude_mode='amplitude_db',
        cmap='turbo',
        dynamic='60 dB',
        freq_range=(0.0, 150.0),
    )

    im = canvas._ax_spec.images[0]
    vmin, vmax = im.get_clim()
    assert (vmax - vmin) == 60.0          # dynamic="60 dB" applied
    assert canvas._ax_spec.get_ylim()[1] <= 150.0  # freq_range applied
```

- [ ] **Step 3: Add failing hover-readout test**

```python
def test_spectrogram_canvas_emits_cursor_info_on_hover(qtbot):
    import numpy as np
    from matplotlib.backend_bases import MouseEvent
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.0, 0.1, 0.2]),
        frequencies=np.array([0.0, 50.0, 100.0]),
        amplitude=np.ones((3, 3), dtype=np.float32),
        params=SpectrogramParams(fs=200.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')
    canvas.draw()

    seen = []
    canvas.cursor_info.connect(seen.append)

    # Synthesize hover at data coords (t=0.1, f=50).
    ax = canvas._ax_spec
    x_pix, y_pix = ax.transData.transform((0.1, 50.0))
    evt = MouseEvent('motion_notify_event', canvas, x_pix, y_pix)
    evt.inaxes = ax
    evt.xdata = 0.1
    evt.ydata = 50.0
    canvas._on_motion(evt)

    assert seen, "cursor_info should fire on hover"
    assert '0.1' in seen[-1] or 't=0.1' in seen[-1]
```

- [ ] **Step 4: Implement plot_result with vmin/vmax/ylim and the lazy dB cache**

```python
def plot_result(self, result, amplitude_mode='amplitude_db', cmap='turbo',
                dynamic='80 dB', freq_range=None):
    self.clear()
    self._result = result
    self._amplitude_mode = amplitude_mode
    self._cmap = cmap
    self._dynamic = dynamic
    self._freq_range = freq_range
    self._selected_index = 0

    gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.28)
    self._ax_spec = self.fig.add_subplot(gs[0, 0])
    self._ax_slice = self.fig.add_subplot(gs[1, 0])

    z = self._display_matrix(result, amplitude_mode)
    extent = [result.times[0], result.times[-1],
              result.frequencies[0], result.frequencies[-1]]
    vmin, vmax = self._color_limits(z, amplitude_mode, dynamic)
    im = self._ax_spec.imshow(
        z,
        origin='lower',
        aspect='auto',
        extent=extent,
        cmap=cmap,
        interpolation='nearest',
        vmin=vmin,
        vmax=vmax,
    )
    self._colorbar = self.fig.colorbar(im, ax=self._ax_spec, pad=0.01)
    self._ax_spec.set_xlabel('Time (s)')
    self._ax_spec.set_ylabel('Frequency (Hz)')
    if freq_range is not None:
        lo, hi = freq_range
        if hi <= 0 or hi <= lo:
            hi = float(result.frequencies[-1])
        self._ax_spec.set_ylim(lo, hi)
    self._cursor_line = self._ax_spec.axvline(result.times[0], color='#ffffff', lw=1.2)
    self._plot_slice()
    self.fig.tight_layout()
    self.draw_idle()

def _color_limits(self, z, amplitude_mode, dynamic):
    zmax = float(np.nanmax(z))
    if amplitude_mode == 'amplitude_db':
        if dynamic == '80 dB':
            return zmax - 80.0, zmax
        if dynamic == '60 dB':
            return zmax - 60.0, zmax
        # Auto -> let matplotlib pick from data
        return float(np.nanmin(z)), zmax
    # Linear amplitude — Auto / Min / Max maps to imshow defaults.
    return float(np.nanmin(z)), zmax

def _display_matrix(self, result, amplitude_mode):
    if amplitude_mode == 'amplitude_db':
        ref = float(result.params.db_reference)
        cache_key = (id(result), ref)
        if self._db_cache is None or self._db_cache[0] != cache_key:
            from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
            db = SpectrogramAnalyzer.amplitude_to_db(
                result.amplitude, ref
            ).astype(np.float32, copy=False)
            self._db_cache = (cache_key, db)
        return self._db_cache[1]
    return result.amplitude

def _plot_slice(self):
    self._ax_slice.clear()
    if self._result is None or self._selected_index is None:
        return
    z = self._display_matrix(self._result, self._amplitude_mode)
    y = z[:, self._selected_index]
    self._ax_slice.plot(self._result.frequencies, y, color=PRIMARY, lw=1.0)
    self._ax_slice.set_xlabel('Frequency (Hz)')
    self._ax_slice.set_ylabel(
        'Amplitude dB' if self._amplitude_mode == 'amplitude_db' else 'Amplitude'
    )
    self._ax_slice.grid(True, color=GRID_LINE, alpha=0.78, ls='--', lw=0.7)
    if self._freq_range is not None:
        lo, hi = self._freq_range
        if hi > 0 and hi > lo:
            self._ax_slice.set_xlim(lo, hi)
```

- [ ] **Step 5: Add click selection and hover handlers**

```python
def __init__(self, parent=None):
    # ... existing init ...
    self.mpl_connect('button_press_event', self._on_click)
    self.mpl_connect('motion_notify_event', self._on_motion)

def _on_click(self, event):
    if self._result is None or event.inaxes is not getattr(self, '_ax_spec', None):
        return
    if event.xdata is None:
        return
    idx = int(np.argmin(np.abs(self._result.times - event.xdata)))
    self.select_time_index(idx)

def select_time_index(self, idx):
    if self._result is None:
        return
    idx = max(0, min(int(idx), len(self._result.times) - 1))
    self._selected_index = idx
    if hasattr(self, '_cursor_line'):
        x = float(self._result.times[idx])
        self._cursor_line.set_xdata([x, x])
    self._plot_slice()
    self.draw_idle()

def _on_motion(self, event):
    if self._result is None or event.inaxes is not getattr(self, '_ax_spec', None):
        self.cursor_info.emit('')
        return
    if event.xdata is None or event.ydata is None:
        return
    t_idx = int(np.argmin(np.abs(self._result.times - event.xdata)))
    f_idx = int(np.argmin(np.abs(self._result.frequencies - event.ydata)))
    z = self._display_matrix(self._result, self._amplitude_mode)
    val = float(z[f_idx, t_idx])
    unit = 'dB' if self._amplitude_mode == 'amplitude_db' else (self._result.unit or '')
    self.cursor_info.emit(
        f"t={self._result.times[t_idx]:.4g} s · "
        f"f={self._result.frequencies[f_idx]:.4g} Hz · "
        f"{val:.4g} {unit}".rstrip()
    )
```

- [ ] **Step 6: Run canvas tests → pass**

```bash
pytest tests/ui/test_chart_stack.py -v
```

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_chart_stack.py
git commit -m "feat: render fft vs time spectrogram canvas with hover and dynamic range"
```

---

### Task 6: MainWindow Synchronous Compute Path with Cache

This task runs entirely on the main thread. Task 7 wraps the compute
in a worker. Splitting the two reduces flake risk while bringing up
end-to-end behavior.

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `mf4_analyzer/ui/inspector.py` (signal relays)
- Test: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Add cache-key test (display-only fields ignored)**

```python
def test_fft_time_cache_key_ignores_display_only_options(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    base = dict(
        fid='f1', channel='ch', time_range=(0.0, 1.0),
        fs=1000.0, nfft=2048, window='hanning', overlap=0.75,
        remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude_db', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )
    changed = dict(base, amplitude_mode='amplitude', cmap='gray',
                   dynamic='60 dB', freq_auto=False, freq_min=10.0, freq_max=2000.0)

    assert win._fft_time_cache_key(base) == win._fft_time_cache_key(changed)
```

- [ ] **Step 2: Add cache state and helpers**

In `MainWindow.__init__`, after existing state fields:

```python
self._fft_time_cache = OrderedDict()
self._fft_time_cache_capacity = 12
```

Methods:

```python
def _fft_time_cache_key(self, params):
    # Only the compute-relevant subset participates.
    return (
        params.get('fid'),
        params.get('channel'),
        tuple(params.get('time_range') or (None, None)),
        float(params.get('fs')),
        int(params.get('nfft')),
        str(params.get('window')),
        float(params.get('overlap')),
        bool(params.get('remove_mean')),
        float(params.get('db_reference', 1.0)),
    )

def _fft_time_cache_get(self, key):
    if key not in self._fft_time_cache:
        return None
    value = self._fft_time_cache.pop(key)
    self._fft_time_cache[key] = value
    return value

def _fft_time_cache_put(self, key, result):
    if key in self._fft_time_cache:
        self._fft_time_cache.pop(key)
    self._fft_time_cache[key] = result
    while len(self._fft_time_cache) > self._fft_time_cache_capacity:
        self._fft_time_cache.popitem(last=False)
```

- [ ] **Step 3: Run cache-key test → pass**

- [ ] **Step 4: Wire inspector relay signals**

In `MainWindow._connect()`:

```python
self.inspector.fft_time_requested.connect(lambda: self.do_fft_time(force=False))
self.inspector.fft_time_force_requested.connect(lambda: self.do_fft_time(force=True))
self.inspector.fft_time_export_full_requested.connect(lambda: self._copy_fft_time_image('full'))
self.inspector.fft_time_export_main_requested.connect(lambda: self._copy_fft_time_image('main'))
```

In `inspector.py`, define and relay the matching signals from
`fft_time_ctx`.

- [ ] **Step 5: Implement signal-extraction helper**

Verify the existing `FileData` shape in this repo before relying on
`fd.df`, `fd.time_array`, `fd.units`. If any attribute name differs,
adapt the helper:

```python
def _get_fft_time_signal(self):
    data = self.inspector.fft_time_ctx.current_signal()
    if not data:
        return None, None, None, None, None
    fid, ch = data
    if fid not in self.files:
        return None, None, None, None, None
    fd = self.files[fid]
    if not hasattr(fd, 'df') or ch not in fd.df.columns:
        return None, None, None, None, None
    t = np.asarray(fd.time_array, dtype=float)
    sig = np.asarray(fd.df[ch].values, dtype=float)
    return fid, ch, t, sig, fd
```

- [ ] **Step 6: Implement synchronous `do_fft_time` (display options applied)**

```python
def do_fft_time(self, force=False):
    from ..signal import SpectrogramAnalyzer, SpectrogramParams
    fid, ch, t, sig, fd = self._get_fft_time_signal()
    if sig is None or len(sig) < 2:
        self.toast("请选择有效信号", "warning")
        return
    p = self.inspector.fft_time_ctx.get_params()
    if self.inspector.top.range_enabled():
        lo, hi = self.inspector.top.range_values()
        m = (t >= lo) & (t <= hi)
        t = t[m]; sig = sig[m]
        time_range = (float(lo), float(hi))
    else:
        time_range = (float(t[0]), float(t[-1]))
    key_params = dict(p, fid=fid, channel=ch, time_range=time_range)
    key = self._fft_time_cache_key(key_params)
    cached = None if force else self._fft_time_cache_get(key)
    if cached is not None:
        self._render_fft_time(cached, p)
        self.statusBar().showMessage(
            f"使用缓存结果 · {cached.metadata.get('frames', 0)} frames · NFFT {p['nfft']}"
        )
        return
    params = SpectrogramParams(
        fs=p['fs'], nfft=p['nfft'], window=p['window'],
        overlap=p['overlap'], remove_mean=p['remove_mean'],
        db_reference=p['db_reference'],
    )
    try:
        result = SpectrogramAnalyzer.compute(
            sig, t, params,
            channel_name=ch,
            unit=getattr(fd, 'units', {}).get(ch, '') if hasattr(fd, 'units') else '',
        )
    except Exception as e:
        # Old chart stays visible — never call canvas.clear() here.
        self.toast(str(e), "error")
        self.statusBar().showMessage(f"FFT vs Time 错误: {e}")
        return
    self._fft_time_cache_put(key, result)
    self._render_fft_time(result, p)
    self.statusBar().showMessage(
        f"FFT vs Time 完成 · {result.metadata.get('frames', 0)} frames"
    )

def _render_fft_time(self, result, p):
    freq_range = None
    if not p.get('freq_auto', True):
        lo = float(p.get('freq_min', 0.0))
        hi = float(p.get('freq_max', 0.0))
        freq_range = (lo, hi)
    self.canvas_fft_time.plot_result(
        result,
        amplitude_mode=p['amplitude_mode'],
        cmap=p['cmap'],
        dynamic=p['dynamic'],
        freq_range=freq_range,
    )
```

Use `self.statusBar()` (the QMainWindow accessor method), not
`self.statusBar` — confirm convention with neighboring code in
`main_window.py` and align.

- [ ] **Step 7: Add cache-hit smoke test**

```python
def test_fft_time_cache_hit_status(qtbot, monkeypatch):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake = SpectrogramResult(
        times=np.array([0.0, 0.1]),
        frequencies=np.array([0.0, 50.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='ch', metadata={'frames': 2, 'hop': 4, 'freq_bins': 2},
    )
    p = dict(
        fid='f1', channel='ch', fs=100.0, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
        time_range=(0.0, 0.1),
    )
    key = win._fft_time_cache_key(p)
    win._fft_time_cache_put(key, fake)

    # Stub _get_fft_time_signal and inspector.get_params to point at
    # this cached item so do_fft_time hits the cache branch.
    monkeypatch.setattr(win, '_get_fft_time_signal',
                        lambda: ('f1', 'ch', np.linspace(0, 0.1, 2),
                                 np.ones(2), object()))
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params', lambda: p)
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)

    win.do_fft_time(force=False)
    assert "使用缓存结果" in win.statusBar().currentMessage()
```

- [ ] **Step 8: Add failed-compute-keeps-old-chart test**

```python
def test_fft_time_failed_compute_keeps_old_chart(qtbot, monkeypatch):
    # ... build a MainWindow, plot a known result first via canvas_fft_time
    # ... then force do_fft_time to raise inside SpectrogramAnalyzer.compute
    # ... assert canvas._ax_spec.images is non-empty afterwards
    ...
```

(Keep the test concrete during implementation; the checklist line is
a placeholder to ensure it gets written and committed.)

- [ ] **Step 9: Run all UI smoke tests**

```bash
pytest tests/ui/test_main_window_smoke.py tests/ui/test_inspector.py tests/ui/test_chart_stack.py -v
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add mf4_analyzer/ui/main_window.py mf4_analyzer/ui/inspector.py tests/ui/test_main_window_smoke.py
git commit -m "feat: compute fft vs time synchronously with cache"
```

---

### Task 7: Move Compute to a Worker Thread

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Add finished-smoke test for the worker**

```python
def test_fft_time_worker_emits_finished(qtbot):
    import numpy as np
    from PyQt5.QtCore import QThread
    from mf4_analyzer.signal.spectrogram import SpectrogramParams
    from mf4_analyzer.ui.main_window import FFTTimeWorker

    fs = 1000.0
    nfft = 256
    t = np.arange(2048) / fs
    sig = np.sin(2 * np.pi * 100 * t)
    worker = FFTTimeWorker(sig, t, SpectrogramParams(fs=fs, nfft=nfft), 'ch', 'V')
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    results = []
    worker.finished.connect(results.append)
    worker.finished.connect(thread.quit)

    thread.start()
    thread.wait(5000)

    assert len(results) == 1
    assert results[0].amplitude.shape[1] > 0
```

- [ ] **Step 2: Add cancel-smoke test**

```python
def test_fft_time_worker_cancels(qtbot):
    import numpy as np
    from PyQt5.QtCore import QThread
    from mf4_analyzer.signal.spectrogram import SpectrogramParams
    from mf4_analyzer.ui.main_window import FFTTimeWorker

    fs = 1000.0
    nfft = 64
    n = 200_000  # many frames so cancel has time to fire
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 100 * t)
    worker = FFTTimeWorker(sig, t, SpectrogramParams(fs=fs, nfft=nfft, overlap=0.9), 'ch', 'V')
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    failures = []
    worker.failed.connect(failures.append)
    worker.failed.connect(thread.quit)

    thread.start()
    worker.cancel()
    thread.wait(5000)

    assert any('cancel' in f.lower() for f in failures)
```

- [ ] **Step 3: Implement worker**

In `mf4_analyzer/ui/main_window.py`:

```python
class FFTTimeWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, sig, t, params, channel_name, unit):
        super().__init__()
        self.sig = sig
        self.t = t
        self.params = params
        self.channel_name = channel_name
        self.unit = unit
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from ..signal import SpectrogramAnalyzer
        try:
            result = SpectrogramAnalyzer.compute(
                self.sig, self.t, self.params,
                self.channel_name, self.unit,
                progress_callback=self.progress.emit,
                cancel_token=lambda: self._cancelled,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)
```

- [ ] **Step 4: Wire `do_fft_time` to use the worker**

Replace the synchronous `try/except SpectrogramAnalyzer.compute` block
with:

- create `FFTTimeWorker`, move to `QThread`
- store `self._fft_time_thread = thread`, `self._fft_time_worker = worker`
- on `finished`: cache, render, status update, then quit/clean up
- on `failed`: toast + status, keep old chart
- if a worker is already running and the user clicks compute, either
  ignore or queue — Phase 1 ignores (status: "正在计算…")

The synchronous code path written in Task 6 stays as a fallback only
if the worker fails to start (it should not — keep one path).

- [ ] **Step 5: Run worker tests → pass**

```bash
pytest tests/ui/test_main_window_smoke.py::test_fft_time_worker_emits_finished tests/ui/test_main_window_smoke.py::test_fft_time_worker_cancels -v
```

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "feat: run fft vs time compute on a worker thread"
```

---

### Task 8: Cache Invalidation Hooks

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Identify the existing hook sites by inspection**

Grep `main_window.py` for the canonical hooks. Confirmed sites:

- `close_all` (around line 411) — clears all loaded files.
- `_on_close_all_requested` (around line 273) — UI dispatcher.
- File-load path that emits `canvas_time.invalidate_envelope_cache("file loaded")` (around line 372).
- Time-axis rebuild via `_show_rebuild_popover` → `fd.rebuild_time_axis(new_fs)` (around lines 213-219).
- Custom-x change path (around line 331).

If a single-file close path is missing, add an explicit hook before
the file is removed from `self.files`.

- [ ] **Step 2: Add invalidation calls**

In each of the five sites above, add:

```python
self._fft_time_cache.clear()
```

For the `rebuild_time_axis` and per-file paths, prefer a targeted
clear:

```python
self._fft_time_cache_clear_for_fid(fid)
```

with helper:

```python
def _fft_time_cache_clear_for_fid(self, fid):
    keys = [k for k in self._fft_time_cache if k[0] == fid]
    for k in keys:
        self._fft_time_cache.pop(k, None)
```

- [ ] **Step 3: Add tests**

```python
def test_fft_time_cache_clears_on_close_all(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._fft_time_cache[('f1', 'ch', (0, 1), 1000.0, 8, 'hanning', 0.5, True, 1.0)] = object()
    win.close_all()
    assert len(win._fft_time_cache) == 0


def test_fft_time_cache_clears_for_fid_on_rebuild(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._fft_time_cache[('f1', 'ch', (0, 1), 1000.0, 8, 'hanning', 0.5, True, 1.0)] = object()
    win._fft_time_cache[('f2', 'ch', (0, 1), 1000.0, 8, 'hanning', 0.5, True, 1.0)] = object()
    win._fft_time_cache_clear_for_fid('f1')
    assert all(k[0] != 'f1' for k in win._fft_time_cache)
    assert any(k[0] == 'f2' for k in win._fft_time_cache)
```

- [ ] **Step 4: Run tests → pass**

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_main_window_smoke.py
git commit -m "feat: invalidate fft vs time cache on file/timebase changes"
```

---

### Task 9: Export Controls

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: Add export-pixmap test**

```python
def test_spectrogram_canvas_export_pixmaps(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2]),
        frequencies=np.array([10.0, 20.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')

    assert not canvas.grab_full_view().isNull()
    assert not canvas.grab_main_chart().isNull()
```

- [ ] **Step 2: Implement pixmap helpers**

`grab_full_view` returns the whole canvas. `grab_main_chart` should
return only the spectrogram + colorbar region. If axis-bbox cropping
is fragile under pytest-qt headless, return `self.grab()` in Phase 1
and document the limitation in the validation report.

- [ ] **Step 3: Implement clipboard copy on MainWindow**

```python
def _copy_fft_time_image(self, mode='full'):
    from PyQt5.QtWidgets import QApplication
    if not self.canvas_fft_time.has_result():
        self.toast("尚无 FFT vs Time 结果可导出", "warning")
        return
    if mode == 'main':
        pix = self.canvas_fft_time.grab_main_chart()
        msg = "已复制 FFT vs Time 主图"
    else:
        pix = self.canvas_fft_time.grab_full_view()
        msg = "已复制 FFT vs Time 完整视图"
    QApplication.clipboard().setPixmap(pix)
    self.statusBar().showMessage(msg, 2000)
    self.toast(msg, "success")
```

- [ ] **Step 4: Run tests → pass**

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/canvases.py mf4_analyzer/ui/main_window.py tests/ui/test_chart_stack.py
git commit -m "feat: export fft vs time charts to clipboard"
```

---

### Task 10: End-to-End Verification and Validation Report

**Files:**
- Create: `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`

- [ ] **Step 1: Run algorithm tests**

```bash
pytest tests/test_fft_amplitude_normalization.py tests/test_spectrogram.py tests/test_signal_no_gui_import.py -v
```

- [ ] **Step 2: Run UI tests**

```bash
pytest tests/ui/ -v
```

- [ ] **Step 3: Run full suite**

```bash
pytest -v
```

Document any pre-existing unrelated failure with exact test names and
trace summary.

- [ ] **Step 4: Manual smoke**

```bash
python -m mf4_analyzer.app
```

(Confirm the package entrypoint name from `pyproject.toml` /
`mf4_analyzer/__main__.py` if this command fails. Do **not** copy
entrypoints from other repos.)

Manual checks:

- App launches.
- Top toolbar shows `FFT vs Time`.
- Compute button is disabled until a signal candidate is selected.
- Loading an MF4/XLSX file populates the FFT vs Time signal selector.
- Clicking `计算时频图` renders a spectrogram and bottom slice.
- Hovering the spectrogram updates the cursor read-out (status text /
  cursor info pane).
- Clicking moves the vertical cursor and updates the bottom FFT.
- Changing `Amplitude` ↔ `Amplitude dB`, color map, or dynamic range
  re-renders without recomputing (status: cache hit).
- `强制重算` recomputes.
- Closing the file and reopening clears the cache.
- Both export buttons copy non-empty images to the clipboard.
- A request that exceeds the 64 MB ceiling is rejected with a clear
  message; old chart stays visible.

- [ ] **Step 5: Create validation report**

Create `docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md`
with the structure below, filled with actual command output, sample
files, and observations from this run:

```markdown
# FFT vs Time 2D Validation Report

**Date:** 2026-04-25
**Spec:** `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`
**Plan:** `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`

## Automated Tests

- Algorithm and signal import tests: <command, exit code, failures>
- UI focused tests: <command, exit code, failures>
- Full test suite: <command, exit code, failures>

## Real Data Checks

| File | Channel | Params | Result | Notes |
|------|---------|--------|--------|-------|

## Manual UI Checks

- FFT vs Time mode appears: <yes/no>
- Compute button disabled without signal: <yes/no>
- Compute button renders spectrogram: <yes/no>
- Hover updates cursor read-out: <yes/no>
- Click updates bottom slice: <yes/no>
- Display-only changes hit cache: <yes/no>
- Force recompute works: <yes/no>
- Close-file invalidates cache: <yes/no>
- Memory ceiling rejection works: <yes/no>
- Full export works: <yes/no>
- Main export works: <yes/no>

## External Comparison Notes

Differences vs. HEAD / MATLAB / scipy explained in terms of window,
scaling, reference, frame time, or frequency range.

## Known Limitations

- No 3D waterfall in Phase 1.
- No multi-channel subplot in Phase 1.
- No PSD `/Hz` display in Phase 1.
- No HDF input in Phase 1.
- No display-layer downsampling in Phase 1 (memory ceiling instead).
- No UI cancel button in Phase 1 (worker.cancel() API in place for future).
```

Confirm the report contains real observations for at least one MF4 or
XLSX file before closing this step.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/reports/2026-04-25-fft-vs-time-2d-validation.md
git commit -m "docs: validate fft vs time 2d"
```

---

## Self-Review Checklist for Executor

Before marking complete, verify:

- [ ] `Amplitude` and `Amplitude dB` share the same cached linear amplitude result; switching modes does not recompute.
- [ ] No PSD UI appears.
- [ ] `SpectrogramAnalyzer` imports no PyQt or matplotlib.
- [ ] Non-uniform time axis is rejected with a clear error.
- [ ] Window helper is shared between FFT and spectrogram and routed through `scipy.signal.get_window`.
- [ ] Cursor readout (hover) and bottom slice (click) use full-resolution result data.
- [ ] FFT vs Time computes only after button click or force recompute.
- [ ] Cache hit is visible in status text.
- [ ] Old chart remains visible after a failed recompute.
- [ ] Compute button is disabled until a signal candidate is set.
- [ ] Dynamic range and freq range actually constrain the canvas (vmin/vmax/ylim assertions in tests).
- [ ] Worker has finished and cancel smoke tests.
- [ ] Cache is invalidated on close-all, single-file close, time-axis rebuild, custom-x change, and file-load paths.
- [ ] `MainWindow.canvas_fft_time` resolves to the same widget as `chart_stack.canvas_fft_time`.
- [ ] Memory ceiling rejection fires above 64 MB.
- [ ] HDF, 3D, subplot, streaming, display-layer downsampling, and UI cancel button are explicitly **not** introduced in Phase 1.

---

## Plan v2 changes (post-review)

This plan supersedes the original 2026-04-25 draft. Concrete changes:

- **A1 Canvas promotion** — Task 3 Step 9 now adds
  `self.canvas_fft_time = self.chart_stack.canvas_fft_time` and Task 3
  Step 9 has a smoke test that catches a missing promotion.
- **A2 Dynamic range / A3 Freq range** — Task 5 Step 2 adds an
  explicit test for vmin/vmax and ylim, and Step 4 implements
  `_color_limits` and freq_range wiring; Task 6 Step 6 plumbs them
  through `do_fft_time` → `_render_fft_time`.
- **A4 Hover readout** — Task 5 Step 3 + Step 5 add `motion_notify_event`
  with a `cursor_info` signal and a synthesized-event test.
- **A5 Worker** — Task 7 is a dedicated task with finished and cancel
  pytest-qt smokes.
- **A6 DC/Nyquist normalization** — Task 1 Step 1 audits existing
  tests and Step 3 documents the corrected (non-doubling) behavior.
- **A7 App entrypoint** — Task 10 Step 4 uses `mf4_analyzer.app` only;
  the stale `epsloadpath.ui.app` reference is gone.
- **A8 scipy** — Task 1 Step 3 routes the window helper through
  `scipy.signal.get_window`; design §12 makes scipy load-bearing.
- **B2 Cache invalidation** — Task 8 lists the five hook sites by
  approximate line number and adds tests.
- **B3 Memory ceiling** — Task 2 Step 3 implements the 64 MB rejection
  and a unit test (`test_memory_ceiling_blocks_oversized_request`).
- **B4 Disable button / failed-keep-old-chart** — Task 4 Step 3 and
  Task 6 Step 8 add the missing tests and ensure the implementation
  matches.
- **B5 Cache-hit status** — Task 6 Step 7 adds the test.
- **B6 Window preset test** — Task 2 Step 1 includes
  `test_window_preset_hann_and_flattop`.
- **C1 time_jitter_tolerance** — moved out of `SpectrogramParams`
  into `compute(...)` kwarg so cache key stability is preserved.
- **C2 Progress throttling** — Task 2 Step 3 throttles to ~50
  emissions per run.
- **C3 dB cache lives on the canvas** — Task 5 Step 4 adds a
  `_db_cache` keyed by `(id(result), db_reference)` and never mutates
  the result object.
- **C4 Preserve combo selection** — Task 4 Step 2's
  `set_signal_candidates` reuses the previously-selected `(fid, ch)`
  if it is still in the new list.

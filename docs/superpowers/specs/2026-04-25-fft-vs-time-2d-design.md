# FFT vs Time 2D Spectrogram — Design Spec

**Date:** 2026-04-25
**Author:** collaborative brainstorm with user
**Status:** revised 2026-04-25 after first plan review (see notes at the end)
**Related demo:** `docs/fft-vs-time-ui-demo.html`
**Brainstorm record:** `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-brainstorm.md`

## 1. Goal

Add a professional **FFT vs Time** analysis mode for offline MF4 and
Excel/XLSX signal files.

The feature answers:

> Which frequency components appear, disappear, or change level over time?

The first version should combine three qualities:

1. **Engineering usefulness:** fast enough for daily file-based diagnosis.
2. **Numeric discipline:** clear amplitude and dB definitions with tests.
3. **Report readiness:** exportable charts with readable color scale,
   cursor state, and parameter context.

The design follows the interaction style of professional analysis tools
such as HEAD ArtemiS: users choose a signal, set analysis parameters, click
compute, inspect the spectrogram, and use a selected time slice for detailed
FFT review.

## 2. Scope

### 2.1 Included in Phase 1

- New top-level mode: **FFT vs Time**.
- Offline file-based analysis for existing MF4 and Excel/XLSX data.
- Strict single-channel analysis selected inside the FFT vs Time panel.
- 2D spectrogram main chart.
- Bottom, always-visible time-slice FFT chart.
- Mouse/click cursor readout:
  - time
  - frequency
  - amplitude or amplitude dB
- Click-to-select time frame; selected frame drives the bottom FFT slice.
- `Amplitude` and `Amplitude dB` display modes.
- `dB re 1 unit` as the first-version dB reference.
- Hann diagnostic default plus Flat Top amplitude-accuracy preset.
- Automatic frequency-range suggestion plus user-lockable range presets.
- Color map and dynamic range controls.
- Result caching with visible cache-hit status.
- Low-visibility **force recompute** action.
- Export:
  - full analysis view: spectrogram + slice FFT + colorbar + summary
  - main chart only: spectrogram + colorbar
- Formal tests for algorithm correctness.
- Smoke tests for UI integration.
- Real MF4/XLSX engineering validation report.
- `scipy` as a formal project dependency for signal-processing foundations.

### 2.2 Explicitly Excluded from Phase 1

- 3D waterfall.
- Multi-channel subplot.
- Live/streaming acquisition.
- HDF input.
- PSD UI or `/Hz` display.
- Claims of exact parity with HEAD ArtemiS.
- Automatic recompute when parameters change.

HDF can be added later at the data-ingestion layer. The FFT vs Time
analysis layer should not depend on whether the source is MF4, XLSX, or a
future HDF loader.

## 3. Existing Baseline

Current project shape:

- UI: PyQt5.
- Plotting: matplotlib.
- Numeric compute: numpy.
- Existing FFT code: `mf4_analyzer/signal/fft.py`.
- Existing main-window FFT entrypoint: `MainWindow.do_fft`.
- Existing top modes: `time`, `fft`, `order`.

Existing FFT behavior:

```text
selected signal range -> window -> FFT -> frequency x amplitude
```

Existing averaged FFT behavior:

```text
signal -> split into frames -> FFT per frame -> average frames
```

The new FFT vs Time behavior keeps every frame:

```text
signal -> split into frames -> FFT per frame -> time x frequency x amplitude
```

## 4. Architecture

Do not extend `MainWindow.do_fft()` into a large mixed-purpose function.
Create a separate analysis chain:

```text
DataLoader / FileData
    ↓
unified signal extraction: time, signal, fs, unit, metadata
    ↓
SpectrogramAnalyzer
    ↓
SpectrogramResult
    ↓
SpectrogramCanvas / ChartStack
    ↓
FFTTimeContextual inspector panel
```

### 4.1 New Signal Module

Create:

```text
mf4_analyzer/signal/spectrogram.py
```

Core objects:

```python
@dataclass(frozen=True)
class SpectrogramParams:
    fs: float
    nfft: int                        # any positive integer; UI offers powers of 2
    window: str = 'hanning'
    overlap: float = 0.5             # 0 <= overlap < 1
    remove_mean: bool = True
    db_reference: float = 1.0

@dataclass
class SpectrogramResult:
    times: np.ndarray
    frequencies: np.ndarray
    amplitude: np.ndarray            # linear, float32, shape (freq_bins, frames)
    params: SpectrogramParams
    channel_name: str
    unit: str = ''
    metadata: dict = field(default_factory=dict)
```

`SpectrogramAnalyzer.compute(...)` must be independent of PyQt and
matplotlib so it can be tested without GUI startup.

**Display-only fields are NOT in `SpectrogramParams`:**

- `amplitude_mode` (`Amplitude` vs `Amplitude dB`) — display-only, derived
  from cached linear amplitude on the canvas, never triggers recompute.
- `cmap`, dynamic range, frequency range — display-only, applied by the
  canvas, never triggers recompute.
- `time_jitter_tolerance` — passed as a kwarg to
  `SpectrogramAnalyzer.compute(..., time_jitter_tolerance=1e-3)` so it
  does not pollute the cache key. Default `1e-3`.

**dB matrix is NOT cached on the result.** The canvas computes it lazily
and keeps it on its own internal cache (keyed by `id(result)` and
`db_reference`). This keeps `SpectrogramResult` stable across display-mode
changes.

### 4.2 UI Additions

Add:

```text
FFTTimeContextual
SpectrogramCanvas
ChartStack fourth card
Toolbar fourth mode button
MainWindow.do_fft_time()
```

`ChartStack` mode mapping becomes conceptually:

```python
{
    "time": 0,
    "fft": 1,
    "fft_time": 2,
    "order": 3,
}
```

Names can be adjusted during implementation, but one stable internal mode
key must be used across toolbar, chart stack, inspector, and tests.

## 5. Computation Definition

Phase 1 exposes only:

```text
Amplitude
Amplitude dB
```

It does not expose PSD.

### 5.1 Frame Construction

For a signal `x`:

1. Validate `fs > 0`.
2. Validate `len(x) >= nfft`.
3. Compute `hop = int(nfft * (1 - overlap))`.
4. Validate `hop > 0`.
5. Split into complete frames only for Phase 1.
6. Frame time is the center of each FFT block:

```text
time_center = time[start] + (nfft - 1) / (2 * fs)
```

The analysis math assumes uniformly sampled data. Phase 1 must check the
selected signal's effective time base before computing:

```text
dt = diff(time)
nominal_dt = 1 / fs
relative_jitter = max(abs(dt - nominal_dt)) / nominal_dt
```

Acceptance rule:

- `relative_jitter <= 1e-3`: treat as uniformly sampled and use `fs`.
- `relative_jitter > 1e-3`: reject the compute with a clear message asking
  the user to rebuild/resample the time axis before FFT vs Time.

This avoids silently using a nominal `fs` on uneven timestamps. Future HDF or
advanced MF4 work may add resampling, but Phase 1 does not resample inside
the spectrogram analyzer.

### 5.2 Window and FFT

For each frame:

1. Optionally subtract the frame mean.
2. Multiply by selected window.
3. Compute one-sided `rfft`.
4. Convert to one-sided amplitude:
   - divide by `nfft`
   - divide by window coherent gain
   - multiply non-DC and non-Nyquist bins by 2
5. Store result in a matrix shaped:

```text
frequency_bins x time_frames
```

Window generation must not drift from existing FFT behavior. Phase 1 should
centralize window construction behind one app-owned helper used by both
`FFTAnalyzer` and `SpectrogramAnalyzer`.

Accepted first-version names:

```text
hanning | hann
hamming
blackman
bartlett
kaiser
flattop
```

The helper must define whether each window is symmetric or FFT-periodic. To
preserve current `FFTAnalyzer` equivalence, Phase 1 should use symmetric
windows for compatibility unless the implementation explicitly updates
both FFT and spectrogram tests to a new shared policy. `scipy.signal`
windows may be used internally, but only through this app-owned helper.

The app's analyzer owns amplitude normalization and labels; scipy defaults
must not become user-facing definitions by accident.

### 5.3 dB Definition

```text
Amplitude dB = 20 * log10(max(amplitude, eps) / db_reference)
```

First-version default:

```text
db_reference = 1.0
label = "dB re 1 unit"
```

Future work may infer reference values from channel units, but Phase 1 does
not guess sensor-specific references.

## 6. UI Design

### 6.1 Top Toolbar

Mode switcher:

```text
时域 | FFT | FFT vs Time | 阶次
```

### 6.2 Right Inspector Panel

Use a dedicated FFT vs Time panel rather than reusing the existing FFT
panel.

Recommended groups:

```text
分析信号
- 通道
- Fs
- 重建时间轴

时频参数
- FFT 点数
- 窗函数
- 重叠率
- 去均值

幅值
- Amplitude / Amplitude dB
- dB reference: 1 unit

范围与色标
- 频率范围: 自动 / 手动锁定
- 动态范围: 60 dB / 80 dB / Auto
- 色图: Turbo / Viridis / Gray

预设
- 诊断模式
- 幅值精度
- 高频细节
- 用户自定义预设

操作
- 计算时频图
- 强制重算
- 导出完整视图
- 导出主图
```

### 6.3 Center Canvas

Use the user-approved layout:

```text
┌─────────────────────────────────────────┐
│ 2D spectrogram + colorbar               │
│ selected time cursor as vertical line   │
├─────────────────────────────────────────┤
│ selected time-slice FFT                 │
└─────────────────────────────────────────┘
```

The bottom slice is always visible in Phase 1. It updates when the user
clicks or otherwise selects a spectrogram time frame.

### 6.4 Interaction

- Clicking a spectrogram time frame selects the nearest frame.
- The main chart shows a vertical cursor at selected time.
- The bottom chart displays that frame's amplitude spectrum.
- Mouse move readout shows nearest time/frequency/value.
- Status bar shows compute/cached/error states.
- Export full view includes:
  - spectrogram
  - colorbar
  - selected time cursor
  - bottom slice FFT
  - compact parameter summary
- Export main chart includes:
  - spectrogram
  - colorbar
  - selected time cursor

## 7. Presets

Presets save both analysis parameters and display choices.

Initial built-ins:

### 7.1 诊断模式

- Window: Hann
- NFFT: 2048
- Overlap: 75%
- Mode: Amplitude dB
- Frequency range: auto
- Dynamic range: 80 dB
- Color map: Turbo or Viridis

### 7.2 幅值精度

- Window: Flat Top
- NFFT: 4096
- Overlap: 75%
- Mode: Amplitude
- Frequency range: auto or user locked
- Dynamic range: Auto

### 7.3 高频细节

- Window: Hann
- NFFT: 4096 or 8192
- Overlap: 50%
- Mode: Amplitude dB
- Frequency range: auto
- Dynamic range: 60 dB

Exact default values can be adjusted during implementation after trying the
real sample files, but the three preset concepts should remain.

Dynamic range controls apply directly to `Amplitude dB`. In linear
`Amplitude` mode, the same UI area should switch to linear color limits
(`Auto`, `Min`, `Max`) rather than showing `60 dB / 80 dB` labels.

## 8. Cache Design

Cache stores computed spectrogram results, not visual-only states.

Cache key includes:

```text
file_id or data_id
channel_name
time_range
fs
nfft
window
overlap
remove_mean
db_reference
```

`Amplitude` vs `Amplitude dB` is a display selection, not a recompute trigger.
The cached result stores linear amplitude. `Amplitude dB` is derived from the
cached amplitude and `db_reference`. Changing only the displayed amplitude
mode should redraw, not recompute.

Cache hit:

```text
使用缓存结果 · <frames> frames · NFFT <nfft>
```

Force recompute bypasses cache and replaces the cached result.

### 8.1 Cache Invalidated By

- File close.
- Close all.
- Channel data mutation.
- Time-axis rebuild.
- Sampling rate change.
- Any future channel-edit operation that changes raw samples or units.

### 8.2 Cache Not Invalidated By

- Color map change.
- Dynamic range change.
- Frequency display range change.
- Selected time slice.
- Export mode.

## 9. Performance Strategy

- No automatic recompute when parameters change.
- Compute only after clicking **计算时频图**.
- Run compute in a worker thread.
- Keep old chart visible if a new compute fails.
- Show progress for long inputs.
- Allow cancellation for long-running compute.
- The signal-layer compute API should accept optional progress and
  cancellation hooks without depending on PyQt:

```python
progress_callback: Callable[[int, int], None] | None
cancel_token: Callable[[], bool] | None
```

  `progress_callback` receives `(current_frame, total_frames)`. It must be
  called from the worker context; any Qt signal emission or UI update belongs
  in the worker wrapper, not inside `SpectrogramAnalyzer`.
- Use `float64` internally where helpful for numeric stability.
- Store/render amplitude matrices as `float32` unless tests show a reason
  to keep `float64`.
- Use matplotlib `imshow` in Phase 1 with the full-resolution matrix.
- Display-layer downsampling for very large matrices is **deferred to a
  future phase** — Phase 1 trusts that the typical workload stays under
  ~2 MB matrices (see §6 of the brainstorm). If a real file blows past a
  configured ceiling, the pre-flight memory check in §10 refuses the
  compute instead of silently downsampling.
- Cursor readouts and selected time-slice FFT use the full-resolution
  `SpectrogramResult`.
- Bottom time-slice FFT uses the selected spectrogram frame, not a
  separate FFT recompute.

### 9.1 Worker Cancellation UI Surface

`SpectrogramAnalyzer.compute(..., cancel_token=...)` is wired
end-to-end (worker → analyzer) in Phase 1, but Phase 1 does **not** add
a user-visible cancel button. Long-running compute is rare for the
target file sizes; if a future profile shows it is needed, the cancel
hook is already in place to add a button without a re-architecture.

The worker emits `progress(current_frame, total_frames)`. To avoid Qt
queue saturation, the worker **throttles** progress emission to roughly
every 2% of total frames (or every 50 frames, whichever is rarer).

## 10. Error Handling

Handle these cases explicitly:

| Case | Behavior |
|------|----------|
| No file / no channel | Disable compute or show "请选择信号" |
| `fs <= 0` | Ask user to rebuild/check time axis |
| Signal length `< nfft` | Show "数据长度不足以完成当前 NFFT" |
| Invalid overlap / hop <= 0 | Reject parameter and keep previous result |
| Frame count / memory estimate exceeds ceiling | Block compute with estimated frame count and MB. Phase 1 ceiling: 64 MB for the float32 amplitude matrix (≈16 M cells, e.g. 2048-bin × 8000-frame). Below that the compute proceeds without warning. |
| Non-uniform time axis | Require rebuild/resample before analysis |
| Compute exception | Keep old chart, show error in status/toast/dialog |
| Cache hit | Show cache status without pretending recompute occurred |

## 11. Testing Plan

### 11.1 Algorithm Unit Tests

Add focused tests for `mf4_analyzer/signal/spectrogram.py`:

- `test_spectrogram_bin_aligned_tone_amplitude`
- `test_spectrogram_two_tone_frequency_bins`
- `test_spectrogram_burst_time_localization` (fixture documents the
  amplitude threshold so future NFFT/overlap edits stay non-flaky)
- `test_spectrogram_db_conversion`
- `test_spectrogram_frame_center_times`
- `test_spectrogram_rejects_signal_shorter_than_nfft`
- `test_spectrogram_rejects_nonuniform_time_axis`
- `test_spectrogram_window_preset_hann_and_flattop` (locks the
  shared `get_analysis_window` helper for both presets — guards against
  silent regression to a hann-only helper)
- `test_spectrogram_memory_ceiling_blocks_oversized_request` (covers
  the §10 memory-ceiling rejection)
- `test_signal_spectrogram_import_has_no_gui_dependencies` (lives in
  the existing `tests/test_signal_no_gui_import.py` — extended)

### 11.2 Existing FFT Cross-Validation

For the same frame, NFFT, window, and amplitude definition:

- Spectrogram slice should match the shared FFT amplitude logic.
- If implementation keeps separate code paths, tests must lock their
  equivalence.

Preferred implementation detail: factor shared one-sided amplitude
normalization so FFT and spectrogram cannot drift silently.

### 11.3 UI Smoke Tests

Add UI tests for:

- Toolbar exposes fourth `FFT vs Time` mode.
- `ChartStack` contains spectrogram card and `MainWindow.canvas_fft_time`
  resolves to the same widget (catches the canvas-promotion gap from
  the first plan review).
- `Inspector` switches to FFTTimeContextual.
- Compute button is **disabled until a valid signal candidate is
  selected**, and re-enables when one is set.
- Parameter getters return expected types.
- Display-only changes (`amplitude_mode`, `cmap`, dynamic range,
  frequency range) **do not** invalidate the cache: a second compute
  with the same compute-relevant params hits the cache and the status
  bar shows "使用缓存结果".
- A failing compute keeps the previous chart visible (assert that
  `_ax_spec` still has the prior image after the toast fires).
- Hover readout: a synthesized `motion_notify_event` over the
  spectrogram emits `cursor_info` with `time / frequency / amplitude`.
- Click selection: a synthesized `button_press_event` moves the cursor
  line and updates the bottom slice.
- `dynamic` and `freq_range` are actually applied to the canvas
  (vmin/vmax and ylim assertions).

### 11.4 Real Data Validation

Create a validation report after implementation:

```text
docs/superpowers/reports/YYYY-MM-DD-fft-vs-time-2d-validation.md
```

Use user-provided MF4/XLSX samples to check:

- Typical channels compute successfully.
- Automatic frequency range is reasonable.
- Selected time-slice FFT peak matches current FFT logic.
- Export full/main chart modes work.
- Any differences from HEAD or other external tools are explained by
  window, scaling, reference, or frame-time definitions.

## 12. Dependency Decision

Add `scipy` as a formal dependency in `requirements.txt`:

```text
scipy>=1.10
```

scipy is **load-bearing in Phase 1**, not aspirational:

- The shared `get_analysis_window(name, n)` helper in
  `mf4_analyzer/signal/fft.py` delegates to `scipy.signal.get_window`
  for `hanning|hamming|blackman|bartlett|kaiser|flattop`. The app keeps
  ownership of window-name normalization (`hann` → `hanning`), the
  `kaiser` `beta=14` default, and the symmetric/periodic policy. scipy
  only supplies the coefficient generation. This replaces the bespoke
  `flattop` polynomial in the current `fft.py`, removing one source of
  silent drift.
- A targeted unit test (§11.1
  `test_spectrogram_window_preset_hann_and_flattop`) locks the helper's
  output so a scipy upgrade cannot silently change normalization.

Future Order work will likely need `scipy.signal` interpolation,
resampling, filtering, anti-aliasing, and peak detection. Phase 1
already pays the dependency cost so Order does not need a separate
"add scipy" change later.

The app continues to own engineering labels and normalization. Raw
scipy defaults are never exposed as user-facing definitions without a
test.

## 13. Implementation Notes for Later Plan

The implementation plan should likely split into these work packages:

1. Add scipy dependency, route the shared window helper through
   `scipy.signal.get_window`, and audit `compute_fft` for the
   DC/Nyquist normalization correction.
2. Add `SpectrogramAnalyzer` with TDD (algorithm tests + non-uniform
   time-axis rejection + memory-ceiling rejection).
3. Add FFT vs Time UI mode plumbing (toolbar, chart-stack card,
   inspector panel selector, **and the
   `MainWindow.canvas_fft_time = self.chart_stack.canvas_fft_time`
   promotion**).
4. Build `FFTTimeContextual` controls and built-in presets.
5. Implement `SpectrogramCanvas` rendering — including dynamic-range
   vmin/vmax wiring, freq_range ylim wiring, click selection, and
   hover readout (`cursor_info`).
6. Wire `MainWindow.do_fft_time` synchronous path with cache + force
   recompute + cache-invalidation hooks across the file/timebase
   surface.
7. Add the worker-thread path with a focused pytest-qt smoke (finished)
   and a cancel smoke.
8. Add export controls and clipboard copy.
9. Real-data validation and report.

The plan is `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md`.

## 14. Revision Notes (2026-04-25)

This design file was revised after the first plan review. Material
changes from the original draft:

- `SpectrogramParams` no longer carries `amplitude_mode` or
  `time_jitter_tolerance`; both are display-only / call-time concerns.
- `SpectrogramResult` no longer carries a cached `amplitude_db`; the
  canvas owns dB derivation.
- §9 commits to the worker path with progress throttling and a code-only
  cancel hook (no UI cancel button in Phase 1).
- §9 explicitly defers display-layer downsampling; §10 introduces a
  hard 64 MB ceiling instead.
- §11.3 adds tests for canvas promotion, hover readout, dynamic-range
  /freq-range wiring, cache-on-display-change, and disabled-button
  state — these were the gaps that turned plan v1 into a "looks done
  but interactions broken" risk.
- §12 commits scipy to a load-bearing role (window helper) instead of
  treating it as a future hook.

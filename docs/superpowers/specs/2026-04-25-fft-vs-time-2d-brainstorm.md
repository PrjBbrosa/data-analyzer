# FFT vs Time 2D Spectrogram — Brainstorm Spec

**Date:** 2026-04-25
**Author:** collaborative brainstorm with user
**Status:** discussion record, not yet an implementation plan

## 1. User Decisions Captured

1. **Do not implement 3D for now.**
   Daily use should prioritize a precise, fast, readable 2D spectrogram
   rather than a visually impressive 3D waterfall.
2. **Accuracy must be controlled and explainable.**
   The implementation does not need to claim parity with HEAD ArtemiS, but
   numeric error must not be large or surprising. The app should expose clear
   analysis definitions instead of ambiguous labels.
3. **Pull selected Phase 2 features into Phase 1.**
   Include the following in the first implementation:
   - Cursor readout on the spectrogram.
   - Time-slice FFT view for the selected time frame.
   - Color/dynamic-range controls.
   - Export image.
   - Result caching.
   Exclude multi-channel subplot from Phase 1.

## 2. Product Goal

Add a new **FFT vs Time** analysis mode that answers:

> Which frequency components appear, disappear, or change level over time?

The first version should feel like a professional diagnostic tool rather
than a demo:

- Smooth interaction on typical MF4/CSV/Excel files.
- Clear engineering units and scaling.
- Predictable parameter controls.
- Useful cursor readouts.
- Ability to export the chart for reports.

## 3. Current Baseline

Current stack:

- UI: PyQt5
- Plotting: matplotlib
- Signal compute: numpy
- Existing FFT code: `mf4_analyzer/signal/fft.py`
- Existing FFT UI entrypoint: `MainWindow.do_fft`
- Current FFT behavior:
  - Single FFT: one selected time record becomes one amplitude spectrum.
  - Averaged FFT: many windowed segments are averaged into one spectrum.

The planned spectrogram differs from averaged FFT because it **keeps each
segment's FFT result as a time frame** instead of averaging all frames into
one curve.

## 4. Conceptual Difference

### Existing FFT

```text
signal[t0:t1] -> window -> FFT -> amplitude[f]
```

Result shape:

```text
frequency x amplitude
```

### Existing Averaged FFT

```text
signal -> split into frames -> window -> FFT per frame -> average frames
```

Result shape remains:

```text
frequency x averaged amplitude
```

### New FFT vs Time / Spectrogram

```text
signal -> split into frames -> window -> FFT per frame -> keep every frame
```

Result shape:

```text
time x frequency x amplitude
```

2D display maps:

```text
X = time
Y = frequency
Color = amplitude / power / dB
```

## 5. Accuracy Direction

The goal is not to imitate another tool's UI labels blindly. The goal is to
define the math precisely and test it.

### 5.1 Required Terms to Define

The implementation must define and document:

- `Amplitude`: one-sided amplitude spectrum with window coherent-gain
  correction.
- `Power`: squared amplitude or power spectrum, if exposed.
- `PSD`: true power spectral density only if normalized by sampling rate and
  window energy / ENBW.
- `dB`: reference value must be explicit. Initial default can be `dB re 1
  unit`, with future support for engineering references such as pressure or
  acceleration.
- `Frame time`: center of each FFT block, not block start, unless explicitly
  labelled otherwise.

### 5.2 Accuracy Tests Needed

At minimum:

1. **Bin-aligned pure tone amplitude test.**
   A sine wave exactly on an FFT bin should recover amplitude within a tight
   tolerance for supported windows.
2. **Off-bin tone sanity test.**
   Verify expected scalloping behavior, especially for Hann and Flat Top.
3. **Two-tone separation test.**
   Confirm two known tones appear at the correct frequency bins.
4. **Time-local burst test.**
   A burst active only between `t1` and `t2` should appear only in matching
   spectrogram frames.
5. **PSD normalization test, if PSD is exposed.**
   Do not label a value PSD unless the normalization is actually `/Hz`.

### 5.3 First-Version Recommendation

Expose only:

- `Amplitude`
- `Amplitude dB`

Defer strict PSD UI until normalization is fully tested. This avoids a
professional-looking but mathematically ambiguous output.

## 6. Performance Direction

2D spectrogram should be feasible with the current stack.

Example:

```text
240k samples, NFFT=2048, overlap=75%
hop = 512
frames ~= 465
freq bins ~= 1024
matrix ~= 465 x 1024
float32 memory ~= 1.8 MB
```

This is small enough for numpy compute and matplotlib `imshow`.

### 6.1 Main Risk

The UI will feel slow if the computation runs on the Qt main thread or if
every small parameter edit triggers a full recompute.

### 6.2 Required Performance Controls

- Compute in a worker thread.
- Show progress and allow cancellation for long files.
- Cache results by:
  - file/data id
  - channel
  - selected time range
  - sample rate
  - nfft
  - window
  - overlap
  - amplitude mode
- Use `float32` for rendered magnitude matrices unless tests prove precision
  needs `float64`.
- Render with `imshow` for Phase 1.
- Decimate only for rendering when the image exceeds practical pixel
  resolution; do not decimate the stored numeric result by default.

## 7. First Implementation Scope

### Included

1. New top-level mode: `FFT vs Time`.
2. New signal compute API:
   - `compute_spectrogram(...)`
   - returns frequencies, frame-center times, magnitude matrix, metadata.
3. Single-channel 2D spectrogram.
4. Cursor readout:
   - time
   - frequency
   - amplitude/dB at nearest bin
5. Time-slice FFT view:
   - selecting a time frame shows that frame's FFT curve.
   - likely implemented as a lower strip or collapsible detail panel.
6. Color controls:
   - color map
   - dynamic range
   - min/max or auto scale
7. Export image.
8. Cache for repeated parameter/view changes.
9. Basic precision tests.
10. UI smoke tests for the new mode.

### Excluded

- 3D waterfall.
- Multi-channel subplot.
- Live acquisition / streaming.
- HEAD-compatible certification claims.
- Strict PSD display unless normalization is completed and tested.

## 8. UI Direction

Top mode switch becomes:

```text
时域 | FFT | FFT vs Time | 阶次
```

Right inspector should switch to a dedicated **FFT vs Time** contextual
panel. It should not reuse the existing FFT panel wholesale, because the
spectrogram has different questions:

- time frame size
- overlap
- color scale
- dynamic range
- selected time slice
- display mode

Recommended right-panel groups:

1. **分析信号**
   - channel
   - Fs
   - optional rebuild-time button
2. **时频参数**
   - NFFT
   - window
   - overlap
   - detrend/remove mean
3. **幅值与单位**
   - amplitude / amplitude dB
   - dB reference
4. **显示**
   - colormap
   - dynamic range
   - frequency range
   - auto/manual color scale
5. **操作**
   - compute/update
   - export image

Central chart area:

```text
[navigation toolbar + cursor mode + export]

2D spectrogram
with colorbar

time-slice FFT strip
or a lower detail panel
```

## 9. Open Questions for Next Discussion

1. Should the spectrogram calculate only after clicking **计算时频图**, or
   auto-refresh after parameter edits with debounce?
2. Should the time-slice FFT be always visible below the spectrogram, or
   hidden behind a toggle to preserve vertical chart space?
3. What should the default y-axis frequency range be?
   - Full Nyquist
   - Auto energy cutoff
   - User-selected default such as 0-2400 Hz
4. Should dB default to `dB re 1 unit`, or should the app infer reference
   values from channel units when possible?
5. Should `Flat Top` be recommended for amplitude accuracy presets, while
   `Hann` remains the default for general spectrogram readability?

## 10. Demo Artifact

UI mockup:

```text
docs/fft-vs-time-ui-demo.html
```

This file is only a design/demo artifact. It is not part of the runtime app.

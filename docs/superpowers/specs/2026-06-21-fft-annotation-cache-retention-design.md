# FFT Annotation Snapping And Result Retention Design

## Problem

Two regressions are visible in the FFT analysis section:

1. Spectrum annotations do not snap to the point visually nearest the mouse. The FFT amplitude row currently chooses one sample per curve by nearest frequency, then chooses between curves with data-space Y distance. This differs from TimeDomain and fails when the nearest visible point is not the same as the nearest X sample.
2. A computed FFT spectrum can disappear after computing FFT-vs-Time and returning to FFT. The disappearing chart is caused by FFT mode re-entry deciding the FFT render signature changed, failing to restore from FFT cache, then rebuilding the time preview with `clear_spectrum=True`.

## Root Cause

### Annotation Snapping

`PgLineCanvas.add_remark_at('amp', x, y)` receives data coordinates and searches with `argmin(abs(freq - x))`. It does not retain the scene/viewport mouse position, so it cannot compare true screen distance. TimeDomain already projects candidate samples into scene coordinates and chooses the smallest pixel distance.

### FFT Result Retention

The FFT multi-source path writes computed results to `analysis_caches['fft']`. The legacy single-signal fallback only draws the spectrum and does not store a recoverable analysis-cache entry. While the app is in FFT-vs-Time, audio-source defaulting can also change `fft_ctx.combo_weighting` through `set_weighting_default()`, which changes the FFT render signature. On return to FFT, `_enter_fft_mode()` treats the FFT inputs as changed and tries to restore from cache. If the active FFT view has no matching cached sources, `_refresh_fft_time_preview()` runs with its default `clear_spectrum=True`, removing `_amp_curves`.

## Requirements

- FFT amplitude-row annotations must snap to the data point closest to the mouse in screen/scene space, matching TimeDomain semantics.
- The nearest-point search must remain efficient by limiting candidates around the clicked X range before projecting to scene coordinates.
- Existing public calls to `add_remark_at('amp', x, y)` must continue to work for tests and non-event callers, but mouse-driven annotation should use the scene position.
- Right-click deletion on the FFT amplitude row should use scene distance when invoked from a mouse position.
- A computed FFT result must stay visible after `FFT -> FFT-vs-Time compute -> FFT`, even when FFT-vs-Time selection or audio defaults change FFT display/compute controls.
- Switching sections must not silently recompute FFT. If FFT parameters changed and no cache hit exists, keep the visible spectrum and mark it stale rather than clearing it.
- The fix must not reintroduce the old PSD row or change FFT-vs-Time heatmap compute math.

## Design

### Screen-Space Spectrum Annotation

Add an amp-row helper in `PgLineCanvas` that accepts the original scene position and the mapped data position. For each spectrum entry:

- load finite `freq` and `amp` arrays;
- compute the clicked data X in the amp ViewBox;
- derive a small data-space X window from the visible X span and ViewBox pixel width, following the TimeDomain approach;
- combine that pixel-derived window with a bounded nearest-index sample window, so sparse or steep curves still expose nearby visible candidates without projecting the whole curve;
- project candidate `(freq, amp)` points with `_plot_amp.vb.mapViewToScene()`;
- choose the candidate with minimum squared scene distance.

`_add_remark_at_viewport_pos()` should call this helper when the click is inside the amp ViewBox. The legacy `add_remark_at('amp', x, y)` path remains data-coordinate compatible for existing non-event callers and tests.

### Stale-Preserve FFT Re-Entry

Change `_enter_fft_mode()` so the cache-miss/no-cache fallback does not clear an already visible FFT spectrum. If the focused FFT canvas has a result, refresh the lower time preview with `clear_spectrum=False`, which keeps the spectrum and shows the existing stale marker path. If no spectrum exists, keep the current empty-preview behavior.

This preserves the user's last computed result without claiming it is fresh. It also avoids hidden section activity from erasing visible FFT work.

## Tests

- Add a `PgLineCanvas` test where a click between two spectrum samples is visually closer to a neighboring sample than the nearest-X sample, proving amp annotations use screen distance.
- Add or extend a right-click/delete test for amp-row scene-distance deletion if the implementation changes that route.
- Add an integration test for `FFT single-signal compute -> FFT-vs-Time compute or equivalent weighting drift -> return FFT`; expected result: FFT canvas still has the previous amplitude curve and is marked stale, not empty.
- Keep the existing `FFT -> Order -> FFT` preservation test green.

## Non-Goals

- No change to FFT-vs-Time spectrogram calculation.
- No automatic FFT recomputation on section switch.
- No broad refactor of analysis view state or project persistence in this pass.

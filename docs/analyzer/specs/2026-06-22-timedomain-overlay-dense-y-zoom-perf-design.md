# Time-Domain Overlay Dense Y-Zoom Performance Design

## Problem

High-sample-rate time-domain data becomes sluggish in overlay mode when users
zoom a channel's Y axis down to a very small span and the chart is full-screen.
The reported bad case shows many overlaid acceleration channels compressed into
a narrow Y window, producing dense vertical strokes across the whole plot. A
similar data set with a wider Y range remains responsive.

The current pyqtgraph time-domain renderer is already X-viewport aware:

- `mf4_analyzer/ui/pg_canvas/renderer.py:_refresh_visible_data` computes a
  `positions_envelope(...)` for the current X range and sends the envelope to
  the visible `PlotDataItem`.
- `mf4_analyzer/signal/envelope.py:build_envelope` and
  `mf4_analyzer/signal/_envelope_cutils.py:positions_envelope` reduce visible
  data to min/max pairs per X pixel bucket.
- `mf4_analyzer/ui/pg_canvas/quality.py:_density_status` disables idle
  antialiasing for dense overlay curves by summing visible curve point counts.

That means the bottleneck is not raw sample count alone. In the slow screenshot,
the X envelope still contains at most about two points per X bucket per channel,
but the Y transform turns those min/max pairs into many long, off-screen or
full-height vertical segments. Qt still has to transform, clip, and rasterize
those segments for every overlapping overlay ViewBox.

## Goals

1. Keep overlay panning, wheel zooming, and Y-axis dragging responsive when
   high-rate data is full-screen and a selected channel is zoomed to a narrow Y
   span.
2. Preserve analytical data fidelity for raw data, statistics, cursor readouts,
   exports that read `channel_data`, and project/session state.
3. Keep the visible curve faithful at screen resolution: visible in-range data
   remains visible; out-of-range excursions are clipped to the chart edge with a
   small pixel margin instead of being drawn thousands of pixels off-screen.
4. Keep subplot/single mode behavior unchanged except for shared helper code
   that is explicitly covered by tests.
5. Keep the existing pyqtgraph renderer architecture. Do not introduce OpenGL or
   a new plotting backend for this fix.

## Non-Goals

- No change to signal-processing outputs, imported samples, or stored project
  data.
- No change to axis labels, tick density controls, or overlay channel selection
  behavior.
- No replacement of `positions_envelope` or its parity contract with
  `build_envelope`.
- No visual mockup or UI setting for the first version. This is an automatic
  performance guard.

## Design

### 1. Clip only the displayed envelope to the visible Y range

Add a renderer-level helper that clips finite envelope Y values to an expanded
visible Y range before calling `PlotDataItem.setData`.

The helper must:

- read the channel-specific `ylim` from the same `axis_facade` that owns the
  curve;
- expand the range by a small pixel margin converted to data units, for example
  3 screen pixels, to avoid chopping strokes exactly at the frame border;
- preserve `NaN` values so discontinuity breaks keep working;
- return the original array unchanged when the Y range or ViewBox geometry is
  invalid;
- operate only on the envelope passed to the visible `PlotDataItem`, never on
  `self.channel_data`.

This directly targets the observed failure mode: expensive off-screen vertical
segments are shortened to the chart edge while the visual "this data is outside
the current Y window" information remains apparent.

### 2. Include the Y range in the visible-data cache key

Today the refresh key is based on channel, X range, and pixel width. If only the
Y range changes, `_refresh_visible_data` can skip `setData`, which would leave a
previously unclipped envelope in place.

Add a quantized Y-range key derived from the curve's current Y range and the
ViewBox height. The key should quantize at about one data-unit-per-screen-pixel
so tiny floating point drift does not invalidate the cache, but real Y zooms and
Y pans do.

The effective range key becomes:

```python
(
    _quantize_range_key(name, xlim, pixel_width),
    _quantize_y_range_key(axis_facade),
    int(effective_pixel_width),
)
```

The existing `_last_range_key` dictionary can stay as the storage location.

### 3. Schedule visible-data refreshes after Y-only interactions

Overlay Y interactions currently set the Y range and request a redraw. After
Y-aware clipping, they must also schedule a visible-data refresh so the clipped
envelope matches the new Y window.

Add a canvas method such as `_schedule_visible_data_refresh()` that mirrors the
X-range path:

- call `disable_interactive_quality()`;
- set `_refresh_pending = True`;
- start `_refresh_timer` if one is not already active;
- allow callers that need an immediate final frame to use the existing
  `_flush_pending_refresh()` path after range mutation.

Use this method from overlay Y-drag, overlay wheel Y zoom/pan, box-zoom Y
redirect, and snap animation finish/update points where `set_ylim` changes the
selected channel range.

### 4. Apply an overlay total-point budget before envelope generation

Overlay mode is more expensive than subplot mode because all curves share the
same plot rectangle through overlapping aux ViewBoxes. The existing AA budget
knows this, but the renderer still gives each channel up to the full chart
width in buckets.

For overlay mode, compute an effective per-channel pixel width:

```python
curve_count = len(self._channel_lines)
overlay_budget = int(self._AA_OVERLAY_SEGMENT_OFF)
effective_width = max(1, min(pixel_width, overlay_budget // max(1, 2 * curve_count)))
```

Then pass `effective_width` to `positions_envelope`. Because the min/max
envelope emits at most two points per bucket, the total drawn overlay point
count remains within the existing overlay off-budget in normal cases.

Subplot and single-channel modes continue to use the full `pixel_width`.

### 5. Keep quality status honest

`QualityManager._density_status()` can continue to read actual `PlotDataItem`
point counts. After the overlay budget lands, the status should reflect the
actual displayed point count, not the raw sample count. Do not increase the
overlay AA thresholds as part of this change.

## Acceptance Criteria

1. In overlay mode with five high-rate channels and a full-screen chart,
   `_refresh_visible_data()` sends no more than the overlay point budget to the
   curve items after the first viewport refresh.
2. When a channel Y range is narrowed, finite displayed Y values are clipped to
   the channel's expanded visible Y range, while `channel_data` retains the raw
   full-amplitude samples.
3. NaN discontinuities remain NaN after clipping.
4. Y-axis wheel zoom, Y-axis drag, and overlay box-zoom schedule a visible-data
   refresh after changing Y ranges.
5. Existing envelope parity tests still pass.
6. Existing overlay interaction tests still pass.
7. The slow performance benchmark remains opt-in and prints measured timings;
   default tests should assert structural behavior, not machine-specific frame
   times.

## Verification Scope

Run the focused checks with writable temp/cache locations:

```powershell
New-Item -ItemType Directory -Force -Path ".state\pytest-tmp" | Out-Null
$tmp=(Resolve-Path ".state\pytest-tmp").Path
$env:TEMP=$tmp
$env:TMP=$tmp
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\ui\test_pg_timedomain_canvas.py
```

Run the opt-in performance probe when evaluating the interaction path:

```powershell
$env:TEMP=$tmp
$env:TMP=$tmp
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\perf\test_timedomain_pan_perf.py -m slow -s
```

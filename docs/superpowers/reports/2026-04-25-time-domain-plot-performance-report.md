# Time-Domain Plot Performance Optimization Report

Date: 2026-04-25

## Goal

Improve the perceived smoothness of time-domain plotting without changing the UI, visual layout, or user interaction model. The existing overlay/subplot modes, cursors, range selection, statistics strip, toolbar behavior, and Matplotlib-based rendering should remain user-visible compatible.

## Current Bottlenecks

The main hotspots are in:

- `mf4_analyzer/ui/canvases.py`
- `mf4_analyzer/ui/main_window.py`

Observed issues:

1. `TimeDomainCanvas.plot_channels()` clears and rebuilds the full Matplotlib figure on each plot:
   - `fig.clear()`
   - `add_subplot()`
   - `twinx()`
   - `plot()`
   - `tight_layout()`
   - `draw()`

2. The current `_ds()` method performs a fixed full-series min/max reduction capped by `MAX_PTS = 8000`.
   - It does not consider the current visible x-range.
   - It does not consider the canvas pixel width.
   - Zooming into a region cannot recover detail from the original data because the plotted line already uses the globally reduced data.

3. Large arrays are copied in `MainWindow.plot_time()`:
   - custom x-axis values are copied;
   - `fd.time_array` is copied;
   - channel values are copied.

4. Rubber-band range selection updates call `draw_idle()` while dragging, which can trigger heavier redraw work than needed.

5. Overlay mode creates one Matplotlib Axes per y-axis via `twinx()`. This should remain visually unchanged, but those axes should not be rebuilt during ordinary pan/zoom updates.

## asammdf Reference

asammdf feels smooth because it combines several display-layer optimizations:

- original arrays stay available;
- the visible x-range is trimmed dynamically;
- min/max envelope data is regenerated from original samples for the current viewport;
- the number of displayed points is tied to the view width in pixels;
- plot structures are reused instead of rebuilt;
- rendering uses custom pyqtgraph/QPainter paths and caching.

The key idea to copy is not the entire pyqtgraph stack. The most valuable first step is viewport-aware min/max envelope downsampling inside the current Matplotlib implementation.

## Recommended Phase 1

Phase 1 should be invisible to users and low risk.

### 1. Replace Fixed `_ds()` With Viewport-Aware Envelope

Introduce an envelope method shaped like:

```python
def _envelope(self, t, sig, xlim, pixel_width):
    ...
```

Behavior:

- use only samples in the current visible x-range;
- divide the visible range into approximately one bucket per screen pixel;
- preserve min and max sample positions per bucket;
- sort each bucket's min/max positions so line order follows time order;
- return the raw visible slice unchanged when the visible point count is already small;
- keep the old full-series fallback for non-monotonic custom x-axis data.

Expected display size:

```text
canvas_width_px * 2 * visible_channel_count
```

For a 1200 px canvas and 4 channels, this is about 9600 displayed points.

### 2. Resample After xlim Changes

Connect Matplotlib x-axis limit changes to a lightweight refresh path:

- detect xlim changes on the primary/shared x-axis (only one connection in subplot mode, since axes share x via `sharex`);
- debounce with a `QTimer` around 30-50 ms;
- on mouse release (`button_release_event`), force a final flush of the
  pending refresh so the end-of-pan/zoom frame is not held back by the
  debounce timer;
- recompute envelope data for each visible channel;
- update existing lines with `line.set_data(x_ds, y_ds)`;
- call `draw_idle()`.

This preserves the existing zoom and pan behavior while making the visible data match the current viewport.

### 3. Avoid Unnecessary Copies

In `MainWindow.plot_time()`:

- use `fd.time_array` by reference when possible;
- prefer `fd.data[ch].to_numpy(copy=False)` over `.values.copy()`;
  note that for extension/object dtypes pandas may still return a
  copy — document the convention that consumers treat the returned
  array as read-only;
- avoid `custom_x.copy()` unless a mutation is required;
- only create filtered arrays when range filtering is enabled.

Statistics must continue to use the real selected data, not the downsampled display data.

### 4. Add Small Envelope Cache

Cache envelope results by a compact key:

```text
data_id, channel_name, quantized_xlim, pixel_width
```

Quantize `xlim` to roughly 0.5%-1% of the current view span (or to the
bucket width) so sub-pixel jitter during continuous pan still hits the
cache. Without quantization every mouse step misses.

Cache invalidation events:

- new file loaded;
- file closed;
- channel edit applied;
- selected channels changed;
- custom x-axis changed;
- range filter changed;
- plot mode changed when it changes axes/line ownership.

Use a small LRU-style cache to avoid unbounded memory growth.

### 5. Free Matplotlib rcParams Wins

Two rcParams are essentially free and meaningfully reduce per-frame
draw cost on long lines. Apply them once at canvas construction:

```python
import matplotlib as mpl
mpl.rcParams['path.simplify'] = True
mpl.rcParams['path.simplify_threshold'] = 0.8
mpl.rcParams['agg.path.chunksize'] = 10000
```

Zero risk to visual output at these thresholds, no API surface change.

### 6. Cache Monotonicity Detection for custom_x

`np.all(np.diff(t) >= 0)` allocates `diff` and scans the whole array.
At tens of millions of samples this is not free and would otherwise run
on every viewport refresh. Compute it once per
`(custom_xaxis_fid, custom_xaxis_ch)` and cache the boolean alongside
the channel; invalidate when the source channel is edited or the
custom-x selection changes.

## Recommended Phase 2

Phase 2 can follow after Phase 1 is verified.

### 1. Reuse Axes and Line2D Objects

Only rebuild the plot structure when the structural signature changes:

- plot mode changed;
- visible channel list changed (compare as an **ordered** sequence —
  reordering channels changes which color/spine binds to which twinx,
  so set-equality is not safe);
- overlay axis count changed;
- subplot count changed.

For ordinary viewport changes:

- keep axes;
- keep line objects;
- keep the existing `SpanSelector` (do not reconstruct it on viewport
  refresh — `enable_span_selector` should be treated as part of the
  structural rebuild path, not the viewport refresh path);
- skip `set_tick_density` / `MaxNLocator` rewiring unless the user
  changed tick density;
- update line data;
- update xlim;
- draw idle.

### 2. Reduce `tight_layout()` Frequency

Call `tight_layout()` only when axes are created or when layout-affecting settings change. Do not call it during pan/zoom refreshes.

### 3. Rubber-Band Blitting

The single and dual cursors already use a blitting-like approach. Apply the same idea to rubber-band range selection:

- capture background;
- update only the rectangle patch while dragging;
- restore and blit the changed region;
- avoid full redraw during mouse movement.

## Edge Cases

### Custom x-axis

Custom x-axis data may be non-monotonic. `searchsorted` is valid only for monotonic data.

Recommended handling:

- detect monotonic x with `np.all(np.diff(t) >= 0)`;
- use fast `searchsorted` when monotonic;
- use mask-based visible filtering or the old `_ds()` fallback when non-monotonic.

### NaN Values

For envelope buckets:

- if all values are NaN, skip the bucket or preserve a NaN break;
- if some values are finite, use `nanargmin` and `nanargmax`;
- preserve finite line continuity behavior as much as possible.

### Statistics

Statistics must not use envelope data. They should continue to use original data after any user-selected range filtering.

### Overlay Axes

Multiple `twinx()` axes are still expensive. Phase 1 keeps the current visual behavior but avoids rebuilding axes during viewport-only updates. Phase 2 can improve this further by reusing axes and lines.

## Expected Impact

For 48 kHz signals with 3-4 channels:

- full-view drawing should be bounded by canvas width instead of total sample count;
- spikes and extrema should remain visible in global view;
- zoomed views should recover local detail from original arrays;
- continuous wheel zoom and drag should feel smoother due to debounce and reduced redraw cost;
- memory pressure should decrease because large array copies are avoided.

## Acceptance Criteria

1. Initial plot appearance is unchanged.
2. Overlay and subplot layouts are unchanged.
3. Cursor, dual cursor, span selection, statistics, and tick density behavior remain unchanged.
4. A narrow spike remains visible in the full-range view.
5. Zooming into the spike region shows local original detail.
6. 48 kHz, 3-4 channel pan/zoom interaction is visibly smoother.
7. Custom x-axis, range filtering, file switching, and channel edits continue to work.
8. Statistics match the original data, not the downsampled display data.

## Recommended Implementation Order

1. Add viewport-aware envelope generation.
2. Wire xlim-change debounce and line data refresh (with
   release-event flush).
3. Remove unnecessary array copies in `plot_time()`.
4. Add a small envelope cache (with quantized xlim key).
5. Apply free rcParams (`path.simplify_threshold`, `agg.path.chunksize`).
6. Cache monotonicity detection for custom_x.
7. Reuse axes/Line2D/SpanSelector objects when plot structure has not
   changed.
8. Optimize rubber-band selection with blitting.

The best first implementation slice is items 1-6. It keeps code changes
focused and gives the biggest user-visible smoothness improvement
without changing the UI.

## Optional Phase 3 (deferred)

For very long captures (e.g. tens of minutes at 48 kHz, hundreds of
millions of samples) the per-frame envelope still scans `O(visible_n)`.
A pre-built coarse envelope (mip-map style) at file load — for example
1 ms-resolution `(min, max)` pairs per channel — lets zoomed-out views
skip the original array entirely and switch to raw only when the view
narrows enough. Not required at typical capture sizes; document as a
future option only.

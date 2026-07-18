# GNUPlot2 FFT / Order Heatmap Colormap Implementation Plan

**Goal:** Add a selectable heatmap colormap to the existing `图表选项` configuration, port Matplotlib's built-in `gnuplot2` LUT without a Matplotlib runtime dependency, and make `gnuplot2` the default for newly rendered FFT-vs-Time and Order heatmaps.

**Architecture:** `PgHeatmapCanvas` remains the single owner of the active map. A local, deterministic 256-entry LUT implements the official Matplotlib `gnuplot2` transfer functions and is returned by `_resolve_colormap("gnuplot2")`; all other supported maps continue to resolve through native pyqtgraph. `ChartOptionsDialog` exposes only supported map names and updates the existing heatmap mappable. Render paths use the canvas-owned active map so an explicitly selected map survives recomputation on that canvas, while new canvases start at `gnuplot2`.

**Non-goals:** Do not change analysis algorithms, dB conversion, automatic/manual Z-level semantics, colorbar interactions, cache keys, project/preset schema, or global Matplotlib settings. Do not claim that `gnuplot2` is an ArtemiS LUT.

## Acceptance Criteria

- A fresh FFT-vs-Time or Order canvas reports and renders `gnuplot2` by default.
- `gnuplot2`'s 256-entry LUT matches the documented Matplotlib transfer function at representative low, mid, and high indices; production code does not import Matplotlib.
- `图表选项 → 色图与色阶` has a `色图` dropdown containing `gnuplot2` and the native maps supported by the installed pyqtgraph runtime.
- Applying a different map updates both `ImageItem` and `ColorBarItem`, does not alter its levels, and persists through the next render on the same canvas.
- Existing supported maps, manual/auto levels, colorbar signal routing, and split layout alignment remain green.

## Task 1: Lock the behavior with tests (RED)

**Files:**

- Modify: `tests/ui/test_colormap_parity.py`
- Modify: `tests/ui/test_dialogs.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`

1. Add a `gnuplot2` LUT test that resolves the map without importing Matplotlib and asserts the exact 256-step RGBA anchors from the Matplotlib transfer functions (including the black low end and white high end).
2. Replace the obsolete `test_chart_options_dialog_applies_heatmap_range_without_cmap_control` expectation with a configuration test that selects `gnuplot2` by default, applies `plasma`, and proves the heatmap mappable and colorbar update while color levels remain unchanged.
3. Add a re-render regression for both direct heatmap callers: set `plasma` through the mappable, render again with the canvas's active map, and assert no reset to the global default.

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_colormap_parity.py tests/ui/test_dialogs.py tests/ui/test_pg_heatmap_canvas.py -q
```

Expected before implementation: `gnuplot2` is unavailable, the dialog has no dropdown, and fresh canvas/default callers still report `turbo`.

## Task 2: Port the official `gnuplot2` LUT and restore the configuration control

**Files:**

- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `mf4_analyzer/ui/dialogs.py`

1. Define `DEFAULT_HEATMAP_CMAP = "gnuplot2"` and a supported-name tuple containing `gnuplot2` plus only installed native pyqtgraph maps.
2. Build the `gnuplot2` 256-step RGBA table from the official Matplotlib channel functions, using NumPy/pyqtgraph only; pass the table to `pg.ColorMap` with positions `linspace(0, 1, 256)`.
3. Make `_resolve_colormap()` return this custom map for `gnuplot2`, preserve native resolution for other supported names, and retain a safe default fallback.
4. Set the canvas initial/default/reset colormap to `gnuplot2`. Keep `_HeatmapMappable.set_cmap()` as the only live mutation path so image and colorbar stay synchronized.
5. Restore the `色图` combo to `ChartOptionsDialog`, initialize it from `mappable.get_cmap().name`, apply it before color-level changes, and disable it when there is no heatmap mappable.

## Task 3: Route renderer defaults through canvas-owned configuration

**Files:**

- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py` only if its fixed legacy `cmap` output would overwrite the canvas setting.

1. Pass `canvas._cmap_name` (with the default fallback) to FFT-vs-Time and Order render calls instead of the hard-coded/legacy `turbo` values.
2. Keep `cmap` out of compute cache keys and leave dB reference / auto-level paths untouched.
3. Retain old preset compatibility: a legacy `cmap` field must not override an explicit chart configuration.

## Task 4: Verify and perform the visual gate

Run the Task 1 suite plus:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_analysis_section_page.py::test_split_fft_time_heatmap_and_slice_plot_areas_align \
  tests/ui/test_auto_color_span.py tests/ui/test_analysis_multiview_integration.py -q
git diff --check
```

Render a representative heatmap through the existing offscreen canvas test path and verify that the colorbar runs from black/blue at the floor through magenta/red/orange to yellow-white at the ceiling, while the Z limits before and after the map change are identical.

## Plan Self-Review

- The implementation is display-only and remains independent of Matplotlib at runtime.
- The dialog is the only newly exposed control; no Inspector/preset/config schema expansion is needed.
- Existing colorbar ownership and level signals remain unchanged, avoiding split-pane or manual-level regressions.

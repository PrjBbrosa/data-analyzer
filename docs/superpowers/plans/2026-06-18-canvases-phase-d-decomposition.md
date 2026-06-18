# Phase D: canvases.py helper extraction + matplotlib canvas retirement

**Date**: 2026-06-18  
**Status**: ready  
**Branch**: refactor/large-file-decomp-abc

---

## Goal

Split `mf4_analyzer/ui/canvases.py` (1791 lines) into:
1. `mf4_analyzer/signal/envelope.py` — pure signal math helpers
2. `mf4_analyzer/ui/plot_helpers.py` — pure UI formatting helpers
3. `canvases.py` reduced to a re-export shim (~30 lines), then further pruned
4. Delete `TimeDomainCanvas` + `PlotCanvas` classes + mpl-only helpers (~lines 61–505 + 506–1791)

---

## Step 1 — Create `signal/envelope.py`

**New file**: `mf4_analyzer/signal/envelope.py`

Symbols to move verbatim:
- `_BUILD_ENVELOPE_LEGACY_MAX_PTS = 8000`
- `_is_monotonic_array(t)`
- `_ds_legacy_pure(t, sig, max_pts)`
- `build_envelope(t, sig, *, xlim, pixel_width, is_monotonic)`

Imports needed: `numpy as np`

## Step 2 — Create `ui/plot_helpers.py`

**New file**: `mf4_analyzer/ui/plot_helpers.py`

Symbols to move verbatim:
- `_split_prefixed_label(text)`
- `_compact_axis_label(name, unit, max_chars)`
- `_middle_ellipsis(text, max_chars)`
- `_set_series_ylabel(ax, label, color, labelpad, unit, side)`
- `_format_single_cursor_channel_html(channel_name, value, unit_suffix, color)`
- `_format_dual_html(rows)`
- `_interp_cursor_value(t, sig, x)`

Imports needed: `numpy as np`, `from html import escape` (deferred in functions)

## Step 3 — Update `canvases.py` to re-export

Add at top of `canvases.py` (after existing imports are still there for the class bodies):
```python
from mf4_analyzer.signal.envelope import (
    build_envelope, _is_monotonic_array, _ds_legacy_pure,
    _BUILD_ENVELOPE_LEGACY_MAX_PTS,
)
from mf4_analyzer.ui.plot_helpers import (
    _compact_axis_label, _middle_ellipsis, _format_dual_html,
    _format_single_cursor_channel_html, _interp_cursor_value,
    _split_prefixed_label, _set_series_ylabel,
)
```
Remove the duplicate function bodies for these symbols.

## Step 4 — Update real importers

| File | Old import | New import |
|---|---|---|
| `signal/_envelope_cutils.py:58` | `from mf4_analyzer.ui.canvases import build_envelope, _is_monotonic_array` | `from mf4_analyzer.signal.envelope import build_envelope, _is_monotonic_array` |
| `ui/pg_canvas/canvas.py:86` | `from mf4_analyzer.ui.canvases import _split_prefixed_label, build_envelope` | from new paths |
| `ui/pg_canvas/cursor.py:15` | `from mf4_analyzer.ui.canvases import _format_dual_html, ...` | `from mf4_analyzer.ui.plot_helpers import ...` |
| `ui/pg_canvas/_shared.py:7` | `from mf4_analyzer.ui.canvases import _compact_axis_label` | `from mf4_analyzer.ui.plot_helpers import _compact_axis_label` |
| `ui/pg_canvas/overlay_axes.py:22` | `from mf4_analyzer.ui.canvases import _is_monotonic_array, _middle_ellipsis` | from new paths |
| `ui/pg_canvas/overlay_axes.py:302` | deferred `from mf4_analyzer.ui.canvases import build_envelope` | `from mf4_analyzer.signal.envelope import build_envelope` |
| `ui/pg_canvas/line_canvas.py:22` | `from mf4_analyzer.ui.canvases import build_envelope` | `from mf4_analyzer.signal.envelope import build_envelope` |
| `ui/chart_stack/cursor_pill.py:162` | deferred `from ..canvases import _format_dual_html` | `from ..plot_helpers import _format_dual_html` |

## Step 5 — Monkeypatch audit

`grep -rn "monkeypatch.setattr.*mf4_analyzer.ui.canvases" tests/` → ZERO hits. No anchors needed.

## Step 6 — Verify no runtime instantiation

Targets verified:
- `app.py` → no hit
- `ui/main_window.py:2867` → comment only
- `ui/chart_stack/**` → only `TimeDomainCanvasPG`, no `TimeDomainCanvas`/`PlotCanvas`
- `ui/_axis_interaction.py` → docstring only
- Full `mf4_analyzer/` grep → only comments, docstrings, and the pg shim doc references

`matplotlib_runtime_use_found: false`

## Step 7 — Delete matplotlib classes from canvases.py

Remove:
- Lines 61–205: mpl-only helpers (`_first_live_axes`, `_open_chart_options_for_axes`, ..., `_apply_heatmap_axes_style`)
- Lines 506–1791: `TimeDomainCanvas(FigureCanvas)` + `PlotCanvas(FigureCanvas)`
- Unused top imports: `FigureCanvas`, `Figure`, `SpanSelector`, `MaxNLocator`, `import matplotlib as _mpl`, `_mpl.rcParams[...]` block, `import time as _time`

Keep in `canvases.py` after Step 7:
- `CHART_FACE`, `AXIS_TEXT`, `AXIS_LINE`, `GRID_LINE`, `PRIMARY`, `DANGER` color constants
- `from .._chart_kw import CHART_TIGHT_LAYOUT_KW, AXIS_HIT_MARGIN_PX`
- Re-export shims for all symbols imported from new modules

## Step 8 — Handle test files

### `tests/ui/test_canvases.py`
- `test_dual_cursor_html_labels_endpoint_delta_with_hollow_triangle` — imports only `_format_dual_html`, survives via re-export shim; no class needed. KEEP but it can stay pointing at `canvases._format_dual_html`.
- All other tests use `TimeDomainCanvas` or `PlotCanvas`. DELETE those tests.

### `tests/ui/test_axis_interaction.py`
- Lines 1–48: `find_axis_for_dblclick` tests — pure `Figure`/`ax` matplotlib, no canvas class. KEEP.
- Lines 50–217: `TimeDomainCanvas`/`PlotCanvas`-based tests — DELETE.
- Final comment at line 218 — KEEP.

### `tests/perf/test_timedomain_pan_perf.py`
- `test_timedomain_pan_refresh_baseline` (~line 106): uses `TimeDomainCanvas`. DELETE.
- `test_timedomain_pan_refresh_pg_canvas` (~line 191): uses `TimeDomainCanvasPG`. KEEP.

### `tests/ui/test_canvases_envelope.py`
- `test_build_envelope_is_module_level` — tests `canvases.build_envelope`; survives via re-export. KEEP as-is.
- `test_build_envelope_matches_timedomain_envelope_behaviour` — uses `TimeDomainCanvas._envelope`. DELETE this test.
- All other `build_envelope` tests — KEEP, update import to `from mf4_analyzer.signal.envelope import build_envelope` where they use it directly.

## Step 9 — Verify import health

```
python -c "import mf4_analyzer.app"
python -c "from mf4_analyzer.signal.envelope import build_envelope, _is_monotonic_array; print('OK')"
python -c "from mf4_analyzer.ui.plot_helpers import _compact_axis_label, _format_dual_html; print('OK')"
```

## Step 10 — Full test suite

`pytest -q --basetemp=.pytest_tmp` → only the 2 known flaky.

## Step 11 — Commit

Explicit pathspec: new files, canvases.py, all importers, touched test files.

---

## Files to change

**New**:
- `mf4_analyzer/signal/envelope.py`
- `mf4_analyzer/ui/plot_helpers.py`

**Modified**:
- `mf4_analyzer/ui/canvases.py`
- `mf4_analyzer/signal/_envelope_cutils.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/cursor.py`
- `mf4_analyzer/ui/pg_canvas/_shared.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- `mf4_analyzer/ui/chart_stack/cursor_pill.py`
- `tests/ui/test_canvases.py`
- `tests/ui/test_axis_interaction.py`
- `tests/perf/test_timedomain_pan_perf.py`
- `tests/ui/test_canvases_envelope.py`

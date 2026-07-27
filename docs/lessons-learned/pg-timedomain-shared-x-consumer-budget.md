---
id: pg-timedomain-shared-x-consumer-budget
status: active
owners: [codex]
keywords: [pyqtgraph, timedomain, hdf, raw-x, cache, resize, benchmark]
paths: [mf4_analyzer/ui/pg_canvas/canvas.py, mf4_analyzer/ui/pg_canvas/overlay_axes.py, tests/ui/test_timedomain_hotpath_perf.py, tests/ui/test_pg_timedomain_canvas.py, scripts/benchmark_timedomain_interaction.py]
checks: ["rg -n '_data_x_union|_scan_finite_x_bounds|_raw_x_bounds_by_fingerprint' mf4_analyzer/ui/pg_canvas", "git diff --check"]
tests: [tests/ui/test_timedomain_hotpath_perf.py, tests/ui/test_pg_timedomain_canvas.py, scripts/benchmark_timedomain_interaction.py]
---

# Pyqtgraph TimeDomain Shared-X Consumer Budget

Trigger: Change TimeDomain buffered pan/zoom, resize settling, selection delta,
or raw X-range computation for dense HDF subplot data.

Past failure: A buffered settle change moved `_data_x_union()` from build/Home
into the range-event consumer. Six 1,188,000-point HDF rows shared one time
array, but every pan/resize re-ran finite scan/copy/min/max per row. A 40 ms
resize debounce could also expire while a slow Cocoa paint was still in flight;
multi-subplot checkbox changes then paid an unrelated full `clear()` rebuild.

Rule: Cache finite raw-X bounds by stable array fingerprint for one render
generation and invalidate only on clear/rebind/real source change. Prove the
cache at the pan/resize consumer, not merely at its producer. Treat resize as a
true quiet window with exactly one final data/layout settle. For compatible
ordinary subplots retain rows and reuse PlotItem/ViewBox on hide/restore;
explicitly fall back for topology or ordering changes. Do not route general
continuous HDF curves into the dense-discrete pixmap backend without a real
Cocoa repaint measurement—the six-image composition can be slower.

Verification: Run `tests/ui/test_timedomain_hotpath_perf.py` for scan/timer
counts, `tests/ui/test_pg_timedomain_canvas.py` for retained identity, and
`tests/ui/test_pg_dense_raster.py` for the continuous-raster exclusion. For a
release candidate, run `scripts/benchmark_timedomain_interaction.py --hdf ...
--assert-standards`; record callback, paint, held-frame and settle metrics
separately, and compare three-run p95 medians against the accepted baseline.

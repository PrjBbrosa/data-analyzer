OVERALL: NEEDS-REWORK

## Summary

- Runtime/perf verdict: **PASS** for the T9 hot path. My live slow perf run measured pyqtgraph pan at P50 `0.712 ms`, P95 `1.045 ms`, with `c_path=True c_calls=245`; the design §8 target is P50 <= 8 ms and P95 <= 15 ms on the C path (`docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md:408-418`).
- Measurement-validity verdict: **PASS**. The timed loop constructs a real `TimeDomainCanvasPG`, mutates different xlims per iteration, and `c_calls=245` matches 49 cache-miss frames x 5 channels, so the 0.7 ms result is not just cache-hit no-ops (`tests/perf/test_timedomain_pan_perf.py:222-240`, `tests/perf/test_timedomain_pan_perf.py:289-317`, `mf4_analyzer/ui/pg_canvases.py:1039-1045`).
- Geometry/parity verdict: **PASS**. The all-finite path is vectorized through `arrayToQPath(..., connect="all", finiteCheck=False)`, while NaN-gap and single-point cases route to the old loop; parity tests compare `(elementType, x, y)` tuples, not only counts (`mf4_analyzer/ui/pg_canvases.py:1121-1143`, `tests/ui/test_pg_timedomain_canvas.py:1900-1910`, `tests/ui/test_pg_timedomain_canvas.py:1962-2005`).
- Ship verdict: **NEEDS-REWORK** before branch merge because the PyInstaller hidden-import manifest still does not list `pyqtgraph` or `mf4_analyzer.ui.pg_canvases`; the packaging acceptance bullet is therefore only partial (`tests/test_packaging_imports.py:14-47`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:613-626`).
- Current full-suite status: **PASS** under the requested command: `1156 passed, 3 skipped, 3 deselected, 81 warnings in 42.06s`. The T8 report's earlier `1148 passed` count is stale after later test additions, not a failure (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:289-318`).

## T8 review

Verdict: **PASS for verification mechanics; NEEDS-REWORK remains for packaging ship gate.**

- Full-suite verification: my live command `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` completed with no failures: `1156 passed, 3 skipped, 3 deselected, 81 warnings in 42.06s`. The 3 deselected tests are expected because `pytest.ini` excludes `slow` by default (`pytest.ini:1-5`). This supersedes the results report's earlier T8 count of `1148 passed, 3 skipped, 3 deselected` (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:289-318`).

  Tail from my run:

  ```text
  tests/ui/test_inspector.py::test_fft_render_honors_axis_toggles
  tests/ui/test_inspector.py::test_fft_render_honors_manual_xy_axis_ranges
    /Users/donghang/Downloads/data analyzer/.venv/lib/python3.12/site-packages/pytestqt/plugin.py:220: UserWarning: Glyph 24230 (...) missing from font(s) DejaVu Sans.
      app.processEvents()

  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  1156 passed, 3 skipped, 3 deselected, 81 warnings in 42.06s
  ```

- PG perf test construction is real, not mocked: `test_timedomain_pan_refresh_pg_canvas` imports `TimeDomainCanvasPG`, wraps the real `asammdf.blocks.cutils.positions`, constructs the canvas, plots 5 x 100k channels, and asserts the C function fired if the C path is available (`tests/perf/test_timedomain_pan_perf.py:191-240`, `tests/perf/test_timedomain_pan_perf.py:263-281`, `tests/perf/test_timedomain_pan_perf.py:344-354`).
- Cache-hit-vs-rebuild check: the timed PG loop uses `starts = np.concatenate([linspace(0, 8, 25), linspace(8, 0, 25)])`, then calls `primary.set_xlim(lo, hi)` and `_flush_pending_refresh()` on every sample (`tests/perf/test_timedomain_pan_perf.py:289-315`). The production skip gate compares only `_last_range_key[name]` to the current range key, so only an immediately repeated xlim is skipped (`mf4_analyzer/ui/pg_canvases.py:1039-1045`). The observed `c_calls=245` equals 49 rebuild frames x 5 channels, proving the timed loop rebuilt envelope+path on the real hot path rather than measuring 50 cache hits.
- T8 report honesty: the results report preserved the Task 8 miss instead of smoothing it over: before T9, pyqtgraph P50 was about `10.7 ms` with `c_path=True c_calls=245`; the report says P50 <= 8 ms was missed and root-causes the pure-Python `QPainterPath` loop (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:352-381`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:397-461`).

## T9 review

Verdict: **PASS for vectorization correctness and parity coverage.**

- API correctness: installed pyqtgraph exposes `def arrayToQPath(x, y, connect='all', finiteCheck=True)`, so the kwargs used by T9 are real in this venv (`.venv/lib/python3.12/site-packages/pyqtgraph/functions.py:2016-2035`). `.venv/bin/python -c 'import pyqtgraph; print(pyqtgraph.__version__)'` prints `0.14.0`.
- Hot path split is correct: `_build_painter_path` uses `arrayToQPath` only when `n >= 2` and both x/y slices are all finite, after converting to contiguous `float64`; it passes `connect="all", finiteCheck=False` only after the explicit finiteness check (`mf4_analyzer/ui/pg_canvases.py:1121-1137`).
- Fallback geometry is preserved: empty input returns a blank `QPainterPath`, and all NaN-gap / single-point / other non-all-finite cases route to `_build_painter_path_loop`, which is the old per-point `moveTo`/`lineTo` logic (`mf4_analyzer/ui/pg_canvases.py:1116-1143`, `mf4_analyzer/ui/pg_canvases.py:1149-1164`).
- Parity test is coordinate-level: `_path_elements` extracts every `QPainterPath` element as `(type, x, y)`, and `TestBuildPainterPathParity` compares the production output to an old-loop reference across all-finite, 50-point all-finite, single/double/leading NaN gaps, single-point, and empty cases (`tests/ui/test_pg_timedomain_canvas.py:1900-1942`, `tests/ui/test_pg_timedomain_canvas.py:1945-2005`). This is not a weak `elementCount()`-only assertion.
- The perf win is end-to-end, not just a micro-bench: T9's report shows before/after pyqtgraph pan P50 `10.707 ms -> 0.739 ms`, P95 `11.080 ms -> 1.081 ms`, with `c_path=True` unchanged (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:367-381`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:463-490`). My re-measurement is consistent: P50 `0.712 ms`, P95 `1.045 ms`.

## Perf-claim verification

Command run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow -s
```

Pasted perf stdout lines from my run:

```text
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.869 p95_ms=11.073 mean_ms=7.254 min_ms=0.081 max_ms=11.078
TIMEDOMAIN_PAN_PERF path=pyqtgraph channels=5 samples=100000 iters=50 p50_ms=0.712 p95_ms=1.045 mean_ms=0.767 min_ms=0.013 max_ms=1.109 c_path=True c_calls=245
TIMEDOMAIN_ENVELOPE_PERF path=build_envelope channels=5 samples=100000 iters=50 p50_ms=1.809 p95_ms=1.870 mean_ms=1.819 min_ms=1.767 max_ms=2.049 c_path=True
TIMEDOMAIN_ENVELOPE_PERF path=positions_envelope channels=5 samples=100000 iters=50 p50_ms=0.028 p95_ms=0.037 mean_ms=0.029 min_ms=0.022 max_ms=0.040 c_path=True
```

Pytest result: `3 passed in 10.02s`.

Judgment: **PASS, real rebuilds.** The pyqtgraph pan line meets the design target by a wide margin. The loop is not primarily measuring cache hits because:

- the timed loop mutates the xlim each iteration (`tests/perf/test_timedomain_pan_perf.py:306-315`);
- the production no-op gate only skips when the per-channel `_last_range_key` equals the current key (`mf4_analyzer/ui/pg_canvases.py:1039-1045`);
- the emitted `c_calls=245` proves 245 real C envelope calls during the timed loop, matching 49 cache-miss frames x 5 channels;
- each rebuild then calls `positions_envelope`, `_build_painter_path`, `_render_path_to_pixmap`, and updates the cache (`mf4_analyzer/ui/pg_canvases.py:1047-1072`).

One of the 50 frames is an intentional range-key hit at the forward/reverse fold (`s=8.0` appears twice consecutively), which is why the expected rebuild count is 49 rather than 50. That does not explain the P50 result; 49/50 timed iterations still exercise the real envelope+path rebuild path.

## Report-completeness audit

Verdict: **PARTIAL / NEEDS-REWORK for packaging; otherwise complete enough for W4 perf verification.**

Design §8 acceptance bullets (`docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md:408-418`):

| Acceptance item | Status | Evidence |
| --- | --- | --- |
| No UI control/text/shortcut/workflow/layout change | **PASS (offscreen + sampled pixels)** | Results report states no intentional UI change and cites invariant tests plus 0-delta chrome pixels (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:630-665`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:697-728`). |
| Time-domain functional logic preserved | **PASS** | Report maps contract and PG parity coverage across subplot/overlay/cursor/wheel/selection behavior (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:522-537`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:637-657`). |
| `ChartOptionsDialog` works for matplotlib and pyqtgraph time canvas | **PASS offscreen; on-screen smoke pending** | Offscreen dialog tests are listed as passing, including second/third subplot handle identity; real-display rapid double-click smoke is explicitly not run (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:536-537`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:544-571`). |
| Full suite passes | **PASS** | My live run: `1156 passed, 3 skipped, 3 deselected, 81 warnings in 42.06s`; T8 report earlier recorded `1148 passed` before later tests increased the count (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:289-318`). |
| Matplotlib baseline and new pyqtgraph result recorded | **PASS** | Report includes Task 8 before numbers and Task 9 after numbers verbatim (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:352-381`). |
| 5ch x 100k pan P50 <= 8 ms and P95 <= 15 ms on C path | **PASS** | Report says T9 met P50/P95, and my run independently measured P50 `0.712 ms`, P95 `1.045 ms`, `c_path=True` (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:463-490`). |
| C-path fallback honesty | **PASS** | T8 miss is preserved as `MISSED`, not massaged; C-path execution is called out separately via `c_path=True c_calls=245` (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:397-461`). |
| Packaging/import smoke covers pyqtgraph | **NEEDS-REWORK** | `tests/test_packaging_imports.py` lists acquisition hidden imports and widgets only; `rg -n 'pyqtgraph|pg_canvases' tests/test_packaging_imports.py` returned no matches (`tests/test_packaging_imports.py:14-47`). The results report correctly records this as partial/open (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:613-626`). |
| Old matplotlib `TimeDomainCanvas` remains until cleanup approval | **PASS / deferred** | Report confirms old canvas remains importable for rollback and cleanup is Phase 7/user-approved (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:602-611`). |

Report-honesty note: the report does show both before (`~10.7 ms`) and after (`~0.7 ms`) pyqtgraph numbers. One non-blocking polish issue remains: §4.3 still shows the pre-T9 pyqtgraph row under a broad "Matplotlib vs pyqtgraph vs design target" heading (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:383-395`), while §4.7 supersedes it with the after-T9 table. I do not treat this as number massaging, but it is easy for a reader to mis-scan.

## Scope-creep audit

Verdict: **PASS for W4/T9 source scope; branch still contains earlier-wave uncommitted files.**

- W4/T9 `pg_canvases.py` change is confined to path construction: `_refresh_visible_data` still computes the same range key, calls `positions_envelope`, calls `_build_painter_path`, renders to pixmap, and writes the same cache entry shape (`mf4_analyzer/ui/pg_canvases.py:1018-1072`). The report explicitly says cache structure, antialiasing, public API, signal surface, and chart-options/double-click code are unchanged (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:504-507`).
- No API/signal change observed in the T9 area: the signal contract remains `cursor_info`, `dual_cursor_info`, `span_selected`, `overlay_channel_selected`; cache fields remain `_curve_path_cache` and `_last_range_key` (`mf4_analyzer/ui/pg_canvases.py:181-185`, `mf4_analyzer/ui/pg_canvases.py:251-263`).
- `ChartStack` production switch is already present from W3, not a T9 path-construction change: `ChartStack.canvas_time = TimeDomainCanvasPG(self)` (`mf4_analyzer/ui/chart_stack.py:967-971`). W4 did not need further chart-stack API changes to deliver the perf fix.
- FFT guard: required command `git diff -- mf4_analyzer | rg -n '^[+-].*(FFTTimeWorker|SpectrogramResult|_fft_time_cache_key|fft_time)'` produced no output. I also found no FFT identifiers in the W4-scoped file set via `rg -n 'FFTTimeWorker|SpectrogramResult|_fft_time_cache_key|fft_time' ...` over `pg_canvases.py`, the perf test, the PG test, the results report, and the new lessons.
- B1-B7 remain out of scope: the design non-goals explicitly say not to migrate FFT/Heatmap/Spectrogram/Order and not to reopen the completed B1-B7 review-followup spec (`docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md:46-55`); the results report repeats B1-B7 as out of scope (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:669-676`).
- Minor doc drift noticed, not a W4 behavior issue: `pg_canvases.py` still has comments saying the PG canvas is "not wired" / "behind tests only", while `chart_stack.py` now constructs it in production (`mf4_analyzer/ui/pg_canvases.py:6-11`, `mf4_analyzer/ui/pg_canvases.py:175-179`, `mf4_analyzer/ui/chart_stack.py:967-971`). This should be cleaned up, but it does not affect the T9 perf path.

## Defensive-gate audit

| Gate | Status | Evidence / judgment |
| --- | --- | --- |
| codex-runtime-verification-entrypoints | **PASS** | Used `.venv/bin/python` with `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen` for both required pytest commands; live full suite passed with 1156 tests and the slow perf suite passed with 3 tests. |
| codex-phantom-api-surface-guards | **PASS** | No fake PG/asammdf surface: the perf test imports real `TimeDomainCanvasPG`, wraps real `asammdf.blocks.cutils.positions`, and asserts C calls when `_HAS_POSITIONS_C` is true (`tests/perf/test_timedomain_pan_perf.py:210-240`, `tests/perf/test_timedomain_pan_perf.py:344-354`). |
| codex-plan-spec-literal-evidence | **PASS** | Audited each design §8 bullet literally against code, tests, report text, and live stdout (`docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md:408-418`). |
| codex-analyzer-doc-routing | **PASS** | Review artifact is under the requested shared analyzer review path: `docs/analyzer/reviews/2026-05-28-pyqtgraph-wave4.md`. No other file was written. |
| codex-fft-time-review-shields | **PASS** | Required FFT grep over `git diff -- mf4_analyzer` was empty; design and results report keep FFT/Heatmap/Spectrogram/Order outside this migration (`docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md:46-55`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:669-676`). |
| codex-visual-parity-rendered-screenshot | **PARTIAL / PENDING ON-SCREEN** | Offscreen screenshot/pixel evidence and geometry parity are recorded (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:492-500`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:697-728`), but real-display double-click/rubber-band smoke is explicitly not run (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:544-571`). |
| signal-processing branch-reached-is-not-behavior-correct | **PASS** | T9 parity tests assert actual element coordinates and types, not branch reach or element count alone (`tests/ui/test_pg_timedomain_canvas.py:1900-1910`, `tests/ui/test_pg_timedomain_canvas.py:1992-2005`). |
| codex-performance-ui-audit-flow | **PASS** | W4 measures the full user-facing pan path (`set_xlim` -> flush -> envelope -> path -> pixmap/cache), not just the 76x envelope micro-bench (`tests/perf/test_timedomain_pan_perf.py:191-215`, `tests/perf/test_timedomain_pan_perf.py:306-333`, `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:463-490`). |

## Outstanding items for ship

1. **MERGE BLOCKER — add pyqtgraph / PG canvas to packaging hidden-import coverage.** `tests/test_packaging_imports.py` has no `pyqtgraph` or `mf4_analyzer.ui.pg_canvases` entry in `REQUIRED_HIDDEN_IMPORTS` / `WIDGET_MODULES`; `rg -n 'pyqtgraph|pg_canvases' tests/test_packaging_imports.py` returned no matches (`tests/test_packaging_imports.py:14-47`). The results report already records this as a real frozen-build gap (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:613-626`).
2. **MERGE / RELEASE GATE — run real-display on-screen smoke.** Offscreen tests cover the dispatch logic, but the report explicitly says the non-offscreen double-click chart-options smoke is not yet run (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:544-571`). This is especially relevant because W3/W4 changed the active renderer surface.
3. **DECISION ITEM — old matplotlib `TimeDomainCanvas` cleanup.** Current state matches the design: old canvas remains for rollback until user approval (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:602-611`). Before merge/release, record whether cleanup is explicitly deferred to a later branch or requested now.
4. **POLISH — update stale PG canvas comments.** `pg_canvases.py` still says the canvas is not wired / behind tests only, but production `ChartStack` now instantiates `TimeDomainCanvasPG` (`mf4_analyzer/ui/pg_canvases.py:6-11`, `mf4_analyzer/ui/pg_canvases.py:175-179`, `mf4_analyzer/ui/chart_stack.py:967-971`). Not a runtime blocker, but it will mislead the next reviewer.

## Final verdict

The pyqtgraph TimeDomain migration is **complete on the runtime/performance axis**: the T9 vectorized `arrayToQPath` path is real, parity-tested at coordinate level, and independently re-measured at P50 `0.712 ms` / P95 `1.045 ms` with `c_path=True`.

It is **not yet shippable as a branch** because the packaging hidden-import acceptance bullet is still open, and the real-display smoke remains pending. After adding pyqtgraph/PG canvas packaging coverage and recording the on-screen smoke result, this should be ready to merge with old matplotlib cleanup explicitly deferred or separately approved.

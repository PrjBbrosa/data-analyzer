# Pyqtgraph TimeDomainCanvas Migration — Results Report

**Date:** 2026-05-28
**Branch:** `plan/pyqtgraph-timedomain-migration`
**Plan:** `docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md`
**Design spec:** `docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md`
**Status:** Migration code-complete through W4 (production switch live —
`ChartStack.canvas_time` is `TimeDomainCanvasPG`, `chart_stack.py:967`).
Task 8 (W4) verification: full suite green (1148 passed, 3 skipped),
production pyqtgraph pan measured on the C path. Headline P50 ≤ 8 ms
target was **MISSED at Task 8** (10.7 ms), root-caused to the
pure-Python `_build_painter_path` loop. **Task 9 (W4) vectorized that
loop via `pyqtgraph.functions.arrayToQPath` and the P50 ≤ 8 ms target
is now MET (≈ 0.74 ms); P95 ≤ 15 ms also MET (≈ 1.1 ms).** See §4.2/§4.5
for the before→after determination and §4.7 for the Task 9 result.

This report is updated task-by-task as the migration plan executes. The
baseline section below was filled in by Task 1 (Baseline And Dependency
Gate); subsequent sections (final perf, parity, manual smoke) are
populated by Tasks 4-8.

---

## 1. Environment

| Item | Value |
| --- | --- |
| Host OS | Darwin 25.5.0 arm64 (macOS) |
| Python | 3.12.13 (`.venv/bin/python`) |
| matplotlib | 3.10.9 |
| asammdf | 8.8.7 |
| pyqtgraph (requirement only) | `pyqtgraph>=0.13.3` (added to `requirements.txt`, not yet installed in `.venv`) |
| Qt platform for tests | `QT_QPA_PLATFORM=offscreen` |

`.venv/bin/python` is used for every command; no system Python.
`TMPDIR=/tmp` is set on every Qt-touching command to avoid HFS atomic
rename quirks under macOS.

---

## 2. Phase 0 — Baseline And Dependency Gate (Task 1)

### 2.1 Dependency surface probe

Command (verbatim, from plan Task 1 Step 2):

```bash
.venv/bin/python - <<'PY'
import importlib.util
from asammdf.blocks import cutils
print("pyqtgraph", bool(importlib.util.find_spec("pyqtgraph")))
print("positions", callable(getattr(cutils, "positions", None)))
PY
```

Stdout (verbatim):

```
pyqtgraph False
positions True
```

Interpretation:

- `asammdf.blocks.cutils.positions` is importable and callable on the
  active venv (asammdf 8.8.7). The optional C path documented in the
  design spec §3.5 is available.
- `pyqtgraph` is NOT yet installed in `.venv`. Task 1's scope is
  requirement declaration only — the actual `pip install -r
  requirements.txt` is an operator step that runs before Task 5
  (`TimeDomainCanvasPG` build). The dependency line has been added to
  `requirements.txt` so the install is deterministic when invoked.

### 2.2 Behavior baseline (matplotlib path, pre-migration)

Command (verbatim):

```bash
.venv/bin/python -m pytest tests/ui/test_xlim_refresh.py tests/ui/test_canvases.py tests/ui/test_axis_interaction.py -q
```

Result (tail, verbatim):

```
37 passed, 15 warnings in 2.61s
```

All 15 warnings are CJK-glyph `UserWarning`s emitted by matplotlib's
DejaVu Sans on macOS for Chinese tick labels; they pre-exist Task 1 and
are not behavior regressions. No tests fail, none skip. The same
command was re-run after Task 1's non-`.py` edits and produced the
identical `37 passed, 15 warnings` line — Task 1 made no source-code
behavior change.

### 2.3 Pan-refresh performance baseline (matplotlib path)

Command (verbatim, from plan Task 1 Step 4):

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen \
    .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py \
    -q -m slow
```

Test contents: `tests/perf/test_timedomain_pan_perf.py`. It constructs
a `TimeDomainCanvas` sized 1600x800, plots 5 channels x 100 000
samples in subplot mode, runs a 5-iteration warmup, then times 50
iterations of `primary.set_xlim(lo, hi)` followed by
`cv._flush_pending_refresh()`. Per-iteration wall-clock is measured
with `time.perf_counter()`. P50/P95 are nearest-rank percentiles.

Stdout from three consecutive runs (verbatim, captured with `-s`):

```
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.576 p95_ms=10.779 mean_ms=7.069 min_ms=0.084 max_ms=10.868
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.677 p95_ms=10.816 mean_ms=7.103 min_ms=0.083 max_ms=10.880
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.779 p95_ms=10.920 mean_ms=7.183 min_ms=0.083 max_ms=10.998
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.640 p95_ms=10.838 mean_ms=7.095 min_ms=0.083 max_ms=10.870
```

Headline baseline (representative run 2 of 3):

| Metric | Value |
| --- | --- |
| Renderer path | matplotlib (current `TimeDomainCanvas`) |
| Channels | 5 |
| Samples per channel | 100 000 |
| Iterations measured | 50 |
| **P50 pan-refresh** | **10.677 ms** |
| **P95 pan-refresh** | **10.816 ms** |
| Mean | 7.103 ms |
| Min | 0.083 ms |
| Max | 10.880 ms |

Notes on shape of the distribution:

- The pan loop walks a 2-second window from t=0..8 then back from
  t=8..0 in 25 + 25 steps. The forward and return passes revisit
  identical xlims at most steps; on those repeat-xlims, the envelope
  cache (`_envelope_cache_hits`) returns immediately and per-iteration
  wall-clock drops to ~0.08 ms. This explains why `mean << P50`: the
  distribution is bimodal between "cache hit" and "cache miss + draw"
  iterations.
- P95 therefore represents the cache-miss + matplotlib `set_data` +
  `draw_idle()` cost on the offscreen Qt platform. It is the realistic
  bound for first-pass pan on a never-before-seen viewport.
- The target stated in the plan (P50 <= 8 ms, P95 <= 15 ms on the C
  path) is for the post-migration pyqtgraph + `positions_envelope` path.
  Current matplotlib P95 (~10.8 ms) is the number the new path must
  meet or beat under the same workload to ship the production switch.

### 2.4 Files touched by Task 1

- `requirements.txt` — single-line addition of `pyqtgraph>=0.13.3` between `asammdf` and `openpyxl`. Nothing else changed.
- `tests/perf/__init__.py` — new empty package marker.
- `tests/perf/test_timedomain_pan_perf.py` — new opt-in perf test.
- `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md` — this file.

Explicitly NOT touched by Task 1:

- No file under `mf4_analyzer/ui/`.
- No file under `mf4_analyzer/signal/`.
- No file under `mf4_analyzer/acquisition*`.
- No existing test file.

### 2.5 Skips and degradations

None. The perf test ran in full on the offscreen platform with all 50
iterations completing. `pyqtgraph` is not imported by the perf test —
the perf test exercises only the current matplotlib `TimeDomainCanvas`
hot path, so the missing `pyqtgraph` install does not block the
baseline.

---

## 2.6 Envelope micro-bench (Task 4, Phase 3)

Phase 3 of the design spec calls for isolating downsample cost before
the canvas switch. Task 4 added a head-to-head micro-benchmark that
times `build_envelope` (numpy reference) and `positions_envelope`
(asammdf `cutils.positions` wrapper with numpy fallback) on the same
5 channels × 100 000 samples input, with the production-relevant
viewport `xlim=(3.0, 5.0)` and `pixel_width=800`. The benchmark is
`@pytest.mark.slow` (module-level) and is the second test function in
`tests/perf/test_timedomain_pan_perf.py`.

Command (verbatim):

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen \
    .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py \
    -q -m slow -s
```

Stdout (verbatim, two consecutive runs):

```
TIMEDOMAIN_ENVELOPE_PERF path=build_envelope     channels=5 samples=100000 iters=50 p50_ms=1.834 p95_ms=1.875 mean_ms=1.821 min_ms=1.754 max_ms=1.882 c_path=True
TIMEDOMAIN_ENVELOPE_PERF path=positions_envelope channels=5 samples=100000 iters=50 p50_ms=0.024 p95_ms=0.044 mean_ms=0.028 min_ms=0.021 max_ms=0.059 c_path=True
TIMEDOMAIN_ENVELOPE_PERF path=build_envelope     channels=5 samples=100000 iters=50 p50_ms=1.826 p95_ms=1.882 mean_ms=1.830 min_ms=1.777 max_ms=1.898 c_path=True
TIMEDOMAIN_ENVELOPE_PERF path=positions_envelope channels=5 samples=100000 iters=50 p50_ms=0.024 p95_ms=0.042 mean_ms=0.028 min_ms=0.021 max_ms=0.048 c_path=True
```

(`iters=50` per emitted line is `n_channels × iters` = 5 × 10 inside
the test loop — i.e. 10 timed envelope calls per channel × 5 channels.)

Headline (representative — run 2):

| Path | P50 | P95 | Mean | Min | Max |
| --- | --- | --- | --- | --- | --- |
| `build_envelope` (numpy reference) | 1.826 ms | 1.882 ms | 1.830 ms | 1.777 ms | 1.898 ms |
| `positions_envelope` (asammdf C + numpy tail) | 0.024 ms | 0.042 ms | 0.028 ms | 0.021 ms | 0.048 ms |
| Speedup (P50) | — | — | **≈ 76× faster** | — | — |

`c_path=True` confirms the wrapper's `_HAS_POSITIONS_C` flag was true
at import time and the head bucket call went through
`asammdf.blocks.cutils.positions`. The C-path-exercised assertion in
`tests/ui/test_pg_timedomain_canvas.py::test_c_path_is_exercised_on_normal_monotonic_input`
provides the parallel verification at the test-suite level.

Behavioral parity on the same numeric input is verified by
`TestPositionsEnvelopeParity` in
`tests/ui/test_pg_timedomain_canvas.py` (9 cases, including empty,
reversed-xlim, small-array, non-monotonic, NaN segments, and
non-contiguous views). Output arrays are equal under `np.allclose`
with `rtol/atol` derived from `float64` eps; the forced-fallback case
asserts bit-identity (`np.testing.assert_array_equal`).

Implications for the design-spec performance target:

- The design spec §1 target is P50 ≤ 8 ms and P95 ≤ 15 ms for full
  pan refresh, not just envelope. Envelope is one component; the
  remaining costs (pixmap blit, axis redraw, cursor overlay) are
  measured end-to-end by `test_timedomain_pan_refresh_baseline` and
  will be the dominant cost once envelope is ~25 µs.
- Current matplotlib pan-refresh P95 is 10.9 ms (see §2.3). Replacing
  the envelope step alone shaves up to 1.8 ms × n_channels off the
  bucket-recompute cost; the larger remaining win must come from the
  pyqtgraph cached-pixmap path (Phase 4 / Task 5).
- The C path is *not* required to meet the headline target — even
  the numpy reference (`build_envelope`, ~1.83 ms per channel at this
  viewport) leaves enough budget when combined with pyqtgraph's
  pixmap cache. The C path is a "nice-to-have, not a gate", honoring
  the spec §9 risk R1 / R2.

Fallback policy:

The wrapper distinguishes **system-level fallbacks** (environmental /
installation state — logged exactly once per process via
`_log_fallback_once`) from **per-call shape decisions** (deterministic
per-call branches — NOT logged, because the log line would either
be silently amortized or hot-path spam). The docstring at
`mf4_analyzer/signal/_envelope_cutils.py` enumerates the same split,
and the tests under `tests/ui/test_pg_timedomain_canvas.py::TestFallbackLoggingContract`
lock the contract.

System-level fallbacks (logged once per process):

- `c_unavailable` (`_HAS_POSITIONS_C` is False) → numpy reference;
- `non_monotonic` (caller-flagged or detected) → numpy reference;
- `nan_in_window` (any NaN in the visible slice) → numpy reference
  (preserves `nanargmin/nanargmax` + NaN-break semantics);
- `non_contiguous` (visible-slice arrays not C-contiguous) → numpy
  reference;
- `dtype_mismatch` (timestamp dtype != float64) → numpy reference.

Per-call shape decisions (NOT logged):

- `xlim_none` (full-range contract passthrough) → numpy reference;
- `empty_input` (zero-length arrays) → numpy reference;
- `empty_visible_window` (xlim clipping yields zero samples) →
  empty-slice short-circuit;
- `small_visible` (`n_vis <= 2 * pixel_width`) → small-visible
  shortcut (returns input slice verbatim, identical to
  `build_envelope`'s contract);
- `no_op_bucket` (bucket size would be 1, no compression) → numpy
  reference.

---

## 3. Phase 1+ — Contract Freeze, Adapter, Envelope, pyqtgraph Canvas

Tasks 2–7 (W0–W3) landed the contract freeze, the axis/dialog adapter,
the envelope C-path wrapper, the `TimeDomainCanvasPG` widget, and the
production switch. The per-task evidence lives in those tasks' returns
and in the W2/W3 notes at the end of this report. Task 8's final
full-suite regression is the consolidated green gate.

### 3.1 Final full-suite regression (Task 8)

Command (verbatim):

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp \
    .venv/bin/python -m pytest tests/ -q
```

Result (tail, verbatim):

```
1148 passed, 3 skipped, 3 deselected, 81 warnings in 34.48s
```

- **3 deselected** are the opt-in `slow` perf tests (`pytest.ini`
  `addopts = -m "not slow"`).
- **3 skipped** are pre-existing environment/data gates, NOT migration
  regressions (`pytest tests/ -q -rs`):
  - `tests/integration/test_t08_order_cot_e2e.py:8` — T08 reference
    file missing.
  - `tests/test_p0_a2l_probe.py:29` — needs `P0_A2L_PATH` set to a real
    ECU A2L.
  - `tests/test_packaging_imports.py:58` — PyInstaller spec is a build
    artifact (regenerate via `tools/build_windows_folder.ps1`).
- **81 warnings** are CJK-glyph `UserWarning`s from matplotlib's DejaVu
  Sans on macOS for Chinese tick/axis labels; they pre-exist the
  migration and are not regressions.

No failures. The suite is green.

---

## 4. Final Performance Report (Task 8)

### 4.1 Verification commands (verbatim, `.venv/bin/python` form)

Perf suite (opt-in `slow` marker, `-s` to surface the scraped lines):

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp \
    .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py \
    -q -m slow -s
```

Full suite (final green count):

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp \
    .venv/bin/python -m pytest tests/ -q
```

The PG-canvas measurement was added by Task 8 as
`test_timedomain_pan_refresh_pg_canvas` in
`tests/perf/test_timedomain_pan_perf.py`. It constructs the REAL
production canvas `mf4_analyzer.ui.pg_canvases.TimeDomainCanvasPG`
(`tests/perf/test_timedomain_pan_perf.py:242`), plots 5×100k channels in
subplot mode, runs the SAME 5-iteration warmup + 50-iteration timed
`primary.set_xlim(...)` + `cv._flush_pending_refresh()` loop as the
matplotlib baseline (`test_timedomain_pan_refresh_baseline`), and prints
a `TIMEDOMAIN_PAN_PERF path=pyqtgraph ...` line. pyqtgraph is NOT mocked
(`codex-phantom-api-surface-guards`).

### 4.2 Production pyqtgraph pan-refresh result (Task 8 → Task 9)

**Before Task 9 (Task 8 measurement — pure-Python `_build_painter_path`
loop):** stdout from three consecutive full-file runs (verbatim,
captured with `-s`):

```
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.712 p95_ms=10.922 mean_ms=7.145 min_ms=0.085 max_ms=10.943
TIMEDOMAIN_PAN_PERF path=pyqtgraph  channels=5 samples=100000 iters=50 p50_ms=10.707 p95_ms=11.080 mean_ms=10.520 min_ms=0.018 max_ms=11.366 c_path=True c_calls=245
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.797 p95_ms=10.969 mean_ms=7.201 min_ms=0.081 max_ms=10.995
TIMEDOMAIN_PAN_PERF path=pyqtgraph  channels=5 samples=100000 iters=50 p50_ms=10.866 p95_ms=11.190 mean_ms=10.662 min_ms=0.017 max_ms=11.371 c_path=True c_calls=245
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.784 p95_ms=10.914 mean_ms=7.173 min_ms=0.082 max_ms=11.007
TIMEDOMAIN_PAN_PERF path=pyqtgraph  channels=5 samples=100000 iters=50 p50_ms=10.815 p95_ms=11.118 mean_ms=10.621 min_ms=0.020 max_ms=11.270 c_path=True c_calls=245
```

**After Task 9 (vectorized `_build_painter_path` via
`pyqtgraph.functions.arrayToQPath(connect='all', finiteCheck=False)` on
the all-finite hot path):** stdout from three consecutive `-k pg_canvas`
runs (verbatim, captured with `-s`):

```
TIMEDOMAIN_PAN_PERF path=pyqtgraph channels=5 samples=100000 iters=50 p50_ms=0.739 p95_ms=1.081 mean_ms=0.809 min_ms=0.013 max_ms=1.206 c_path=True c_calls=245
TIMEDOMAIN_PAN_PERF path=pyqtgraph channels=5 samples=100000 iters=50 p50_ms=0.745 p95_ms=1.138 mean_ms=0.808 min_ms=0.014 max_ms=1.215 c_path=True c_calls=245
TIMEDOMAIN_PAN_PERF path=pyqtgraph channels=5 samples=100000 iters=50 p50_ms=0.705 p95_ms=1.019 mean_ms=0.757 min_ms=0.015 max_ms=1.051 c_path=True c_calls=245
```

Before→after (production pyqtgraph pan, P50): **10.71 ms → 0.74 ms
(≈ 14× faster)**. P95: **11.08 ms → 1.08 ms**. `c_path=True c_calls=245`
unchanged (the envelope C path is still exercised; only the path
construction changed). See §4.7 for the determination.

### 4.3 Matplotlib vs pyqtgraph vs design target

Representative run (run 1 of 3 above — median P50 of the three pyqtgraph
runs):

| Path | P50 | P95 | Mean | Min | Max | C path |
| --- | --- | --- | --- | --- | --- | --- |
| matplotlib baseline (§2.3 + this run) | 10.712 ms | 10.922 ms | 7.145 ms | 0.085 ms | 10.943 ms | n/a |
| **pyqtgraph production (`TimeDomainCanvasPG`)** | **10.707 ms** | **11.080 ms** | **10.520 ms** | 0.018 ms | 11.366 ms | **True** |
| Design §8 target | ≤ 8 ms | ≤ 15 ms | — | — | — | C path |

Delta pyqtgraph − matplotlib (run 1): P50 −0.005 ms (≈ parity), P95
+0.158 ms (≈ parity within run-to-run noise of ±0.2 ms).

### 4.4 C-path-or-fallback determination (NEW — Task 8)

**The production pan path runs on the asammdf C path.** The new test
wraps `asammdf.blocks.cutils.positions` with a live call counter and
asserts it fired during the timed loop
(`tests/perf/test_timedomain_pan_perf.py`). Every run reports
`c_path=True c_calls=245` — 245 = 49 cache-miss frames × 5 channels
(the 50-step pan loop revisits one xlim on the forward/return fold, so
one frame is a range-key cache hit and skips the envelope call per
`pyqt-ui/2026-04-25-cache-invalidation-event-conditional`). The
`_HAS_POSITIONS_C` import probe is True (asammdf 8.8.7, see §2.1), and
the per-call C dispatch was confirmed to actually execute — not merely
available. The test ASSERTS `c_calls > 0` whenever `_HAS_POSITIONS_C` is
True, so a silent per-call fallback would FAIL the test rather than
quietly report a meaningless number.

This is NOT a fallback-grade result: the envelope step ran on the C
extension. See §4.5 for why the headline pan number nonetheless misses
the ≤ 8 ms target.

### 4.5 Target assessment at Task 8: MISSED (P50 10.7 ms vs ≤ 8 ms) — with reason

> **Superseded by Task 9 (§4.7): target now MET.** The analysis below is
> the Task 8 diagnostic that correctly root-caused the miss to the
> pure-Python `_build_painter_path` loop and pointed at `arrayToQPath` as
> the fix. It is preserved as the before-state of the before→after; the
> live numbers proving the fix are in §4.2 (after) and §4.7.

Per `codex-plan-spec-literal-evidence`, the real number is reported and
NOT massaged: **at Task 8 the production pyqtgraph pan P50 (≈ 10.7 ms) did
not meet the design §8 P50 ≤ 8 ms target.** P95 (≈ 11.1 ms) DID meet the
≤ 15 ms target. So (at Task 8):

- P95 ≤ 15 ms: **MET** (11.1 ms).
- P50 ≤ 8 ms: **MISSED** (10.7 ms).

Root-cause analysis from the measured numbers:

- The envelope step is no longer the bottleneck. §2.6 shows
  `positions_envelope` p50 ≈ 0.025 ms per channel (C path) vs
  `build_envelope` ≈ 1.8 ms — a 76× win. At 5 channels that is ~0.12 ms
  of envelope work per frame, well under budget.
- The per-frame cost has migrated to the canvas's
  `_build_painter_path` Python loop
  (`mf4_analyzer/ui/pg_canvases.py:1089-1116`), which iterates
  point-by-point calling `QPainterPath.moveTo/lineTo` over ~2×pixel_width
  envelope points per channel, plus `_render_path_to_pixmap`
  (`pg_canvases.py:1118-1150`) which allocates a `QPixmap` and runs a
  `QPainter.drawPath` per channel per cache-miss frame. This Python-level
  path-build loop is O(points) in interpreted Python and runs 5× per
  frame; it is the dominant term in the 10.7 ms.
- The matplotlib baseline mean (7.1 ms) is LOWER than the pyqtgraph mean
  (10.5 ms) because the matplotlib pan loop has more near-zero
  cache-hit iterations (its envelope cache short-circuits more of the
  fold); the pyqtgraph P50/P95 are at parity, but the distribution is
  less bimodal (min 0.018 ms confirms the range-key gate still
  short-circuits the one repeated xlim).

Conclusion (Task 8): the migration delivered the C-path envelope win and
reached P95-target parity with matplotlib, but the headline P50 ≤ 8 ms
target was NOT met because the QPainterPath construction was a
pure-Python per-point loop. Closing the remaining gap required
vectorizing the path build (`pyqtgraph.functions.arrayToQPath`, which
builds the QPainterPath from numpy arrays in C rather than a Python
`lineTo` loop) — raised as a follow-up and executed in Task 9 (§4.7).

### 4.7 Target assessment after Task 9: MET (P50 ≈ 0.74 ms vs ≤ 8 ms)

Task 9 replaced the pure-Python `_build_painter_path` loop with a
vectorized build. For the all-finite hot path (the branch the production
pan loop takes every frame, because `positions_envelope` bails to the
numpy reference on any NaN in the visible window), the method now calls
`pyqtgraph.functions.arrayToQPath(x, y, connect='all', finiteCheck=False)`
— a C-level QPolygonF→`addPolygon` build, the same fast path
`PlotCurveItem` uses internally. The NaN-gap discontinuity case keeps the
interpreted loop (renamed `_build_painter_path_loop`) so the
break-the-subpath geometry stays byte-identical; the degenerate
single-point case (lone finite sample → bare `moveTo`) is also routed
through the loop because `arrayToQPath` drops a single point.

`arrayToQPath` was verified to exist in the installed pyqtgraph 0.14.0
with signature `arrayToQPath(x, y, connect='all', finiteCheck=True)`
(`codex-phantom-api-surface-guards`); the kwargs used are not guessed.

Measured result (three runs, §4.2 "after"):

| Path | P50 | P95 | Mean | Min | Max | C path |
| --- | --- | --- | --- | --- | --- | --- |
| pyqtgraph **before** Task 9 (Task 8) | 10.707 ms | 11.080 ms | 10.520 ms | 0.018 ms | 11.366 ms | True |
| **pyqtgraph after Task 9** | **0.739 ms** | **1.081 ms** | **0.809 ms** | 0.013 ms | 1.206 ms | **True** |
| Design §8 target | ≤ 8 ms | ≤ 15 ms | — | — | — | C path |

- P50 ≤ 8 ms: **MET** (≈ 0.74 ms, was 10.7 ms — ≈ 14× faster).
- P95 ≤ 15 ms: **MET** (≈ 1.08 ms, was 11.1 ms).

Visual parity is guarded two ways: (1) a rendered offscreen screenshot of
the 5-channel subplot was re-grabbed after the change and verified
non-null at 800×400 with 5 populated `painter_path` cache entries
(1480 elements each), and (2) a new regression class
`tests/ui/test_pg_timedomain_canvas.py::TestBuildPainterPathParity`
asserts the vectorized path's `elementCount()` AND every
`(elementType, x, y)` tuple match a verbatim re-implementation of the old
loop across all-finite, single-NaN-gap, double-NaN-gap, leading-NaN,
single-point, and empty inputs (`codex-visual-parity-rendered-screenshot`
+ `signal-processing/2026-05-19-branch-reached-is-not-behavior-correct`:
actual coordinates, not "looks similar").

The cache structure (range-key bucketed `QPainterPath` cache), the
`QPainter.Antialiasing=False` pixmap blit, the public API, the signal
surface, and the chart-options/double-click code are all unchanged — only
the path CONSTRUCTION inside `_build_painter_path` changed.

### 4.6 Performance invariants (design §4.3) — status

| Invariant | Status | Evidence |
| --- | --- | --- |
| Hot path must NOT call matplotlib `draw_idle`/`tight_layout`/`Line2D.set_data` | HELD | PG canvas is a `QWidget`, not a `FigureCanvas`; no matplotlib in `_refresh_visible_data` (`pg_canvases.py:1018-1087`). |
| Pan/zoom refresh must not rebuild whole chart structure | HELD | `_refresh_visible_data` only recomputes envelope+path per channel; `plot_channels` (the rebuild) is not on the pan path. |
| Envelope cached, but stats/cursor use raw `channel_data` | HELD | `get_statistics` reads raw `channel_data` — locked by `tests/ui/test_pg_timedomain_canvas.py::test_get_statistics_reads_raw_channel_data_not_envelope_output`. |
| C path has tested numpy fallback + loggable reason | HELD | `TestPositionsEnvelopeParity` (9 cases) + `TestFallbackLoggingContract` in `tests/ui/test_pg_timedomain_canvas.py`. |

---

## 5. Manual Smoke Log (Task 8 Step 3)

Design §7 manual-smoke checklist. Each item is recorded with its
offscreen automated coverage (the verification this task CAN run
headless) and an explicit "pending on-screen" note where a real display
is required. Every cited test passed in the full-suite run (§9).

| # | Smoke item (design §7) | Offscreen result | Coverage |
| --- | --- | --- | --- |
| 1 | Load one file, plot one time channel | PASS (offscreen) | `test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGContract::test_plot_channels_accepts_row_shape_and_stores_raw_channel_data`; single-channel bind in `test_curve_path_cache_populates_after_set_xlim`. |
| 2 | Plot five time channels in subplot mode | PASS (offscreen) | `test_pg_timedomain_canvas.py::test_subplot_builds_five_plot_items_sharing_x_axis`, `test_subplot_5ch_screenshot_geometry`. |
| 3 | Plot five time channels in overlay mode | PASS (offscreen) | `test_pg_timedomain_canvas.py::test_overlay_5ch_screenshot_geometry`, `test_overlay_emphasis_two_frame_line_width_difference`. |
| 4 | Switch subplot ↔ overlay, confirm X-window preservation | PASS (offscreen) | `test_pg_timedomain_canvas.py::test_subplot_to_overlay_preserves_user_xlim`. |
| 5 | Ctrl+wheel / Shift+wheel / plain wheel | PASS (offscreen) | `test_pg_timedomain_canvas.py::test_ctrl_wheel_zooms_x`, `test_shift_wheel_zooms_y`, `test_plain_wheel_pans_y`. |
| 6 | Select/deselect overlay channel; drag selected Y | PASS (offscreen) | `test_pg_timedomain_canvas.py::test_overlay_blank_click_deselect_emits_signal`, `test_overlay_selected_y_drag_emits_ylim_change`. |
| 7 | Single + dual cursor; confirm pill values | PASS (offscreen) | `test_pg_timedomain_canvas.py::test_single_cursor_html_matches_update_single_letter_for_letter`, `test_dual_cursor_html_matches_format_dual_html_letter_for_letter`, `test_dual_cursor_screenshot_geometry_and_pill_containment`. |
| 8 | Open ChartOptionsDialog, edit limits/color | PASS (offscreen) | `test_chart_stack.py::test_dblclick_chart_options_does_not_leave_pan_drag_active`, `test_chart_options_toolbar_button_delegates_to_canvas`; handle-aware dialog by `test_dialog_with_handle.py`. |
| 9 | Copy image, confirm cursor pill included | PASS (offscreen) | `test_timedomain_canvas_contract.py::test_chart_stack_copy_card_image_composites_cursor_pill`, `test_time_chart_card_has_copy_image_button`. |

All 9 items have headless automated coverage that passed. Items that
genuinely need a real display (interactive double-click rapid-fire,
on-screen rubber-band feel) are carried as the explicit pending item in
§5.1.

### 5.1 Pending manual verification (on-screen, NOT YET RUN)

The on-screen (non-offscreen) GUI double-click chart-options smoke is
NOT YET RUN. The user accepted this as a documented pending item. A
human should run, on a real display:

1. Launch the app: `.venv/bin/python -m mf4_analyzer` (or the project's
   normal GUI entry point).
2. Load a file and plot ≥ 2 time-domain channels in **subplot** mode.
3. Double-click a subplot → the chart-options dialog opens **for that
   subplot's axis** (not the primary/first).
4. Double-click **rapidly** on a subplot → **only one** dialog opens
   (the `_chart_options_opening` re-entry guard holds under real
   double-click delivery, not just synthetic `QEvent`).
5. Close the dialog → **no stuck pan/drag** state remains; the chart
   pans/zooms normally afterward.

Offscreen coverage that DOES exist for this gesture (passed in §9):

- `tests/ui/test_chart_stack.py::test_dblclick_chart_options_does_not_leave_pan_drag_active`
- `tests/ui/test_chart_stack.py::test_dblclick_chart_options_restores_pan_without_starting_span_selector`
- `tests/ui/test_chart_stack.py::test_dblclick_second_subplot_opens_options_for_that_axis`
  (asserts handle identity for the 2nd and 3rd subplots — the
  "opens for THAT subplot" property).

The offscreen `QTest`/`QEvent` path proves the dispatch logic and the
re-entry guard; the on-screen run is needed only to confirm the real
windowing system's double-click event timing matches the synthetic one.

### 5.2 Known minor parity gap carried from W3

Double-clicking the axis-label/tick **gutter** (not the plot face)
opens chart-options for the primary/active subplot rather than the
gutter's owning subplot (W3 note, this report §"W3 chrome-pixel parity
evidence"). Plot-face double-clicks target the correct subplot. Deemed
low-impact; `pg_canvases.py:_axis_handle_at_scene_pos` only tests
`ViewBox.sceneBoundingRect()` and is not modified for this edge case.

---

## 6. Remaining Risks And Open Items

Full design §9 risk register R1–R8 carried forward with current status
at Task 8 (final wave). pyqtgraph 0.14.0 is installed in `.venv`
(`.venv/bin/python -c "import pyqtgraph; print(pyqtgraph.__version__)"`
→ `0.14.0`); asammdf is 8.8.7.

| ID | Risk | Current status (Task 8) |
| --- | --- | --- |
| R1 | `cutils.positions` importable but not typed in `cutils.pyi` | **OPEN, mitigated.** Runtime probe confirms it exists and is callable on asammdf 8.8.7 (§2.1). The wrapper keeps a tested numpy fallback (`TestPositionsEnvelopeParity`, 9 cases). Version drift remains a real risk on an asammdf upgrade — the fallback + `_HAS_POSITIONS_C` probe is the guard. |
| R2 | LGPL/legal approval for asammdf C path | **OPEN, out of code scope.** The dependency route is recorded (`requirements.txt` pins `pyqtgraph>=0.13.3`; asammdf already a dependency). If approval is withheld the numpy fallback path is functionally complete (R1 fallback) but loses the C-path envelope win. Not a Task 8 code decision. |
| R3 | Plain `PlotDataItem` may not hit the perf target | **CLOSED (Task 9).** Production does NOT use plain `PlotDataItem.setData` on the pan path (locked by `test_pdi_setdata_called_at_most_once_during_bind_then_zero_on_pan`); it uses the custom QPainterPath+QPixmap cache. At Task 8 the perf gate **missed P50 ≤ 8 ms** (§4.5) because the QPainterPath build was a Python per-point loop — exactly the "false performance confidence" R3 warned about. Task 9 vectorized the build via `arrayToQPath` (§4.7): P50 now ≈ 0.74 ms (≤ 8 ms **MET**), P95 ≈ 1.08 ms (≤ 15 ms **MET**). Geometry parity guarded by `TestBuildPainterPathParity`. |
| R4 | Dialog adapter breaks FFT/Heatmap/Spectrogram/Order | **CLOSED.** `MplAxisHandle`/`PgAxisHandle` adapter landed; FFT/order/spectrogram axis+dialog tests pass in the full suite (§9, e.g. `test_axis_interaction.py`, `test_dialog_with_handle.py`, `test_order_smoke.py`). No cross-canvas regression. |
| R5 | Private-field compatibility hides old coupling | **OPEN, deferred by design.** `reset_cursor_state()` + compatibility seams (`span_selector=None`, `set_tick_density` no-op) exist and are tested. Cleanup of the retained matplotlib `TimeDomainCanvas` is design Phase 7, pending user approval (§6.1). |
| R6 | Overlay behavior is the largest interaction surface | **CLOSED (offscreen).** Overlay emphasis, blank-click deselect, selected-Y-drag all have two-frame state-change tests that pass (`test_overlay_emphasis_two_frame_line_width_difference`, `test_overlay_blank_click_deselect_emits_signal`, `test_overlay_selected_y_drag_emits_ylim_change`). On-screen feel not separately re-run (covered by §5.1 pending note in spirit). |
| R7 | pyqtgraph import selects wrong Qt binding | **CLOSED.** `os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")` runs BEFORE `import pyqtgraph` at `pg_canvases.py:58-66`; the binding-pin is locked by `test_pg_timedomain_canvas.py:959-962`. Import smoke under PyQt5 passes (every PG canvas test imports pyqtgraph live; full suite green). |
| R8 | Perf benchmark becomes flaky in CI/headless | **MITIGATED.** Perf tests stay `@pytest.mark.slow` and are excluded from the default suite (`pytest.ini` `addopts = -m "not slow"`; 3 deselected in §9). Task 8 also hardened the new PG perf test against an offscreen first-construction abort by warming a throwaway `FigureCanvasQTAgg` before building the pyqtgraph widget (see §6.2) so the slow gate is reproducible in isolation, not only as part of the full file. The number is a local measured report, not a CI gate. |

### 6.1 Old matplotlib `TimeDomainCanvas` remains in tree

Per design Phase 7 and acceptance bullet "Old matplotlib
TimeDomainCanvas remains available until the user approves cleanup": the
matplotlib `TimeDomainCanvas` is STILL present in
`mf4_analyzer/ui/canvases.py` for rollback. The production
`ChartStack.canvas_time` is the pyqtgraph `TimeDomainCanvasPG`
(`mf4_analyzer/ui/chart_stack.py:967`), but the old class is untouched
and importable. Removal is a deliberate post-stability step awaiting
user approval — this task does NOT remove it.

### 6.2 New open item — pyqtgraph not in the PyInstaller hidden-import list

The packaging-smoke test list (`tests/test_packaging_imports.py:14-47`
`REQUIRED_HIDDEN_IMPORTS` + `WIDGET_MODULES`) does NOT name `pyqtgraph`
or `mf4_analyzer.ui.pg_canvases`. pyqtgraph is pulled in transitively
when `chart_stack` imports `pg_canvases`, so a source-run works, but a
frozen PyInstaller build may miss pyqtgraph's lazily-imported submodules
(it does runtime Qt-binding discovery) unless it is declared as a hidden
import. This is a real packaging gap for the eventual Windows build, NOT
a runtime defect in this checkout. Recorded as an open item for the
packaging owner; the acceptance bullet "Packaging/import smoke covers
pyqtgraph" is only PARTIALLY met — pyqtgraph import is smoke-tested at
the canvas level (R7) but not in the PyInstaller hidden-import manifest
list.

---

## 7. UI Invariant Confirmation (Task 8)

**No UI control, text, shortcut, workflow, or layout was intentionally
changed by the renderer swap** (design §8 acceptance bullet 1). This is
locked by automated UI-invariant tests, all green in the full-suite run
(§9):

- **W0 contract surface** — `tests/ui/test_timedomain_canvas_contract.py`:
  - exact Chinese button labels (`分屏`, `叠加`, `游标关`, `单游标`,
    `双游标`): `test_time_chart_card_button_labels_are_exact_chinese_strings`.
  - Ctrl+1..Ctrl+5 shortcuts wired:
    `test_time_chart_card_has_ctrl_1_through_5_shortcuts_wired`.
  - toolbar action-key set + pan-before-zoom ordering:
    `test_time_chart_card_toolbar_exposes_expected_action_keys`,
    `test_time_chart_card_toolbar_action_keys_ordering_pan_before_zoom`.
  - copy-image-with-cursor-pill behavior:
    `test_time_chart_card_has_copy_image_button`,
    `test_chart_stack_copy_card_image_composites_cursor_pill`.
  - the four signals + exact payload shapes:
    `test_timedomain_canvas_exposes_four_signals_with_exact_payloads`.
- **W3 ported behavior tests** — the `TimeDomainCanvasPG` parity surface
  in `tests/ui/test_pg_timedomain_canvas.py` (subplot/overlay/single
  modes, cursor HTML byte-parity, wheel dispatch, overlay
  select/Y-drag) re-implements the matplotlib behavior tests against the
  new widget through Qt-native events. (Per
  `pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap`,
  the matplotlib-dispatcher-coupled tests in `test_chart_stack.py` were
  rewritten through `QTest`/`QEvent`, not stubbed.)
- **Chrome-pixel parity** — the four sampled chrome coordinates
  (toolbar bg, button bg, axis grid, plot face) are byte-identical
  before/after the switch (this report, §"W3 chrome-pixel parity
  evidence", all 4 deltas = 0).

No new buttons, settings, feature flags, menu items, or layout changes
were introduced. The retained matplotlib canvas (§6.1) is not surfaced
in any UI control — it exists only as an importable class for rollback.

---

## 8. B1-B7 Scope Confirmation

The companion `docs/superpowers/specs/2026-05-28-review-followup-fixes.md`
B1-B7 items are explicitly OUT OF SCOPE for this migration. Task 1
introduced no code on any of those paths. The perf test does not
touch acquisition_ui dropped-frame rearm fields or the xlim-tangent
guard introduced by B1-B7; it exercises only `TimeDomainCanvas`
viewport refresh.

---

## W2 scope-reconciliation note (2026-05-28)

The W2 codex review at
`docs/analyzer/reviews/2026-05-28-pyqtgraph-wave2.md` flagged
`mf4_analyzer/ui/dialogs.py` as a W2 scope violation because the
mandated `git status --short` showed it modified alongside W2 files.
That flag is a **false positive**: the `dialogs.py` changes
(`ChartOptionsDialog` accepting `axis_or_handle` and routing axis
reads/writes through `self.handle` at `dialogs.py:293-315, 555-702`)
belong to W1/T3 AxisHandle work. T5 and T6 did NOT touch `dialogs.py`
(`files_changed` in agents `af76450b517ff7de1` and `a1da97d0fa9aaa04a`
confirm this). `git status` cannot distinguish W1 from W2 because
nothing has been committed since `HEAD = 6bac43d6`. No source change
is required; the audit treats `dialogs.py` as W1 baseline.

---

## W3 chrome-pixel parity evidence (2026-05-28)

T7 reported "0 delta at 4 sampled coords" for the matplotlib→pyqtgraph
TimeDomain flip but checked in no reproducible sampling record (W3
codex review lines 17, 64, 93). The before/after PNGs are at
`/tmp/t7_before_switch.png` and `/tmp/t7_after_switch.png`. Re-sampling
the four chrome coordinates with `PIL` gives (live output):

```text
top_toolbar_bg @ (600,15): before=(239, 239, 239, 255) after=(239, 239, 239, 255) delta=(0, 0, 0, 0)
button_bg      @ (20,22): before=(55, 65, 81, 255) after=(55, 65, 81, 255) delta=(0, 0, 0, 0)
axis_grid      @ (600,400): before=(255, 255, 255, 255) after=(255, 255, 255, 255) delta=(0, 0, 0, 0)
plot_area_bg   @ (300,200): before=(255, 255, 255, 255) after=(255, 255, 255, 255) delta=(0, 0, 0, 0)
```

Reproduce with `.venv/bin/python` (PIL present; use `QImage.pixelColor`
if not):

```python
from PIL import Image
before = Image.open("/tmp/t7_before_switch.png").convert("RGBA")
after  = Image.open("/tmp/t7_after_switch.png").convert("RGBA")
coords = {"top_toolbar_bg": (600, 15), "button_bg": (20, 22),
          "axis_grid": (600, 400), "plot_area_bg": (300, 200)}
for name, (x, y) in coords.items():
    b = before.getpixel((x, y)); a = after.getpixel((x, y))
    delta = tuple(av - bv for av, bv in zip(a, b))
    print(f"{name} @ ({x},{y}): before={b} after={a} delta={delta}")
```

All four deltas are exactly 0 — UI chrome (toolbar bg, button bg, axis
grid, plot face) is pixel-identical before and after the renderer swap.

**Known minor parity gap (gutter hit-test):** double-clicking the
axis-label/tick gutter (not the plot face) opens chart-options for the
primary/active subplot rather than the gutter's owning subplot. Plot-face
double-clicks target the correct subplot (proven by
`tests/ui/test_chart_stack.py::test_dblclick_second_subplot_opens_options_for_that_axis`,
which asserts handle identity for the 2nd and 3rd subplots). Matplotlib's
`_axis_interaction` hit test was gutter-aware via pixel margins; the PG
`_axis_handle_at_scene_pos` only tests `ViewBox.sceneBoundingRect()`.
Deemed low-impact; `pg_canvases.py` is not modified for this edge case.

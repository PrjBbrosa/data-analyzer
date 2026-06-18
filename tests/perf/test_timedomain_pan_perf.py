"""Opt-in TimeDomainCanvas pan/zoom refresh micro-benchmark.

Implements Task 1 step 3 of the pyqtgraph migration plan
(`docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md`).

Scenario:
    - 5 channels x 100_000 samples each
    - synthetic monotonic timestamps + smooth sinusoids
    - repeated ``primary.set_xlim(...)`` + ``cv._flush_pending_refresh()``
      mimicking a user dragging the pan tool one window at a time

Measurement:
    - Discard a small warmup batch (envelope cache cold-start, first
      matplotlib draw_idle dispatch).
    - Record per-iteration wall-clock in milliseconds.
    - Report P50 and P95 (and N, mean, min, max for sanity).

This test is marked ``slow`` so the default suite does not run it. The
test never asserts a numeric threshold — it is a measurement gate
whose stdout the migration's results report consumes.
"""

from __future__ import annotations

import importlib.util
import os
import statistics
import time

import numpy as np
import pytest

# Mirror tests/ui/conftest.py: force offscreen before QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# --- Module-level skip conditions ----------------------------------------
# We use importlib.util.find_spec rather than MagicMocking PyQt5; this honors
# the codex-phantom-api-surface-guards lesson: probe real installability
# without faking the dependency surface.
_HAS_PYQT5 = importlib.util.find_spec("PyQt5") is not None
if not _HAS_PYQT5:  # pragma: no cover - import-time gate
    pytest.skip("PyQt5 not installed; perf test requires Qt offscreen.",
                allow_module_level=True)


pytestmark = pytest.mark.slow


# --- helpers --------------------------------------------------------------


def _qapp_or_skip():
    """Initialize a QApplication on the offscreen platform, or skip."""
    try:
        from PyQt5.QtWidgets import QApplication
    except Exception as exc:  # pragma: no cover - import gate
        pytest.skip(f"PyQt5 import failed: {exc!r}")
    app = QApplication.instance()
    if app is None:
        try:
            app = QApplication([])
        except Exception as exc:  # pragma: no cover - offscreen gate
            pytest.skip(f"QApplication could not initialize offscreen: {exc!r}")
    return app


def _make_channels(n_channels: int, n_samples: int):
    """Build (name, True, t, sig, color, unit, fid) rows for plot_channels.

    Smooth deterministic signals so envelope output is non-trivial but
    every sample is finite (no NaN-segment branch dominating the timer).
    """
    rng = np.random.default_rng(42)
    t = np.linspace(0.0, 10.0, n_samples)
    rows = []
    palette = ["#1769e0", "#dc2626", "#16a34a", "#a855f7", "#f59e0b",
               "#0891b2", "#e11d48"]
    for i in range(n_channels):
        # Mix a few harmonics plus a tiny noise floor so the envelope
        # min/max bands are non-degenerate at any visible viewport.
        sig = (
            np.sin(2 * np.pi * (1.0 + 0.3 * i) * t)
            + 0.5 * np.cos(2 * np.pi * (5.0 + 0.7 * i) * t)
            + 0.05 * rng.standard_normal(n_samples)
        ).astype(np.float64)
        rows.append(
            (f"[A] ch{i}", True, t, sig, palette[i % len(palette)],
             "g", "fidA"),
        )
    return rows


def _percentile(values: list[float], q: float) -> float:
    """Compute the q-th percentile (0..100) using nearest-rank."""
    if not values:
        return float("nan")
    s = sorted(values)
    # nearest-rank: index = ceil(q/100 * N) - 1, clamped
    k = max(0, min(len(s) - 1, int(round((q / 100.0) * len(s))) - 1))
    return s[k]


# --- the benchmark -------------------------------------------------------


# test_timedomain_pan_refresh_baseline was removed in Phase D (2026-06-18)
# when TimeDomainCanvas (matplotlib) was retired.  The pyqtgraph benchmark
# below (test_timedomain_pan_refresh_pg_canvas) is the surviving gate.


def test_timedomain_pan_refresh_pg_canvas():
    """Time the NEW pyqtgraph production pan refresh on 5x100k channels.

    This is the post-migration hot path that ChartStack now uses in
    production (W3): the pyqtgraph ``TimeDomainCanvasPG`` whose
    ``set_xlim`` fires ``sigXRangeChanged`` → 40 ms QTimer-debounced
    ``_refresh_visible_data`` → ``positions_envelope`` (asammdf C path)
    → visible ``PlotDataItem.setData``. We drive the SAME workload,
    warmup, and pan loop as ``test_timedomain_pan_refresh_baseline`` so
    the report can compare matplotlib-vs-pyqtgraph apples-to-apples.

        primary.set_xlim(lo, hi)   # fires sigXRangeChanged → schedules
                                   # the debounced refresh QTimer
        cv._flush_pending_refresh()  # drains synchronously →
                                     # _refresh_visible_data →
                                     # positions_envelope + setData,
                                     # gated on the per-channel
                                     # range key so same-xlim is a no-op

    Per ``codex-phantom-api-surface-guards``: a REAL ``TimeDomainCanvasPG``
    is constructed — pyqtgraph is NOT mocked. The C path is verified
    LIVE by wrapping ``asammdf.blocks.cutils.positions`` with a call
    counter and asserting it fired during the timed loop; the emitted
    line records ``c_path=True/False`` so a fallback-grade run is
    self-evident in the report.
    """
    from PyQt5.QtCore import QCoreApplication

    _qapp_or_skip()
    # Defer canvas/env imports until after QApplication exists (mirrors
    # the matplotlib baseline + the rest of the UI suite).
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    from mf4_analyzer.signal import _envelope_cutils as ec

    # --- LIVE C-path verification ---------------------------------------
    # _HAS_POSITIONS_C is the import-time probe; but a per-call C dispatch
    # can still fall back (NaN window, non-contiguous, small visible,
    # etc.). To record what ACTUALLY ran on the hot path, wrap the C
    # function with a counter. We patch the same object the wrapper calls
    # (``asammdf.blocks.cutils.positions``) so the counter reflects real
    # C invocations, not just the flag.
    c_calls = {"n": 0}
    from asammdf.blocks import cutils as _cutils
    _orig_positions = getattr(_cutils, "positions", None)

    if ec._HAS_POSITIONS_C and callable(_orig_positions):
        def _counting_positions(*args, **kwargs):
            c_calls["n"] += 1
            return _orig_positions(*args, **kwargs)
        _cutils.positions = _counting_positions

    # Stabilize the offscreen Qt raster paint backend BEFORE constructing
    # the pyqtgraph GraphicsLayoutWidget. Under ``QT_QPA_PLATFORM=offscreen``
    # the FIRST pyqtgraph widget built in a fresh process aborts in
    # ``QWidget.__init__`` unless a matplotlib ``FigureCanvasQTAgg`` (which
    # initializes the Agg/raster paint device the offscreen plugin shares)
    # has been constructed first. The full perf file gets this for free
    # because ``test_timedomain_pan_refresh_baseline`` runs earlier; we
    # construct + discard a throwaway canvas here so the PG test is robust
    # in isolation (``-k pg_canvas``) too. This is a test-harness ordering
    # quirk, NOT a production path — production always has the matplotlib
    # backend imported and a live main window before any canvas is built.
    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        _warmup = FigureCanvasQTAgg(Figure())
        _warmup.draw()
        del _warmup
    except Exception:
        pass
    QCoreApplication.processEvents()

    try:
        cv = TimeDomainCanvasPG()
        cv.resize(1600, 800)
        # Force a real layout pass so the ViewBox has non-zero geometry;
        # otherwise _current_pixel_width() falls back to MAX_PTS and the
        # bucket count (hence C-path eligibility) differs from production.
        cv.show()
        QCoreApplication.processEvents()

        n_channels = 5
        n_samples = 100_000
        rows = _make_channels(n_channels, n_samples)
        # subplot mode mirrors the matplotlib baseline: per-axis envelope
        # work across 5 stacked ViewBoxes, the typical interactive layout.
        cv.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        primary = cv._primary_xaxis_ax
        assert primary is not None, "TimeDomainCanvasPG primary axis not set"

        # Drain any plot_channels-scheduled refresh so the warmup starts
        # from a known-quiet state.
        cv._refresh_pending = False
        if cv._refresh_timer.isActive():
            cv._refresh_timer.stop()

        # Identical pan schedule to the matplotlib baseline: a 2-second
        # window walked t=0..8 then back t=8..0 in 25+25 steps.
        window_w = 2.0
        starts = np.concatenate([
            np.linspace(0.0, 8.0, 25),
            np.linspace(8.0, 0.0, 25),
        ])

        # Warmup: first refreshes pay first-draw + cache-miss cost.
        for s in starts[:5]:
            primary.set_xlim(float(s), float(s) + window_w)
            cv._flush_pending_refresh()

        # Reset the C-call counter AFTER warmup so the recorded flag
        # reflects the timed loop only.
        c_calls["n"] = 0

        # Timed loop.
        samples_ms: list[float] = []
        for s in starts:
            lo = float(s)
            hi = lo + window_w
            t0 = time.perf_counter()
            primary.set_xlim(lo, hi)
            cv._flush_pending_refresh()
            t1 = time.perf_counter()
            samples_ms.append((t1 - t0) * 1000.0)

        c_path_active = ec._HAS_POSITIONS_C and c_calls["n"] > 0

        n = len(samples_ms)
        p50 = _percentile(samples_ms, 50.0)
        p95 = _percentile(samples_ms, 95.0)
        mean = statistics.fmean(samples_ms)
        mn = min(samples_ms)
        mx = max(samples_ms)

        # Emit a single line the results report scrapes — same field
        # shape as the matplotlib baseline plus an explicit c_path flag.
        print(
            f"\nTIMEDOMAIN_PAN_PERF "
            f"path=pyqtgraph channels={n_channels} samples={n_samples} "
            f"iters={n} p50_ms={p50:.3f} p95_ms={p95:.3f} "
            f"mean_ms={mean:.3f} min_ms={mn:.3f} max_ms={mx:.3f} "
            f"c_path={c_path_active} c_calls={c_calls['n']}"
        )

        # Smoke assertions only — never gate on absolute timing.
        assert n > 0
        assert all(v >= 0.0 for v in samples_ms)
        # The range gate populated, proving the hot path ran (not a no-op).
        assert len(cv._last_range_key) >= 1
        # After the last flush, no pending refresh should remain.
        assert cv._refresh_pending is False
        assert cv._refresh_timer.isActive() is False
        # The migration's whole point is the C-path pan. If the import
        # probe says C is available, the timed loop MUST have exercised
        # it — a silent fallback would make the measurement meaningless
        # (codex-phantom-api-surface-guards: record which path ran).
        if ec._HAS_POSITIONS_C:
            assert c_calls["n"] > 0, (
                "positions_envelope reported C available but the C "
                "function was never called during the timed pan loop; "
                "the perf number would be fallback-grade — investigate "
                "the per-call fallback branch before trusting it."
            )
    finally:
        # Restore the real cutils.positions so we don't leak the spy into
        # later tests in the same process.
        if _orig_positions is not None:
            _cutils.positions = _orig_positions


# -- envelope micro-benchmark (Task 4 Step 3) -----------------------------


def _bench_envelope_calls(fn, t, channels, *, xlim, pixel_width, iters):
    """Time ``fn(t, sig, xlim, pixel_width, is_monotonic=True)`` across
    every (t, sig) channel pair, ``iters`` repetitions per channel.

    Returns a flat list of per-call wall-clock milliseconds so the
    caller can compute P50/P95 across both channels and iterations.
    """
    samples_ms: list[float] = []
    for _ in range(iters):
        for sig in channels:
            t0 = time.perf_counter()
            fn(t, sig, xlim=xlim, pixel_width=pixel_width,
               is_monotonic=True)
            t1 = time.perf_counter()
            samples_ms.append((t1 - t0) * 1000.0)
    return samples_ms


def test_envelope_micro_benchmark_build_vs_positions():
    """Compare ``build_envelope`` and ``positions_envelope`` head-to-head
    on the canonical 5 x 100k workload from the design spec §1.

    No Qt is needed for this measurement (the envelope functions are
    pure-numeric). The test reports two TIMEDOMAIN_ENVELOPE_PERF lines
    so the migration's results report can scrape them.

    The test is `@pytest.mark.slow` (module-level pytestmark) so it
    stays opt-in. It never asserts numeric thresholds — it is a
    measurement gate.
    """
    from mf4_analyzer.ui.canvases import build_envelope
    from mf4_analyzer.signal._envelope_cutils import (
        positions_envelope,
        _HAS_POSITIONS_C,
    )

    n_channels = 5
    n_samples = 100_000
    rows = _make_channels(n_channels, n_samples)
    # _make_channels returns (name, True, t, sig, color, unit, fid).
    t = rows[0][2]
    channels = [row[3] for row in rows]

    # Pick a realistic visible window: 2-second slice of a 10-second
    # span (matches the pan loop above). pixel_width=800 mirrors the
    # ~800-px-wide chart area in the canvas test.
    xlim = (3.0, 5.0)
    pixel_width = 800
    iters = 10

    # Warmup: pay first-call cost (NumPy/Numba JIT, page-faults).
    _ = _bench_envelope_calls(
        build_envelope, t, channels,
        xlim=xlim, pixel_width=pixel_width, iters=2,
    )
    _ = _bench_envelope_calls(
        positions_envelope, t, channels,
        xlim=xlim, pixel_width=pixel_width, iters=2,
    )

    # Timed loops.
    build_ms = _bench_envelope_calls(
        build_envelope, t, channels,
        xlim=xlim, pixel_width=pixel_width, iters=iters,
    )
    pos_ms = _bench_envelope_calls(
        positions_envelope, t, channels,
        xlim=xlim, pixel_width=pixel_width, iters=iters,
    )

    def _report(label: str, samples: list[float]) -> None:
        n = len(samples)
        p50 = _percentile(samples, 50.0)
        p95 = _percentile(samples, 95.0)
        mean = statistics.fmean(samples)
        mn = min(samples)
        mx = max(samples)
        print(
            f"\nTIMEDOMAIN_ENVELOPE_PERF "
            f"path={label} channels={n_channels} samples={n_samples} "
            f"iters={n} p50_ms={p50:.3f} p95_ms={p95:.3f} "
            f"mean_ms={mean:.3f} min_ms={mn:.3f} max_ms={mx:.3f} "
            f"c_path={_HAS_POSITIONS_C}"
        )

    _report("build_envelope", build_ms)
    _report("positions_envelope", pos_ms)

    # Smoke assertions only — we don't gate on absolute timing, but we
    # do gate on (a) at least one call per channel completed and (b)
    # no negative wall-clock readings.
    assert len(build_ms) == n_channels * iters
    assert len(pos_ms) == n_channels * iters
    assert all(v >= 0.0 for v in build_ms)
    assert all(v >= 0.0 for v in pos_ms)

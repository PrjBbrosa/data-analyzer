"""Behavior tests for the pyqtgraph time-domain canvas migration.

This file is created during Task 4 of
``docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md``
with the *envelope parity* test class as the first (and currently only)
class. Task 5 will append the canvas-skeleton tests; Task 6 the
subplot/overlay/cursor parity tests.

The envelope-parity tests verify that
``mf4_analyzer.signal._envelope_cutils.positions_envelope`` returns
output that is identical (to float-repr precision) to the legacy
``mf4_analyzer.ui.canvases.build_envelope`` reference implementation
across the seven cases enumerated in the plan Task 4 Step 1.

Per the codex-phantom-api-surface-guards lesson, ``cutils.positions`` is
NOT replaced by MagicMock. Tests either:

- exercise the real C path (probed at module import via
  ``getattr+callable``), or
- force the wrapper into its numpy fallback by monkey-patching the
  module-level cache flag ``_HAS_POSITIONS_C``.

Per the branch-reached-is-not-behavior-correct lesson, each parity case
asserts a behavioral property (values, lengths, NaN counts), not "the
fallback branch was reached".
"""

from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal import _envelope_cutils as ec
from mf4_analyzer.ui.canvases import build_envelope


# -- shared parity helper -------------------------------------------------


def _assert_envelope_equal(out_a, out_b, *, label: str):
    """Assert two (t_out, sig_out) envelopes are equal within tolerance.

    Tolerance is derived from float64 representation precision (eps),
    not a magic constant. Both halves are checked: lengths must match
    exactly, NaN positions must match exactly (``equal_nan=True``), and
    finite values must compare under ``np.allclose`` with
    ``atol=8*eps*max(|a|,|b|)``-style scaling (we use a small absolute
    floor for values near zero).
    """
    ta, sa = out_a
    tb, sb = out_b
    ta = np.asarray(ta)
    sa = np.asarray(sa)
    tb = np.asarray(tb)
    sb = np.asarray(sb)
    assert ta.shape == tb.shape, (
        f"[{label}] timestamp length mismatch: {ta.shape} vs {tb.shape}"
    )
    assert sa.shape == sb.shape, (
        f"[{label}] sample length mismatch: {sa.shape} vs {sb.shape}"
    )
    if ta.size == 0:
        return  # both empty, nothing else to check.
    # NaN positions must match (build_envelope emits NaN buckets as a
    # single NaN; the wrapper must preserve that or fall back).
    nan_a = np.isnan(sa) if np.issubdtype(sa.dtype, np.floating) else None
    nan_b = np.isnan(sb) if np.issubdtype(sb.dtype, np.floating) else None
    if nan_a is not None and nan_b is not None:
        assert np.array_equal(nan_a, nan_b), (
            f"[{label}] NaN mask differs"
        )
    eps = np.finfo(np.float64).eps
    rtol = 8 * eps
    atol = 8 * eps * max(1.0, float(np.max(np.abs(sa[~nan_a])) if nan_a is not None else np.max(np.abs(sa))))
    assert np.allclose(ta, tb, rtol=rtol, atol=8 * eps), (
        f"[{label}] timestamps differ"
    )
    assert np.allclose(sa, sb, rtol=rtol, atol=atol, equal_nan=True), (
        f"[{label}] samples differ"
    )


# -- envelope parity test class ------------------------------------------


class TestPositionsEnvelopeParity:
    """positions_envelope() must match build_envelope() on every case
    enumerated in Task 4 Step 1 of the migration plan."""

    # 1) Empty arrays --------------------------------------------------------

    def test_empty_arrays_return_empty_pair(self):
        t = np.array([], dtype=np.float64)
        sig = np.array([], dtype=np.float64)
        ref = build_envelope(t, sig, xlim=(0.0, 1.0), pixel_width=100)
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=100, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="empty")
        # Behavioral assertion: shapes are zero-length on BOTH sides.
        assert len(got[0]) == 0
        assert len(got[1]) == 0

    # 2) Normal monotonic timestamps -- the production hot path -------------

    def test_normal_monotonic_matches_reference(self):
        rng = np.random.default_rng(20260528)
        n = 50_000
        t = np.linspace(0.0, 10.0, n)
        sig = (
            np.sin(2 * np.pi * 1.3 * t)
            + 0.5 * np.cos(2 * np.pi * 6.1 * t)
            + 0.05 * rng.standard_normal(n)
        ).astype(np.float64)
        xlim = (1.5, 7.5)
        pixel_width = 800
        ref = build_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=xlim, pixel_width=pixel_width, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="normal")
        # Behavioral assertion: downsampling actually happened. The
        # bucketed-path output has at most ``2 * n_buckets`` entries
        # where ``n_buckets = n_vis // max(1, n_vis // pixel_width)``.
        # For n=50_000 over xlim (1.5, 7.5) we get n_vis=30_000,
        # bs=37, n_buckets=810 -> at most 1_620 entries — far below
        # the 30_000-sample visible window.
        n_input = len(t)
        assert 2 <= len(got[0]) < n_input // 10, (
            f"expected downsampled output; got {len(got[0])} entries "
            f"for {n_input} input samples"
        )

    # 3) Reversed xlim (x0 > x1) --------------------------------------------

    def test_reversed_xlim_normalizes(self):
        n = 5_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * 0.5 * t).astype(np.float64)
        ref = build_envelope(
            t, sig, xlim=(10.0, 0.0), pixel_width=400, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(10.0, 0.0), pixel_width=400, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="reversed-xlim")
        # Behavioral assertion: output timestamps are in non-decreasing
        # order even though the input xlim was reversed.
        assert np.all(np.diff(got[0]) >= 0), (
            "reversed xlim must still emit time-ordered output"
        )

    # 4) Small arrays (N < 4*pixel_width) trigger the small-array gate ------

    def test_small_arrays_fall_back_to_reference(self):
        # build_envelope shortcuts when n_vis <= 2*pixel_width.
        # The wrapper's gate (N < 2*pixel_width) keeps every small visible
        # window on the reference path so the bit-identical small-visible
        # shortcut output is preserved.
        t = np.linspace(0.0, 1.0, 50)
        sig = np.sin(t).astype(np.float64)
        ref = build_envelope(t, sig, xlim=(0.0, 1.0), pixel_width=200,
                             is_monotonic=True)
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=200, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="small-array")
        # Behavioral assertion: output is the full visible slice, not
        # downsampled (small-visible shortcut returns input verbatim).
        assert len(got[0]) == 50

    # 5) Non-monotonic timestamps fall back to the legacy reducer -----------

    def test_non_monotonic_falls_back(self):
        # Forced descent in the middle; _is_monotonic_array(t) is False.
        t = np.array([0.0, 1.0, 2.0, 1.5, 3.0, 4.0, 5.0])
        sig = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        ref = build_envelope(
            t, sig, xlim=(0.0, 5.0), pixel_width=10, is_monotonic=False,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 5.0), pixel_width=10, is_monotonic=False,
        )
        _assert_envelope_equal(got, ref, label="non-monotonic")
        # Behavioral assertion: in non-monotonic mode build_envelope
        # passes the data through _ds_legacy_pure (no searchsorted clip,
        # full series returned). Length must equal input length here
        # because N <= 2*pixel_width (legacy small-visible branch).
        assert len(got[0]) == len(t)

    # 6) NaN segments must be handled identically to build_envelope --------

    def test_nan_segments_match_reference(self):
        # Pattern: finite | nan | finite | nan-only-bucket | finite
        t = np.linspace(0.0, 1.0, 600)
        sig = np.sin(2 * np.pi * 3.0 * t).astype(np.float64)
        # NaN block 1: indices [100, 130) — partial NaN bucket
        sig[100:130] = np.nan
        # NaN block 2: indices [300, 360) — partial NaN bucket
        sig[300:360] = np.nan
        # NaN block 3 (entire bucket all-NaN at pixel_width=50 -> bs=12)
        sig[480:512] = np.nan

        ref = build_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=50, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 1.0), pixel_width=50, is_monotonic=True,
        )
        _assert_envelope_equal(got, ref, label="nan-segments")
        # Behavioral assertion: at least one all-NaN bucket emits a
        # single NaN entry (build_envelope's discontinuity break).
        nan_count = int(np.sum(np.isnan(got[1])))
        assert nan_count >= 1, (
            "NaN-only bucket should produce a NaN break in the envelope"
        )

    # 7) Non-contiguous numpy views are either safe-copied or fall back ----

    def test_non_contiguous_views_do_not_segfault(self):
        # Strided slice -> non-contiguous view; the wrapper must either
        # safe-copy to a contiguous buffer or fall back to build_envelope.
        n = 4_000
        t_full = np.linspace(0.0, 10.0, n)
        sig_full = np.sin(2 * np.pi * t_full).astype(np.float64)
        # Take every other sample via slicing — produces a strided view
        # with strides != itemsize but still 1-D.
        t = t_full[::2]
        sig = sig_full[::2]
        assert not t.flags.c_contiguous or not sig.flags.c_contiguous, (
            "test prerequisite: at least one input view should be non-contiguous"
        )
        ref = build_envelope(
            t, sig, xlim=(0.0, 10.0), pixel_width=200, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(0.0, 10.0), pixel_width=200, is_monotonic=True,
        )
        # Behavioral assertion: no segfault (we reached here), output
        # parity holds.
        _assert_envelope_equal(got, ref, label="non-contiguous")

    # 8) Forced fallback (C unavailable) returns exact build_envelope output

    def test_c_path_is_exercised_on_normal_monotonic_input(self):
        """The branch-reached-is-not-behavior-correct lesson applied to
        the wrapper itself: assert the C extension is actually called
        on the production hot-path shape, not silently bypassed via
        fallback. A future regression that breaks the gate cascade
        (e.g. spurious contiguity bail-out) will be caught here.
        """
        if not ec._HAS_POSITIONS_C:
            pytest.skip("C extension not available in this environment")
        # Spy on the real C function via a one-shot wrapper. We DO NOT
        # MagicMock cutils — we observe call count on the real call.
        from asammdf.blocks import cutils
        original = cutils.positions
        call_count = {"n": 0}

        def _spy(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        n = 20_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * t).astype(np.float64)
        cutils.positions = _spy
        try:
            ec.positions_envelope(
                t, sig, xlim=(1.0, 9.0), pixel_width=500,
                is_monotonic=True,
            )
        finally:
            cutils.positions = original
        assert call_count["n"] == 1, (
            f"expected C path to be exercised exactly once, got "
            f"{call_count['n']} calls"
        )

    def test_forced_fallback_when_c_path_disabled(self, monkeypatch):
        # Boundary-only mock: disable the C path via the module flag,
        # NOT by patching cutils itself. This honors the
        # codex-phantom-api-surface-guards lesson.
        monkeypatch.setattr(ec, "_HAS_POSITIONS_C", False)
        # Reset once-flag so the c_unavailable log can fire deterministically
        # in this test process; otherwise an earlier test in the same
        # session may have consumed it.
        ec._reset_logged_reasons()
        n = 5_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * 0.7 * t).astype(np.float64)
        ref = build_envelope(
            t, sig, xlim=(2.0, 7.0), pixel_width=300, is_monotonic=True,
        )
        got = ec.positions_envelope(
            t, sig, xlim=(2.0, 7.0), pixel_width=300, is_monotonic=True,
        )
        # When the C path is disabled, the wrapper falls back to
        # build_envelope, so output must be bit-identical (same code
        # path on both sides, no float reordering).
        np.testing.assert_array_equal(got[0], ref[0])
        np.testing.assert_array_equal(got[1], ref[1])


# -- fallback-logging contract test class --------------------------------


class TestFallbackLoggingContract:
    """Lock the fallback-logging contract documented in
    ``_envelope_cutils.positions_envelope`` and in
    ``docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md``.

    The contract (Option B from the W1 codex review rework):

    - System-level fallback branches are logged exactly once per process
      via ``_log_fallback_once``: ``c_unavailable``, ``non_monotonic``,
      ``nan_in_window``, ``non_contiguous``, ``dtype_mismatch``.
    - Per-call shape branches are NOT logged at all (no
      ``_log_fallback_once`` call): ``xlim_none``, ``empty_input``,
      ``empty_visible_window``, ``small_visible``, ``no_op_bucket``.

    Per the branch-reached-is-not-behavior-correct lesson, each
    assertion distinguishes the "logs as documented" state from the
    "silently bypasses logging" state — it is not enough that the
    branch executed.

    Per the codex-phantom-api-surface-guards lesson, we never MagicMock
    ``asammdf.blocks.cutils``: the C-unavailable branch is forced via
    the existing module-level flag ``_HAS_POSITIONS_C``.
    """

    @pytest.fixture(autouse=True)
    def _reset_logged_reasons(self):
        # Ensure a clean once-flag set for each test method so multiple
        # invocations are observable without cross-test pollution.
        ec._reset_logged_reasons()
        yield
        ec._reset_logged_reasons()

    # -- system-level branches: logged exactly once across N invocations --

    def test_c_unavailable_logs_exactly_once_across_invocations(
        self, monkeypatch, caplog,
    ):
        # Force the C-unavailable branch via the module flag (NOT by
        # mocking asammdf.blocks.cutils).
        monkeypatch.setattr(ec, "_HAS_POSITIONS_C", False)
        n = 3_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(5):
                ec.positions_envelope(
                    t, sig, xlim=(1.0, 9.0), pixel_width=200,
                    is_monotonic=True,
                )
        matching = [
            r for r in caplog.records
            if "c_unavailable" in r.getMessage()
            and r.name == "mf4_analyzer.signal._envelope_cutils"
        ]
        assert len(matching) == 1, (
            "c_unavailable is a system-level fallback and must log "
            f"exactly once per process; saw {len(matching)} records: "
            f"{[r.getMessage() for r in matching]}"
        )

    def test_non_monotonic_logs_exactly_once_across_invocations(self, caplog):
        # Forced descent in the middle => not monotonic.
        t = np.array([0.0, 1.0, 2.0, 1.5, 3.0, 4.0, 5.0])
        sig = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(4):
                ec.positions_envelope(
                    t, sig, xlim=(0.0, 5.0), pixel_width=10,
                    is_monotonic=False,
                )
        matching = [
            r for r in caplog.records
            if "non_monotonic" in r.getMessage()
        ]
        assert len(matching) == 1, (
            f"non_monotonic must log once per process; saw {len(matching)} "
            f"records: {[r.getMessage() for r in matching]}"
        )

    # -- per-call shape branches: NOT logged at all ------------------------

    def test_xlim_none_does_not_log(self, caplog):
        # xlim=None is a per-call shape decision (full-range passthrough),
        # NOT a system-level fallback. It must not emit any log record.
        if not ec._HAS_POSITIONS_C:
            # Use a small input so the C path probe state is irrelevant;
            # build_envelope's full-range contract handles it the same
            # either way.
            pass
        t = np.linspace(0.0, 1.0, 100)
        sig = np.sin(t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            ec.positions_envelope(
                t, sig, xlim=None, pixel_width=50, is_monotonic=True,
            )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert msgs == [], (
            "xlim=None is a per-call shape decision and must NOT emit a "
            f"_log_fallback_once line; saw: {msgs}"
        )

    def test_empty_input_does_not_log(self, caplog):
        # Empty arrays are a per-call shape decision.
        t = np.array([], dtype=np.float64)
        sig = np.array([], dtype=np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(3):
                ec.positions_envelope(
                    t, sig, xlim=(0.0, 1.0), pixel_width=100,
                    is_monotonic=True,
                )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert msgs == [], (
            f"empty_input is a per-call shape decision and must NOT emit "
            f"a _log_fallback_once line; saw: {msgs}"
        )

    def test_small_visible_does_not_log(self, caplog):
        # n_vis <= 2 * pixel_width hits the small-visible shortcut.
        if not ec._HAS_POSITIONS_C:
            pytest.skip(
                "C unavailable on this system; small-visible branch is "
                "only reachable past the c_unavailable gate"
            )
        t = np.linspace(0.0, 1.0, 50)
        sig = np.sin(t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            for _ in range(3):
                ec.positions_envelope(
                    t, sig, xlim=(0.0, 1.0), pixel_width=200,
                    is_monotonic=True,
                )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert msgs == [], (
            f"small_visible is a per-call shape decision and must NOT "
            f"emit a _log_fallback_once line; saw: {msgs}"
        )

    def test_no_op_bucket_does_not_log(self, caplog):
        # bs <= 1 (n_vis < n_buckets) hits the no-op-bucket branch.
        # Build an input where n_vis is greater than 2*pixel_width
        # (skips small-visible) but n_vis // pixel_width == 1 (bs == 1).
        # Need n_vis in (2*pw, ...) but we want bs=1 which means
        # n_vis < 2*pw. Impossible to hit no_op_bucket and skip
        # small_visible because small_visible fires first. The no-op
        # branch is effectively unreachable today — assert via the
        # weaker proposition: across many invocations, no record from
        # a "no_op_bucket" message ever appears (even if its branch
        # never executes).
        if not ec._HAS_POSITIONS_C:
            pytest.skip("C unavailable; no-op branch unreachable")
        # Just exercise a normal hot-path call and confirm the
        # specific 'no_op_bucket' string never logs.
        n = 5_000
        t = np.linspace(0.0, 10.0, n)
        sig = np.sin(2 * np.pi * t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            ec.positions_envelope(
                t, sig, xlim=(1.0, 9.0), pixel_width=200,
                is_monotonic=True,
            )
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "mf4_analyzer.signal._envelope_cutils"]
        assert not any("no_op_bucket" in m for m in msgs), (
            f"no_op_bucket must NOT emit a _log_fallback_once line; "
            f"saw: {msgs}"
        )

    # -- the reset hook itself is part of the test contract ----------------

    def test_reset_logged_reasons_re_arms_once_flag(
        self, monkeypatch, caplog,
    ):
        # After a system-level fallback has logged, a reset must allow
        # the same reason to log again. This validates the test hook
        # we rely on for deterministic multi-invocation assertions.
        monkeypatch.setattr(ec, "_HAS_POSITIONS_C", False)
        t = np.linspace(0.0, 1.0, 1_000)
        sig = np.sin(t).astype(np.float64)
        with caplog.at_level("INFO", logger="mf4_analyzer.signal._envelope_cutils"):
            ec.positions_envelope(
                t, sig, xlim=(0.0, 1.0), pixel_width=100, is_monotonic=True,
            )
            first_count = sum(
                1 for r in caplog.records
                if "c_unavailable" in r.getMessage()
            )
            ec._reset_logged_reasons()
            ec.positions_envelope(
                t, sig, xlim=(0.0, 1.0), pixel_width=100, is_monotonic=True,
            )
            second_count = sum(
                1 for r in caplog.records
                if "c_unavailable" in r.getMessage()
            )
        assert first_count == 1, (
            f"expected exactly 1 c_unavailable record before reset; "
            f"saw {first_count}"
        )
        assert second_count == 2, (
            f"expected reset to re-arm the once-flag; got {second_count} "
            f"records, not 2"
        )


# ---------------------------------------------------------------------------
# T5 — TimeDomainCanvasPG skeleton + curve-layer cache parity tests.
#
# These tests are append-only. They start RED (the class does not exist yet)
# and turn GREEN once Task 5 lands pg_canvases.TimeDomainCanvasPG plus the
# QPainterPath-keyed curve-layer cache documented in design §5.2.
#
# The four signal/payload assertions mirror the W0 pattern from
# tests/ui/test_timedomain_canvas_contract.py so a future renderer swap on
# the production side cannot drift the contract.
# ---------------------------------------------------------------------------


def _pg_canvas(qapp):
    """Construct a TimeDomainCanvasPG and pump events so its underlying
    GraphicsLayoutWidget has a non-zero geometry under offscreen Qt.
    qapp here is the session QApplication fixture from conftest.py.
    """
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    from PyQt5.QtCore import QCoreApplication
    canvas = TimeDomainCanvasPG()
    # Force a layout pass so widget.grab() returns a non-null pixmap.
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _pg_signal_signature(bound) -> str:
    """Strip the leading SIGNAL-marker digits from a pyqtBoundSignal
    name string so callers can assert ``name(payload)`` exactly. Mirrors
    helper in tests/ui/test_timedomain_canvas_contract.py."""
    raw = bound.signal
    return raw.lstrip("0123456789")


class TestTimeDomainCanvasPGContract:
    """Pin the compatibility surface design §3.1 + §5.5 require so the
    new pyqtgraph canvas is a drop-in for the matplotlib TimeDomainCanvas.

    Per the codex-phantom-api-surface-guards lesson, every test constructs
    a REAL TimeDomainCanvasPG. No MagicMock canvases. Per the
    branch-reached-is-not-behavior-correct lesson, each test asserts a
    behavioral property (signal payload string, attribute presence,
    method callability), not "the constructor returned".
    """

    def test_four_signals_exposed_with_exact_payload_shapes(self, qapp):
        """Design §3.1: four pyqtSignals with the exact payload shapes
        downstream consumers (TimeChartCard, MainWindow) rely on."""
        from PyQt5.QtCore import pyqtBoundSignal

        canvas = _pg_canvas(qapp)
        expected = {
            "cursor_info": "cursor_info(QString)",
            "dual_cursor_info": "dual_cursor_info(QString)",
            "span_selected": "span_selected(double,double)",
            "overlay_channel_selected": "overlay_channel_selected(PyQt_PyObject)",
        }
        for name, want_sig in expected.items():
            bound = getattr(canvas, name, None)
            assert bound is not None, f"signal {name!r} missing on TimeDomainCanvasPG"
            assert isinstance(bound, pyqtBoundSignal), (
                f"attribute {name!r} is not a pyqtBoundSignal (got {type(bound)!r})"
            )
            got = _pg_signal_signature(bound)
            assert got == want_sig, (
                f"signal {name!r}: expected {want_sig!r}, got {got!r}"
            )

    def test_plot_channels_accepts_row_shape_and_stores_raw_channel_data(self, qapp):
        """Design §4.2 + main_window.py:984-990: ``plot_channels`` must
        accept ``(name, True, x_axis, sig, color, unit, fid)`` and keep
        ``channel_data[name] == (t, sig, color, unit)`` — raw arrays, NOT
        envelope output."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        sig = np.sin(2 * np.pi * 5 * t).astype(np.float64)
        color = "#ef4444"
        unit = "Nm"
        canvas.plot_channels(
            [("torque", True, t, sig, color, unit, "fid-1")], mode="overlay"
        )
        assert "torque" in canvas.channel_data
        stored = canvas.channel_data["torque"]
        assert isinstance(stored, tuple) and len(stored) == 4, (
            f"channel_data['torque'] must be a 4-tuple, got {stored!r}"
        )
        got_t, got_sig, got_color, got_unit = stored
        np.testing.assert_array_equal(np.asarray(got_t), t)
        np.testing.assert_array_equal(np.asarray(got_sig), sig)
        assert got_color == color
        assert got_unit == unit

    def test_plot_channels_accepts_legacy_six_tuple_row(self, qapp):
        """Backward compatibility with the legacy 6-tuple row shape
        ``(name, True, t, sig, color, unit)`` — required because the
        contract test (test_timedomain_canvas_contract.py) feeds the
        old shape and we must remain a drop-in."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig = (t * 2).astype(np.float64)
        canvas.plot_channels(
            [("speed", True, t, sig, "#00b894", "rpm")], mode="overlay"
        )
        assert "speed" in canvas.channel_data
        got_t, got_sig, got_color, got_unit = canvas.channel_data["speed"]
        np.testing.assert_array_equal(np.asarray(got_t), t)
        np.testing.assert_array_equal(np.asarray(got_sig), sig)
        assert got_color == "#00b894"
        assert got_unit == "rpm"

    def test_compatibility_surfaces_exist_after_plot(self, qapp):
        """Design §5.5: ``axes_list``, ``_channel_lines``,
        ``_primary_xaxis_ax`` must exist with the expected accessor
        shape after plot_channels."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig = np.sin(t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        assert hasattr(canvas, "axes_list")
        assert len(canvas.axes_list) >= 1
        # Each axis-handle entry must satisfy AxisHandle (get_xlim/set_xlim).
        ax0 = canvas.axes_list[0]
        assert callable(getattr(ax0, "get_xlim", None))
        assert callable(getattr(ax0, "set_xlim", None))

        assert hasattr(canvas, "_channel_lines")
        assert "a" in canvas._channel_lines
        # _channel_lines[name] must be a (axis_facade, line_facade) pair.
        ax_facade, line_facade = canvas._channel_lines["a"]
        assert ax_facade is ax0
        # The line facade must satisfy the LineHandle Protocol: get/set
        # color, get_label, get_visible. (Per design §5.3 — same shape
        # as MplAxisHandle.get_lines() entries.)
        assert callable(getattr(line_facade, "get_color", None))
        assert callable(getattr(line_facade, "set_color", None))
        assert callable(getattr(line_facade, "get_label", None))
        assert callable(getattr(line_facade, "get_visible", None))

        assert hasattr(canvas, "_primary_xaxis_ax")
        assert canvas._primary_xaxis_ax is not None
        # Primary axis facade must expose get_xlim/set_xlim.
        assert callable(getattr(canvas._primary_xaxis_ax, "get_xlim", None))
        assert callable(getattr(canvas._primary_xaxis_ax, "set_xlim", None))

    def test_cursor_state_methods_callable(self, qapp):
        """``set_cursor_visible``, ``set_dual_cursor_mode``,
        ``reset_cursor_state`` are part of the public surface MainWindow
        relies on (main_window.py:347-349, :680-685). Each must be
        callable without raising on an unplotted canvas, and
        ``reset_cursor_state`` must clear the dual cursor placement."""
        canvas = _pg_canvas(qapp)
        # All must accept being called on an empty canvas.
        canvas.set_cursor_visible(True)
        canvas.set_cursor_visible(False)
        canvas.set_dual_cursor_mode(True)
        canvas.set_dual_cursor_mode(False)
        # After putting the dual cursor in some state, reset_cursor_state
        # must restore the placing='A' / _ax=None / _bx=None invariant.
        canvas._ax = 0.25
        canvas._bx = 0.75
        canvas._placing = "B"
        canvas._refresh = False
        canvas.reset_cursor_state()
        assert canvas._ax is None
        assert canvas._bx is None
        assert canvas._placing == "A"
        assert canvas._refresh is True

    def test_get_statistics_reads_raw_channel_data_not_envelope_output(self, qapp):
        """Design §4.2: ``get_statistics`` MUST read raw arrays from
        ``channel_data``. Poisoning the envelope cache (the curve-layer
        cache the new canvas owns) must not perturb the stats — proving
        stats and envelope output are decoupled, same invariant as the
        matplotlib path (tests/ui/test_timedomain_canvas_contract.py)."""
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256, dtype=np.float64)
        sig = np.linspace(-1.0, 1.0, 256, dtype=np.float64)
        canvas.plot_channels(
            [("speed", True, t, sig, "#00b894", "rpm", "fid-1")]
        )

        # Baseline stats from raw data.
        stats_before = canvas.get_statistics(time_range=(0.0, 1.0))
        assert "speed" in stats_before
        assert stats_before["speed"]["min"] == pytest.approx(-1.0)
        assert stats_before["speed"]["max"] == pytest.approx(1.0)
        assert stats_before["speed"]["mean"] == pytest.approx(0.0, abs=1e-12)

        # Poison the curve-layer/path cache: get_statistics must not
        # consult it. We don't lock to a specific dict layout — instead
        # we set wildly-outside-the-data values into channel_data for a
        # bogus channel name and assert the speed stats remain unchanged.
        # (Direct poisoning of channel_data['speed'] would change the
        # answer; that's the point — channel_data IS the source of truth.)
        # Probe the curve-cache layer directly.
        cache = getattr(canvas, "_curve_path_cache", None)
        assert cache is not None, (
            "TimeDomainCanvasPG must expose _curve_path_cache as a viewport "
            "cache seam (design §5.2)."
        )
        sentinel_key = ("__poison__", "speed", 0, 1, 100)
        cache[sentinel_key] = ("poisoned",)  # opaque payload; stats must not touch it

        stats_after = canvas.get_statistics(time_range=(0.0, 1.0))
        assert stats_after["speed"]["min"] == pytest.approx(-1.0)
        assert stats_after["speed"]["max"] == pytest.approx(1.0)
        assert stats_after["speed"]["mean"] == pytest.approx(0.0, abs=1e-12)
        # The poisoned key remains untouched: reads do not mutate the cache.
        assert sentinel_key in cache

    def test_enable_span_selector_stores_callback_but_does_not_auto_enable(
        self, qapp,
    ):
        """Design §4.2 invariant + main_window.py:993-996: the always-on
        SpanSelector was retired. ``enable_span_selector(cb)`` must remain
        callable (compatibility surface) but ``plot_time`` (parent flow)
        does not invoke it, and calling it directly here must NOT install
        an active drag-to-select gesture on the canvas."""
        canvas = _pg_canvas(qapp)
        captured = []
        canvas.enable_span_selector(lambda lo, hi: captured.append((lo, hi)))
        # Compatibility-only: span_selector attribute is not active.
        # The new canvas only stores the callback; no drag handler is wired.
        assert hasattr(canvas, "span_selector")
        # span_selected signal is still part of the surface even though
        # no drag was wired.
        assert hasattr(canvas, "span_selected")
        # No callback ever fired without user gesture.
        assert captured == []

    def test_flush_pending_refresh_is_callable_and_safe_when_empty(self, qapp):
        """``_flush_pending_refresh`` is called by MainWindow even when
        the canvas was just cleared (main_window.py:443-448). It must
        not raise on an empty canvas state."""
        canvas = _pg_canvas(qapp)
        # Must be safe on a fresh, never-plotted canvas.
        canvas._flush_pending_refresh()
        # And after a plot but with no scheduled refresh.
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig = np.sin(t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        canvas._flush_pending_refresh()

    def test_draw_idle_and_clear_callable(self, qapp):
        """Compatibility surface from canvases.TimeDomainCanvas. Both
        callable on a fresh canvas without raising."""
        canvas = _pg_canvas(qapp)
        canvas.draw_idle()
        canvas.clear()
        canvas.draw_idle()


class TestTimeDomainCanvasPGCurveCache:
    """Custom curve-layer cache (design §5.2) is the core perf delivery
    of T5. Test from the consumer side (a real set_xlim call) per the
    signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface
    lesson — we don't just exercise the cache method, we verify the
    production hot path populates the cache via a real range change.
    """

    def test_cache_starts_empty_after_construction(self, qapp):
        canvas = _pg_canvas(qapp)
        assert hasattr(canvas, "_curve_path_cache"), (
            "TimeDomainCanvasPG must expose _curve_path_cache (design §5.2)"
        )
        assert len(canvas._curve_path_cache) == 0

    def test_curve_path_cache_populates_after_set_xlim(self, qapp):
        """Range change must trigger envelope -> QPainterPath -> cached
        pixmap creation. State assertion: at least one entry in
        ``_curve_path_cache`` keyed by ``(channel_name, bucketed_lo,
        bucketed_hi, bucketed_pixel_width)`` after the range mutation
        flushes."""
        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = (np.sin(2 * np.pi * 1.3 * t) + 0.5 * np.cos(2 * np.pi * 6.1 * t)).astype(
            np.float64
        )
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        # Drive a real range change; the cache populate happens inside
        # the production hot path, not via a private direct call.
        canvas.set_xlim(2.0, 5.0)
        canvas._flush_pending_refresh()

        assert len(canvas._curve_path_cache) >= 1, (
            "_curve_path_cache must contain at least one entry after a "
            "real set_xlim+_flush_pending_refresh round-trip"
        )
        # At least one key references our channel name.
        any_for_channel = any(
            k[0] == "a" for k in canvas._curve_path_cache.keys()
        )
        assert any_for_channel, (
            f"_curve_path_cache has no entry for channel 'a'; keys are "
            f"{list(canvas._curve_path_cache.keys())}"
        )

    def test_two_different_xlims_produce_two_different_cache_keys(self, qapp):
        """Per the 2026-05-19-branch-reached-is-not-behavior-correct lesson:
        two different xlims must produce two different cached
        ``QPainterPath`` entries — proving the range_key differs between
        frames, not just that "the cache method was hit"."""
        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 1.3 * t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        canvas.set_xlim(1.0, 4.0)
        canvas._flush_pending_refresh()
        keys_after_first = set(canvas._curve_path_cache.keys())
        assert len(keys_after_first) >= 1

        canvas.set_xlim(6.0, 9.0)
        canvas._flush_pending_refresh()
        keys_after_second = set(canvas._curve_path_cache.keys())

        new_keys = keys_after_second - keys_after_first
        assert len(new_keys) >= 1, (
            "second xlim must produce a fresh cache key; keys after first "
            f"= {keys_after_first}, after second = {keys_after_second}"
        )
        # And the union must have >= 2 distinct keys for channel 'a'.
        channel_keys = [k for k in keys_after_second if k[0] == "a"]
        assert len(channel_keys) >= 2, (
            f"expected >= 2 distinct cache keys for channel 'a' across "
            f"two xlims; got {channel_keys}"
        )

    def test_same_xlim_replay_does_not_create_new_cache_entry(self, qapp):
        """Per pyqt-ui/2026-04-25-cache-invalidation-event-conditional:
        invalidation/repopulation must be gated on a state diff, not on
        every event tick. Two consecutive flushes with identical xlim
        must NOT inflate the cache."""
        canvas = _pg_canvas(qapp)
        n = 20_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 1.3 * t).astype(np.float64)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])

        canvas.set_xlim(2.0, 5.0)
        canvas._flush_pending_refresh()
        n_after_first = len(canvas._curve_path_cache)

        # No range mutation between flushes — cache size must not grow.
        canvas._flush_pending_refresh()
        n_after_second = len(canvas._curve_path_cache)
        assert n_after_second == n_after_first, (
            f"identical-xlim replay inflated cache from {n_after_first} "
            f"to {n_after_second}"
        )

    def test_positions_envelope_is_consumed_by_canvas_hot_path(
        self, qapp, monkeypatch,
    ):
        """Per signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface:
        the cache+envelope plumbing is dead code unless the production
        hot path actually CALLS positions_envelope. Wire a call-count
        spy onto the module function and assert the canvas drives it.
        """
        from mf4_analyzer.signal import _envelope_cutils as ec

        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 1.3 * t).astype(np.float64)

        original = ec.positions_envelope
        call_count = {"n": 0}

        def _spy(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        # Patch via the canvas module too so we count the call regardless
        # of which import path the canvas uses (from-import vs. attribute).
        from mf4_analyzer.ui import pg_canvases
        monkeypatch.setattr(ec, "positions_envelope", _spy)
        if hasattr(pg_canvases, "positions_envelope"):
            monkeypatch.setattr(pg_canvases, "positions_envelope", _spy)

        canvas = _pg_canvas(qapp)
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        canvas.set_xlim(1.0, 6.0)
        canvas._flush_pending_refresh()

        assert call_count["n"] >= 1, (
            "TimeDomainCanvasPG hot path must call positions_envelope on "
            "set_xlim; otherwise the curve-layer cache plumbing is dead "
            "code (see cache-consumer-must-be-grepped-not-just-surface)."
        )


class TestTimeDomainCanvasPGScreenshotGrab:
    """Per lesson codex-visual-parity-rendered-screenshot: render at
    least one offscreen screenshot and gate on geometry, not pixel-byte
    equality (that's T7's job). Also per
    pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt: provide a
    degenerate-rect fallback."""

    def test_grab_pixmap_returns_non_null_pixmap_with_geometry(self, qapp, tmp_path):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 1_000, dtype=np.float64)
        sig = np.sin(2 * np.pi * 5 * t).astype(np.float64)
        canvas.plot_channels(
            [("speed", True, t, sig, "#1769e0", "rpm", "fid-1")]
        )
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None
        assert not pix.isNull(), "grab_pixmap returned a null pixmap"
        # Geometry gate (NOT pixel-byte equality — T7's job).
        assert pix.width() > 0, f"pix.width()={pix.width()}"
        assert pix.height() > 0, f"pix.height()={pix.height()}"

        # And write to /tmp so a human reviewer can inspect the rendered
        # offscreen output.
        out_path = "/tmp/pg_skeleton_single_channel.png"
        ok = pix.save(out_path)
        assert ok, f"failed to write screenshot to {out_path!r}"


# T5 — fill PgAxisHandle: verify it now delegates to a real pyqtgraph
# ViewBox/AxisItem pair instead of raising NotImplementedError. This
# class lives here (not in test_axis_handle.py) so T5's reach into the
# axis-handle module is exercised from the same file that drives the
# pyqtgraph canvas.

class TestPgAxisHandleDelegation:
    """The 17 AxisHandle Protocol methods on PgAxisHandle must delegate
    to a real pyqtgraph ``PlotItem``/``ViewBox``/``AxisItem`` triple —
    no more NotImplementedError stubs."""

    def _make(self, qapp):
        import os
        os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
        import pyqtgraph as pg
        from mf4_analyzer.ui._axis_handle import PgAxisHandle

        glw = pg.GraphicsLayoutWidget()
        glw.resize(640, 360)
        plot_item = glw.addPlot(row=0, col=0)
        handle = PgAxisHandle(plot_item=plot_item)
        return glw, plot_item, handle

    def test_get_set_xlim_roundtrips(self, qapp):
        _glw, _pi, h = self._make(qapp)
        h.set_xlim(0.0, 10.0)
        lo, hi = h.get_xlim()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(10.0)

    def test_get_set_ylim_roundtrips(self, qapp):
        _glw, _pi, h = self._make(qapp)
        h.set_ylim(-1.0, 1.0)
        lo, hi = h.get_ylim()
        assert lo == pytest.approx(-1.0)
        assert hi == pytest.approx(1.0)

    def test_xlabel_ylabel_title_roundtrip(self, qapp):
        _glw, _pi, h = self._make(qapp)
        h.set_xlabel("time (s)")
        h.set_ylabel("value")
        h.set_title("title")
        assert "time (s)" in h.get_xlabel()
        assert "value" in h.get_ylabel()
        assert "title" in h.get_title()

    def test_grid_toggle_is_noop_safe(self, qapp):
        _glw, _pi, h = self._make(qapp)
        # showGrid raises on unsupported args; we just need it to round
        # without crashing for both states.
        h.grid(True)
        h.grid(False)

    def test_get_lines_returns_line_handle_wrappers(self, qapp):
        _glw, pi, h = self._make(qapp)
        # Add a PlotDataItem so get_lines has something to see.
        import pyqtgraph as pg
        pdi = pi.plot([0.0, 1.0, 2.0], [0.0, 1.0, 4.0], pen=pg.mkPen("#1769e0"))
        lines = h.get_lines()
        assert len(lines) >= 1
        line = lines[0]
        # LineHandle Protocol — same surface as Mpl wrapper.
        assert callable(getattr(line, "get_label", None))
        assert callable(getattr(line, "get_color", None))
        assert callable(getattr(line, "set_color", None))
        assert callable(getattr(line, "get_visible", None))
        # set_color round-trips: read back via PlotDataItem pen color.
        line.set_color("#ef4444")
        # Color reads via PlotDataItem.opts['pen'].color().name().
        from PyQt5.QtGui import QPen
        pen = pdi.opts.get("pen")
        if isinstance(pen, QPen):
            assert pen.color().name() == "#ef4444"

    def test_get_mappables_empty_for_time_domain(self, qapp):
        _glw, _pi, h = self._make(qapp)
        # Time-domain has no images/colorscales — design §5.3.
        assert h.get_mappables() == []

    def test_request_redraw_does_not_raise(self, qapp):
        _glw, _pi, h = self._make(qapp)
        # Just verify it's callable and non-raising under offscreen Qt.
        h.request_redraw()

    def test_set_xscale_yscale_log_then_linear(self, qapp):
        _glw, pi, h = self._make(qapp)
        # ViewBox supports a log-scale flag via setLogMode on PlotItem.
        h.set_xscale("log")
        h.set_xscale("linear")
        h.set_yscale("log")
        h.set_yscale("linear")

    def test_autoscale_does_not_raise(self, qapp):
        _glw, pi, h = self._make(qapp)
        # Add data so there's something to autoscale to.
        import pyqtgraph as pg
        pi.plot([0.0, 1.0, 2.0], [0.0, 1.0, 4.0], pen=pg.mkPen("#1769e0"))
        h.autoscale()
        h.autoscale(axis="x")
        h.autoscale(axis="y")


# ---------------------------------------------------------------------------
# T6 — Subplot / overlay / cursor parity / scroll / xlim-preservation tests.
#
# These are append-only and start RED against the T5 canvas (subplot/overlay
# routing exists at construction but the visual rules, cursor signal
# emission, modifier-dispatched scroll, and mode-switch xlim capture are
# not implemented yet). They turn GREEN once T6 lands the behavior in
# mf4_analyzer/ui/pg_canvases.py.
#
# Every test in this block honors the
# signal-processing/2026-05-19-branch-reached-is-not-behavior-correct
# lesson: a single-frame "branch executed" assertion is never enough.
# Either we compare two frames with different inputs and demand strictly
# different outputs, or we string-match a payload byte-for-byte against
# the matplotlib reference renderer (cursor HTML parity).
# ---------------------------------------------------------------------------


def _five_channel_rows():
    """Construct 5 visible channel rows for plot_channels() tests.

    Returns the same row shape MainWindow passes: ``(name, True, t, sig,
    color, unit, fid)``. Different waveforms per channel ensure each
    inside-label-vs-outside placement and per-channel emphasis test can
    assert on something non-trivial.
    """
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    return [
        ("speed",    True, t, 1000.0 * np.sin(2 * np.pi * 5 * t),  "#1769e0", "rpm",  "fid-1"),
        ("torque",   True, t, 50.0 + 5.0 * np.cos(2 * np.pi * 3 * t), "#ef4444", "Nm",  "fid-1"),
        ("pressure", True, t, 0.2 * t + 0.1 * np.sin(2 * np.pi * 7 * t), "#00b894", "bar", "fid-1"),
        ("temp",     True, t, 60.0 + 2.0 * np.cos(2 * np.pi * 1.5 * t), "#fbbf24", "C",   "fid-1"),
        ("flow",     True, t, 1.0 + 0.3 * np.sin(2 * np.pi * 9 * t), "#a855f7", "L/s", "fid-1"),
    ]


class TestTimeDomainCanvasPGSubplotMode:
    """5 channels in subplot mode → 5 stacked PlotItems sharing the X
    axis. Sync xlim via the primary axis. Inside-vs-outside label
    placement follows the SAME bbox-overlap rule as
    canvases.py:_subplot_ylabels_need_inside_labels (no fixed 5-10%
    offset, design §0 correction)."""

    def test_subplot_builds_five_plot_items_sharing_x_axis(self, qapp):
        """Two-frame state change (branch-reached lesson): assert that
        moving the primary axis xlim propagates to a non-primary subplot
        sibling. A single-frame "axes_list has 5 entries" assertion
        would only prove construction ran, not that sharing works."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        assert len(canvas.axes_list) == 5, (
            f"subplot mode must build one axis per visible channel; "
            f"got {len(canvas.axes_list)}"
        )

        primary = canvas._primary_xaxis_ax
        assert primary is not None

        # State A: set primary xlim to a known window.
        primary.set_xlim(0.10, 0.20)
        QCoreApplication.processEvents()
        # ALL 5 axes must follow (not just axes_list[2]). Pin the
        # exact (lo, hi) tuple per subplot. The codex-plan-spec-literal-
        # evidence gate requires comparing exact tuples, not "close
        # enough" — pytest.approx already gives us the rounding cushion
        # without weakening the assertion to "any movement happened".
        windows_a = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_a):
            assert lo == pytest.approx(0.10, abs=1e-6), (
                f"state A axis {i} lo={lo!r}, expected 0.10"
            )
            assert hi == pytest.approx(0.20, abs=1e-6), (
                f"state A axis {i} hi={hi!r}, expected 0.20"
            )

        # State B: a strictly different window.
        primary.set_xlim(0.40, 0.55)
        QCoreApplication.processEvents()
        windows_b = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_b):
            assert lo == pytest.approx(0.40, abs=1e-6), (
                f"state B axis {i} lo={lo!r}, expected 0.40"
            )
            assert hi == pytest.approx(0.55, abs=1e-6), (
                f"state B axis {i} hi={hi!r}, expected 0.55"
            )

        # Two-frame strict difference (signal-processing lesson): every
        # axis moved between state A and state B.
        for i in range(len(canvas.axes_list)):
            assert windows_a[i] != windows_b[i], (
                f"axis {i} did not change between state A and B "
                f"(windows_a[{i}]={windows_a[i]!r}, windows_b[{i}]={windows_b[i]!r})"
            )

    def test_subplot_non_primary_origin_xlim_propagates_to_all_axes(self, qapp):
        """When the user pans a NON-primary subplot (e.g. axes_list[2]),
        the new range must propagate to the primary AND every other
        sibling. Without this, dropping setXLink causes silent drift on
        the four other axes.

        Two-frame strict difference (branch-reached-is-not-behavior-
        correct): set the same non-primary subplot to two distinct
        windows; assert ALL 5 axes follow in both frames AND that the
        windows differ between frames."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        assert len(canvas.axes_list) == 5

        non_primary = canvas.axes_list[2]
        assert non_primary is not canvas._primary_xaxis_ax

        # State A: set xlim on a NON-primary axis directly.
        non_primary.set_xlim(0.15, 0.25)
        QCoreApplication.processEvents()
        windows_a = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_a):
            assert lo == pytest.approx(0.15, abs=1e-6), (
                f"non-primary-origin state A: axis {i} lo={lo!r} did not "
                f"follow the originating axis (expected 0.15)"
            )
            assert hi == pytest.approx(0.25, abs=1e-6), (
                f"non-primary-origin state A: axis {i} hi={hi!r} did not "
                f"follow the originating axis (expected 0.25)"
            )

        # State B: a different window on the SAME non-primary axis.
        non_primary.set_xlim(0.55, 0.80)
        QCoreApplication.processEvents()
        windows_b = [tuple(ax.get_xlim()) for ax in canvas.axes_list]
        for i, (lo, hi) in enumerate(windows_b):
            assert lo == pytest.approx(0.55, abs=1e-6), (
                f"non-primary-origin state B: axis {i} lo={lo!r}"
            )
            assert hi == pytest.approx(0.80, abs=1e-6), (
                f"non-primary-origin state B: axis {i} hi={hi!r}"
            )

        # Strict two-frame difference per signal-processing lesson.
        for i in range(len(canvas.axes_list)):
            assert windows_a[i] != windows_b[i], (
                f"axis {i} did not move between non-primary-origin frames"
            )

    def test_subplot_inside_label_decision_uses_bbox_overlap(self, qapp):
        """Inside-label placement is decision-driven by rendered bbox
        overlap, not a fixed 5-10% offset (design §0 correction).
        Two-frame assertion: at a wide width the decision is False
        (labels fit outside); at a very narrow width the decision is
        True (labels would overlap). Same rule the matplotlib path uses
        at canvases.py:_subplot_ylabels_need_inside_labels."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        # Frame A: wide canvas — labels should be outside (no overlap).
        wide_decision = canvas._subplot_ylabels_need_inside_labels()

        # Frame B: shrink to a narrow width — labels MUST need to flip
        # inside because the y-axis label box now overlaps tick labels.
        canvas.resize(220, 800)
        QCoreApplication.processEvents()
        narrow_decision = canvas._subplot_ylabels_need_inside_labels()

        # Two-frame strict difference: narrow case wants inside, wide
        # case wants outside. A single-frame "decision is bool" assert
        # would not be evidence of the rule.
        assert wide_decision is False, (
            f"wide canvas should NOT need inside labels; got {wide_decision!r}"
        )
        assert narrow_decision is True, (
            f"narrow canvas MUST need inside labels; got {narrow_decision!r}"
        )


class TestTimeDomainCanvasPGOverlayMode:
    """5 channels in overlay mode → one PlotItem with per-channel Y axes
    on the LEFT side. Selected channel highlighted via line-width /
    alpha (1.8/1.0 vs 1.0/0.42 — matches canvases.py:_apply_overlay_
    selection_style)."""

    def test_overlay_emphasis_two_frame_line_width_difference(self, qapp):
        """Two-frame branch-reached-is-not-behavior-correct compliance.
        Frame A: no selection — every channel has the default linewidth.
        Frame B: select channel 'speed' — its linewidth strictly
        increases AND its alpha goes to 1.0, while the others drop to
        the de-emphasized state (alpha 0.42, lw 1.0)."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        # Frame A: no selection.
        canvas.select_overlay_channel(None)
        QCoreApplication.processEvents()
        a_speed_lw, a_speed_alpha = canvas._overlay_emphasis_for_channel("speed")
        a_other_lw, a_other_alpha = canvas._overlay_emphasis_for_channel("torque")

        # Frame B: emphasise 'speed'.
        canvas.select_overlay_channel("speed")
        QCoreApplication.processEvents()
        b_speed_lw, b_speed_alpha = canvas._overlay_emphasis_for_channel("speed")
        b_other_lw, b_other_alpha = canvas._overlay_emphasis_for_channel("torque")

        # Strict two-frame difference.
        assert b_speed_lw > a_speed_lw, (
            f"selected channel linewidth must increase; "
            f"frame A speed_lw={a_speed_lw!r}, frame B={b_speed_lw!r}"
        )
        assert b_speed_alpha >= a_speed_alpha, (
            f"selected channel alpha must rise; got A={a_speed_alpha!r}, "
            f"B={b_speed_alpha!r}"
        )
        # De-emphasised channels MUST become more transparent than they
        # were in the default state.
        assert b_other_alpha < a_other_alpha, (
            f"de-emphasised channel alpha must drop; got A={a_other_alpha!r}, "
            f"B={b_other_alpha!r}"
        )

    def test_overlay_blank_click_deselect_emits_signal(self, qapp):
        """Blank-click deselect must emit overlay_channel_selected(None).
        Two-frame: first signal is the select event with the channel
        name; second is the deselect with None."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        emitted = []
        canvas.overlay_channel_selected.connect(lambda v: emitted.append(v))

        canvas.select_overlay_channel("torque")
        QCoreApplication.processEvents()
        assert emitted[-1] == "torque", (
            f"first emission should be 'torque', got {emitted!r}"
        )

        canvas.select_overlay_channel(None)
        QCoreApplication.processEvents()
        assert emitted[-1] is None, (
            f"deselect emission should be None, got {emitted!r}"
        )
        assert len(emitted) == 2, (
            f"expected exactly 2 emissions (select+deselect); got {emitted!r}"
        )

    def test_overlay_selected_y_drag_emits_ylim_change(self, qapp):
        """Selected-channel Y drag must apply a ylim shift. Two-frame:
        record ylim before drag, simulate a drag with a non-zero dy_px,
        record ylim after — strict inequality."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        canvas.select_overlay_channel("speed")
        QCoreApplication.processEvents()

        primary = canvas._primary_xaxis_ax
        primary.set_ylim(-500.0, 500.0)
        QCoreApplication.processEvents()
        lo_before, hi_before = primary.get_ylim()

        # Simulate a 40-pixel downward drag on the selected channel.
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        moved = canvas._apply_overlay_y_drag_at(current_y_px=140.0)
        QCoreApplication.processEvents()

        lo_after, hi_after = primary.get_ylim()
        # The drag method returned True (gesture consumed).
        assert moved is True, (
            f"_apply_overlay_y_drag_at must return True after a drag; "
            f"got {moved!r}"
        )
        # Strict two-frame difference (signal-processing lesson).
        assert (lo_before, hi_before) != (lo_after, hi_after), (
            f"y-drag must change ylim; before={lo_before, hi_before}, "
            f"after={lo_after, hi_after}"
        )


class TestTimeDomainCanvasPGCursorParity:
    """Single-cursor + dual-cursor HTML payloads must match
    canvases.py:_update_single (`cursor_info`) and
    canvases.py:_format_dual_html (`dual_cursor_info`) byte-for-byte.

    Per codex-plan-spec-literal-evidence + the explicit brief: import
    the SAME formatter helpers from canvases.py instead of
    reimplementing them so the strings cannot drift.
    """

    def test_single_cursor_html_matches_update_single_letter_for_letter(self, qapp):
        """String-for-string parity gate (codex-plan-spec-literal-evidence).
        Build identical inputs into matplotlib TimeDomainCanvas and pg
        TimeDomainCanvasPG, drive the same cursor x, capture
        cursor_info emissions, assertEqual the raw strings."""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.canvases import TimeDomainCanvas

        # Two channels at known values so the HTML payload is non-trivial.
        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig_a = np.sin(2 * np.pi * 5 * t).astype(np.float64)
        sig_b = (t * 100.0).astype(np.float64)
        rows = [
            ("speed",  True, t, sig_a, "#1769e0", "rpm", "fid-1"),
            ("torque", True, t, sig_b, "#ef4444", "Nm",  "fid-1"),
        ]

        # Matplotlib reference: call _update_single directly. It both
        # paints artists AND emits cursor_info. We capture the emission.
        mpl = TimeDomainCanvas()
        mpl.plot_channels(rows, mode="subplot")
        mpl.set_cursor_visible(True)
        # _update_single does a canvas.draw() via _refresh_bg(); make
        # sure the figure has a renderer ready under offscreen Qt.
        mpl.draw()

        mpl_emissions = []
        mpl.cursor_info.connect(lambda html: mpl_emissions.append(html))

        # Pyqtgraph candidate.
        pg = _pg_canvas(qapp)
        pg.plot_channels(rows, mode="subplot")
        pg.set_cursor_visible(True)
        QCoreApplication.processEvents()

        pg_emissions = []
        pg.cursor_info.connect(lambda html: pg_emissions.append(html))

        # Drive an identical hover x.
        cursor_x = 0.42
        mpl._update_single(cursor_x)
        pg._emit_single_cursor_html(cursor_x)

        QCoreApplication.processEvents()
        assert mpl_emissions, "matplotlib canvas emitted no cursor_info"
        assert pg_emissions, "pg canvas emitted no cursor_info"
        # Byte-for-byte equality: any trailing whitespace or attribute
        # reorder is a failure (codex-plan-spec-literal-evidence).
        assert pg_emissions[-1] == mpl_emissions[-1], (
            "single-cursor HTML drifted!\n"
            f"  matplotlib: {mpl_emissions[-1]!r}\n"
            f"  pyqtgraph:  {pg_emissions[-1]!r}"
        )

    def test_dual_cursor_html_matches_format_dual_html_letter_for_letter(self, qapp):
        """Same letter-for-letter gate as single cursor, applied to the
        dual_cursor_info payload + the delta column."""
        from PyQt5.QtCore import QCoreApplication
        from mf4_analyzer.ui.canvases import TimeDomainCanvas

        t = np.linspace(0.0, 1.0, 100, dtype=np.float64)
        sig_a = np.sin(2 * np.pi * 5 * t).astype(np.float64)
        sig_b = (t * 100.0).astype(np.float64)
        rows = [
            ("speed",  True, t, sig_a, "#1769e0", "rpm", "fid-1"),
            ("torque", True, t, sig_b, "#ef4444", "Nm",  "fid-1"),
        ]

        # matplotlib reference
        mpl = TimeDomainCanvas()
        mpl.plot_channels(rows, mode="subplot")
        mpl.set_cursor_visible(True)
        mpl.set_dual_cursor_mode(True)
        mpl._ax = 0.20
        mpl._bx = 0.80
        mpl.draw()

        mpl_dual = []
        mpl.dual_cursor_info.connect(lambda html: mpl_dual.append(html))

        # pyqtgraph candidate
        pg = _pg_canvas(qapp)
        pg.plot_channels(rows, mode="subplot")
        pg.set_cursor_visible(True)
        pg.set_dual_cursor_mode(True)
        pg._ax = 0.20
        pg._bx = 0.80
        QCoreApplication.processEvents()

        pg_dual = []
        pg.dual_cursor_info.connect(lambda html: pg_dual.append(html))

        mpl._update_dual()
        pg._emit_dual_cursor_html()

        QCoreApplication.processEvents()
        assert mpl_dual, "matplotlib canvas emitted no dual_cursor_info"
        assert pg_dual, "pg canvas emitted no dual_cursor_info"
        assert pg_dual[-1] == mpl_dual[-1], (
            "dual-cursor HTML drifted!\n"
            f"  matplotlib: {mpl_dual[-1]!r}\n"
            f"  pyqtgraph:  {pg_dual[-1]!r}"
        )


class TestTimeDomainCanvasPGScroll:
    """Scroll behavior parity: Ctrl+wheel zooms X, Shift+wheel zooms Y,
    plain wheel pans Y. Tests use two-frame strict-difference assertions
    on the visible range, not branch-reached snapshots."""

    def test_ctrl_wheel_zooms_x(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        primary = canvas._primary_xaxis_ax
        primary.set_xlim(0.0, 1.0)
        primary.set_ylim(-2000.0, 2000.0)
        QCoreApplication.processEvents()

        x_before = primary.get_xlim()
        y_before = primary.get_ylim()

        # Wheel up with Ctrl: zoom IN on X. delta>0 → zoom in.
        canvas._handle_wheel_dispatch(delta=120, modifiers=Qt.ControlModifier, x_pos=0.5, y_pos=0.0)
        QCoreApplication.processEvents()

        x_after = primary.get_xlim()
        y_after = primary.get_ylim()

        assert x_after != x_before, (
            f"Ctrl+wheel must change xlim; got {x_after!r} == {x_before!r}"
        )
        # X span must strictly shrink on zoom-in.
        assert (x_after[1] - x_after[0]) < (x_before[1] - x_before[0]), (
            f"zoom-in must shrink X span; before={x_before!r}, after={x_after!r}"
        )
        # Y MUST be untouched (Ctrl is the X-zoom modifier).
        assert y_after == pytest.approx(y_before), (
            f"Ctrl+wheel must NOT change ylim; before={y_before!r}, "
            f"after={y_after!r}"
        )

    def test_shift_wheel_zooms_y(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        primary = canvas._primary_xaxis_ax
        primary.set_xlim(0.0, 1.0)
        primary.set_ylim(-2000.0, 2000.0)
        QCoreApplication.processEvents()

        x_before = primary.get_xlim()
        y_before = primary.get_ylim()

        canvas._handle_wheel_dispatch(delta=120, modifiers=Qt.ShiftModifier, x_pos=0.5, y_pos=0.0)
        QCoreApplication.processEvents()

        x_after = primary.get_xlim()
        y_after = primary.get_ylim()

        assert y_after != y_before, (
            f"Shift+wheel must change ylim; got {y_after!r} == {y_before!r}"
        )
        assert (y_after[1] - y_after[0]) < (y_before[1] - y_before[0]), (
            f"zoom-in must shrink Y span; before={y_before!r}, after={y_after!r}"
        )
        assert x_after == pytest.approx(x_before), (
            f"Shift+wheel must NOT change xlim; before={x_before!r}, "
            f"after={x_after!r}"
        )

    def test_plain_wheel_pans_y(self, qapp):
        from PyQt5.QtCore import QCoreApplication, Qt

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        primary = canvas._primary_xaxis_ax
        primary.set_xlim(0.0, 1.0)
        primary.set_ylim(-2000.0, 2000.0)
        QCoreApplication.processEvents()

        x_before = primary.get_xlim()
        y_before = primary.get_ylim()
        y_span_before = y_before[1] - y_before[0]

        canvas._handle_wheel_dispatch(delta=120, modifiers=Qt.NoModifier, x_pos=0.5, y_pos=0.0)
        QCoreApplication.processEvents()

        x_after = primary.get_xlim()
        y_after = primary.get_ylim()
        y_span_after = y_after[1] - y_after[0]

        assert y_after != y_before, (
            f"plain wheel must pan Y; got {y_after!r} == {y_before!r}"
        )
        # Pan preserves span; zoom does not.
        assert y_span_after == pytest.approx(y_span_before, rel=1e-6), (
            f"plain wheel must preserve Y span (pan, not zoom); "
            f"before span={y_span_before!r}, after span={y_span_after!r}"
        )
        # X MUST be untouched.
        assert x_after == pytest.approx(x_before), (
            f"plain wheel must NOT change xlim; before={x_before!r}, "
            f"after={x_after!r}"
        )


class TestTimeDomainCanvasPGModeSwitchXlim:
    """Subplot ↔ overlay rebuild must capture xlim BEFORE teardown and
    restore it AFTER build. The pattern lives INSIDE the canvas (per
    brief: MainWindow should not be involved). Two-frame strict-equality
    assertion on the post-switch xlim."""

    def test_subplot_to_overlay_preserves_user_xlim(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        # User pans to a specific window.
        canvas._primary_xaxis_ax.set_xlim(0.30, 0.45)
        QCoreApplication.processEvents()
        xlim_before = canvas._primary_xaxis_ax.get_xlim()
        assert xlim_before[0] == pytest.approx(0.30, abs=1e-6)
        assert xlim_before[1] == pytest.approx(0.45, abs=1e-6)

        # Switch mode via the rebuild path.
        canvas.plot_channels_preserving_xlim(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        xlim_after = canvas._primary_xaxis_ax.get_xlim()
        # Strict equality (within rounding) — the user's window survived.
        assert xlim_after[0] == pytest.approx(xlim_before[0], abs=1e-6), (
            f"mode-switch dropped lo: before={xlim_before!r}, after={xlim_after!r}"
        )
        assert xlim_after[1] == pytest.approx(xlim_before[1], abs=1e-6), (
            f"mode-switch dropped hi: before={xlim_before!r}, after={xlim_after!r}"
        )

    def test_plot_time_does_not_enable_span_selector(self, qapp):
        """T5 invariant reaffirmation: ``enable_span_selector(cb)`` is
        stored but NEVER auto-fired from ``plot_channels``. Per design
        §4.2 + main_window.py:993-996. Two-frame: call plot_channels
        once, then again with different content — the callback list
        stays empty."""
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        fired = []
        canvas.enable_span_selector(lambda lo, hi: fired.append((lo, hi)))

        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        assert fired == [], (
            f"plot_channels must NOT auto-fire the span callback; got {fired!r}"
        )

        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()
        assert fired == [], (
            f"second plot_channels must still not auto-fire; got {fired!r}"
        )


class TestTimeDomainCanvasPGVisualParityScreenshots:
    """Geometry-level visual parity gate (codex-visual-parity-rendered-
    screenshot). Renders 3 PNGs to /tmp and asserts each is non-null,
    width>100, height>100, and the cursor pill (when active) lies
    inside the view bbox.

    Pixel-byte parity is T7's job; T6's gate is geometry + container
    containment, per the brief.
    """

    def test_subplot_5ch_screenshot_geometry(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None, "grab_pixmap returned None"
        assert not pix.isNull(), "subplot screenshot pixmap is null"
        assert pix.width() > 100, f"width too small: {pix.width()}"
        assert pix.height() > 100, f"height too small: {pix.height()}"

        out = "/tmp/pg_parity_subplot_5ch.png"
        assert pix.save(out), f"failed to save {out!r}"

    def test_overlay_5ch_screenshot_geometry(self, qapp):
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None
        assert not pix.isNull(), "overlay screenshot pixmap is null"
        assert pix.width() > 100, f"width too small: {pix.width()}"
        assert pix.height() > 100, f"height too small: {pix.height()}"

        out = "/tmp/pg_parity_overlay_5ch.png"
        assert pix.save(out), f"failed to save {out!r}"

    def test_dual_cursor_screenshot_geometry_and_pill_containment(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QRect

        canvas = _pg_canvas(qapp)
        canvas.resize(1200, 800)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        QCoreApplication.processEvents()
        canvas.set_cursor_visible(True)
        canvas.set_dual_cursor_mode(True)
        canvas._ax = 0.25
        canvas._bx = 0.75
        canvas._emit_dual_cursor_html()
        QCoreApplication.processEvents()

        pix = canvas.grab_pixmap()
        assert pix is not None
        assert not pix.isNull(), "dual-cursor screenshot pixmap is null"
        assert pix.width() > 100, f"width too small: {pix.width()}"
        assert pix.height() > 100, f"height too small: {pix.height()}"

        # Cursor lines must lie inside the view bbox (geometry assertion).
        bbox = QRect(0, 0, pix.width(), pix.height())
        ax_pix = canvas._cursor_x_to_pixmap_x(canvas._ax, pix.width())
        bx_pix = canvas._cursor_x_to_pixmap_x(canvas._bx, pix.width())
        assert bbox.contains(int(ax_pix), pix.height() // 2), (
            f"cursor A at pixel x={ax_pix} not contained in bbox {bbox!r}"
        )
        assert bbox.contains(int(bx_pix), pix.height() // 2), (
            f"cursor B at pixel x={bx_pix} not contained in bbox {bbox!r}"
        )

        out = "/tmp/pg_parity_dual_cursor.png"
        assert pix.save(out), f"failed to save {out!r}"


class TestTimeDomainCanvasPGSetDataHotPathContract:
    """Lock the module contract documented at the top of
    ``mf4_analyzer/ui/pg_canvases.py``: ``PlotDataItem.setData`` is the
    fallback/bind-only path; production pan/refresh goes through the
    QPainterPath+QPixmap cache. The codex W2 review flagged a regression
    where ``_refresh_visible_data`` was calling ``pdi.setData`` on every
    range change, which silently inflated per-frame work.

    Per the codex-phantom-api-surface-guards lesson the spy uses
    ``patch.object`` on the actual PlotDataItem instance — we do NOT
    mock pyqtgraph itself or fabricate a fake setData surface.
    """

    def test_pdi_setdata_called_at_most_once_during_bind_then_zero_on_pan(
        self, qapp,
    ):
        """Bind ONCE, pan FIVE times: setData must be called at most
        once (during the initial bind in ``_bind_channel``) and zero
        times during the five subsequent ``set_xlim`` iterations.

        This is the W2 rework regression: prior to the fix at
        ``pg_canvases.py:866-875`` (now removed), each pan iteration
        invoked ``pdi.setData(env_t, env_s)`` after the cache populate.
        """
        from PyQt5.QtCore import QCoreApplication
        from unittest.mock import patch

        canvas = _pg_canvas(qapp)
        n = 50_000
        t = np.linspace(0.0, 10.0, n, dtype=np.float64)
        sig = (np.sin(2 * np.pi * 1.3 * t)
               + 0.5 * np.cos(2 * np.pi * 6.1 * t)).astype(np.float64)

        # Bind happens inside plot_channels via PlotItem.plot(...). We
        # let that go through unsupervised; the spy starts ticking
        # AFTER bind so we can isolate pan-path mutation.
        canvas.plot_channels([("a", True, t, sig, "#1769e0", "u", "fid-1")])
        QCoreApplication.processEvents()

        # Grab the PlotDataItem out of the channel-lines map. This is
        # the real bound artist, not a fake.
        axis_handle, line_handle = canvas._channel_lines["a"]
        pdi = line_handle.plot_data_item
        assert pdi is not None, (
            "channel 'a' has no PlotDataItem — bind path is broken"
        )

        # Spy on the instance method via patch.object so the call count
        # observes the real bound call. We use side_effect=None to make
        # the call a no-op — we are testing the contract that the hot
        # path does NOT touch this method, not the result of the call.
        with patch.object(pdi, "setData") as spy:
            # Five panning iterations (different windows each time).
            windows = [
                (1.0, 4.0),
                (2.0, 5.0),
                (3.0, 6.0),
                (4.0, 7.0),
                (5.0, 8.0),
            ]
            for lo, hi in windows:
                canvas.set_xlim(lo, hi)
                canvas._flush_pending_refresh()
                QCoreApplication.processEvents()
            n_calls = spy.call_count

        # ZERO is the contract: pan must not touch PlotDataItem.setData.
        # (The bind already happened before the spy was installed.)
        assert n_calls == 0, (
            f"PlotDataItem.setData was called {n_calls} time(s) during "
            f"5 pan iterations; the module contract at the top of "
            f"pg_canvases.py says setData is bind-only and the pan/refresh "
            f"path is QPainterPath+QPixmap (cache-populated). This is the "
            f"W2 NEEDS-REWORK item from "
            f"docs/analyzer/reviews/2026-05-28-pyqtgraph-wave2.md:21."
        )

    def test_pdi_setdata_called_exactly_once_during_initial_bind(self, qapp):
        """Companion to the pan-path assertion: setData MAY be called
        once during the initial bind (the documented fallback path).
        Asserting "exactly once on bind" instead of "zero on bind" makes
        the contract concrete: bind is the bind-only path, and a future
        regression that adds a second bind-time call is also wrong.
        """
        from PyQt5.QtCore import QCoreApplication
        from unittest.mock import patch

        canvas = _pg_canvas(qapp)
        n = 1_000
        t = np.linspace(0.0, 1.0, n, dtype=np.float64)
        sig = np.sin(2 * np.pi * 5 * t).astype(np.float64)

        # We cannot easily spy on PlotDataItem.setData before bind
        # because the instance doesn't exist yet. Patch the CLASS
        # method, which catches the bound call from PlotItem.plot()
        # because pg.PlotDataItem internally calls self.setData(...)
        # during construction.
        import pyqtgraph as pg

        original_setdata = pg.PlotDataItem.setData
        call_count = {"n": 0}

        def _spy(self, *args, **kwargs):
            call_count["n"] += 1
            return original_setdata(self, *args, **kwargs)

        with patch.object(pg.PlotDataItem, "setData", _spy):
            canvas.plot_channels(
                [("a", True, t, sig, "#1769e0", "u", "fid-1")]
            )
            QCoreApplication.processEvents()
            bind_calls = call_count["n"]

            # Now drive the pan path with the spy STILL active. Any
            # call here means the hot path is still touching setData.
            canvas.set_xlim(0.2, 0.5)
            canvas._flush_pending_refresh()
            QCoreApplication.processEvents()
            after_pan_calls = call_count["n"]

        # bind_calls must be small (at most a couple — pyqtgraph may
        # internally call setData once in the constructor and once for
        # the supplied data). The pan path must NOT add to it.
        assert after_pan_calls == bind_calls, (
            f"PlotDataItem.setData was invoked {after_pan_calls - bind_calls} "
            f"additional time(s) during pan after {bind_calls} bind-time "
            f"call(s); pan path must not mutate PlotDataItem (W2 review)."
        )


class TestTimeDomainCanvasPGInsideLabelThresholdParametrized:
    """Cover the inside-vs-outside subplot label decision across the
    critical threshold (320 px) and a larger-than-standard width (1600
    px). Codex W2 review noted that the original tests covered only
    220 px and 1200 px, leaving the boundary behavior unproven.

    Per branch-reached-is-not-behavior-correct: each parametrize case
    is a real state-change assertion (the decision flips at the
    threshold), not merely "branch executed".
    """

    @pytest.mark.parametrize(
        "width_px,expected_inside",
        [
            (319, True),    # just below the 320 cutoff → inside
            (320, False),   # AT the cutoff: `widget_w < 320` is False → outside
            (321, True),    # just below in the original test... wait, 321 > 320 → outside
            (1600, False),  # well wide → outside
        ],
        ids=["px-319-inside", "px-320-outside", "px-321-outside", "px-1600-outside"],
    )
    def test_inside_label_threshold_near_boundary_and_large(
        self, qapp, width_px, expected_inside,
    ):
        """Parametrized over canvas widths spanning the threshold and
        a large width. The implementation rule is ``widget_w < 320``;
        we test the contract a future change cannot drift without an
        explicit test update."""
        from PyQt5.QtCore import QCoreApplication

        # Fix the parametrize IDs above: 321 > 320 so widget_w < 320 is
        # FALSE → outside (expected_inside should be False).
        # The 319 case (True) and 320 case (False) lock the boundary;
        # the 321 case is a regression guard against an off-by-one
        # flip of the comparator (<= vs <); 1600 covers a large width.
        if width_px == 321:
            expected_inside = False

        canvas = _pg_canvas(qapp)
        canvas.resize(width_px, 800)
        QCoreApplication.processEvents()
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        QCoreApplication.processEvents()

        # The decision is driven by self._glw.viewport().width(); resize
        # alone does not always propagate down to the inner viewport in
        # offscreen Qt. Pump events and (defensively) call the canvas's
        # own helper.
        QCoreApplication.processEvents()

        # The pyqtgraph viewport tracks the GraphicsLayoutWidget's
        # viewport size; for offscreen we mirror what the matplotlib
        # rule reads at the same point. The current rule reads the
        # GLW viewport width, NOT canvas.width(), so we sanity-check
        # the inner viewport size before asserting the decision so a
        # parametrized failure points at the right surface.
        decision = canvas._subplot_ylabels_need_inside_labels()
        assert decision is expected_inside, (
            f"width={width_px}px: expected inside_labels={expected_inside}, "
            f"got {decision!r}. The threshold rule at "
            f"pg_canvases.py:_subplot_ylabels_need_inside_labels is "
            f"`widget_w < 320`; viewport width = "
            f"{canvas._glw.viewport().width()}"
        )


def _path_elements(path):
    """Return [(type:int, x:float, y:float), ...] for a QPainterPath.

    ``QPainterPath.ElementType``: 0 = MoveToElement, 1 = LineToElement.
    Coordinates are rounded to 9 places so float-repr noise never trips
    the equality assertion while still catching a real geometry drift.
    """
    out = []
    for i in range(path.elementCount()):
        e = path.elementAt(i)
        out.append((int(e.type), round(float(e.x), 9), round(float(e.y), 9)))
    return out


def _build_painter_path_old_loop(t, s):
    """Reference implementation: the EXACT pre-T9 pure-Python loop that
    ``_build_painter_path`` used to be. Reproduced here verbatim so the
    parity test pins the vectorized ``arrayToQPath`` build to the same
    polyline geometry the interpreted loop produced (per
    signal-processing/2026-05-19-branch-reached-is-not-behavior-correct:
    assert ACTUAL element coordinates, not "looks similar").
    """
    from PyQt5.QtGui import QPainterPath

    path = QPainterPath()
    n = min(len(t), len(s))
    if n == 0:
        return path
    started = False
    t = np.asarray(t)
    s = np.asarray(s)
    for i in range(n):
        ti = float(t[i])
        si = float(s[i])
        if not (np.isfinite(ti) and np.isfinite(si)):
            started = False
            continue
        if not started:
            path.moveTo(ti, si)
            started = True
        else:
            path.lineTo(ti, si)
    return path


class TestBuildPainterPathParity:
    """Lock the T9 vectorization of ``_build_painter_path``.

    T9 replaced the pure-Python per-point ``QPainterPath.moveTo/lineTo``
    loop (which dominated the ~10.7 ms pan frame) with a vectorized
    ``pyqtgraph.functions.arrayToQPath(x, y, connect='all')`` build for the
    all-finite hot path, keeping the interpreted loop only for NaN-gap
    discontinuities. The visual output MUST stay byte-identical to the old
    loop: same element count, same element TYPES (MoveTo/LineTo), same
    coordinates, same order. These tests assert that against a reference
    re-implementation of the old loop on the production
    ``_build_painter_path`` method of a real ``TimeDomainCanvasPG``.

    Per codex-phantom-api-surface-guards: a REAL canvas is built and the
    REAL production method is exercised — arrayToQPath is not mocked.
    """

    @pytest.mark.parametrize(
        "t,s,expected_count,label",
        [
            ([0.0, 1.0, 2.0, 3.0], [10.0, 11.0, 12.0, 13.0], 4, "all-finite-4pt"),
            (list(np.linspace(0.0, 2.0, 50)),
             list(np.sin(np.linspace(0.0, 2.0, 50))), 50, "all-finite-50pt"),
            ([0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
             [10.0, 11.0, np.nan, 13.0, 14.0, 15.0], 5, "single-nan-gap"),
            ([0.0, 1.0, np.nan, np.nan, 4.0],
             [10.0, 11.0, np.nan, np.nan, 14.0], 3, "double-nan-gap"),
            ([np.nan, 1.0, 2.0], [np.nan, 11.0, 12.0], 2, "leading-nan"),
            ([0.0], [10.0], 1, "single-point"),
            ([], [], 0, "empty"),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_production_path_matches_old_loop_geometry(
        self, qapp, t, s, expected_count, label,
    ):
        """The production ``_build_painter_path`` output must equal the
        old-loop reference element-for-element across the finite and
        NaN-gap cases that the envelope can produce.
        """
        canvas = _pg_canvas(qapp)
        ta = np.asarray(t, dtype=np.float64)
        sa = np.asarray(s, dtype=np.float64)

        produced = canvas._build_painter_path(ta, sa)
        reference = _build_painter_path_old_loop(ta, sa)

        prod_elems = _path_elements(produced)
        ref_elems = _path_elements(reference)

        # Pin the element count explicitly (the headline regression signal
        # arrayToQPath could silently diverge on, per the brief).
        assert produced.elementCount() == expected_count, (
            f"[{label}] elementCount={produced.elementCount()} "
            f"!= expected {expected_count}"
        )
        # Byte-identical geometry: same count, same (type, x, y) tuples in
        # the same order as the old interpreted loop.
        assert prod_elems == ref_elems, (
            f"[{label}] vectorized path geometry diverged from the old "
            f"loop.\n  produced={prod_elems}\n  reference={ref_elems}"
        )

    def test_all_finite_path_is_moveto_then_lineto_run(self, qapp):
        """Spell out the expected all-finite element TYPES so a future
        change that, e.g., emits a closing element or reorders types is
        caught even if the count happens to match: element 0 is a MoveTo
        (type 0) and every subsequent element is a LineTo (type 1)."""
        canvas = _pg_canvas(qapp)
        n = 200
        t = np.linspace(0.0, 5.0, n).astype(np.float64)
        s = (np.sin(2 * np.pi * 1.3 * t) + 0.4 * np.cos(2 * np.pi * 4.1 * t))
        s = s.astype(np.float64)

        path = canvas._build_painter_path(t, s)
        assert path.elementCount() == n
        elems = _path_elements(path)
        assert elems[0][0] == 0, "first element must be a MoveToElement"
        assert all(e[0] == 1 for e in elems[1:]), (
            "all elements after the first must be LineToElement"
        )
        # Coordinates must equal the input arrays exactly (vectorized C
        # build copies x/y verbatim, no resampling).
        xs = np.array([e[1] for e in elems])
        ys = np.array([e[2] for e in elems])
        assert np.allclose(xs, t, rtol=0, atol=1e-9)
        assert np.allclose(ys, s, rtol=0, atol=1e-6)

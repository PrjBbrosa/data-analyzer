"""Regression coverage for CRC-like high-variation time-domain rendering."""

import importlib
import importlib.util

import numpy as np

from mf4_analyzer.signal.envelope import build_envelope
from mf4_analyzer.ui.pg_canvas.renderer import (
    _HIGH_VARIATION_BUCKET_BUDGET,
)


def _real_crc_shape():
    rng = np.random.default_rng(20260722)
    t = np.arange(5727, dtype=np.float64) / 100.0
    crc_like = rng.integers(0, 256, size=t.size).astype(np.float64)
    return t, crc_like


def _render_profile_api():
    module_name = "mf4_analyzer.ui.pg_canvas.render_profile"
    assert importlib.util.find_spec(module_name) is not None, (
        "RenderProfile must be a pure module so classification can run on raw "
        "arrays before any display envelope is built"
    )
    return importlib.import_module(module_name)


def test_dense_discrete_profile_is_stable_across_full_and_zoomed_windows():
    api = _render_profile_api()
    t, crc_like = _real_crc_shape()

    profile = api.classify_render_profile(t, crc_like, source_revision=17)

    assert profile.strategy == "dense_discrete"
    assert profile.source_length == 5727
    assert profile.approx_unique_count == 256
    assert profile.transition_fraction > 0.99
    assert api.bucket_width_for(
        profile, mode="subplot", pixel_width=1145, interactive=False,
    ) == _HIGH_VARIATION_BUCKET_BUDGET
    # A viewport does not get reclassified from its current envelope.  The
    # same raw-data profile therefore selects the same policy at zoom scale.
    assert api.bucket_width_for(
        profile, mode="subplot", pixel_width=800, interactive=False,
    ) == _HIGH_VARIATION_BUCKET_BUDGET
    interactive_width = api.bucket_width_for(
        profile, mode="subplot", pixel_width=1145, interactive=True,
    )
    assert 1 <= interactive_width < _HIGH_VARIATION_BUCKET_BUDGET


def test_dense_discrete_profile_is_data_based_not_channel_name_or_noise():
    api = _render_profile_api()
    t, crc_like = _real_crc_shape()
    smooth = np.sin(t).astype(np.float64)
    continuous_noise = np.random.default_rng(8).normal(size=t.size)
    rolling_counter = (np.arange(t.size) % 256).astype(np.float64)
    sparse_state = np.zeros(t.size, dtype=np.float64)
    sparse_state[1000:1100] = 1.0

    assert api.classify_render_profile(
        t, crc_like, source_revision="same-name",
    ).strategy == "dense_discrete"
    assert api.classify_render_profile(
        t, smooth, source_revision="EPS_CRC1",
    ).strategy == "general"
    assert api.classify_render_profile(
        t, continuous_noise, source_revision="EPS_CRC1",
    ).strategy == "general"
    assert api.classify_render_profile(
        t, rolling_counter, source_revision="counter",
    ).strategy == "dense_discrete"
    assert api.classify_render_profile(
        t, sparse_state, source_revision="EPS_CRC1",
    ).strategy == "general"


def test_long_periodic_counter_does_not_alias_to_constant_profile():
    api = _render_profile_api()
    # The old 8192-point linspace sampled this exact length every 256 source
    # points, so a modulo-256 counter appeared constant at every probe.
    n = 256 * 8191 + 1
    t = np.arange(n, dtype=np.float64)
    counter = (np.arange(n, dtype=np.uint32) % 256).astype(np.float64)

    profile = api.classify_render_profile(t, counter, source_revision=19)

    assert profile.strategy == "dense_discrete"
    assert profile.approx_unique_count == 256
    assert profile.transition_fraction > 0.99


def test_sampled_source_revision_is_stable_then_detects_in_place_change():
    api = _render_profile_api()
    t, values = _real_crc_shape()

    revision_before = api.source_revision_for(t, values)
    assert api.source_revision_for(t, values) == revision_before

    values[:] = np.arange(values.size) % 256
    assert api.source_revision_for(t, values) != revision_before


def test_initial_bind_builds_dense_discrete_envelope_once(qapp, monkeypatch):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui import pg_canvases
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    t, crc_like = _real_crc_shape()
    calls = []
    original = pg_canvases.build_envelope

    def _spy(*args, **kwargs):
        calls.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(pg_canvases, "build_envelope", _spy)
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()
    try:
        canvas.plot_channels([
            ("integrity_byte", True, t, crc_like, "#1769e0", "", "actual-blf"),
        ], mode="subplot")

        initial_calls = [call for call in calls if call.get("xlim") is None]
        assert len(initial_calls) == 1
        assert initial_calls[0]["pixel_width"] == _HIGH_VARIATION_BUCKET_BUDGET
    finally:
        canvas.close()


def test_viewport_refresh_selects_dense_width_before_one_envelope_call(
    qapp, monkeypatch,
):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui import pg_canvases
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    t, crc_like = _real_crc_shape()
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()
    try:
        canvas.plot_channels([
            ("integrity_byte", True, t, crc_like, "#1769e0", "", "actual-blf"),
        ], mode="subplot")
        axis = canvas._channel_lines["integrity_byte"][0]
        axis.set_ylim(0.0, 255.0)
        canvas._primary_xaxis_ax.set_xlim(10.0, 26.0)

        calls = []
        original = pg_canvases.positions_envelope

        def _spy(*args, **kwargs):
            calls.append(dict(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(pg_canvases, "positions_envelope", _spy)
        canvas._last_range_key.clear()
        canvas._refresh_visible_data()

        assert len(calls) == 1
        assert calls[0]["pixel_width"] == _HIGH_VARIATION_BUCKET_BUDGET
    finally:
        canvas.close()


def test_buffer_override_is_single_pass_records_coverage_and_keeps_viewbox(
    qapp, monkeypatch,
):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui import pg_canvases
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    t, crc_like = _real_crc_shape()
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()
    try:
        canvas.plot_channels([
            ("integrity_byte", True, t, crc_like, "#1769e0", "", "actual-blf"),
        ], mode="subplot")
        axis = canvas._channel_lines["integrity_byte"][0]
        axis.set_ylim(0.0, 255.0)
        canvas._primary_xaxis_ax.set_xlim(10.0, 26.0)
        view_before = tuple(canvas._primary_xaxis_ax.get_xlim())
        raw_t, raw_y, _color, _unit = canvas.channel_data["integrity_byte"]

        calls = []
        original = pg_canvases.positions_envelope

        def _spy(*args, **kwargs):
            calls.append(dict(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(pg_canvases, "positions_envelope", _spy)
        canvas._last_range_key.clear()
        coverage = canvas._renderer._refresh_visible_data(
            xlim_override=(6.0, 30.0), interactive=False,
        )

        assert len(calls) == 1
        assert calls[0]["xlim"] == (6.0, 30.0)
        assert calls[0]["pixel_width"] == _HIGH_VARIATION_BUCKET_BUDGET
        assert tuple(canvas._primary_xaxis_ax.get_xlim()) == view_before
        assert coverage == canvas._display_x_coverage
        assert coverage[0] <= view_before[0]
        assert coverage[1] >= view_before[1]
        assert 6.0 <= coverage[0] <= coverage[1] <= 30.0
        current_raw_t, current_raw_y, _color, _unit = (
            canvas.channel_data["integrity_byte"]
        )
        assert current_raw_t is raw_t is t
        assert current_raw_y is raw_y is crc_like
    finally:
        canvas.close()


def test_interactive_override_uses_coarse_single_pass_and_skips_settled_tail(
    qapp, monkeypatch,
):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui import pg_canvases
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    t, crc_like = _real_crc_shape()
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()
    try:
        canvas.plot_channels([
            ("integrity_byte", True, t, crc_like, "#1769e0", "", "actual-blf"),
        ], mode="subplot")
        axis = canvas._channel_lines["integrity_byte"][0]
        axis.set_ylim(0.0, 255.0)

        envelope_calls = []
        tail_calls = []
        original = pg_canvases.positions_envelope

        def _envelope_spy(*args, **kwargs):
            envelope_calls.append(dict(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(pg_canvases, "positions_envelope", _envelope_spy)
        monkeypatch.setattr(
            canvas._tick_density_controller,
            "_apply_target_x_ticks_to_all_axes",
            lambda: tail_calls.append("ticks"),
        )
        monkeypatch.setattr(
            canvas, "_emit_xrange_changed", lambda: tail_calls.append("range"),
        )
        monkeypatch.setattr(
            canvas, "schedule_idle_quality", lambda: tail_calls.append("quality"),
        )
        canvas._last_range_key.clear()
        coverage = canvas._renderer._refresh_visible_data(
            xlim_override=(6.0, 30.0), interactive=True,
        )

        assert coverage == canvas._display_x_coverage
        assert len(envelope_calls) == 1
        assert envelope_calls[0]["xlim"] == (6.0, 30.0)
        assert envelope_calls[0]["pixel_width"] < _HIGH_VARIATION_BUCKET_BUDGET
        assert tail_calls == []
    finally:
        canvas.close()


def test_in_place_raw_change_invalidates_cached_render_profile(qapp, monkeypatch):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui import pg_canvases
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    t, _crc_like = _real_crc_shape()
    values = np.sin(t).astype(np.float64)
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()
    try:
        canvas.plot_channels([
            ("same-array", True, t, values, "#1769e0", "", "source"),
        ], mode="subplot")
        cached_before = next(iter(canvas._channel_render_profiles.values()))
        assert cached_before.strategy == "general"

        # Keep object identity and length unchanged while replacing the raw
        # contents with a rolling counter.
        values[:] = np.arange(values.size) % 256
        calls = []
        original = pg_canvases.positions_envelope

        def _spy(*args, **kwargs):
            calls.append(dict(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(pg_canvases, "positions_envelope", _spy)
        canvas._last_range_key.clear()
        canvas._renderer._refresh_visible_data(interactive=False)

        cached_after = next(iter(canvas._channel_render_profiles.values()))
        assert cached_after.strategy == "dense_discrete"
        assert cached_after.source_revision != cached_before.source_revision
        assert len(calls) == 1
        assert calls[0]["pixel_width"] == _HIGH_VARIATION_BUCKET_BUDGET
        raw_t, raw_y, _color, _unit = canvas.channel_data["same-array"]
        assert raw_t is t
        assert raw_y is values
    finally:
        canvas.close()


def test_dense_discrete_profile_preserves_raw_channel_array(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    t, crc_like = _real_crc_shape()
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    QCoreApplication.processEvents()

    canvas.plot_channels([
        ("integrity_byte", True, t, crc_like, "#1769e0", "", "actual-blf"),
    ], mode="subplot")
    QCoreApplication.processEvents()

    line = canvas._channel_lines["integrity_byte"][1].plot_data_item
    shown_t, _shown_y = line.getData()
    expected_t, _expected_y = build_envelope(
        t,
        crc_like,
        xlim=None,
        pixel_width=_HIGH_VARIATION_BUCKET_BUDGET,
        is_monotonic=True,
    )
    assert len(shown_t) == len(expected_t)
    raw_t, raw_y, _color, _unit = canvas.channel_data["integrity_byte"]
    assert raw_t is t
    assert raw_y is crc_like
    canvas.close()


def test_dense_discrete_settled_envelope_preserves_bucket_extrema():
    api = _render_profile_api()
    t, crc_like = _real_crc_shape()
    # Force a narrow pulse into the source; min/max envelope must retain it.
    crc_like[2871] = 1024.0
    profile = api.classify_render_profile(t, crc_like, source_revision=18)
    width = api.bucket_width_for(
        profile, mode="subplot", pixel_width=1145, interactive=False,
    )

    env_t, env_y = build_envelope(
        t, crc_like, xlim=None, pixel_width=width, is_monotonic=True,
    )

    assert np.all(np.diff(env_t) >= 0.0)
    assert np.nanmin(env_y) == np.nanmin(crc_like)
    assert np.nanmax(env_y) == 1024.0

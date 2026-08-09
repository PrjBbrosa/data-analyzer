from types import SimpleNamespace
import warnings

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter


def _result():
    frequencies = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    transfer = np.array([1 + 0j, 2 + 0j, np.nan + 1j * np.nan, -1j, -2 + 0j])
    coherence = np.array([1.0, 0.95, np.nan, 0.4, 0.9])
    return SimpleNamespace(
        frequencies=frequencies,
        transfer=transfer,
        coherence=coherence,
        effective=SimpleNamespace(fs=100.0, df=1.0, segments=4),
        warnings=(),
    )


def test_frf_canvas_builds_three_shared_frequency_plots(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
    from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 700)
    canvas.show()
    qtbot.wait(20)

    assert canvas.plots == (
        canvas._plot_magnitude,
        canvas._plot_phase,
        canvas._plot_coherence,
    )
    assert canvas._plot_phase.vb.linkedView(pg.ViewBox.XAxis) is canvas._plot_magnitude.vb
    assert canvas._plot_coherence.vb.linkedView(pg.ViewBox.XAxis) is canvas._plot_magnitude.vb
    # Upper rows retain a one-pixel bottom frame; hiding that axis entirely
    # used to leave the magnitude and phase plots visually open.
    for plot in (canvas._plot_magnitude, canvas._plot_phase):
        bottom = plot.getAxis("bottom")
        assert bottom.isVisible() is True
        assert bottom.style["showValues"] is False
        assert bottom.height() <= 1.0
    assert canvas._plot_coherence.getAxis("bottom").labelText == "Frequency (Hz)"
    for plot in canvas.plots:
        assert isinstance(plot.vb, _ModifierWheelViewBox)
        assert getattr(plot, "buttonsHidden", False) is True
        assert plot.vb.border is None


def test_frf_canvas_display_transforms_do_not_mutate_result(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    result = _result()
    original_f = result.frequencies.copy()
    original_h = result.transfer.copy()

    canvas.set_result(result, {
        "magnitude_scale": "db",
        "frequency_scale": "log",
        "phase_mode": "unwrapped",
        "coherence_threshold": 0.8,
        "fade_low_coherence": True,
    }, {"input_unit": "N", "output_unit": "m/s"})

    assert np.all(canvas._draw_frequencies > 0)
    assert canvas._magnitude_curve.xData.size == 4
    assert canvas._phase_curve.opts["connect"] == "finite"
    assert canvas._coherence_curve.opts["connect"] == "finite"
    assert canvas._threshold_line.value() == 0.8
    assert canvas._magnitude_low_curve.xData.size == canvas._magnitude_curve.xData.size
    np.testing.assert_array_equal(result.frequencies, original_f)
    np.testing.assert_array_equal(result.transfer, original_h)

    canvas.set_display_params({
        "magnitude_scale": "linear",
        "frequency_scale": "linear",
        "phase_mode": "wrapped",
        "coherence_threshold": 0.5,
        "fade_low_coherence": False,
    })
    assert canvas._draw_frequencies[0] == 0.0
    assert canvas._magnitude_curve.xData.size == result.frequencies.size
    assert canvas._threshold_line.value() == 0.5
    assert canvas._magnitude_low_curve.isVisible() is False

    canvas.set_ylim("coherence", -2.0, 3.0)
    assert canvas.get_ylim("coherence") == pytest.approx((0.0, 1.0))


def test_frf_canvas_coherence_range_cursor_and_independent_y_ranges(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})

    y_range = canvas._plot_coherence.vb.viewRange()[1]
    assert y_range[0] == 0.0
    assert y_range[1] == 1.0

    canvas.set_ylim("magnitude", -30.0, 10.0)
    canvas.set_ylim("phase", -180.0, 180.0)
    canvas.set_ylim("coherence", 0.0, 1.0)
    assert canvas.get_ylims() == {
        "magnitude": (-30.0, 10.0),
        "phase": (-180.0, 180.0),
        "coherence": (0.0, 1.0),
    }

    seen = []
    canvas.cursor_info.connect(seen.append)
    readout = canvas.set_cursor_frequency(1.1)
    assert "f=1" in readout
    assert "|H|=" in readout
    assert "phase=" in readout
    assert "coherence=" in readout
    assert seen[-1] == readout
    assert all(line.value() == 1.0 for line in canvas._cursor_lines)


def test_frf_cursor_is_off_by_default_and_mouse_gate_clears_all_three_lines(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 700)
    canvas.show()
    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})
    qtbot.wait(20)
    seen = []
    canvas.cursor_info.connect(seen.append)
    scene_pos = canvas._plot_magnitude.vb.sceneBoundingRect().center()

    assert canvas.cursor_enabled() is False
    canvas._on_scene_mouse_moved(scene_pos)
    assert seen == []
    assert all(line.isVisible() is False for line in canvas._cursor_lines)

    canvas.set_cursor_enabled(True)
    canvas._on_scene_mouse_moved(scene_pos)
    assert seen and "f=" in seen[-1]
    assert all(line.isVisible() for line in canvas._cursor_lines)

    canvas.set_cursor_enabled(False)
    assert seen[-1] == ""
    assert all(line.isVisible() is False for line in canvas._cursor_lines)


def test_frf_dual_cursor_reports_frequency_delta_and_both_frf_values(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})
    primary, detail = [], []
    canvas.cursor_info.connect(primary.append)
    canvas.dual_cursor_info.connect(detail.append)

    canvas.set_cursor_mode("dual")
    text = canvas.set_dual_cursor_frequencies(1.1, 3.8)

    assert "A=1 Hz" in text and "B=4 Hz" in text and "Δf=+3 Hz" in text
    assert "background-color:#e8f1ff" in text
    assert "|H|=" in detail[-1] and "coherence=" in detail[-1]
    assert "ΔY：Δ|H|=" in detail[-1]
    assert "Δphase=" in detail[-1] and "Δcoherence=" in detail[-1]
    assert "background-color:#e8f1ff" in detail[-1]
    assert all(line.value() == pytest.approx(1.0) for line in canvas._cursor_a_lines)
    assert all(line.value() == pytest.approx(4.0) for line in canvas._cursor_b_lines)

    canvas.set_cursor_mode("off")
    assert primary[-1] == "" and detail[-1] == ""
    assert all(not line.isVisible() for lines in (
        canvas._cursor_lines, canvas._cursor_a_lines, canvas._cursor_b_lines,
    ) for line in lines)


def test_frf_canvas_log_xlim_and_cursor_keep_public_units_in_hz(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    result = _result()
    result.frequencies = np.array([0.0, 1.0, 10.0, 100.0, 1000.0])
    canvas.set_result(result, {"frequency_scale": "log"}, {})

    canvas.set_xlim(1.0, 100.0)
    assert canvas.get_xlim() == pytest.approx((1.0, 100.0))

    canvas.set_display_params({"magnitude_scale": "linear"})
    assert canvas.get_xlim() == pytest.approx((1.0, 100.0))

    readout = canvas.set_cursor_frequency(10.0)
    assert "f=10 Hz" in readout
    assert all(line.value() == pytest.approx(1.0) for line in canvas._cursor_lines)
    assert canvas._magnitude_low_points.opts["symbol"] == "o"
    assert np.count_nonzero(np.isfinite(canvas._magnitude_low_points.yData)) == 1


def test_frf_canvas_remarks_snap_to_panel_data_and_keep_hz_on_log_axis(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    result = SimpleNamespace(
        frequencies=np.array([1.0, 10.0, 100.0]),
        transfer=np.array([1.0 + 0j, 3.0 + 0j, 5.0 + 0j]),
        coherence=np.array([0.9, 0.8, 0.7]),
    )
    canvas.set_result(
        result,
        {"frequency_scale": "log", "magnitude_scale": "linear"},
        {"input_unit": "N", "output_unit": "m/s"},
    )
    canvas.set_remark_enabled(True)

    canvas.add_remark_at("magnitude", 11.0)
    assert canvas.remark_count() == 1
    magnitude = canvas._remarks[0]
    assert magnitude["vb"] is canvas._plot_magnitude.vb
    assert magnitude["data_x"] == pytest.approx(1.0)  # log10(10 Hz)
    label = magnitude["text"].textItem.toPlainText()
    assert "X=10 Hz" in label
    assert "Y=3 m/s/N" in label

    canvas.add_remark_at("coherence", 97.0)
    assert canvas.remark_count() == 2
    assert canvas._remarks[1]["vb"] is canvas._plot_coherence.vb

    canvas.remove_remark_near("magnitude", 10.0)
    assert canvas.remark_count() == 1
    assert canvas._remarks[0]["vb"] is canvas._plot_coherence.vb

    canvas.clear_remarks()
    assert canvas.remark_count() == 0


def test_frf_canvas_log_axis_uses_sparse_physical_hz_decades(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    result = _result()
    result.frequencies = np.array([0.0, 1.0, 10.0, 100.0, 1000.0])
    canvas.resize(1600, 1000)
    canvas.show()
    canvas.set_result(result, {"frequency_scale": "log"}, {})
    canvas.set_xlim(1.0, 1000.0)
    qtbot.wait(20)

    axis = canvas._plot_coherence.getAxis("bottom")
    assert axis._tickLevels[0] == [
        (0.0, "1"), (1.0, "10"), (2.0, "100"), (3.0, "1000"),
    ]
    expected_minor = [
        np.log10(value)
        for decade in (1.0, 10.0, 100.0)
        for value in (2.0 * decade, 3.0 * decade, 4.0 * decade,
                      5.0 * decade, 6.0 * decade, 7.0 * decade,
                      8.0 * decade, 9.0 * decade)
    ]
    assert [coord for coord, label in axis._tickLevels[1]] == pytest.approx(expected_minor)
    assert {label for _coord, label in axis._tickLevels[1]} == {""}
    # The FRF grid is intentionally as visible as the time-domain grid.
    assert axis.grid == round(0.28 * 255.0)
    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        _axis_spec, tick_specs, text_specs = axis.generateDrawSpecs(painter)
    finally:
        painter.end()
    # The 2..9 multipliers are visible full-height grids in every FRF row, so
    # the coherence X axis aligns with the magnitude and phase frequency grid.
    vertical_lengths = [abs(p2.y() - p1.y()) for _pen, p1, p2 in tick_specs]
    assert vertical_lengths and min(vertical_lengths) > 100.0
    for plot in canvas.plots:
        assert plot.getAxis("bottom")._tickLevels == axis._tickLevels
    physical_labels = {"1", "10", "100", "1000"}
    visible_specs = [
        (rect, text) for rect, _flags, text in text_specs
        if text in physical_labels
    ]
    # AxisItem may suppress an edge label that would cross the plot boundary;
    # all visible labels must remain sparse physical-Hz decades.
    assert len(visible_specs) >= 2
    assert {text for _rect, text in visible_specs} <= physical_labels
    text_rects = [rect for rect, _text in visible_specs]
    assert all(
        text_rects[index].right() < text_rects[index + 1].left()
        for index in range(len(text_rects) - 1)
    )


def _wideband_result():
    frequencies = np.array([0.0, 5.0, 20.0, 40.0, 80.0, 200.0])
    transfer = np.array(
        [1 + 0j, 2 + 0j, 3 + 1j, 1 - 1j, 0.5 + 0.5j, 0.25 + 0j]
    )
    coherence = np.array([1.0, 0.95, 0.99, 0.97, 0.93, 0.9])
    return SimpleNamespace(
        frequencies=frequencies,
        transfer=transfer,
        coherence=coherence,
        effective=SimpleNamespace(fs=1000.0, df=1.0, segments=4),
        warnings=(),
    )


def test_frf_canvas_log_axis_keeps_labels_when_zoomed_inside_one_decade(qtbot):
    """Regression: zooming between two decade integers blanked the whole axis.

    ``_sync_frequency_ticks`` pinned decade powers only, so a 20..80 Hz view --
    which straddles no integer power of ten -- produced ``[[], []]`` and
    pyqtgraph drew a frequency axis with no labels at all.
    """
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(1600, 1000)
    canvas.show()
    canvas.set_result(_wideband_result(), {"frequency_scale": "log"}, {})

    canvas.set_xlim(20.0, 80.0)
    qtbot.wait(20)

    axis = canvas._plot_coherence.getAxis("bottom")
    major = axis._tickLevels[0]
    assert len(major) >= 2
    assert [label for _coord, label in major] == ["20", "50"]
    # Labels remain physical Hz, not log10 coordinates.
    for coord, label in major:
        assert float(label) == pytest.approx(10.0 ** coord)

    # Widening back out restores the sparse decade row unchanged.
    canvas.set_xlim(1.0, 100.0)
    qtbot.wait(20)
    assert axis._tickLevels[0] == [(0.0, "1"), (1.0, "10"), (2.0, "100")]
    expected_minor = [
        np.log10(value)
        for decade in (1.0, 10.0)
        for value in (2.0 * decade, 3.0 * decade, 4.0 * decade,
                      5.0 * decade, 6.0 * decade, 7.0 * decade,
                      8.0 * decade, 9.0 * decade)
    ]
    assert [coord for coord, label in axis._tickLevels[1]] == pytest.approx(expected_minor)
    assert {label for _coord, label in axis._tickLevels[1]} == {""}


def test_frf_canvas_densest_mantissa_row_keeps_labels_from_colliding(qtbot):
    """``setTicks`` is a hard specification -- pyqtgraph never thins it.

    The worst case the ladder can produce is a just-under-two-decade window
    holding five 1-2-5 rungs (20/50/100/200/500), so that row is the one whose
    label geometry has to be checked.
    """
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    result = _wideband_result()
    result.frequencies = np.array([0.0, 10.5, 50.0, 200.0, 500.0, 950.0])
    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 620)
    canvas.show()
    canvas.set_result(result, {"frequency_scale": "log"}, {})
    canvas.set_xlim(10.5, 950.0)
    qtbot.wait(20)

    axis = canvas._plot_coherence.getAxis("bottom")
    labels = [label for _coord, label in axis._tickLevels[0]]
    assert labels == ["20", "50", "100", "200", "500"]

    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        _axis_spec, _tick_specs, text_specs = axis.generateDrawSpecs(painter)
    finally:
        painter.end()
    rects = [
        rect for rect, _flags, text in text_specs if text in set(labels)
    ]
    assert len(rects) >= 2
    rects.sort(key=lambda rect: rect.left())
    assert all(
        rects[index].right() < rects[index + 1].left()
        for index in range(len(rects) - 1)
    )


def test_frf_canvas_cursor_magnitude_carries_its_scale_unit(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(
        _wideband_result(),
        {"magnitude_scale": "db", "frequency_scale": "linear"},
        {"input_unit": "N", "output_unit": "m/s"},
    )

    db_readout = canvas.set_cursor_frequency(20.0)
    assert " dB" in db_readout
    assert "phase=" in db_readout and "coherence=" in db_readout

    canvas.set_display_params({"magnitude_scale": "linear"})
    linear_readout = canvas.set_cursor_frequency(20.0)
    assert " dB" not in linear_readout
    # Linear magnitude keeps the directional ratio unit of the pair.
    assert "m/s/N" in linear_readout
    magnitude = float(
        linear_readout.split("|H|=")[1].split(" ")[0]
    )
    assert magnitude == pytest.approx(abs(3 + 1j), rel=1e-4)


def test_frf_canvas_cursor_omits_a_dimensionless_ratio_suffix(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(
        _wideband_result(),
        {"magnitude_scale": "linear", "frequency_scale": "linear"},
        {"input_unit": "N", "output_unit": "N"},
    )

    readout = canvas.set_cursor_frequency(20.0)
    assert " dB" not in readout
    # output/input of matching units is "1"; a bare "1" suffix reads as a digit.
    assert "|H|=3.1623 |" in readout

    canvas.set_result(
        _wideband_result(), {"magnitude_scale": "linear"}, {},
    )
    assert "ratio" not in canvas.set_cursor_frequency(20.0)


def test_frf_canvas_toolbar_history_round_trips_log_ranges_in_hz(qtbot):
    from mf4_analyzer.ui.chart_stack.toolbar import PgNavigationToolbar
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    toolbar = PgNavigationToolbar(canvas)
    qtbot.addWidget(canvas)
    qtbot.addWidget(toolbar)
    result = _result()
    result.frequencies = np.array([0.0, 1.0, 10.0, 100.0, 1000.0])
    canvas.set_result(result, {"frequency_scale": "log"}, {})
    canvas.set_xlim(1.0, 10.0)
    toolbar.rebind_history_capture()

    canvas.set_xlim(10.0, 100.0)
    toolbar._commit_pending_view()
    toolbar.back()
    assert canvas.get_xlim() == pytest.approx((1.0, 10.0))
    toolbar.forward()
    assert canvas.get_xlim() == pytest.approx((10.0, 100.0))


def test_frf_canvas_reuses_analysis_wheel_and_tick_density_contract(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})
    canvas._plot_magnitude.setXRange(0.0, 4.0, padding=0)
    canvas._plot_magnitude.setYRange(-10.0, 10.0, padding=0)

    x_before, y_before = canvas._plot_magnitude.vb.viewRange()
    assert canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ControlModifier, x_pos=2.0, y_pos=0.0,
        view_box=canvas._plot_magnitude.vb,
    ) is True
    x_after, y_after = canvas._plot_magnitude.vb.viewRange()
    assert x_after[1] - x_after[0] < x_before[1] - x_before[0]
    assert y_after == pytest.approx(y_before)

    assert canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ShiftModifier, x_pos=2.0, y_pos=0.0,
        view_box=canvas._plot_magnitude.vb,
    ) is True
    _, y_zoomed = canvas._plot_magnitude.vb.viewRange()
    assert y_zoomed[1] - y_zoomed[0] < y_before[1] - y_before[0]

    canvas.set_tick_density(20, 12)
    assert canvas._plot_coherence.getAxis("bottom")._tickDensity == pytest.approx(2.0)
    for plot in canvas.plots:
        axis = plot.getAxis("left")
        assert axis._tickDensity == pytest.approx(2.0)
        assert axis.style["maxTickLevel"] == 0


def test_frf_canvas_wheel_zoom_temporarily_disables_curve_antialiasing(
    qtbot, monkeypatch
):
    """FRF must take the cheap raster path for an active wheel gesture."""
    from mf4_analyzer.ui.pg_canvas import frf_canvas

    # This unit test directly invokes the idle slot; preceding widget tests
    # can leave Qt's process-wide button state stale.  The production guard is
    # still covered by its real mouse-event paths, while this probe explicitly
    # exercises the no-button branch.
    monkeypatch.setattr(
        frf_canvas,
        "QApplication",
        SimpleNamespace(mouseButtons=lambda: Qt.NoButton),
    )
    PgFrfCanvas = frf_canvas.PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})
    canvas._plot_magnitude.setXRange(0.0, 4.0, padding=0)
    canvas._plot_magnitude.setYRange(-10.0, 10.0, padding=0)
    curves = (
        canvas._magnitude_curve,
        canvas._magnitude_low_curve,
        canvas._phase_curve,
        canvas._phase_low_curve,
        canvas._coherence_curve,
    )
    assert all(curve.opts["antialias"] for curve in curves)

    assert canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ControlModifier, x_pos=2.0, y_pos=0.0,
        view_box=canvas._plot_magnitude.vb,
    ) is True

    assert canvas._aa_on is False
    assert all(curve.opts["antialias"] is False for curve in curves)
    assert canvas._aa_idle_timer.isActive()

    canvas._enable_idle_quality()

    assert canvas._aa_on is True
    assert all(curve.opts["antialias"] is True for curve in curves)

    # Native pan/plain-wheel gestures arrive through ViewBox's manual-range
    # signal rather than the modifier-wheel dispatch above.
    view_box = canvas._plot_magnitude.vb
    view_box.sigRangeChangedManually.emit(view_box.state["mouseEnabled"])

    assert canvas._aa_on is False
    assert all(curve.opts["antialias"] is False for curve in curves)
    assert canvas._aa_idle_timer.isActive()


def test_frf_canvas_never_sends_all_nan_data_to_low_coherence_scatter(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    result = _result()
    result.coherence = np.ones(result.frequencies.shape, dtype=float)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        canvas.set_result(result, {
            "frequency_scale": "linear",
            "coherence_threshold": 0.8,
            "fade_low_coherence": True,
        }, {})

    assert canvas._magnitude_low_points.xData is None
    assert canvas._phase_low_points.xData is None


def test_frf_canvas_low_coherence_scatter_keeps_isolated_finite_bins(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(_result(), {
        "frequency_scale": "linear",
        "coherence_threshold": 0.8,
        "fade_low_coherence": True,
    }, {})

    np.testing.assert_array_equal(canvas._magnitude_low_points.xData, [3.0])
    assert np.isfinite(canvas._magnitude_low_points.yData).all()
    np.testing.assert_array_equal(canvas._phase_low_points.xData, [3.0])
    assert np.isfinite(canvas._phase_low_points.yData).all()


def test_frf_canvas_nan_coherence_is_low_trust_for_real_zero_output(qtbot):
    from mf4_analyzer.signal.frf import FrfParams, compute_frf
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    fs = 64.0
    time = np.arange(1024, dtype=float) / fs
    result = compute_frf(
        np.sin(2.0 * np.pi * 5.0 * time), np.zeros(time.shape), fs=fs,
        params=FrfParams(
            t_win_s=1.0, overlap=0.5, nfft_mode="manual", nfft=64,
            window="hanning", detrend="none",
        ),
    )
    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        canvas.set_result(result, {
            "frequency_scale": "linear",
            "fade_low_coherence": True,
            "coherence_threshold": 0.8,
        }, {})

    assert not np.any(np.isfinite(canvas._magnitude_curve.yData))
    assert np.count_nonzero(np.isfinite(canvas._magnitude_low_curve.yData)) == 3


def test_frf_canvas_marks_only_finite_singleton_runs(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    isolated = SimpleNamespace(
        frequencies=np.array([0.0, 1.0, 2.0]),
        transfer=np.array([np.nan + 1j * np.nan, 2.0 + 0j, np.nan + 1j * np.nan]),
        coherence=np.array([np.nan, 0.95, np.nan]),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        canvas.set_result(isolated, {
            "frequency_scale": "linear", "fade_low_coherence": False,
        }, {})
    np.testing.assert_array_equal(canvas._magnitude_singleton_points.xData, [1.0])
    np.testing.assert_array_equal(canvas._phase_singleton_points.xData, [1.0])

    only_dc = SimpleNamespace(
        frequencies=np.array([0.0]), transfer=np.array([2.0 + 0j]),
        coherence=np.array([0.95]),
    )
    canvas.set_result(only_dc, {
        "frequency_scale": "linear", "fade_low_coherence": False,
    }, {})
    np.testing.assert_array_equal(canvas._magnitude_singleton_points.xData, [0.0])

    continuous = SimpleNamespace(
        frequencies=np.array([0.0, 1.0, 2.0]),
        transfer=np.array([1.0 + 0j, 2.0 + 0j, 3.0 + 0j]),
        coherence=np.ones(3),
    )
    canvas.set_result(continuous, {
        "frequency_scale": "linear", "fade_low_coherence": False,
    }, {})
    assert canvas._magnitude_singleton_points.xData is None


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ({"output_unit": "m/s²", "input_unit": "N"}, "Magnitude (m/s²/N)"),
        ({"output_unit": "N", "input_unit": "N"}, "Magnitude (1)"),
        ({"output_unit": "m/s²"}, "Magnitude (m/s²)"),
        ({"input_unit": "N"}, "Magnitude (1/N)"),
    ],
)
def test_frf_canvas_linear_ratio_unit_respects_missing_endpoints(
    qtbot, context, expected,
):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.set_result(_result(), {
        "frequency_scale": "linear", "magnitude_scale": "linear",
    }, context)
    assert canvas._plot_magnitude.getAxis("left").labelText == expected


def test_frf_canvas_deferred_delete_drains_owned_pyqtgraph_tree(qapp):
    from PyQt5 import sip
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})
    canvas.close()
    canvas.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert sip.isdeleted(canvas)


def test_frf_canvas_state_hints_and_full_reset(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)

    for state, text in (
        ("empty", "请选择输入和输出"),
        ("stale", "参数已变化，点击计算"),
        ("progress", "正在计算"),
        ("error", "计算失败"),
    ):
        canvas.set_state(state)
        assert canvas.state() == state
        assert text in canvas._empty_hint_text

    canvas.set_result(_result(), {"frequency_scale": "linear"}, {})
    assert canvas.has_result()
    canvas.full_reset()
    assert not canvas.has_result()
    assert canvas.get_xlim() is None
    assert canvas.state() == "empty"

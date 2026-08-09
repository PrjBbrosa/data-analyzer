from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QCoreApplication, QEvent

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_models import (
    BatchFrfFigureSpec,
    BatchFrfSeries,
    BatchRenderContext,
)


def _series(label="Acceleration / Force", *, phase=0.0, nan_gap=False):
    frequency = np.array([0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0])
    transfer = (1.0 + frequency / 10.0) * np.exp(
        1j * (phase + frequency / 20.0)
    )
    coherence = np.array([0.95, 0.92, 0.35, 0.91, 0.4, 0.88, 0.97])
    if nan_gap:
        transfer[3] = np.nan + 1j * np.nan
        coherence[3] = np.nan
    return BatchFrfSeries(
        frequency_hz=frequency,
        transfer=transfer,
        coherence=coherence,
        label=label,
        source_display_name="Rig A",
        input_channel="Force",
        output_channel="Acceleration",
        input_unit="N",
        output_unit="m/s²",
    )


def _runner_frf_file(
    tmp_path, name, *, gain=2.0, output_channels=("response",), idx=0,
):
    from mf4_analyzer.io import FileData

    fs = 100.0
    time = np.arange(400, dtype=float) / fs
    command = np.sin(2.0 * np.pi * 5.0 * time)
    values = {"Time": time, "command": command}
    units = {"command": "V"}
    for offset, output in enumerate(output_channels, start=1):
        values[output] = gain * offset * command
        units[output] = "N"
    frame = pd.DataFrame(values)
    return FileData(
        tmp_path / f"{name}.csv", frame, list(frame.columns), units, idx=idx,
    )


def _runner_frf_preset(*, output_channels, grouping):
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput
    from mf4_analyzer.batch_types import FrfPairRule

    return AnalysisPreset.free_config(
        name="FRF renderer identity",
        method="frf",
        frf_pair_rules=(FrfPairRule("command", tuple(output_channels)),),
        params={
            "estimator": "h1",
            "window": "hanning",
            "periodic_window": True,
            "t_win_s": 0.5,
            "overlap": 0.5,
            "nfft_mode": "auto",
            "detrend": "none",
            "render_group_by": grouping,
        },
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            image_size="custom",
            image_width=640,
            image_height=420,
        ),
    )


def _page_text(scene) -> str:
    return " ".join(
        getattr(getattr(item, "item", item), "toPlainText", lambda: "")()
        for item in scene.page_labels
    )


def test_frf_dto_is_qt_neutral_and_validates_raw_arrays():
    item = _series()
    assert item.frequency_hz.ndim == item.transfer.ndim == item.coherence.ndim == 1
    assert np.iscomplexobj(item.transfer)
    assert item.frequency_hz[0] == 0.0

    with pytest.raises(ValueError, match="strictly increasing"):
        BatchFrfSeries(np.array([0.0, 1.0, 1.0]), np.ones(3, complex), np.ones(3), "x")
    with pytest.raises(ValueError, match="complex"):
        BatchFrfSeries(np.array([0.0, 1.0]), np.ones(2), np.ones(2), "x")
    with pytest.raises(ValueError, match="equal lengths"):
        BatchFrfSeries(np.array([0.0, 1.0]), np.ones(2, complex), np.ones(1), "x")
    with pytest.raises(ValueError, match="one-dimensional"):
        BatchFrfSeries(np.ones((2, 2)), np.ones(4, complex), np.ones(4), "x")


def test_frf_figure_spec_validates_display_contract():
    item = _series()
    spec = BatchFrfFigureSpec(
        (item,), magnitude_scale="db", frequency_scale="log",
        phase_mode="unwrapped", coherence_threshold=0.8,
        fade_low_coherence=True,
    )
    assert spec.series == (item,)
    with pytest.raises(ValueError, match="magnitude_scale"):
        BatchFrfFigureSpec((item,), magnitude_scale="absolute")
    with pytest.raises(ValueError, match="coherence_threshold"):
        BatchFrfFigureSpec((item,), coherence_threshold=2.0)


def test_frf_renderer_builds_shared_three_panel_scene_without_mutating_dc(qapp):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    first = _series(nan_gap=True)
    second = _series("Angle / Force", phase=0.3)
    spec = BatchFrfFigureSpec((first, second))
    context = BatchRenderContext(
        source_display_name="Rig A", method="frf",
        effective_facts={
            "estimator": "h1", "window": "hanning",
            "nfft_effective": 4096, "segments": 8, "actual_fs": 2048.0,
        },
    )
    scene = build_batch_scene(
        ("frf", spec),
        options=BatchRenderOptions(
            width_px=960, height_px=640, line_width=2.0,
        ),
        context=context,
    )
    try:
        scene.show_and_settle()
        assert len(scene.plots) == 3
        assert tuple(scene.panel_titles) == ("Magnitude", "Phase", "Coherence")
        assert scene.plots[0].getAxis("bottom").isVisible() is False
        assert scene.plots[1].getAxis("bottom").isVisible() is False
        assert scene.plots[2].getAxis("bottom").labelText == "Frequency (Hz)"
        assert scene.plots[2].getAxis("bottom")._tickLevels[0] == [
            (0.0, "1"), (1.0, "10"),
        ]
        scene.plots[0].setXRange(0.0, 1.2, padding=0)
        qapp.processEvents()
        assert scene.plots[1].vb.viewRange()[0] == pytest.approx(
            scene.plots[0].vb.viewRange()[0]
        )
        assert scene.plots[2].vb.viewRange()[0] == pytest.approx(
            scene.plots[0].vb.viewRange()[0]
        )
        assert scene.plots[2].vb.viewRange()[1] == pytest.approx((0.0, 1.0))

        for series_index in range(2):
            colors = {
                scene.frf_panel_curves[panel][series_index].opts["pen"].color().name()
                for panel in range(3)
            }
            assert len(colors) == 1
            assert all(
                scene.frf_panel_curves[panel][series_index].opts["pen"].widthF()
                == pytest.approx(2.0)
                for panel in range(3)
            )
        # PlotDataItem.getData() is in pyqtgraph's log10 view coordinates;
        # xData retains the supplied physical-Hz bins and proves DC was not
        # handed to the logarithmic drawing path.
        assert np.nanmin(scene.frf_panel_curves[0][0].xData) > 0.0
        assert first.frequency_hz[0] == 0.0
        assert np.isnan(first.transfer[3].real)
        assert scene.frf_threshold_line.value() == pytest.approx(0.8)
        page_text = " ".join(
            getattr(getattr(item, "item", item), "toPlainText", lambda: "")()
            for item in scene.page_labels
        )
        assert "Acceleration / Force" in page_text
        for fact in ("H1", "hanning", "NFFT=4096", "segments=8", "Fs=2048 Hz"):
            assert fact in page_text
    finally:
        scene.close()


def test_frf_narrow_band_log_axis_still_labels_physical_hz(qapp):
    """Regression: a narrow band straddling no decade integer lost every label.

    ``_apply_tick_density`` pinned decade powers only, so a 20..80 Hz FRF with
    a log frequency axis exported a PNG whose frequency axis was blank.
    """
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    frequency = np.array([20.0, 30.0, 40.0, 55.0, 70.0, 80.0])
    narrow = BatchFrfSeries(
        frequency_hz=frequency,
        transfer=(1.0 + frequency / 100.0) * np.exp(1j * frequency / 200.0),
        coherence=np.full(frequency.size, 0.95),
        label="Acceleration / Force",
        source_display_name="Rig A",
        input_channel="Force",
        output_channel="Acceleration",
        input_unit="N",
        output_unit="m/s²",
    )
    scene = build_batch_scene(
        ("frf", BatchFrfFigureSpec((narrow,), frequency_scale="log")),
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=BatchRenderContext(source_display_name="Rig A", method="frf"),
    )
    try:
        scene.show_and_settle()
        axis = scene.plots[2].getAxis("bottom")
        assert axis.logMode is True
        major = axis._tickLevels[0]
        assert len(major) >= 2
        for coord, label in major:
            assert float(label) == pytest.approx(10.0 ** coord, rel=1e-9)
        assert {label for _coord, label in major} == {"20", "50"}
        minor_hz = [10.0 ** coord for coord, _label in axis._tickLevels[1]]
        assert minor_hz == pytest.approx([30.0, 40.0, 60.0, 70.0, 80.0])
        assert {label for _coord, label in axis._tickLevels[1]} == {""}
    finally:
        scene.close()


def test_frf_render_options_control_exact_image_geometry_and_background(qapp):
    from PyQt5.QtGui import QColor

    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.batch_render_qt._export import render_scene_image

    options = BatchRenderOptions(
        width_px=800, height_px=480, dpi=180,
        background="white", line_width=1.0,
    )
    scene = build_batch_scene(
        ("frf", BatchFrfFigureSpec((_series(),))),
        options=options,
        context=BatchRenderContext(source_display_name="Rig A", method="frf"),
    )
    try:
        image = render_scene_image(scene)
        assert (image.width(), image.height()) == (800, 480)
        assert QColor(image.pixel(0, 0)).name() == "#ffffff"
        assert image.dotsPerMeterX() == pytest.approx(180 / 0.0254, abs=2)
    finally:
        scene.close()


def test_frf_representative_preview_and_run_share_byte_identical_builder(qapp):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.batch_render_qt._export import render_scene_image

    payload = ("frf", BatchFrfFigureSpec((_series(),)))
    options = BatchRenderOptions(width_px=640, height_px=420)
    context = BatchRenderContext(source_display_name="Rig A", method="frf")
    images = []
    for _consumer in ("preview", "run"):
        scene = build_batch_scene(payload, options=options, context=context)
        try:
            images.append(render_scene_image(scene))
        finally:
            scene.close()
    assert images[0] == images[1]


@pytest.mark.parametrize(
    ("grouping", "source_count", "outputs", "expected_identity"),
    [
        ("none", 1, ("response",), "response / command"),
        ("source", 1, ("response-a", "response-b", "response-c"),
         "3 outputs / command"),
        ("channel", 3, ("response",), "response / command · 3 sources"),
    ],
)
def test_real_batch_runner_frf_png_uses_dto_identity_for_group_subtitle(
    qapp, tmp_path, monkeypatch,
    grouping, source_count, outputs, expected_identity,
):
    import mf4_analyzer.batch_render_qt as renderer
    from mf4_analyzer.batch import BatchRunner

    built_scenes = []
    real_builder = renderer.build_batch_scene

    def capture_scene(*args, **kwargs):
        scene = real_builder(*args, **kwargs)
        built_scenes.append({
            "text": _page_text(scene),
            "panels": tuple(scene.panel_titles),
            "series_count": len(scene.frf_panel_curves[0]),
        })
        return scene

    monkeypatch.setattr(renderer, "build_batch_scene", capture_scene)
    files = {
        index: _runner_frf_file(
            tmp_path,
            "duplicate-readable-name" if grouping == "channel"
            else f"source-{index + 1}",
            gain=index + 1.0,
            output_channels=outputs, idx=index,
        )
        for index in range(source_count)
    }
    result = BatchRunner(files).run(
        _runner_frf_preset(output_channels=outputs, grouping=grouping),
        tmp_path / f"out-{grouping}",
    )

    assert result.status == "done"
    if grouping == "none":
        image_path = result.items[0].image_path
    else:
        assert len(result.render_groups) == 1
        image_path = result.render_groups[0].image_path
    assert image_path is not None
    image_bytes = Path(image_path).read_bytes()
    assert image_bytes.startswith(b"\x89PNG")
    assert built_scenes == [{
        "text": built_scenes[0]["text"],
        "panels": ("Magnitude", "Phase", "Coherence"),
        "series_count": source_count * len(outputs),
    }]
    assert expected_identity in built_scenes[0]["text"]


def test_frf_renderer_never_drops_group_members_or_parses_identity_from_label(qapp):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    first = replace(
        _series(label="same readable label"),
        input_channel="portable input",
        output_channel="portable output",
        effective_facts={
            "estimator": "h2", "window": "hann", "nfft_effective": 2048,
            "segments": 4, "actual_fs": 1024.0,
        },
    )
    series = (first,) + tuple(
        replace(
            _series(label="same readable label", phase=index * 0.05),
            source_display_name=f"Rig {index + 1}",
            input_channel="portable input",
            output_channel="portable output",
        )
        for index in range(1, 9)
    )
    scene = build_batch_scene(
        ("frf", BatchFrfFigureSpec(series)),
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=BatchRenderContext(source_display_name="Rig A", method="frf"),
    )
    try:
        scene.show_and_settle()
        assert all(len(panel) == 9 for panel in scene.frf_panel_curves)
        page_text = " ".join(
            getattr(getattr(item, "item", item), "toPlainText", lambda: "")()
            for item in scene.page_labels
        )
        assert "portable output / portable input" in page_text
        assert "same readable label" not in page_text
        for fact in ("H2", "hann", "NFFT=2048", "segments=4", "Fs=1024 Hz"):
            assert fact in page_text
    finally:
        scene.close()


def test_frf_dto_and_renderer_accept_zero_output_with_nan_coherence(qapp):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.signal.frf import FrfParams, compute_frf

    fs = 64.0
    time = np.arange(1024, dtype=float) / fs
    result = compute_frf(
        np.sin(2.0 * np.pi * 5.0 * time),
        np.zeros(time.shape, dtype=float),
        fs=fs,
        params=FrfParams(
            t_win_s=1.0, overlap=0.5, nfft_mode="manual", nfft=64,
            window="hanning", detrend="none",
        ),
    )
    assert np.any(np.isfinite(result.transfer.real))
    assert not np.any(np.isfinite(result.coherence))

    series = BatchFrfSeries(
        result.frequencies, result.transfer, result.coherence,
        "Zero output / Input",
        input_channel="Input", output_channel="Zero output",
        input_unit=123, output_unit=None,
    )
    assert series.input_unit == "123"
    assert series.output_unit == ""
    scene = build_batch_scene(
        ("frf", BatchFrfFigureSpec((series,))),
        options=BatchRenderOptions(width_px=640, height_px=420),
    )
    try:
        scene.show_and_settle()
        assert len(scene.frf_panel_curves[0]) == 1
    finally:
        scene.close()


@pytest.mark.parametrize(
    ("input_unit", "output_unit", "expected"),
    [
        ("N", "m/s²", "Magnitude (m/s²/N)"),
        ("N", "N", "Magnitude (1)"),
        ("", "m/s²", "Magnitude (m/s²)"),
        ("N", "", "Magnitude (1/N)"),
    ],
)
def test_frf_linear_magnitude_axis_uses_directional_ratio_units(
    qapp, input_unit, output_unit, expected,
):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    series = replace(
        _series(), input_unit=input_unit, output_unit=output_unit,
    )
    scene = build_batch_scene((
        "frf", BatchFrfFigureSpec((series,), magnitude_scale="linear"),
    ))
    try:
        scene.show_and_settle()
        assert scene.plots[0].getAxis("left").labelText == expected
    finally:
        scene.close()


def test_frf_mixed_linear_ratio_units_are_explicit_per_series(qapp):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    first = _series("Acceleration / Force")
    second = replace(
        _series("Angle / Torque", phase=0.2),
        input_channel="Torque", output_channel="Angle",
        input_unit="N·m", output_unit="deg",
    )
    scene = build_batch_scene((
        "frf", BatchFrfFigureSpec((first, second), magnitude_scale="linear"),
    ))
    try:
        scene.show_and_settle()
        assert scene.plots[0].getAxis("left").labelText == "Magnitude (mixed ratios)"
        labels = [label.text for _sample, label in scene.legend.items]
        assert labels == [
            "Acceleration / Force [m/s²/N]",
            "Angle / Torque [deg/N·m]",
        ]
        for sample, _label in scene.legend.items:
            assert sample.item in scene.frf_bright_curves[0]
            assert sample.item.opts["pen"].color().alpha() == 255
    finally:
        scene.close()


def test_frf_renderer_marks_only_singleton_runs_and_preserves_nan_gaps(qapp):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    isolated = BatchFrfSeries(
        np.array([0.0, 1.0, 2.0]),
        np.array([np.nan + 1j * np.nan, 2.0 + 0j, np.nan + 1j * np.nan]),
        np.array([np.nan, 0.95, np.nan]),
        "Output / Input", input_channel="Input", output_channel="Output",
    )
    scene = build_batch_scene((
        "frf", BatchFrfFigureSpec(
            (isolated,), magnitude_scale="linear", frequency_scale="linear",
            fade_low_coherence=True,
        ),
    ))
    try:
        scene.show_and_settle()
        for panel in (0, 1):
            marker = scene.frf_high_singleton_markers[panel][0]
            np.testing.assert_array_equal(marker.xData, [1.0])
            assert marker.opts["symbolBrush"].color().alpha() == 255
        assert scene.frf_low_singleton_markers[0][0].xData is None
    finally:
        scene.close()

    only_dc = replace(
        isolated,
        frequency_hz=np.array([0.0]),
        transfer=np.array([2.0 + 0j]),
        coherence=np.array([0.2]),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        scene = build_batch_scene((
            "frf", BatchFrfFigureSpec(
                (only_dc,), magnitude_scale="linear", frequency_scale="linear",
                fade_low_coherence=True,
            ),
        ))
        try:
            scene.show_and_settle()
            marker = scene.frf_low_singleton_markers[0][0]
            np.testing.assert_array_equal(marker.xData, [0.0])
            assert marker.opts["symbolBrush"].color().alpha() < 255
        finally:
            scene.close()


def test_frf_scene_close_deferred_delete_releases_widget(qapp):
    from PyQt5 import sip
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    scene = build_batch_scene(("frf", BatchFrfFigureSpec((_series(),))))
    widget = scene.widget
    scene.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert sip.isdeleted(widget)

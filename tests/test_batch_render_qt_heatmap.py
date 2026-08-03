from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QRectF, Qt

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt import BatchRenderContext
from mf4_analyzer.batch_render_qt._builder import build_batch_scene


GOLDEN = "tests/data/colormap_golden.npz"


def _spectro(*, metadata=None):
    return SimpleNamespace(
        x=np.asarray([10.0, 20.0, 40.0]),
        y=np.asarray([1.0, 4.0]),
        # BatchRunner's _Spectro2D producer is x-major: X rows, Y columns.
        matrix=np.asarray(
            [
                [0.10, 0.20],
                [0.30, 0.40],
                [0.50, 0.60],
            ]
        ),
        x_name="time_s",
        y_name="frequency_hz",
        metadata=dict(metadata or {}),
    )


def _context(*, unit="g", method="FFT vs Time"):
    return BatchRenderContext(
        source_display_name="单帧热图.mf4",
        channel="Acceleration",
        unit=unit,
        method=method,
        task_id="T3-heatmap",
    )


def _open_scene(qapp, kind, *, payload=None, params=None, warnings_out=None):
    scene = build_batch_scene(
        (kind, _spectro() if payload is None else payload),
        params=params,
        context=_context(method="Order" if kind == "order_time" else "FFT vs Time"),
        options=BatchRenderOptions(width_px=960, height_px=640),
        warnings_out=warnings_out,
    )
    scene.show_and_settle()
    qapp.processEvents()
    return scene


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_uses_row_major_turbo_golden_and_has_no_native_chrome(qapp, kind):
    scene = _open_scene(
        qapp,
        kind,
        params={"amplitude_mode": "amplitude", "cmap": "turbo"},
    )
    try:
        golden = np.load(GOLDEN)["turbo"]
        assert scene.image_item.axisOrder == "row-major"
        np.testing.assert_array_equal(scene.heatmap_lut, golden)
        assert scene.colorbar.colorMapMenu is False
        assert scene.colorbar.vb.menuEnabled() is False
        assert scene.colorbar.vb.state["mouseEnabled"] == [False, False]
        assert scene.plots[0].menuEnabled() is False
        assert scene.plots[0].vb.state["mouseEnabled"] == [False, False]
        auto_button = getattr(scene.plots[0], "autoBtn", None)
        assert auto_button is None or not auto_button.isVisible()
        assert scene.widget.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert scene.widget.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert scene.widget.focusPolicy() == Qt.NoFocus
    finally:
        scene.close()


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_x_major_payload_becomes_one_row_major_display_matrix(qapp, kind):
    payload = _spectro(metadata={"coverage_start": 2.0, "coverage_end": 60.0})
    if kind == "order_time":
        payload.y_name = "order"
    scene = _open_scene(
        qapp,
        kind,
        payload=payload,
        params={"amplitude_mode": "amplitude"},
    )
    try:
        expected = np.asarray([[0.10, 0.30, 0.50], [0.20, 0.40, 0.60]])
        np.testing.assert_array_equal(scene.display_matrix, expected)
        np.testing.assert_array_equal(scene.image_item.image, expected)
        assert scene.display_matrix[0, 0] == pytest.approx(0.10)
        assert scene.display_matrix[0, -1] == pytest.approx(0.50)
        assert scene.display_matrix[-1, 0] == pytest.approx(0.20)
        assert scene.display_matrix[-1, -1] == pytest.approx(0.60)
        # Only time/X uses frame coverage. Frequency/order Y follows the real
        # single-file axis endpoints, not half-cell expansion.
        expected_rect = QRectF(2.0, 1.0, 58.0, 3.0)
        assert scene.heatmap_rect == expected_rect
        assert scene.image_item.mapRectToParent(
            scene.image_item.boundingRect()
        ) == expected_rect
        assert tuple(scene.plots[0].vb.viewRange()[0]) == pytest.approx((2.0, 60.0))
        assert tuple(scene.plots[0].vb.viewRange()[1]) == pytest.approx((1.0, 4.0))
    finally:
        scene.close()


def test_heatmap_dataframe_pivot_has_same_orientation_as_object_payload(qapp):
    payload = _spectro()
    frame = pd.DataFrame(
        {
            "time_s": np.repeat(payload.x, payload.y.size),
            "order": np.tile(payload.y, payload.x.size),
            "amplitude": payload.matrix.reshape(-1),
        }
    )
    scene = _open_scene(
        qapp,
        "order_time",
        payload=frame,
        params={"amplitude_mode": "amplitude"},
    )
    try:
        np.testing.assert_array_equal(
            scene.display_matrix,
            np.asarray([[0.10, 0.30, 0.50], [0.20, 0.40, 0.60]]),
        )
        assert scene.plots[0].getAxis("bottom").labelText == "Time (s)"
        assert scene.plots[0].getAxis("left").labelText == "Order"
    finally:
        scene.close()


@pytest.mark.parametrize(
    ("kind", "params", "expected_levels", "expected_label"),
    [
        (
            "fft_time",
            {
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
                "z_auto": False,
                "z_floor": -42.5,
                "z_ceiling": -3.5,
            },
            (-42.5, -3.5),
            "Amplitude (dB re 1×10⁰)",
        ),
        (
            "order_time",
            {
                "amplitude_mode": "amplitude",
                "z_auto": False,
                "z_floor": 0.15,
                "z_ceiling": 0.55,
            },
            (0.15, 0.55),
            "Amplitude (g)",
        ),
    ],
)
def test_heatmap_manual_levels_and_colorbar_label_are_exact(
    qapp, kind, params, expected_levels, expected_label
):
    scene = _open_scene(qapp, kind, params=params)
    try:
        assert tuple(scene.heatmap_levels) == pytest.approx(expected_levels)
        assert tuple(scene.image_item.getLevels()) == pytest.approx(expected_levels)
        assert tuple(scene.colorbar.levels()) == pytest.approx(expected_levels)
        assert scene.colorbar.getAxis("left").labelText == expected_label
    finally:
        scene.close()


@pytest.mark.parametrize(
    ("kind", "params", "expected"),
    [
        (
            "fft_time",
            {"amplitude_mode": "amplitude", "z_auto": True},
            (0.10, 0.60),
        ),
        (
            "order_time",
            {
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
                "z_auto": True,
            },
            None,
        ),
    ],
)
def test_heatmap_auto_levels_are_exact(qapp, kind, params, expected):
    if expected is None:
        from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

        matrix = SpectrogramAnalyzer.amplitude_to_db(
            _spectro().matrix.T, reference=1.0
        )
        ceiling = float(np.percentile(matrix[np.isfinite(matrix)], 99.0))
        expected = (ceiling - 30.0, ceiling)
    scene = _open_scene(qapp, kind, params=params)
    try:
        assert tuple(scene.heatmap_levels) == pytest.approx(expected)
        assert tuple(scene.image_item.getLevels()) == pytest.approx(expected)
        assert tuple(scene.colorbar.levels()) == pytest.approx(expected)
    finally:
        scene.close()


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_heatmap_db_conversion_calls_spectrogram_analyzer_once(
    qapp, monkeypatch, kind
):
    from mf4_analyzer.batch_render_qt import _builder

    calls = []

    def fake_amplitude_to_db(values, reference=1.0):
        calls.append((np.asarray(values).copy(), float(reference)))
        return np.asarray(values, dtype=float) + 7.0

    monkeypatch.setattr(
        _builder.SpectrogramAnalyzer,
        "amplitude_to_db",
        staticmethod(fake_amplitude_to_db),
    )
    scene = _open_scene(
        qapp,
        kind,
        params={
            "amplitude_mode": "amplitude_db",
            "db_reference_mode": "manual",
            "db_reference": 2.0,
        },
    )
    try:
        assert len(calls) == 1
        np.testing.assert_array_equal(calls[0][0], _spectro().matrix.T)
        assert calls[0][1] == pytest.approx(2.0)
        np.testing.assert_array_equal(scene.display_matrix, _spectro().matrix.T + 7.0)
    finally:
        scene.close()


def test_valid_non_turbo_heatmap_colormap_remains_available(qapp):
    scene = _open_scene(
        qapp,
        "order_time",
        params={"amplitude_mode": "amplitude", "cmap": "viridis"},
    )
    try:
        np.testing.assert_array_equal(
            scene.heatmap_lut, np.load(GOLDEN)["viridis"]
        )
    finally:
        scene.close()


def test_invalid_heatmap_colormap_falls_back_to_turbo_and_warns(qapp):
    warnings_out = []
    scene = _open_scene(
        qapp,
        "order_time",
        params={"amplitude_mode": "amplitude", "cmap": "not-a-real-map"},
        warnings_out=warnings_out,
    )
    try:
        np.testing.assert_array_equal(
            scene.heatmap_lut, np.load(GOLDEN)["turbo"]
        )
        assert warnings_out == [
            "Invalid colormap 'not-a-real-map'; using 'turbo'."
        ]
    finally:
        scene.close()


def test_heatmap_scene_text_has_semantic_labels_without_main_navigation(qapp):
    scene = _open_scene(
        qapp,
        "fft_time",
        params={
            "amplitude_mode": "amplitude_db",
            "db_reference_mode": "manual",
            "db_reference": 1.0,
        },
    )
    try:
        texts = "\n".join(scene.texts())
        assert "Time (s)" in texts
        assert "Frequency (Hz)" in texts
        assert "Amplitude (dB re 1×10⁰)" in texts
        assert "TraceLab batch export" in texts
        assert "T3-heatmap" not in texts
        assert "Task" not in texts
        # 方法名不再印在页眉——三条坐标轴标题已经说清楚这是什么图；页眉第二行
        # 只留通道名。主窗口那整条导航行更不能泄漏进导出图。
        assert "Acceleration" in texts
        assert "FFT vs Time" not in texts
        assert "时域" not in texts
        assert "阶次" not in texts
    finally:
        scene.close()

"""Guideline-hardening Task 7 — GUI↔batch constant convergence (C1/C3-C5/C8/C9/C12/C13)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "mf4_analyzer" / "batch_render_qt" / "_builder.py"
PALETTE = ROOT / "mf4_analyzer" / "batch_render_qt" / "_palette.py"
SHARED = ROOT / "mf4_analyzer" / "qt_analysis_shared.py"


def test_c1_channel_header_label_tracks_font_scale(qapp):
    """C1: the analysis/channel row must use a theme point size that scales."""
    from mf4_analyzer.batch_image_options import BatchRenderOptions
    from mf4_analyzer.batch_render_qt import BatchRenderContext, BatchSeries, BatchTimeFigureSpec
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.batch_render_qt._export import render_scene_image
    import numpy as np

    x = np.linspace(0.0, 1.0, 51)
    payload = (
        "time",
        BatchTimeFigureSpec(
            series=(
                BatchSeries(x=x, y=np.sin(2 * np.pi * x), label="c0", unit="g"),
            )
        ),
    )
    context = BatchRenderContext(
        source_display_name="src.mf4",
        channel='accel["front"]',
        unit="g",
        method="time",
    )
    options = BatchRenderOptions(width_px=960, height_px=640)

    def channel_pt(params):
        scene = build_batch_scene(
            payload, params=params, options=options, context=context,
        )
        try:
            render_scene_image(scene)
            # identity, channel, facts, footer — channel is row 1 when present.
            assert scene.page_labels[1].item.toPlainText() == 'accel["front"]'
            return (
                float(scene.theme.channel_font_pt),
                float(scene.page_labels[1].item.font().pointSizeF()),
            )
        finally:
            scene.close()

    base_theme, base_drawn = channel_pt({})
    scaled_theme, scaled_drawn = channel_pt({"font_scale": 1.5})
    assert base_drawn == pytest.approx(base_theme)
    assert scaled_drawn == pytest.approx(scaled_theme)
    assert scaled_theme == pytest.approx(base_theme * 1.5)
    assert scaled_drawn != pytest.approx(base_drawn)


def test_c3_builder_imports_auto_span_constants_from_shared():
    """C3: builder must not redeclare the absolute-dB auto-window constants."""
    source = BUILDER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "_AUTO_SPAN_DB" not in assigned
    assert "_AUTO_CEILING_PERCENTILE" not in assigned
    assert "_AUTO_CEILING_PCT" not in assigned
    shared = SHARED.read_text(encoding="utf-8")
    assert "_AUTO_SPAN_DB: float = 30.0" in shared
    assert "_AUTO_CEILING_PCT: float = 99.0" in shared
    assert "from mf4_analyzer.qt_analysis_shared import" in source
    assert "_AUTO_SPAN_DB" in source
    assert "_AUTO_CEILING_PCT" in source or "_AUTO_CEILING_PERCENTILE" in source


def test_c4_builder_uses_shared_slice_max_span_not_local_dead_span():
    """C4: dead-span display floor must reuse ``_SLICE_MAX_SPAN_DB``."""
    source = BUILDER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "_DISPLAY_DEAD_SPAN_DB" not in assigned
    assert "_DISPLAY_DEAD_SPAN_DB" not in source
    assert "_SLICE_MAX_SPAN_DB" in source


def test_c5_batch_output_scale_delegates_to_contract_render_in_db():
    """C5: one authority — contract.render_in_db, including amplitude_axis."""
    from mf4_analyzer.batch_compute import batch_output_scale
    from mf4_analyzer.batch_render_qt.contract import render_in_db

    cases = [
        ("fft", {}),
        ("fft_time", {}),
        ("order_time", {}),
        ("fft", {"amplitude_mode": "amplitude"}),
        ("fft", {"amplitude_mode": "amplitude_db"}),
        ("fft", {"amplitude_mode": "Amplitude dB"}),
        ("fft", {"amplitude_axis": "db"}),
        ("fft", {"amp_y": "db"}),
        ("order_time", {"amplitude_mode": "amplitude"}),
    ]
    for kind, params in cases:
        expected = bool(render_in_db(kind, params))
        render_db, scale = batch_output_scale(kind, params)
        assert render_db is expected
        assert scale == ("db" if expected else "linear")


def test_c8_heatmap_interp_defaults_live_in_shared():
    """C8: canvas and batch builder share one interp default + smooth set."""
    from mf4_analyzer import qt_analysis_shared as shared
    from mf4_analyzer.batch_render_qt import _builder
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas

    assert shared.DEFAULT_HEATMAP_INTERP == "bilinear"
    assert shared.HEATMAP_SMOOTH_INTERP_MODES == frozenset(
        {"bilinear", "bicubic", "hanning"}
    )
    assert heatmap_canvas.DEFAULT_HEATMAP_INTERP is shared.DEFAULT_HEATMAP_INTERP
    assert heatmap_canvas.HEATMAP_SMOOTH_INTERP_MODES is shared.HEATMAP_SMOOTH_INTERP_MODES
    builder_source = BUILDER.read_text(encoding="utf-8")
    assert "DEFAULT_HEATMAP_INTERP" in builder_source
    assert "HEATMAP_SMOOTH_INTERP_MODES" in builder_source
    assert '"bilinear", "bicubic", "hanning"' not in builder_source
    assert "params.get(\"interp\", \"bilinear\")" not in builder_source


def test_c9_amplitude_mode_helper_covers_dialects_and_order_defaults_db():
    """C9: shared helper + Order batch default aligns with GUI (dB)."""
    from mf4_analyzer.qt_analysis_shared import (
        amplitude_mode_is_db,
        default_amplitude_mode_for_kind,
    )
    from mf4_analyzer.batch_render_qt.contract import render_in_db
    from mf4_analyzer.batch_compute import batch_output_scale

    assert amplitude_mode_is_db("amplitude_db")
    assert amplitude_mode_is_db("Amplitude dB")
    assert amplitude_mode_is_db("db")
    assert not amplitude_mode_is_db("amplitude")
    assert not amplitude_mode_is_db("Amplitude")
    assert default_amplitude_mode_for_kind("order_time") == "amplitude_db"
    assert default_amplitude_mode_for_kind("fft_time") == "amplitude_db"
    assert default_amplitude_mode_for_kind("fft") == "amplitude"
    assert render_in_db("order_time", {}) is True
    assert batch_output_scale("order_time", {}) == (True, "db")


def test_c12_frf_frequency_scale_normalizes_and_set_xlim_uses_helper(qtbot):
    """C12: strip/lower on ingest; set_xlim must call ``_is_log_frequency``."""
    from types import SimpleNamespace
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    frequencies = np.array([0.0, 1.0, 10.0, 100.0])
    transfer = np.array([1 + 0j, 2 + 0j, 3 + 0j, 4 + 0j])
    coherence = np.ones(4)
    result = SimpleNamespace(
        frequencies=frequencies,
        transfer=transfer,
        coherence=coherence,
        effective=SimpleNamespace(fs=200.0, df=1.0, segments=2, time_start=0.0, time_end=1.0),
        warnings=(),
    )
    canvas.set_result(result, {
        "magnitude_scale": "db",
        "frequency_scale": "  Log  ",
        "phase_mode": "wrapped",
        "coherence_threshold": 0.8,
        "fade_low_coherence": False,
    }, {"input_unit": "N", "output_unit": "m/s"})
    assert canvas.display_params()["frequency_scale"] == "log"
    assert canvas._is_log_frequency() is True
    # Would raise / produce NaN view if the set_xlim log guard still compared
    # the raw string without lowercasing / helper.
    canvas.set_xlim(0.0, 100.0)
    lo, hi = canvas.get_xlim()
    assert lo > 0.0
    assert hi == pytest.approx(100.0)


def test_c13_palette_docstring_admits_slice_colour_fork():
    """C13: docstring must admit the intentional #dc2626 vs #e03131 fork."""
    text = PALETTE.read_text(encoding="utf-8")
    assert "#dc2626" in text
    assert "#e03131" in text
    assert "same hue" not in text.lower()
    assert "fork" in text.lower() or "分叉" in text or "not identical" in text.lower()

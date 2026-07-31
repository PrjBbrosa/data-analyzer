from __future__ import annotations

import inspect
import re
import warnings
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from xml.etree import ElementTree

import matplotlib as mpl
import matplotlib.image as mpimg
import numpy as np
import pandas as pd
import pytest
from PIL import Image

from mf4_analyzer import db_reference
from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer


def _spectro(*, x=None, y=None, matrix=None):
    x_values = np.asarray([2.0] if x is None else x, dtype=float)
    y_values = np.asarray([50.0] if y is None else y, dtype=float)
    values = np.asarray([[1.0]] if matrix is None else matrix, dtype=float)
    return SimpleNamespace(
        x=x_values,
        y=y_values,
        matrix=values,
        x_name="time_s",
        y_name="frequency_hz",
    )


def test_render_options_defaults_are_immutable():
    from mf4_analyzer.batch_render import BatchRenderOptions

    options = BatchRenderOptions()

    assert (options.width_px, options.height_px, options.dpi, options.format) == (
        1920,
        1080,
        144,
        "png",
    )
    with pytest.raises(FrozenInstanceError):
        options.width_px = 1920


def test_default_png_has_exact_pixel_size(tmp_path):
    from mf4_analyzer.batch_render import render_batch_image

    data = pd.DataFrame(
        {"frequency_hz": [0.0, 1.0], "amplitude": [0.0, 1.0]}
    )

    output = render_batch_image(("fft", data), tmp_path / "fft.png")
    pixels = mpimg.imread(output)

    assert output == tmp_path / "fft.png"
    assert output.stat().st_size > 0
    assert pixels.shape[:2] == (1080, 1920)


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (2560, 1440), (3840, 2160), (777, 431)],
)
def test_png_requested_pixel_size_and_dpi_metadata_are_exact(
    tmp_path, width, height
):
    from mf4_analyzer.batch_render import BatchRenderOptions, render_batch_image

    data = pd.DataFrame(
        {"frequency_hz": [0.0, 100.0], "amplitude": [0.0, 1.0]}
    )
    target = tmp_path / f"spectrum-{width}x{height}.png"

    render_batch_image(
        ("fft", data),
        target,
        options=BatchRenderOptions(
            width_px=width,
            height_px=height,
            dpi=144,
            format="PNG",
        ),
    )

    with Image.open(target) as image:
        assert image.size == (width, height)
        assert image.format == "PNG"
        assert image.info["dpi"] == pytest.approx((144.0, 144.0), abs=0.02)


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"format": "jpg"}, "format"),
        ({"width_px": 319}, "width_px"),
        ({"height_px": 16_385}, "height_px"),
        ({"width_px": 10_000, "height_px": 10_000}, "pixels"),
        ({"dpi": 35}, "dpi"),
        ({"dpi": 1_201}, "dpi"),
    ],
)
def test_render_options_reject_unsupported_or_unsafe_geometry(kwargs, error):
    from mf4_analyzer.batch_render import BatchRenderOptions

    with pytest.raises(ValueError, match=error):
        BatchRenderOptions(**kwargs)


@pytest.mark.parametrize("field", ["width_px", "height_px", "dpi"])
def test_render_options_reject_bool_geometry(field):
    from mf4_analyzer.batch_render import BatchRenderOptions

    with pytest.raises(TypeError, match=field):
        BatchRenderOptions(**{field: True})


def test_render_context_is_frozen_and_copies_effective_facts():
    from mf4_analyzer.batch_render import BatchRenderContext

    facts = {"window": "hann", "effective_nfft": 4096}
    context = BatchRenderContext(
        source_display_name="drive.mf4",
        group="Powertrain",
        channel="Accel_Z",
        unit="m/s²",
        method="FFT",
        task_id="task-12345678",
        effective_facts=facts,
    )
    facts["window"] = "rectangular"

    assert context.effective_facts["window"] == "hann"
    with pytest.raises(TypeError):
        context.effective_facts["window"] = "flattop"
    with pytest.raises(FrozenInstanceError):
        context.channel = "Other"


def test_figure_context_writes_title_facts_footer_and_physical_unit():
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0], "amplitude": [1.0, 2.0]}
    )
    context = BatchRenderContext(
        source_display_name="road-run.mf4",
        group="Front axle",
        channel="Wheel acceleration",
        unit="m/s²",
        method="FFT",
        task_id="recipe-0123456789",
        effective_facts={
            "window": "flattop",
            "effective_nfft": 2048,
            "weighting": "A",
            "averaging": "rms",
            "overlap": 0.5,
        },
    )

    figure = _build_batch_figure(
        ("fft", data),
        params={
            "amp_y": "dB",
            "weighting": "A",
            "db_reference": 1.0,
            "db_reference_mode": "manual",
        },
        context=context,
    )
    rendered_text = "\n".join(text.get_text() for text in figure.texts)

    assert "road-run.mf4" in rendered_text
    assert "Front axle" in rendered_text
    assert "Wheel acceleration" in rendered_text
    assert "FFT" in rendered_text
    assert "window=flattop" in rendered_text
    assert "NFFT=2048" in rendered_text
    assert "weighting=A" in rendered_text
    assert "recipe-0123456789" in rendered_text
    assert figure.axes[0].get_xlabel() == "Frequency (Hz)"
    assert figure.axes[0].get_ylabel() == "Amplitude (dBA re 1×10⁰)"


def test_dollar_title_and_unit_are_created_as_literal_text_and_remain_literal_in_svg(
    tmp_path,
):
    """A later draw-only rc_context must not leave artists math-enabled."""
    from mf4_analyzer.batch_render import (
        BatchRenderContext,
        BatchRenderOptions,
        _build_batch_figure,
        render_batch_image,
    )

    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0], "amplitude": [1.0, 2.0]}
    )
    context = BatchRenderContext(
        source_display_name="run-$single$-frame.mf4",
        channel="acceleration-$raw$",
        unit="$m/s^2$",
        method="FFT",
    )
    initial_parse_math = mpl.rcParams["text.parse_math"]
    mpl.rcParams["text.parse_math"] = True
    try:
        figure = _build_batch_figure(("fft", data), context=context)
        dollar_artists = [
            artist
            for artist in figure.findobj(match=mpl.text.Text)
            if "$" in artist.get_text()
        ]
        target = tmp_path / "literal-dollar.svg"
        render_batch_image(
            ("fft", data),
            target,
            options=BatchRenderOptions(format="svg"),
            context=context,
        )
    finally:
        mpl.rcParams["text.parse_math"] = initial_parse_math

    assert dollar_artists
    assert all(not artist.get_parse_math() for artist in dollar_artists)
    root = ElementTree.parse(target).getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    svg_text = "\n".join(
        "".join(node.itertext())
        for node in root.findall(".//svg:text", namespace)
    )
    assert "run-$single$-frame.mf4" in svg_text
    assert "acceleration-$raw$" in svg_text
    assert "Amplitude ($m/s^2$)" in svg_text
    assert mpl.rcParams["text.parse_math"] == initial_parse_math


def test_runner_canonical_effective_nfft_overrides_requested_auto():
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0], "amplitude": [1.0, 2.0]}
    )
    figure = _build_batch_figure(
        ("fft", data),
        params={"nfft": "auto"},
        context=BatchRenderContext(
            channel="Acceleration",
            method="FFT",
            effective_facts={"nfft_effective": 64},
        ),
    )
    rendered_text = "\n".join(text.get_text() for text in figure.texts)

    assert "NFFT=64" in rendered_text
    assert "NFFT=auto" not in rendered_text


def test_numeric_zero_group_identity_is_not_elided():
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    frame = pd.DataFrame(
        {"time_s": [0.0, 1.0], "series": ["raw", "raw"], "value": [0.0, 1.0]}
    )
    figure = _build_batch_figure(
        ("time", frame),
        context=BatchRenderContext(
            source_display_name="run.mf4",
            group=0,
            channel="speed",
            method="Time",
        ),
    )

    assert "run.mf4 · 0" in "\n".join(
        text.get_text() for text in figure.texts
    )


def test_linear_context_uses_unit_and_does_not_show_db_reference():
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0], "amplitude": [1.0, 2.0]}
    )
    figure = _build_batch_figure(
        ("fft", data),
        params={
            "amp_y": "Linear",
            "db_reference": 2.0,
            "db_reference_mode": "manual",
        },
        context=BatchRenderContext(channel="force", unit="N", method="FFT"),
    )
    all_text = "\n".join(
        [*(text.get_text() for text in figure.texts), figure.axes[0].get_ylabel()]
    )

    assert figure.axes[0].get_ylabel() == "Amplitude (N)"
    assert "dB" not in all_text
    assert "reference" not in all_text.lower()


def test_time_context_has_physical_axes_legend_and_method_label():
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    frame = pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 0.0, 1.0],
            "series": ["original", "original", "filtered", "filtered"],
            "value": [0.0, 1.0, 0.1, 0.8],
        }
    )
    figure = _build_batch_figure(
        ("time", frame),
        context=BatchRenderContext(
            source_display_name="run.mf4",
            channel="Velocity",
            unit="m/s",
            method="Time",
        ),
    )
    axis = figure.axes[0]
    figure_text = "\n".join(text.get_text() for text in figure.texts)

    assert axis.get_xlabel() == "Time (s)"
    assert axis.get_ylabel() == "Amplitude (m/s)"
    assert [text.get_text() for text in axis.get_legend().get_texts()] == [
        "original",
        "filtered",
    ]
    assert "run.mf4" in figure_text
    assert "Velocity" in figure_text
    assert "Time" in figure_text


@pytest.mark.parametrize(
    ("kind", "method", "expected_x", "expected_y"),
    [
        ("fft_time", "FFT vs Time", "Time (s)", "Frequency (Hz)"),
        ("order_time", "Order", "Time (s)", "Order"),
    ],
)
def test_heatmap_context_has_semantic_axes_method_and_db_colorbar(
    kind, method, expected_x, expected_y
):
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    payload = _spectro(
        x=[0.0, 1.0],
        y=[1.0, 2.0],
        matrix=[[1.0, 2.0], [2.0, 4.0]],
    )
    if kind == "order_time":
        payload.y_name = "order"
    figure = _build_batch_figure(
        (kind, payload),
        params={
            "amplitude_mode": "amplitude_db",
            "db_reference": 1.0,
            "db_reference_mode": "manual",
        },
        context=BatchRenderContext(
            source_display_name="run.mf4",
            channel="Acceleration",
            unit="m/s²",
            method=method,
            effective_facts={"window": "hann", "effective_nfft": 1024},
        ),
    )
    figure_text = "\n".join(text.get_text() for text in figure.texts)

    assert figure.axes[0].get_xlabel() == expected_x
    assert figure.axes[0].get_ylabel() == expected_y
    assert figure.axes[-1].get_ylabel() == "Amplitude (dB re 1×10⁰)"
    assert method in figure_text
    assert "window=hann" in figure_text
    assert "NFFT=1024" in figure_text


def test_long_context_keeps_nonzero_plot_bounds():
    from mf4_analyzer.batch_render import BatchRenderContext, _build_batch_figure

    long_value = "source-with-a-very-long-name-" * 20
    frame = pd.DataFrame(
        {"time_s": [0.0, 1.0], "series": ["raw", "raw"], "value": [0.0, 1.0]}
    )
    figure = _build_batch_figure(
        ("time", frame),
        context=BatchRenderContext(
            source_display_name=long_value,
            group=long_value,
            channel=long_value,
            unit="m/s",
            method="Time",
            task_id=long_value,
        ),
    )
    bounds = figure.axes[0].get_position()

    assert bounds.width > 0.4
    assert bounds.height > 0.4


def test_svg_is_parseable_vector_output_with_text_and_requested_page_size(tmp_path):
    from mf4_analyzer.batch_render import (
        BatchRenderContext,
        BatchRenderOptions,
        render_batch_image,
    )

    target = tmp_path / "spectrum.svg"
    initial_fonttype = mpl.rcParams["svg.fonttype"]
    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0, 30.0], "amplitude": [1.0, 2.0, 1.5]}
    )

    render_batch_image(
        ("fft", data),
        target,
        options=BatchRenderOptions(
            width_px=1920,
            height_px=1080,
            dpi=144,
            format="svg",
        ),
        context=BatchRenderContext(
            source_display_name="road-run.mf4",
            channel="Accel_Z",
            unit="m/s²",
            method="FFT",
            task_id="task-a1b2c3d4",
        ),
    )

    root = ElementTree.parse(target).getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    text_values = [
        "".join(node.itertext())
        for node in root.findall(".//svg:text", namespace)
    ]
    path_nodes = root.findall(".//svg:path", namespace)
    assert [float(value) for value in root.attrib["viewBox"].split()] == pytest.approx(
        [0.0, 0.0, 960.0, 540.0], rel=0, abs=0.01
    )
    assert any("road-run.mf4" in value for value in text_values)
    assert any("Frequency (Hz)" in value for value in text_values)
    assert path_nodes
    assert not root.findall(".//svg:image", namespace)
    assert "data:image/png" not in target.read_text(encoding="utf-8")
    assert mpl.rcParams["svg.fonttype"] == initial_fonttype


def test_cjk_context_prints_png_and_svg_without_missing_glyph_warnings(tmp_path):
    from mf4_analyzer.batch_render import (
        BatchRenderContext,
        BatchRenderOptions,
        _available_cjk_font_families,
        render_batch_image,
    )

    cjk_families = _available_cjk_font_families()
    if not cjk_families:
        pytest.skip("no installed CJK font covers the renderer contract glyphs")
    initial_family = tuple(mpl.rcParams["font.family"])
    initial_sans = tuple(mpl.rcParams["font.sans-serif"])
    initial_unicode_minus = mpl.rcParams["axes.unicode_minus"]
    initial_svg_fonttype = mpl.rcParams["svg.fonttype"]
    data = pd.DataFrame(
        {"frequency_hz": [-1.0, 0.0, 1.0], "amplitude": [1.0, 2.0, 1.5]}
    )
    context = BatchRenderContext(
        source_display_name="单帧振动.mf4",
        group="前轴",
        channel="加速度",
        unit="米/秒²",
        method="频谱",
        task_id="中文-proof",
    )
    png_target = tmp_path / "中文-proof.png"
    svg_target = tmp_path / "中文-proof.svg"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        render_batch_image(
            ("fft", data),
            png_target,
            params={"x_auto": False, "x_min": -1.0, "x_max": 1.0},
            context=context,
        )
        render_batch_image(
            ("fft", data),
            svg_target,
            params={"x_auto": False, "x_min": -1.0, "x_max": 1.0},
            options=BatchRenderOptions(format="svg"),
            context=context,
        )

    glyph_warnings = [
        str(item.message)
        for item in caught
        if "glyph" in str(item.message).lower()
        or "missing from font" in str(item.message).lower()
    ]
    assert glyph_warnings == []
    with Image.open(png_target) as image:
        assert image.size == (1920, 1080)
        assert np.asarray(image).std() > 0.0
    root = ElementTree.parse(svg_target).getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    svg_text = "\n".join(
        "".join(node.itertext())
        for node in root.findall(".//svg:text", namespace)
    )
    assert "单帧振动.mf4" in svg_text
    assert "加速度" in svg_text
    assert "频谱" in svg_text
    assert tuple(mpl.rcParams["font.family"]) == initial_family
    assert tuple(mpl.rcParams["font.sans-serif"]) == initial_sans
    assert mpl.rcParams["axes.unicode_minus"] == initial_unicode_minus
    assert mpl.rcParams["svg.fonttype"] == initial_svg_fonttype


def test_pdf_is_one_nonempty_vector_page_with_requested_media_box(tmp_path):
    from mf4_analyzer.batch_render import BatchRenderOptions, render_batch_image

    target = tmp_path / "spectrum.pdf"
    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0, 30.0], "amplitude": [1.0, 2.0, 1.5]}
    )

    render_batch_image(
        ("fft", data),
        target,
        options=BatchRenderOptions(
            width_px=1920,
            height_px=1080,
            dpi=144,
            format="pdf",
        ),
    )

    content = target.read_bytes()
    media_box = re.search(
        rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]", content
    )
    assert content.startswith(b"%PDF-")
    assert content.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type\s*/Page\b", content)) == 1
    assert media_box is not None
    assert float(media_box.group(1)) == pytest.approx(960.0, abs=0.01)
    assert float(media_box.group(2)) == pytest.approx(540.0, abs=0.01)
    assert b"/Subtype /Image" not in content


@pytest.mark.parametrize(
    ("amplitude", "expected_top"),
    [
        (np.zeros(4), -200.0),
        (np.ones(4), 0.0),
    ],
)
def test_fft_db_zero_and_constant_inputs_have_finite_reasonable_range(
    amplitude, expected_top
):
    from mf4_analyzer.batch_render import _build_batch_figure

    data = pd.DataFrame(
        {"frequency_hz": np.arange(amplitude.size, dtype=float), "amplitude": amplitude}
    )

    figure = _build_batch_figure(
        ("fft", data),
        params={
            "amp_y": "dB",
            "db_reference": 1.0,
            "db_reference_mode": "manual",
        },
    )
    axis = figure.axes[0]
    plotted = np.asarray(axis.lines[0].get_ydata(), dtype=float)
    low, high = axis.get_ylim()

    assert np.all(np.isfinite(plotted))
    assert np.all(np.isfinite([low, high]))
    assert low > -1000.0
    assert high == pytest.approx(expected_top)
    assert high - low == pytest.approx(30.0)


def test_fft_db_render_delegates_conversion_and_label_formatting(monkeypatch):
    from mf4_analyzer.batch_render import _build_batch_figure

    calls = {"convert": 0, "label": 0}
    original_convert = SpectrogramAnalyzer.amplitude_to_db
    original_label = db_reference.format_amplitude_label

    def convert_spy(amplitude, reference=1.0):
        calls["convert"] += 1
        return original_convert(amplitude, reference=reference)

    def label_spy(resolution, **kwargs):
        calls["label"] += 1
        return original_label(resolution, **kwargs)

    monkeypatch.setattr(SpectrogramAnalyzer, "amplitude_to_db", convert_spy)
    monkeypatch.setattr(db_reference, "format_amplitude_label", label_spy)
    data = pd.DataFrame(
        {"frequency_hz": [10.0, 20.0], "amplitude": [1.0, 2.0]}
    )

    figure = _build_batch_figure(
        ("fft", data),
        params={
            "amp_y": "dB",
            "weighting": "A",
            "db_reference": 1.0,
            "db_reference_mode": "manual",
        },
    )

    assert calls == {"convert": 1, "label": 1}
    assert figure.axes[0].get_ylabel() == "Amplitude (dBA re 1×10⁰)"


@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_single_frame_single_bin_heatmap_has_nonzero_bounds(kind):
    from mf4_analyzer.batch_render import _build_batch_figure

    figure = _build_batch_figure((kind, _spectro()))
    axis = figure.axes[0]
    left, right, bottom, top = axis.images[0].get_extent()

    assert np.all(np.isfinite([left, right, bottom, top]))
    assert right > left
    assert top > bottom
    x_low, x_high = axis.get_xlim()
    y_low, y_high = axis.get_ylim()
    assert x_high > x_low
    assert y_high > y_low


def test_long_dataframe_heatmap_payload_is_supported(tmp_path):
    from mf4_analyzer.batch_render import render_batch_image

    data = pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 0.0, 1.0],
            "frequency_hz": [10.0, 10.0, 20.0, 20.0],
            "amplitude": [0.25, 0.5, 1.0, 2.0],
        }
    )

    output = render_batch_image(("fft_time", data), tmp_path / "heatmap.png")

    assert output.exists()
    assert output.stat().st_size > 0


def test_time_payload_preserves_series_and_manual_ranges():
    from mf4_analyzer.batch_render import _build_batch_figure

    data = pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 0.0, 1.0],
            "series": ["raw", "raw", "filtered", "filtered"],
            "value": [0.0, 1.0, 0.25, 0.75],
        }
    )

    figure = _build_batch_figure(
        ("time", data),
        params={
            "x_auto": False,
            "x_min": 0.2,
            "x_max": 0.8,
            "y_auto": False,
            "y_min": -1.0,
            "y_max": 2.0,
        },
    )
    axis = figure.axes[0]

    assert len(axis.lines) == 2
    assert axis.get_xlim() == pytest.approx((0.2, 0.8))
    assert axis.get_ylim() == pytest.approx((-1.0, 2.0))


def test_renderer_source_is_gui_framework_free():
    import mf4_analyzer.batch_render as renderer

    source = inspect.getsource(renderer)

    for forbidden in ("PyQt", "pyqtgraph", "QApplication", "QWidget", "QPixmap"):
        assert forbidden not in source
    assert "matplotlib.pyplot" not in source

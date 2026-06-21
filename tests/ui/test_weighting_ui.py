import pytest


WEIGHTING_TOOLTIP = "A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL"


def _combo_texts(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def _weighting(ctx):
    return ctx.get_params()["weighting"]


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTContextual"],
            ).FFTContextual(),
            id="fft",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTTimeContextual"],
            ).FFTTimeContextual(),
            id="fft_time",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["OrderContextual"],
            ).OrderContextual(),
            id="order",
        ),
    ],
)
def test_contextual_weighting_defaults_tooltip_and_params(qapp, factory):
    ctx = factory()

    assert _combo_texts(ctx.combo_weighting) == ["None", "A"]
    assert ctx.combo_weighting.currentText() == "None"
    assert ctx.combo_weighting.toolTip() == WEIGHTING_TOOLTIP
    assert ctx.get_params()["weighting"] == "None"
    assert ctx.current_params()["weighting"] == "None"
    assert ctx._collect_preset()["weighting"] == "None"


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTContextual"],
            ).FFTContextual(),
            id="fft",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTTimeContextual"],
            ).FFTTimeContextual(),
            id="fft_time",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["OrderContextual"],
            ).OrderContextual(),
            id="order",
        ),
    ],
)
def test_contextual_weighting_roundtrip_and_legacy_defaults_none(qapp, factory):
    ctx = factory()

    ctx.set_weighting_default("A")
    assert _weighting(ctx) == "A"
    saved = ctx._collect_preset()

    ctx.set_weighting_default("None")
    ctx._apply_preset_values(saved)
    assert _weighting(ctx) == "A"

    ctx.apply_params({"weighting": "None"})
    assert _weighting(ctx) == "None"

    ctx.set_weighting_default("A")
    legacy = {k: v for k, v in saved.items() if k != "weighting"}
    ctx._apply_preset_values(legacy)
    # After the Task-6 fix: a preset dict without 'weighting' key must NOT
    # reset the current weighting (mirrors apply_params guard behaviour).
    # Old behaviour was `d.get('weighting', 'None')` which reset A → None;
    # the guard `if 'weighting' in d:` preserves the current selection.
    assert _weighting(ctx) == "A"

    ctx.set_weighting_default("A")
    ctx.apply_params({})
    assert _weighting(ctx) == "A"


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTContextual"],
            ).FFTContextual(),
            id="fft",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTTimeContextual"],
            ).FFTTimeContextual(),
            id="fft_time",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["OrderContextual"],
            ).OrderContextual(),
            id="order",
        ),
    ],
)
def test_set_weighting_default_is_noop_while_applying_preset(qapp, factory):
    ctx = factory()
    ctx.combo_weighting.setCurrentText("None")

    ctx._applying_preset = True
    try:
        ctx.set_weighting_default("A")
    finally:
        ctx._applying_preset = False

    assert _weighting(ctx) == "None"


@pytest.mark.parametrize(
    "factory,partial",
    [
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTContextual"],
            ).FFTContextual(),
            {"nfft": 4096},
            id="fft",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["FFTTimeContextual"],
            ).FFTTimeContextual(),
            {"z_auto": False, "z_floor": -39.03, "z_ceiling": -9.03},
            id="fft_time",
        ),
        pytest.param(
            lambda: __import__(
                "mf4_analyzer.ui.inspector_sections",
                fromlist=["OrderContextual"],
            ).OrderContextual(),
            {"z_auto": False, "z_floor": -39.03, "z_ceiling": -9.03},
            id="order",
        ),
    ],
)
def test_partial_apply_params_preserves_weighting(qapp, factory, partial):
    ctx = factory()
    ctx.set_weighting_default("A")
    ctx.apply_params(partial)
    assert _weighting(ctx) == "A"


def test_fft_cache_params_include_weighting():
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

    base = {
        "window": "hanning",
        "nfft_effective": 1024,
        "avg_mode": "单帧",
        "avg_overlap": 50,
    }

    none_key = FFTMixin._fft_compute_cache_params(
        dict(base, weighting="None")
    )
    a_key = FFTMixin._fft_compute_cache_params(dict(base, weighting="A"))

    assert none_key["weighting"] == "None"
    assert a_key["weighting"] == "A"
    assert none_key != a_key


def test_analysis_cache_keys_include_weighting_for_view_switch_paths(
    qapp, qtbot, monkeypatch
):
    from types import SimpleNamespace

    import numpy as np
    import pandas as pd

    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    t = np.arange(2048, dtype=float) / 1000.0
    win.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({
            "sig": np.sin(2.0 * np.pi * 50.0 * t),
            "rpm": np.full_like(t, 1200.0),
        }),
        time_array=t,
        fs=1000.0,
        channel_units={"sig": "", "rpm": "rpm"},
    )
    monkeypatch.setattr(win, "_pane_time_range_for", lambda *_args, **_kw: None)

    mode = {"weighting": "None"}

    def fft_params():
        return {
            "window": "hanning",
            "nfft": 1024,
            "nfft_mode": "fixed",
            "t_win_s": 1.5,
            "avg_mode": "单帧",
            "avg_overlap": 50,
            "weighting": mode["weighting"],
        }

    monkeypatch.setattr(win.inspector.fft_ctx, "get_params", fft_params)
    monkeypatch.setattr(win.inspector.fft_ctx, "current_params", fft_params)
    fft_none = win._analysis_cache_key("fft", "f1", "sig", pane_idx=0)
    mode["weighting"] = "A"
    fft_a = win._analysis_cache_key("fft", "f1", "sig", pane_idx=0)
    assert fft_none != fft_a

    def fft_time_params():
        return {
            "signal": ("f1", "sig"),
            "fs": 1000.0,
            "nfft": 512,
            "nfft_mode": "fixed",
            "t_win_s": 1.5,
            "window": "hanning",
            "overlap": 0.5,
            "remove_mean": True,
            "db_reference": 1.0,
            "weighting": mode["weighting"],
        }

    mode["weighting"] = "None"
    monkeypatch.setattr(win.inspector.fft_time_ctx, "get_params", fft_time_params)
    fft_time_none = win._analysis_cache_key("fft_time", "f1", "sig", pane_idx=0)
    mode["weighting"] = "A"
    fft_time_a = win._analysis_cache_key("fft_time", "f1", "sig", pane_idx=0)
    assert fft_time_none != fft_time_a

    def order_params():
        return {
            "nfft": 512,
            "nfft_mode": "fixed",
            "nfft_preview": 512,
            "window": "hanning",
            "max_order": 20.0,
            "order_res": 0.1,
            "time_res": 0.05,
            "rpm_factor": 1.0,
            "fs": 1000.0,
            "weighting": mode["weighting"],
        }

    def order_current_params():
        return dict(order_params(), samples_per_rev=256)

    mode["weighting"] = "None"
    monkeypatch.setattr(win.inspector.order_ctx, "get_params", order_params)
    monkeypatch.setattr(win.inspector.order_ctx, "current_params", order_current_params)
    monkeypatch.setattr(win.inspector.order_ctx, "rpm_factor", lambda: 1.0)
    order_none = win._analysis_cache_key(
        "order", "f1", "sig", rpm_source=("f1", "rpm"), pane_idx=0)
    mode["weighting"] = "A"
    order_a = win._analysis_cache_key(
        "order", "f1", "sig", rpm_source=("f1", "rpm"), pane_idx=0)
    assert order_none != order_a


def test_fft_time_colorbar_drag_preserves_weighting(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    ctx = win.inspector.fft_time_ctx
    ctx.set_weighting_default("A")

    win._on_analysis_levels_dragged("fft_time", 0, -39.03, -9.03)
    params = ctx.get_params()

    assert params["weighting"] == "A"
    assert params["z_auto"] is False
    assert params["z_floor"] == pytest.approx(-39.03)
    assert params["z_ceiling"] == pytest.approx(-9.03)


def test_order_colorbar_drag_preserves_weighting(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    ctx = win.inspector.order_ctx
    ctx.set_weighting_default("A")

    win._on_analysis_levels_dragged("order", 0, -39.03, -9.03)
    params = ctx.current_params()

    assert params["weighting"] == "A"
    assert params["z_auto"] is False
    assert params["z_floor"] == pytest.approx(-39.03)
    assert params["z_ceiling"] == pytest.approx(-9.03)


def test_project_io_dialog_filters_include_audio_video_extensions():
    from mf4_analyzer.ui.main_window._project_io_mixin import (
        AUDIO_VIDEO_FILE_FILTER,
        OPEN_FILES_FILTER,
        PROJECT_OR_DATA_FILTER,
    )

    expected = "*.mp4 *.mov *.mkv *.m4v *.mp3 *.m4a *.aac *.wav *.flac"

    assert expected in PROJECT_OR_DATA_FILTER
    assert expected in OPEN_FILES_FILTER
    assert AUDIO_VIDEO_FILE_FILTER == f"音视频文件 ({expected})"

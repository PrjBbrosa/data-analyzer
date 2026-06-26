from types import SimpleNamespace

import numpy as np

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window import window as window_mod
from mf4_analyzer.ui.plot_risk import PlotRisk, PlotRiskLevel


def _risk(level, *, filter_enabled=False):
    return PlotRisk(
        level=level,
        channel_count=9 if level is PlotRiskLevel.DANGER else 5,
        series_count=9 if level is PlotRiskLevel.DANGER else 5,
        sample_total=6_000_000 if level is PlotRiskLevel.DANGER else 100,
        max_channel_samples=6_000_000 if level is PlotRiskLevel.DANGER else 100,
        filter_enabled=filter_enabled,
        reasons=("测试风险",),
    )


def _checked(count):
    return [("f1", f"ch{i}", "#1f77b4") for i in range(count)]


def _fake_time_data():
    return [
        (
            "ch0",
            True,
            np.array([0.0, 1.0], dtype=float),
            np.array([1.0, 2.0], dtype=float),
            "#1f77b4",
            "V",
            "f1",
        )
    ]


def _make_window(qapp, qtbot, monkeypatch, *, mode, checked):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    qapp.processEvents()

    w.files["f1"] = object()
    monkeypatch.setattr(w.channel_list, "get_checked_channels", lambda: list(checked))
    monkeypatch.setattr(w.chart_stack, "plot_mode_for_canvas", lambda _canvas: mode)
    monkeypatch.setattr(w.canvas_time, "set_tick_density", lambda *_args: None)
    return w


def test_warning_risk_shows_label_without_prompt(qapp, qtbot, monkeypatch):
    checked = _checked(5)
    w = _make_window(qapp, qtbot, monkeypatch, mode="overlay", checked=checked)
    monkeypatch.setattr(
        window_mod,
        "estimate_time_overlay_risk",
        lambda **_kwargs: _risk(PlotRiskLevel.WARNING),
        raising=False,
    )
    monkeypatch.setattr(w, "_build_time_plot_data", lambda *_args, **_kwargs: _fake_time_data())
    monkeypatch.setattr(w.canvas_time, "plot_channels", lambda *_args, **_kwargs: None)

    def fail_question(*_args, **_kwargs):
        raise AssertionError("warning risk must not prompt")

    monkeypatch.setattr(window_mod.QMessageBox, "question", fail_question)

    w._plot_time_on_canvas(w.canvas_time, update_primary_ui=False, user_initiated=True)

    label = w._plot_risk_label
    assert label.isVisible()
    assert label.property("riskLevel") == "warning"


def test_danger_cancel_prompts_and_skips_expensive_plot(qapp, qtbot, monkeypatch):
    checked = _checked(9)
    w = _make_window(qapp, qtbot, monkeypatch, mode="overlay", checked=checked)
    monkeypatch.setattr(
        window_mod,
        "estimate_time_overlay_risk",
        lambda **_kwargs: _risk(PlotRiskLevel.DANGER),
        raising=False,
    )
    calls = {"question": 0, "build": 0, "plot": 0}

    def fake_question(*_args, **_kwargs):
        calls["question"] += 1
        return window_mod.QMessageBox.No

    def fake_build(*_args, **_kwargs):
        calls["build"] += 1
        return _fake_time_data()

    def fake_plot(*_args, **_kwargs):
        calls["plot"] += 1

    monkeypatch.setattr(window_mod.QMessageBox, "question", fake_question)
    monkeypatch.setattr(w, "_build_time_plot_data", fake_build)
    monkeypatch.setattr(w.canvas_time, "plot_channels", fake_plot)

    w._plot_time_on_canvas(w.canvas_time, update_primary_ui=False, user_initiated=True)

    assert calls == {"question": 1, "build": 0, "plot": 0}
    assert w._plot_risk_label.isVisible()
    assert w._plot_risk_label.property("riskLevel") == "danger"


def test_danger_confirm_allows_plotting(qapp, qtbot, monkeypatch):
    checked = _checked(9)
    w = _make_window(qapp, qtbot, monkeypatch, mode="overlay", checked=checked)
    monkeypatch.setattr(
        window_mod,
        "estimate_time_overlay_risk",
        lambda **_kwargs: _risk(PlotRiskLevel.DANGER),
        raising=False,
    )
    calls = {"question": 0, "build": 0, "plot": 0}

    def fake_question(*_args, **_kwargs):
        calls["question"] += 1
        return window_mod.QMessageBox.Yes

    def fake_build(*_args, **_kwargs):
        calls["build"] += 1
        return _fake_time_data()

    def fake_plot(*_args, **_kwargs):
        calls["plot"] += 1

    monkeypatch.setattr(window_mod.QMessageBox, "question", fake_question)
    monkeypatch.setattr(w, "_build_time_plot_data", fake_build)
    monkeypatch.setattr(w.canvas_time, "plot_channels", fake_plot)

    w._plot_time_on_canvas(w.canvas_time, update_primary_ui=False, user_initiated=True)

    assert calls == {"question": 1, "build": 1, "plot": 1}
    assert w._plot_risk_label.isVisible()
    assert w._plot_risk_label.property("riskLevel") == "danger"


def test_low_risk_non_overlay_primary_path_clears_label(qapp, qtbot, monkeypatch):
    checked = _checked(5)
    w = _make_window(qapp, qtbot, monkeypatch, mode="overlay", checked=checked)
    risks = [_risk(PlotRiskLevel.WARNING), _risk(PlotRiskLevel.OK)]
    modes = ["overlay", "subplot"]
    monkeypatch.setattr(
        window_mod,
        "estimate_time_overlay_risk",
        lambda **_kwargs: risks.pop(0),
        raising=False,
    )
    monkeypatch.setattr(
        w.chart_stack,
        "plot_mode_for_canvas",
        lambda _canvas: modes.pop(0),
    )
    monkeypatch.setattr(w, "_build_time_plot_data", lambda *_args, **_kwargs: _fake_time_data())
    monkeypatch.setattr(w.canvas_time, "plot_channels", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        window_mod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: window_mod.QMessageBox.Yes,
    )

    w._plot_time_on_canvas(w.canvas_time, update_primary_ui=False, user_initiated=True)
    assert w._plot_risk_label.isVisible()

    w._plot_time_on_canvas(w.canvas_time, update_primary_ui=False, user_initiated=True)

    assert not w._plot_risk_label.isVisible()
    assert w._plot_risk_label.text() == ""


def test_estimate_overlay_risk_uses_checked_range_and_effective_filter(
    qapp, qtbot, monkeypatch
):
    w = MainWindow()
    qtbot.addWidget(w)
    checked = [("f1", "speed", "#1f77b4"), ("f2", "rpm", "#ff7f0e")]
    w.files["f1"] = object()
    w.files["f2"] = object()
    captured = []

    def fake_estimator(**kwargs):
        captured.append(kwargs)
        return _risk(PlotRiskLevel.OK, filter_enabled=kwargs["filter_enabled"])

    monkeypatch.setattr(
        window_mod,
        "estimate_time_overlay_risk",
        fake_estimator,
        raising=False,
    )
    monkeypatch.setattr(w.inspector.top, "range_enabled", lambda: True)
    monkeypatch.setattr(w.inspector.top, "range_values", lambda: (1.25, 3.5))

    fp = w.inspector.filter_panel
    monkeypatch.setattr(fp, "is_enabled", lambda: True)
    monkeypatch.setattr(fp, "show_original", lambda: True)
    monkeypatch.setattr(fp, "show_filtered", lambda: True)
    monkeypatch.setattr(
        fp,
        "filter_spec",
        lambda: SimpleNamespace(cutoff=0.0, cutoff_lo=0.0, cutoff_hi=0.0),
    )

    w._estimate_current_time_overlay_risk("overlay", checked)

    monkeypatch.setattr(
        fp,
        "filter_spec",
        lambda: SimpleNamespace(cutoff=12.5, cutoff_lo=0.0, cutoff_hi=0.0),
    )
    w._estimate_current_time_overlay_risk("overlay", checked)

    assert captured[0]["checked"] is checked
    assert captured[0]["files"] is w.files
    assert captured[0]["mode"] == "overlay"
    assert captured[0]["time_range"] == (1.25, 3.5)
    assert captured[0]["filter_enabled"] is False
    assert captured[0]["show_original"] is True
    assert captured[0]["show_filtered"] is True
    assert captured[1]["filter_enabled"] is True
    assert captured[1]["show_original"] is True
    assert captured[1]["show_filtered"] is True

"""Record-only TimeDomain Views must plot when Navigator checked is empty."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pyqtgraph as pg
import pytest

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.time_curve_bindings import TimeDataRef
from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parents[2]
_UCAN_SAMPLE = _ROOT / "testdoc" / "WWT" / "U-Can_D6-CSER double_00479.wwt"


def _accept_wwt_layout(mw, monkeypatch):
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *a, **k: True)
    monkeypatch.setattr(
        mw._ultraview, "add_time_views_from_native_layout", lambda *a, **k: (),
    )


def _load_wwt_and_plot(mw, monkeypatch, path, *, plot=True):
    """Load a synthetic WWT. ``plot=True`` keeps the live View-restore path."""
    _accept_wwt_layout(mw, monkeypatch)
    if not plot:
        monkeypatch.setattr(mw, "plot_time", lambda *a, **k: None)
        monkeypatch.setattr(mw, "_apply_active_view", lambda *a, **k: None)
    mw._load_one(str(path))


def _window(qapp, qtbot):
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.resize(1200, 760)
    mw.show()
    qapp.processEvents()
    return mw


def _drawn_series(canvas):
    """Visible PlotDataItems with at least one sample."""
    drawn = []
    lines = getattr(canvas, "_channel_lines", None)
    if not lines:
        return drawn
    items = (
        lines.composite_items()
        if hasattr(lines, "composite_items")
        else ((None, name, pair) for name, pair in dict(lines).items())
    )
    for _ck, name, pair in items:
        line = pair[1] if isinstance(pair, tuple) and len(pair) == 2 else pair
        pdi = getattr(line, "plot_data_item", None)
        if pdi is None:
            continue
        if not pdi.isVisible():
            continue
        x, y = pdi.getData()
        if x is None or y is None or len(x) == 0:
            continue
        drawn.append((str(name), pdi, x, y))
    return drawn


def _names(drawn):
    return [name for name, _pdi, _x, _y in drawn]


def test_record_only_view_plots_when_navigator_is_empty(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = wwt.record_only_gap_curves(tmp_path / "gap.wwt")
    mw = _window(qapp, qtbot)
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append(msg))
    _load_wwt_and_plot(mw, monkeypatch, path)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    kinds = [binding.y_ref.kind for binding in view.curve_bindings]
    assert kinds == ["wwt_record", "wwt_record"]
    assert view.checked == []
    assert mw.channel_list.get_checked_channels() == []

    result = mw._plot_time_on_canvas(
        mw.canvas_time, update_primary_ui=True, user_initiated=True,
    )
    qapp.processEvents()

    assert result is not None
    assert result.rows
    drawn = _drawn_series(mw.canvas_time)
    assert drawn, "record-only View must bind a real PlotDataItem"
    assert all(isinstance(pdi, pg.PlotDataItem) for _n, pdi, _x, _y in drawn)
    names = _names(drawn)
    assert any(wwt.GAP_Y_POS in name for name in names)
    assert any(wwt.GAP_Y_SPEED in name for name in names)
    assert mw.canvas_time._empty_hint_text in ("", None)
    assert "请在左侧勾选至少一个通道" not in toasts
    assert mw.statusBar.currentMessage() != "未选择时间域通道"


def test_unchecking_measurement_keeps_record_only_tolerance(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt")
    mw = _window(qapp, qtbot)
    _load_wwt_and_plot(mw, monkeypatch, path)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    kinds = [binding.y_ref.kind for binding in view.curve_bindings]
    assert kinds == ["channel", "wwt_record"]
    meas = next(
        binding for binding in view.curve_bindings if binding.y_ref.kind == "channel"
    )
    y_key = (meas.y_ref.fid, meas.y_ref.channel)
    assert y_key in {(fid, ch) for fid, ch, _c in mw.channel_list.get_checked_channels()}

    mw._plot_time_on_canvas(mw.canvas_time, update_primary_ui=True)
    qapp.processEvents()
    both = _names(_drawn_series(mw.canvas_time))
    assert any(wwt.MEAS_Y in name for name in both)
    assert any(wwt.TOL_Y in name for name in both)

    persisted = list(view.curve_bindings)
    mw.channel_list.set_checked_channels([])
    assert mw.channel_list.get_checked_channels() == []
    result = mw._plot_time_on_canvas(
        mw.canvas_time, update_primary_ui=True, user_initiated=True,
    )
    qapp.processEvents()

    assert view.curve_bindings == persisted
    assert result is not None
    names = _names(_drawn_series(mw.canvas_time))
    assert any(wwt.TOL_Y in name for name in names)
    assert not any(wwt.MEAS_Y in name for name in names)
    assert y_key not in result.successful_channel_keys


def test_unchecking_channel_backed_binding_does_not_resurrect_it(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")
    mw = _window(qapp, qtbot)
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append(msg))
    _load_wwt_and_plot(mw, monkeypatch, path)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    assert any(binding.y_ref.kind == "channel" for binding in view.curve_bindings)
    assert not any(binding.y_ref.kind == "wwt_record" for binding in view.curve_bindings)

    mw.channel_list.set_checked_channels([])
    result = mw._plot_time_on_canvas(
        mw.canvas_time, update_primary_ui=True, user_initiated=True,
    )
    qapp.processEvents()

    assert result is None
    assert _drawn_series(mw.canvas_time) == []
    assert "请在左侧勾选至少一个通道" in toasts


def test_failed_record_only_binding_keeps_issue_and_does_not_fallback(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt")
    mw = _window(qapp, qtbot)
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append(msg))
    _load_wwt_and_plot(mw, monkeypatch, path, plot=False)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    meas = next(
        binding for binding in view.curve_bindings if binding.y_ref.kind == "channel"
    )
    broken = [
        replace(
            binding,
            x_ref=TimeDataRef(
                kind="wwt_record", fid=binding.y_ref.fid, record_index=999,
            ),
        )
        if binding.y_ref.kind == "wwt_record"
        else binding
        for binding in view.curve_bindings
    ]
    view.curve_bindings = broken
    y_fid, y_channel = meas.y_ref.fid, meas.y_ref.channel
    mw.channel_list.set_checked_channels([])

    result = mw._plot_time_on_canvas(
        mw.canvas_time, update_primary_ui=True, user_initiated=True,
    )
    qapp.processEvents()

    assert result is not None
    assert any(issue.code == "missing_record" for issue in result.issues)
    assert result.rows == []
    assert (y_fid, y_channel) not in result.successful_channel_keys
    fd = mw.files[y_fid]
    prefixed = fd.get_prefixed_channel(y_channel)
    assert all(row[0] != prefixed for row in result.rows)
    assert _drawn_series(mw.canvas_time) == []
    assert "请在左侧勾选至少一个通道" not in toasts


def test_ucan_record_only_views_plot_when_customer_sample_present(
    qapp, qtbot, monkeypatch,
):
    if not _UCAN_SAMPLE.is_file():
        pytest.skip(f"optional customer WWT sample missing: {_UCAN_SAMPLE}")
    mw = _window(qapp, qtbot)
    _load_wwt_and_plot(mw, monkeypatch, _UCAN_SAMPLE)
    qapp.processEvents()

    record_only = [
        idx
        for idx, view in enumerate(mw.view_manager.views)
        if view.checked == []
        and any(binding.y_ref.kind == "wwt_record" for binding in view.curve_bindings)
        and not any(binding.y_ref.kind == "channel" for binding in view.curve_bindings)
    ]
    assert record_only, "U-Can sample should include record-only Views"
    for idx in record_only:
        mw.view_manager.set_active(idx)
        qapp.processEvents()
        assert mw.channel_list.get_checked_channels() == []
        drawn = _drawn_series(mw.canvas_time)
        assert drawn, f"U-Can View index {idx} must plot record-only XY"
        assert all(isinstance(pdi, pg.PlotDataItem) for _n, pdi, _x, _y in drawn)
        assert mw.canvas_time._empty_hint_text in ("", None)

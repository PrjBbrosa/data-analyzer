"""RED contract: WWT native X viewport ``-100..100`` survives full restore.

Do not edit ``tests/ui/test_wwt_native_render.py``. This file uses in-repo
synthetic SFNS-like bytes. Customer ``testdoc/`` samples skip if missing.

Current production writes native ``lo/hi`` into the proposal, then
``_preserved_xlim_fits_data()`` rejects the margin and Home/restore fall
back to the data union (~``-83..83``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parents[2]
_NATIVE = (wwt.SFNS_NATIVE_X_LO, wwt.SFNS_NATIVE_X_HI)
_DATA = (wwt.SFNS_DATA_X_LO, wwt.SFNS_DATA_X_HI)


def _patch_ultraview_dpr(monkeypatch):
    """Dirty UltraView capture is missing ``_device_pixel_ratio`` at MainWindow init."""
    from mf4_analyzer.ui.main_window.ultraview_capture_coordinator import (
        UltraViewCaptureCoordinator,
    )

    monkeypatch.setattr(
        UltraViewCaptureCoordinator,
        "_device_pixel_ratio",
        lambda self: 2.0,
        raising=False,
    )


def _proposals_for(path):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(path)
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    return build_wwt_view_proposals(loaded.document, registered), loaded


def _xlim_tuple(value):
    if value is None:
        return None
    return (float(value[0]), float(value[1]))


def _axis_item_xlim(handle):
    getter = getattr(handle, "x_axis_item", None)
    axis = getter() if callable(getter) else None
    if axis is None:
        return None
    rng = getattr(axis, "range", None)
    if rng is None or len(rng) < 2:
        return None
    return (float(rng[0]), float(rng[1]))


def _handle_xlim(canvas):
    master = getattr(canvas, "_x_master_handle", None)
    handles = []
    if master is not None:
        handles.append(master)
    handles.extend(list(getattr(canvas, "axes_list", []) or ()))
    for handle in handles:
        getter = getattr(handle, "get_xlim", None)
        if not callable(getter):
            continue
        try:
            lo, hi = getter()
        except Exception:
            continue
        return handle, (float(lo), float(hi)), _axis_item_xlim(handle)
    return None, None, None


def test_sfns_like_proposal_xlim_is_native_minus_100_to_100(tmp_path):
    path = wwt.sfns_like_custom_x_native_viewport(tmp_path / "sfns.wwt")
    proposals, loaded = _proposals_for(path)
    assert len(proposals) == 1
    xlim = _xlim_tuple(proposals[0].state.xlim)
    assert xlim == pytest.approx(_NATIVE)
    intent = proposals[0].state.x_viewport_intent
    assert intent is not None
    assert intent.source == "wwt_native"
    assert _xlim_tuple(intent.home_range) == pytest.approx(_NATIVE)
    data_x = loaded.groups[0]["data"][wwt.SFNS_RACK_TRAVEL].to_numpy()
    assert float(np.nanmin(data_x)) == pytest.approx(wwt.SFNS_DATA_X_LO, abs=1.0)
    assert float(np.nanmax(data_x)) == pytest.approx(wwt.SFNS_DATA_X_HI, abs=1.0)


def test_full_restore_keeps_native_xlim_on_viewstate_handle_and_axisitem(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """After production restore, ViewState / handle / AxisItem are all -100..100."""
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow

    _patch_ultraview_dpr(monkeypatch)
    path = wwt.sfns_like_custom_x_native_viewport(tmp_path / "sfns.wwt")
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.resize(1200, 760)
    mw.show()
    qapp.processEvents()
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mw._ultraview, "add_time_views_from_native_layout", lambda *_a, **_k: (),
    )
    mw._load_one(str(path))
    qapp.processEvents()
    mw._apply_active_view(mw.view_manager.active)
    qapp.processEvents()

    state = mw.view_manager.get(mw.view_manager.active)
    state_xlim = _xlim_tuple(state.xlim)
    canvas = mw.canvas_time
    handle, handle_xlim, axis_xlim = _handle_xlim(canvas)

    reached = {
        "viewstate": state_xlim,
        "handle": handle_xlim,
        "axisitem": axis_xlim,
    }
    assert handle is not None, (
        f"could not reach overlay X handle after restore; captured={reached!r}"
    )
    assert state_xlim == pytest.approx(_NATIVE), reached
    assert handle_xlim == pytest.approx(_NATIVE), reached
    if axis_xlim is None:
        pytest.fail(
            "could not reach AxisItem.range after restore; "
            f"ViewState/handle captured={reached!r}"
        )
    assert axis_xlim == pytest.approx(_NATIVE), reached


def test_wwt_home_targets_native_range_not_data_union(
    qapp, qtbot, tmp_path, monkeypatch,
):
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow

    _patch_ultraview_dpr(monkeypatch)
    path = wwt.sfns_like_custom_x_native_viewport(tmp_path / "sfns.wwt")
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.resize(1200, 760)
    mw.show()
    qapp.processEvents()
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mw._ultraview, "add_time_views_from_native_layout", lambda *_a, **_k: (),
    )
    mw._load_one(str(path))
    qapp.processEvents()
    mw._apply_active_view(mw.view_manager.active)
    qapp.processEvents()

    state = mw.view_manager.get(mw.view_manager.active)
    intent = getattr(state, "x_viewport_intent", None)
    if intent is None:
        intent = (state.axis_opts or {}).get("x_viewport_intent")
    assert intent is not None, (
        "WWT View is missing x_viewport_intent; Home has no native target"
    )
    home_range = getattr(intent, "home_range", None)
    if home_range is None and isinstance(intent, dict):
        home_range = intent.get("home_range")
    assert _xlim_tuple(home_range) == pytest.approx(_NATIVE)

    canvas = mw.canvas_time
    canvas.restore_visible_xlim((-20.0, 20.0), flush=True)
    qapp.processEvents()
    home = getattr(canvas, "reset_view_to_data_extents", None)
    assert callable(home)
    home()
    qapp.processEvents()
    _handle, handle_xlim, _axis = _handle_xlim(canvas)
    assert handle_xlim == pytest.approx(_NATIVE), (
        f"WWT Home must return to native {_NATIVE}, not data union {_DATA}; "
        f"got {handle_xlim!r}"
    )


def test_wwt_zoom_survives_view_capture_and_home_returns_native(
    qapp, qtbot, tmp_path, monkeypatch,
):
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow

    _patch_ultraview_dpr(monkeypatch)
    path = wwt.sfns_like_custom_x_native_viewport(tmp_path / "sfns.wwt")
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.show()
    qapp.processEvents()
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mw._ultraview, "add_time_views_from_native_layout", lambda *_a, **_k: (),
    )
    mw._load_one(str(path))
    qapp.processEvents()
    mw._apply_active_view(mw.view_manager.active)
    qapp.processEvents()
    canvas = mw.canvas_time
    canvas.restore_visible_xlim((-20.0, 20.0), flush=True)
    qapp.processEvents()
    state = mw.view_manager.get(mw.view_manager.active)
    mw._view_bridge.capture_canvas_ranges_into(state, canvas)
    mw._apply_active_view(mw.view_manager.active)
    qapp.processEvents()
    _handle, zoomed, _axis = _handle_xlim(canvas)
    assert zoomed == pytest.approx((-20.0, 20.0), abs=0.5)
    canvas.reset_view_to_data_extents()
    qapp.processEvents()
    _handle, home_xlim, _axis = _handle_xlim(canvas)
    assert home_xlim == pytest.approx(_NATIVE)


def test_ordinary_home_uses_data_union_not_wwt_margin(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    qapp.processEvents()
    t = np.linspace(0.0, 1.0, 80, dtype=np.float64)
    canvas.plot_channels(
        [("y", True, t, t, "#1769e0", "", "fid-1")],
        mode="overlay",
    )
    qapp.processEvents()
    canvas.set_x_viewport_intent(None)
    canvas.restore_visible_xlim((0.2, 0.4), flush=True)
    qapp.processEvents()
    canvas.reset_view_to_data_extents()
    qapp.processEvents()
    _handle, xlim, _axis = _handle_xlim(canvas)
    assert xlim is not None
    assert xlim[0] == pytest.approx(0.0, abs=0.05)
    assert xlim[1] == pytest.approx(1.0, abs=0.05)


def test_invalid_and_non_overlapping_native_range_are_dropped():
    from types import SimpleNamespace

    from mf4_analyzer.ui.wwt_view_import import _resolve_native_x_viewport

    record = SimpleNamespace(values=np.asarray([-83.0, 0.0, 83.0]))
    inverted = []
    xlim, intent = _resolve_native_x_viewport(
        SimpleNamespace(lo=100.0, hi=-100.0, record_index=0),
        (record,),
        window_index=0,
        warnings=inverted,
    )
    assert xlim is None and intent is None
    assert any("native_x_range_invalid" in item for item in inverted)

    disjoint = []
    xlim, intent = _resolve_native_x_viewport(
        SimpleNamespace(lo=200.0, hi=300.0, record_index=0),
        (record,),
        window_index=0,
        warnings=disjoint,
    )
    assert xlim is None and intent is None
    assert any("native_x_range_no_overlap" in item for item in disjoint)


def test_optional_customer_sfns_native_viewport_skip_if_missing():
    sample_dir = _ROOT / "testdoc" / "2024_3_17"
    matches = sorted(sample_dir.glob("SFNS_*.wwt")) if sample_dir.is_dir() else []
    if not matches:
        pytest.skip("customer testdoc/2024_3_17/SFNS_*.wwt missing")
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(matches[0])
    proposals = build_wwt_view_proposals(
        loaded.document, register_groups_for_test(loaded.groups, owner_fid="f1"),
    )
    assert proposals, "customer SFNS file should still yield a WinWert proposal"
    xlim = _xlim_tuple(proposals[0].state.xlim)
    if xlim is None:
        pytest.skip("customer sample has no proposal xlim")
    assert xlim[0] < xlim[1]

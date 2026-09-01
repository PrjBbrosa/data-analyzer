"""Regression coverage for the retired WWT viewport-intent contract.

WWT may supply the initial range for a new ordinary ViewState, but it must not
leave an alternate Canvas Home policy behind. Home therefore returns to the
raw plotted data union just like every other TimeDomain View.
"""
from __future__ import annotations

import pytest

from tests._helpers import wwt_factory as wwt


def _patch_ultraview_dpr(monkeypatch):
    """Keep this UI path independent of the unrelated capture probe defect."""
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
    return build_wwt_view_proposals(loaded.document, registered)


def _load_sfns_view(qapp, qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    _patch_ultraview_dpr(monkeypatch)
    path = wwt.sfns_like_custom_x_native_viewport(tmp_path / "sfns.wwt")
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 760)
    window.show()
    qapp.processEvents()
    monkeypatch.setattr(
        window._wwt_import, "_ask_layout", lambda *_args, **_kwargs: True,
    )
    window._load_one(str(path))
    qapp.processEvents()
    window._apply_active_view(window.view_manager.active)
    qapp.processEvents()
    return window, window.view_manager.get(window.view_manager.active)


def test_sfns_like_proposal_keeps_initial_xlim_without_viewport_intent(tmp_path):
    proposals = _proposals_for(
        wwt.sfns_like_custom_x_native_viewport(tmp_path / "sfns.wwt")
    )

    assert len(proposals) == 1
    state = proposals[0].state
    assert state.xlim == pytest.approx((
        wwt.SFNS_NATIVE_X_LO,
        wwt.SFNS_NATIVE_X_HI,
    ))
    assert not hasattr(state, "x_viewport_intent")
    assert "x_viewport_intent" not in state.to_dict()


def test_preserved_xlim_does_not_keep_wwt_margin_outside_data_union():
    from mf4_analyzer.ui.main_window import MainWindow

    class Canvas:
        @staticmethod
        def get_data_x_union():
            return (wwt.SFNS_DATA_X_LO, wwt.SFNS_DATA_X_HI)

    assert not MainWindow._preserved_xlim_fits_data(
        Canvas(), wwt.SFNS_NATIVE_X_LO, wwt.SFNS_NATIVE_X_HI,
    )


def test_wwt_home_uses_ordinary_data_union(qapp, qtbot, tmp_path, monkeypatch):
    window, _state = _load_sfns_view(qapp, qtbot, tmp_path, monkeypatch)
    canvas = window.canvas_time
    expected = canvas.get_data_x_union()
    assert expected == pytest.approx((
        wwt.SFNS_DATA_X_LO,
        wwt.SFNS_DATA_X_HI,
    ))

    canvas.restore_visible_xlim((-20.0, 20.0), flush=True)
    qapp.processEvents()
    canvas.reset_view_to_data_extents()
    qapp.processEvents()

    assert canvas.axes_list[0].get_xlim() == pytest.approx(expected)
    assert not hasattr(canvas, "x_viewport_intent")
    assert not hasattr(canvas, "set_x_viewport_intent")


def test_wwt_density_action_only_saves_ordinary_density(
    qapp, qtbot, tmp_path, monkeypatch,
):
    window, state = _load_sfns_view(qapp, qtbot, tmp_path, monkeypatch)

    window._update_all_tick_density_pair(17, 11)
    qapp.processEvents()

    assert window.canvas_time._tick_density_controller.density == (17, 11)
    assert state.axis_opts["tick_density"] == {"x": 17, "y": 11}
    assert "native_ticks" not in state.axis_opts

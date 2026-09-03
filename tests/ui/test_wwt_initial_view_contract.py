"""First-frame contracts for the simplified WWT TimeDomain import path."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from mf4_analyzer.io.wwt_document import load_wwt_document
from mf4_analyzer.ui.time_curve_bindings import bound_time_plot_rows
from mf4_analyzer.ui.time_xaxis import (
    CHANNEL_MODE,
    PER_SOURCE_NAME,
    CustomXAxisSpec,
)
from mf4_analyzer.ui.view_state import ViewState
from mf4_analyzer.ui.wwt_view_import import (
    build_wwt_view_proposals,
    register_groups_for_test,
)
from tests._helpers import wwt_factory as wwt


def _load_rack_initial_view(qapp, qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    path = wwt.rack_travel_force_initial_view(tmp_path / "rack-initial.wwt")
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


def _ordinary_rack_row(rows):
    return next(row for row in rows if "Rack Force" in str(row[0]))


def test_wwt_first_frame_keeps_imported_ranges_with_generic_density(
    qapp, qtbot, tmp_path, monkeypatch,
):
    window, state = _load_rack_initial_view(qapp, qtbot, tmp_path, monkeypatch)
    canvas = window.canvas_time
    controller = canvas._tick_density_controller
    handle = canvas.axes_list[0]

    assert state.xlim == (wwt.SFNS_NATIVE_X_LO, wwt.SFNS_NATIVE_X_HI)
    assert tuple(state.ylims.values()) == ((
        wwt.RACK_INITIAL_Y_LO, wwt.RACK_INITIAL_Y_HI,
    ),)
    assert handle.get_xlim() == (wwt.SFNS_NATIVE_X_LO, wwt.SFNS_NATIVE_X_HI)
    assert handle.get_ylim() == (
        wwt.RACK_INITIAL_Y_LO, wwt.RACK_INITIAL_Y_HI,
    )
    assert tuple(float(value) for value in handle.y_axis_item().range) == (
        wwt.RACK_INITIAL_Y_LO, wwt.RACK_INITIAL_Y_HI,
    )
    assert controller.density == (20, 15)
    assert not hasattr(controller, "native_tick_policy")


def test_record_only_wwt_first_frame_may_intentionally_clip_data_union(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """A committed WinWert first frame is not a stale carried viewport."""
    from mf4_analyzer.ui.main_window import MainWindow

    path = wwt.record_only_clipped_initial_view(tmp_path / "record-only-clip.wwt")
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        window._wwt_import, "_ask_layout", lambda *_args, **_kwargs: True,
    )

    window._load_one(str(path))
    qapp.processEvents()

    state = window.view_manager.get(window.view_manager.active)
    assert state.checked == []
    assert len(state.curve_bindings) == 2
    assert all(
        binding.y_ref.kind == "wwt_record" for binding in state.curve_bindings
    )
    assert state.xlim == (-2.5, 2.5)
    assert window.canvas_time.get_data_x_union() == (
        0.0042724609375, 4.853515625,
    )
    assert window.canvas_time.get_visible_xlim() == (-2.5, 2.5)
    top = window.inspector.top
    assert top.xaxis_mode() == "channel"
    assert top.choice_xaxis.buttons()[1].text() == "曲线自带"
    assert top._combo_xaxis_ch.currentText() == "文件内绑定 · 2 条曲线"
    assert not top.choice_xaxis.isEnabled()
    assert not top.btn_apply_xaxis.isEnabled()

    window._capture_range_change_into_view(state, window.canvas_time)

    assert top.choice_xaxis.buttons()[1].text() == "曲线自带"
    assert top._combo_xaxis_ch.currentText() == "文件内绑定 · 2 条曲线"
    assert not top.choice_xaxis.isEnabled()


def test_channel_backed_wwt_filter_builds_normal_companion(
    qapp, qtbot, tmp_path, monkeypatch,
):
    window, _state = _load_rack_initial_view(qapp, qtbot, tmp_path, monkeypatch)
    panel = window.inspector.filter_panel
    panel.set_enabled(True)
    panel.set_kind("低通")
    panel.set_cutoff(100.0)
    panel.set_order(4)

    rows = window._build_time_plot_data().rows
    assert len(rows) == 2
    primary = _ordinary_rack_row(rows)
    companion = next(row for row in rows if len(row) > 7 and row[7].get("dash"))
    assert primary[1] is True
    assert companion[1] is True
    assert companion[7]["companion_of"] == primary[0]
    np.testing.assert_array_equal(companion[2], primary[2])


def test_channel_backed_wwt_custom_x_change_is_not_binding_pinned(
    qapp, qtbot, tmp_path, monkeypatch,
):
    window, state = _load_rack_initial_view(qapp, qtbot, tmp_path, monkeypatch)
    original = np.asarray(_ordinary_rack_row(window._build_time_plot_data().rows)[2])
    state.axis_opts = {
        **state.axis_opts,
        "x_axis": CustomXAxisSpec(label="Time").to_axis_opts(),
    }
    window._apply_active_view(window.view_manager.active)
    qapp.processEvents()

    changed = np.asarray(_ordinary_rack_row(window._build_time_plot_data().rows)[2])
    assert not np.array_equal(changed, original)
    np.testing.assert_allclose(changed, window.files[state.checked[0][0]].time_array)


def test_mixed_initial_axis_groups_do_not_overwrite_wwt_custom_x_on_open(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """Programmatic axis-group restore must not masquerade as a user edit."""
    from mf4_analyzer.ui.main_window import MainWindow

    path = wwt.speed_unit_alias_shared_axis(tmp_path / "mixed-axis-custom-x.wwt")
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        window._wwt_import, "_ask_layout", lambda *_args, **_kwargs: True,
    )

    window._load_one(str(path))
    qapp.processEvents()

    state = window.view_manager.get(window.view_manager.active)
    spec = CustomXAxisSpec.from_axis_opts(state.axis_opts.get("x_axis"))
    assert state.axis_opts.get("channel_axis_groups")
    assert spec.mode == CHANNEL_MODE
    assert spec.resolver == PER_SOURCE_NAME
    assert spec.channel == wwt.CHAN_X

    result = window._build_time_plot_data()
    assert result.issues == []
    matched = 0
    for row in result.rows:
        if row[6] not in window.files or row[0] not in {
            window.files[row[6]].get_prefixed_channel(wwt.SPEED_ALIAS_TORQUE),
            window.files[row[6]].get_prefixed_channel(wwt.SPEED_ALIAS_STEER),
        }:
            continue
        matched += 1
        expected_x = window.files[row[6]].data[wwt.CHAN_X].to_numpy(copy=False)
        np.testing.assert_array_equal(row[2], expected_x)
    assert matched == 2


def test_record_only_and_independent_xy_still_render_exact_arrays(tmp_path):
    loaded = load_wwt_document(wwt.record_only_gap_curves(tmp_path / "gap.wwt"))
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    assert len(proposals) == 1
    bindings = proposals[0].state.curve_bindings
    assert bindings and all(binding.y_ref.kind == "wwt_record" for binding in bindings)
    files = {
        "f1": SimpleNamespace(
            data=loaded.groups[0]["data"],
            source_metadata={"wwt_record_store": loaded.document.records},
            time_array=loaded.groups[0]["data"][wwt.TIME_NAME].to_numpy(),
        ),
    }

    result = bound_time_plot_rows(bindings, files)
    assert result.issues == []
    assert len(result.rows) == len(bindings)
    records = {record.index: record for record in loaded.document.records}
    rows_by_name = {str(row[0]): row for row in result.rows}
    for binding in bindings:
        row = rows_by_name[binding.display_name]
        expected_x = np.asarray(records[binding.x_ref.record_index].values)
        expected_y = np.asarray(records[binding.y_ref.record_index].values)
        np.testing.assert_equal(row[2], expected_x)
        np.testing.assert_equal(row[3], expected_y)
        assert row[4] == binding.color
        assert np.isnan(row[3]).any()


def test_legacy_project_native_fields_do_not_reactivate_wwt_policy(
    qapp, qtbot, tmp_path, monkeypatch,
):
    window, state = _load_rack_initial_view(qapp, qtbot, tmp_path, monkeypatch)
    legacy_payload = state.to_dict()
    legacy_payload["axis_opts"] = {
        **legacy_payload["axis_opts"],
        "native_ticks": {
            "x": {"major": 20.0, "grid": 10.0},
            "y": {"legacy-axis": {"lo": -1500.0, "hi": 1500.0}},
        },
    }
    legacy_payload["x_viewport_intent"] = {
        "source": "wwt_native",
        "initial_range": [-100.0, 100.0],
        "home_range": [-100.0, 100.0],
    }
    legacy_state = ViewState.from_dict(legacy_payload)
    assert legacy_state.checked == state.checked
    assert legacy_state.xlim == (wwt.SFNS_NATIVE_X_LO, wwt.SFNS_NATIVE_X_HI)
    window.view_manager.views[window.view_manager.active] = legacy_state

    window._apply_active_view(window.view_manager.active)
    qapp.processEvents()

    assert not hasattr(
        window.canvas_time._tick_density_controller, "native_tick_policy",
    )
    assert window.canvas_time.axes_list[0].get_xlim() == (
        wwt.SFNS_NATIVE_X_LO, wwt.SFNS_NATIVE_X_HI,
    )

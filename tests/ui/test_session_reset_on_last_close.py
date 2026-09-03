"""Empty-workspace session reset when the last logical source is closed (R6)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.time_xaxis import (
    CHANNEL_MODE,
    PER_SOURCE_NAME,
    TIME_MODE,
    CustomXAxisSpec,
)
from mf4_analyzer.ui.view_state import ViewManager, is_reusable_blank_view


ANALYSIS_SECTIONS = ("fft", "fft_time", "frf", "order")


def _csv(path, channels=("sig", "rpm", "in", "out")):
    t = np.linspace(0.0, 1.0, 64)
    df = pd.DataFrame({"time": t})
    for name in channels:
        df[name] = np.sin(2 * np.pi * 3 * t)
    df.to_csv(path, index=False)
    return str(path)


def _load_two(qtbot, tmp_path):
    a = _csv(tmp_path / "a.csv")
    b = _csv(tmp_path / "b.csv")
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(a)
    win._load_one(b)
    fid_a, fid_b = list(win.files)
    return win, fid_a, fid_b


def _set_per_source_xaxis(win, channel="sig", label="Speed"):
    spec = CustomXAxisSpec(
        mode=CHANNEL_MODE,
        resolver=PER_SOURCE_NAME,
        channel=channel,
        source_fid=None,
        label=label,
    )
    win._custom_xaxis.adopt(spec, xlabel=label)
    win.inspector.top.set_xaxis_mode("channel")
    win.inspector.top.set_xaxis_label(label)


def _dirty_session(win):
    """Leave extra Views, Custom-X, time-range, and filter away from defaults."""
    assert win.view_manager.new_view() == 1
    for section in ANALYSIS_SECTIONS:
        assert win.analysis_managers[section].new_view() == 1
    _set_per_source_xaxis(win)
    top = win.inspector.top
    top.chk_range.setChecked(True)
    top.set_range_values(0.1, 0.8)
    panel = win.inspector.filter_panel
    panel.set_enabled(True)
    panel.set_kind("高通")
    panel.set_cutoff(50.0)
    panel.set_order(6)


def _assert_empty_workspace_defaults(win):
    assert win.files == {}
    assert len(win.view_manager.views) == 1
    assert win.view_manager.active == 0
    assert win.view_manager.views[0].name == "View 1"
    assert is_reusable_blank_view(win.view_manager.views[0])
    for section in ANALYSIS_SECTIONS:
        mgr = win.analysis_managers[section]
        assert len(mgr.views) == 1, section
        assert mgr.active == 0
        assert mgr.views[0].name == "View 1"
        assert mgr.views[0].attached_file_ids == []
    assert win.inspector.top.xaxis_mode() == TIME_MODE
    assert win._custom_xaxis.spec == CustomXAxisSpec()
    assert win.inspector.top.xaxis_label() == ""
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == (0.0, 0.0)
    panel = win.inspector.filter_panel
    assert panel.is_enabled() is False
    assert panel.combo_kind.currentText() == "低通"
    assert panel.spin_cut.value() == pytest.approx(100.0)
    assert panel.combo_order.currentText() == "4"


def test_view_manager_reset_to_single_default_replaces_state(qapp):
    manager = ViewManager()
    manager.new_view()
    manager.new_view()
    manager.views[0].checked = [("f0", "sig")]
    manager.set_split(1)

    manager.reset_to_single_default()

    assert len(manager.views) == 1
    assert manager.active == 0
    assert manager.split_with is None
    assert manager.views[0].name == "View 1"
    assert manager.views[0].checked == []
    assert is_reusable_blank_view(manager.views[0])


def test_close_all_resets_session_and_reopen_uses_time_axis(qapp, qtbot, tmp_path):
    win, _fid_a, _fid_b = _load_two(qtbot, tmp_path)
    _dirty_session(win)
    before_options = win.chart_stack.cursor_display_options()

    win.close_all(force=True)
    _assert_empty_workspace_defaults(win)
    assert win.chart_stack.cursor_display_options() == before_options

    win._load_one(_csv(tmp_path / "c.csv"))
    win.plot_time()
    assert win.inspector.top.xaxis_mode() == TIME_MODE
    assert win._custom_xaxis.spec.mode == TIME_MODE
    assert win._custom_xaxis.spec.resolver is None


def test_close_last_file_one_by_one_resets_session(qapp, qtbot, tmp_path):
    win, fid_a, fid_b = _load_two(qtbot, tmp_path)
    _dirty_session(win)

    win._close(fid_a, force=True)
    assert fid_b in win.files
    assert len(win.view_manager.views) == 2
    assert win._custom_xaxis.spec.resolver == PER_SOURCE_NAME
    assert win.inspector.top.xaxis_mode() == CHANNEL_MODE

    win._close(fid_b, force=True)
    _assert_empty_workspace_defaults(win)


def test_close_files_group_resets_when_workspace_empties(
    qapp, qtbot, tmp_path, monkeypatch,
):
    win, fid_a, fid_b = _load_two(qtbot, tmp_path)
    _dirty_session(win)
    monkeypatch.setattr(win, "_confirm_global_file_close", lambda *a, **k: True)

    win._close_files([fid_a, fid_b])
    _assert_empty_workspace_defaults(win)


def test_closing_one_of_two_files_keeps_custom_x_and_extra_views(
    qapp, qtbot, tmp_path,
):
    win, fid_a, fid_b = _load_two(qtbot, tmp_path)
    _dirty_session(win)

    win._close(fid_a, force=True)

    assert list(win.files) == [fid_b]
    assert len(win.view_manager.views) == 2
    for section in ANALYSIS_SECTIONS:
        assert len(win.analysis_managers[section].views) == 2
    assert win._custom_xaxis.spec == CustomXAxisSpec(
        mode=CHANNEL_MODE,
        resolver=PER_SOURCE_NAME,
        channel="sig",
        source_fid=None,
        label="Speed",
    )
    assert win.inspector.top.xaxis_mode() == CHANNEL_MODE
    assert win.inspector.top.range_enabled() is True
    assert win.inspector.filter_panel.is_enabled() is True


def test_close_one_wwt_file_resets_only_its_now_empty_view(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from tests._helpers import wwt_factory as wwt

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(
        win._wwt_import, "_ask_layout", lambda *_args, **_kwargs: True,
    )
    first_path = wwt.rack_travel_force_initial_view(tmp_path / "first.wwt")
    second_path = wwt.rack_travel_force_initial_view(tmp_path / "second.wwt")
    win._load_one(str(first_path))
    win._load_one(str(second_path))
    qapp.processEvents()

    assert len(win.view_manager.views) == 2
    first_fid = next(
        fid for fid, data in win.files.items()
        if str(data.filepath) == str(first_path)
    )
    first_before, second_before = win.view_manager.views
    first_view_id = first_before.view_id
    second_view_id = second_before.view_id
    assert first_before.name.startswith("WinWert")
    assert second_before.name.startswith("WinWert")
    win.view_manager.set_active(0)
    qapp.processEvents()

    win._close(first_fid, force=True)
    qapp.processEvents()

    first_after, second_after = win.view_manager.views
    assert first_after.view_id == first_view_id
    assert first_after.name == "View 1"
    assert is_reusable_blank_view(first_after)
    assert second_after.view_id == second_view_id
    assert second_after.name == second_before.name
    assert second_after.attached_file_ids == second_before.attached_file_ids
    assert win.inspector.top.xaxis_mode() == TIME_MODE
    assert win._custom_xaxis.spec == CustomXAxisSpec()
    assert win.inspector.top.choice_xaxis.buttons()[1].text() == "指定通道"
    assert win.inspector.top.choice_xaxis.isEnabled()
    assert win.inspector.top.btn_apply_xaxis.isEnabled()


def test_merged_imported_axis_group_survives_project_reload(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from tests._helpers import wwt_factory as wwt

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win._wwt_import, "_ask_layout", lambda *_args, **_kwargs: True)
    win._load_one(str(wwt.speed_unit_alias_shared_axis(tmp_path / "axis.wwt")))
    qapp.processEvents()

    state = win.view_manager.get(win.view_manager.active)
    assert len(state.checked) == 2
    win.channel_list.merge_axis_group(state.checked)
    qapp.processEvents()
    expected_axis = next(iter(
        state.axis_opts["channel_axis_groups"].values()
    ))
    project = tmp_path / "axis-groups.tlproj"
    win.save_project(project)

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(project)

    reloaded = restored.view_manager.get(restored.view_manager.active)
    groups = reloaded.axis_opts["channel_axis_groups"]
    assert {channel for _fid, channel in reloaded.checked} == {
        channel for _fid, channel in state.checked
    }
    assert set(groups.values()) == {expected_axis}
    assert {json.loads(key)[1] for key in groups} == {
        channel for _fid, channel in state.checked
    }


@pytest.mark.parametrize("flag", ("_restoring_project", "_opening_project", "_applying_view"))
def test_empty_workspace_reset_skipped_while_restore_guards_hold(
    qapp, qtbot, flag,
):
    win = MainWindow()
    qtbot.addWidget(win)
    win.view_manager.new_view()
    leftover_id = win.view_manager.views[0].view_id
    assert not win.files

    setattr(win, flag, True)
    win._reset_empty_workspace_session()

    assert len(win.view_manager.views) == 2
    assert win.view_manager.views[0].view_id == leftover_id


def test_open_project_does_not_collapse_views_or_custom_x(qapp, qtbot, tmp_path):
    win, _fid_a, _fid_b = _load_two(qtbot, tmp_path)
    assert win.view_manager.new_view() == 1
    _set_per_source_xaxis(win)
    win._capture_current_view()
    project = tmp_path / "session.tlproj"
    win.save_project(project)

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(project)

    assert len(restored.files) == 2
    assert len(restored.view_manager.views) == 2
    assert restored._custom_xaxis.spec == CustomXAxisSpec(
        mode=CHANNEL_MODE,
        resolver=PER_SOURCE_NAME,
        channel="sig",
        source_fid=None,
        label="Speed",
    )
    assert restored.inspector.top.xaxis_mode() == CHANNEL_MODE

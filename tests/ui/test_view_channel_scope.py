from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.plot_risk import PlotRisk, PlotRiskLevel


def _window(qtbot, qapp):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 760)
    window.show()
    qapp.processEvents()
    return window


def _loaded_window(qtbot, qapp, loaded_csv):
    window = _window(qtbot, qapp)
    window.load_file(loaded_csv)
    qapp.processEvents()
    return window


def _fid(window):
    return next(iter(window.files))


def _checked_pairs(window):
    return [
        (fid, channel)
        for fid, channel, _color in window.navigator.get_checked_channels()
    ]


def test_normal_load_auto_attaches_only_current_view(
    qtbot, qapp, loaded_csv
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)

    assert window.view_manager.get(0).attached_file_ids == [fid]
    assert window.navigator.get_attached_file_ids() == [fid]

    window._on_view_new()
    qapp.processEvents()

    assert window.view_manager.get(1).attached_file_ids == []
    assert window.navigator.get_attached_file_ids() == []


def test_auto_attach_off_affects_only_future_loads(qtbot, qapp, loaded_csv):
    from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs

    window = _window(qtbot, qapp)
    window.navigator.set_follow_prefs(FollowPrefs(False, False, False))

    window.load_file(loaded_csv)
    qapp.processEvents()

    assert window.navigator.auto_attach_enabled() is False
    assert window.view_manager.get(0).attached_file_ids == []
    assert window.navigator.get_attached_file_ids() == []


def test_auto_attach_preference_is_reused_by_new_windows(qtbot, qapp):
    from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs

    first = _window(qtbot, qapp)
    first.navigator.set_follow_prefs(FollowPrefs(False, False, False))
    first._on_follow_prefs_changed(first.navigator.follow_prefs())

    second = _window(qtbot, qapp)

    assert second.navigator.auto_attach_enabled() is False


def test_manual_attach_targets_new_focused_view_only(qtbot, qapp, loaded_csv):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window._on_view_new()
    qapp.processEvents()

    added = window._attach_files_to_focused_view([fid, fid, "missing"])

    assert added == (fid,)
    assert window.view_manager.get(0).attached_file_ids == [fid]
    assert window.view_manager.get(1).attached_file_ids == [fid]
    assert window.navigator.get_attached_file_ids() == [fid]


def test_drop_attach_reports_added_and_already_attached(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window._on_view_new()
    messages = []
    monkeypatch.setattr(
        window,
        "toast",
        lambda message, level="info": messages.append((message, level)),
    )

    assert window._attach_files_from_drop([fid]) == (fid,)
    assert "已加入主栏" in messages[-1][0]
    assert window.view_manager.get(1).name in messages[-1][0]

    assert window._attach_files_from_drop([fid]) == ()
    assert "文件已在当前 View 中" in messages[-1][0]


def test_duplicate_view_preserves_attached_files(qtbot, qapp, loaded_csv):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)

    window._on_view_duplicate(0)

    assert window.view_manager.get(1).attached_file_ids == [fid]


def test_attach_targets_secondary_focused_view(qtbot, qapp, loaded_csv):
    from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs

    window = _window(qtbot, qapp)
    window._on_view_new()
    window.view_manager.set_split(0)
    window.navigator.set_follow_prefs(FollowPrefs(False, False, False))
    window.load_file(loaded_csv)
    fid = _fid(window)
    window._on_chart_focus_changed(True)

    window._attach_files_to_focused_view([fid])

    assert window.view_manager.get(window._secondary_view_idx).attached_file_ids == [fid]
    assert window.view_manager.get(window._primary_view_idx).attached_file_ids == []


def test_detach_cancel_preserves_attachment_and_checked_state(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "speed")])
    window._capture_focused_view()
    monkeypatch.setattr(window, "_confirm_detach_files", lambda *_args: False)

    changed = window._detach_files_from_focused_view([fid], "sample")

    assert changed is False
    state = window.view_manager.get(0)
    assert state.attached_file_ids == [fid]
    assert state.checked == [(fid, "speed")]


def test_confirmed_detach_filters_view_state_and_replots_once(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "speed")])
    window.navigator.set_hidden_channels([(fid, "speed")])
    window._overlay_primary = (fid, "speed")
    window._capture_focused_view()
    monkeypatch.setattr(window, "_confirm_detach_files", lambda *_args: True)
    replots = []
    monkeypatch.setattr(
        window,
        "_replot_canvas_for_view",
        lambda *args, **kwargs: replots.append(args),
    )

    changed = window._detach_files_from_focused_view([fid], "sample")

    state = window.view_manager.get(0)
    assert changed is True
    assert state.attached_file_ids == []
    assert state.checked == []
    assert state.hidden_channels == []
    assert state.colors == {}
    assert state.overlay_primary is None
    assert window.navigator.get_attached_file_ids() == []
    assert len(replots) == 1


def test_global_file_close_cleans_every_time_view(qtbot, qapp, loaded_csv):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window._on_view_new()
    window._attach_files_to_focused_view([fid])
    for state in window.view_manager.views:
        state.checked = [(fid, "speed")]
        state.hidden_channels = [(fid, "speed")]
        state.colors = {(fid, "speed"): "#123456"}
        state.overlay_primary = (fid, "speed")

    window._close(fid, force=True)

    assert fid not in window.files
    for state in window.view_manager.views:
        assert state.attached_file_ids == []
        assert state.checked == []
        assert state.hidden_channels == []
        assert state.colors == {}
        assert state.overlay_primary is None


def test_channel_editor_removal_cleans_deleted_channel_from_every_view(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "speed"), (fid, "torque")])
    window.navigator.set_hidden_channels([(fid, "torque")])
    window.navigator.set_channel_colors({(fid, "torque"): "#123456"})
    window._overlay_primary = (fid, "torque")
    window._capture_focused_view()

    window._on_view_new()
    window._attach_files_to_focused_view([fid])
    window.navigator.set_checked_channels([(fid, "speed"), (fid, "torque")])
    window.navigator.set_hidden_channels([(fid, "torque")])
    window.navigator.set_channel_colors({(fid, "torque"): "#123456"})
    window._overlay_primary = (fid, "torque")
    window._capture_focused_view()

    primary = window.view_manager.get(0)
    primary.axis_opts = {
        "x_axis": {
            "mode": "channel",
            "resolver": "exact_source",
            "fid": fid,
            "channel": "torque",
        }
    }

    # Stage 1 indexes Time/Analysis uses and asks before a global channel
    # delete; headless tests must accept that confirm or the modal hangs.
    monkeypatch.setattr(window, "_confirm_global_channel_delete", lambda _uses: True)
    window._apply_channel_edits(fid, {}, {"torque"})
    qapp.processEvents()

    for state in window.view_manager.views:
        assert (fid, "torque") not in state.checked
        assert (fid, "torque") not in state.hidden_channels
        assert (fid, "torque") not in state.colors
        assert state.overlay_primary is None
    assert primary.axis_opts["x_axis"] == {
        "mode": "time",
        "resolver": None,
        "fid": None,
        "channel": None,
        "label": "",
    }


def test_file_removal_preserves_per_source_name_axis_spec():
    from mf4_analyzer.ui.view_state import ViewState

    state = ViewState(
        name="Logical",
        tab_color="#2d7ff9",
        attached_file_ids=["f1", "f2"],
        checked=[("f1", "speed"), ("f2", "speed")],
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "angle",
                "label": "Angle",
            }
        },
    )

    MainWindow._filter_time_view_state_for_removed_fids(state, {"f1"})

    assert state.attached_file_ids == ["f2"]
    assert state.checked == [("f2", "speed")]
    assert state.axis_opts["x_axis"] == {
        "mode": "channel",
        "resolver": "per_source_name",
        "fid": None,
        "channel": "angle",
        "label": "Angle",
    }


def test_channel_removal_preserves_per_source_name_axis_spec():
    from mf4_analyzer.ui.view_state import ViewState

    state = ViewState(
        name="Logical",
        tab_color="#2d7ff9",
        checked=[("f1", "speed"), ("f2", "speed")],
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "angle",
                "label": "Angle",
            }
        },
    )

    MainWindow._filter_time_view_state_for_removed_channels(
        state, {("f1", "angle")}
    )

    assert state.axis_opts["x_axis"] == {
        "mode": "channel",
        "resolver": "per_source_name",
        "fid": None,
        "channel": "angle",
        "label": "Angle",
    }


def test_wwt_view_color_seed_does_not_pollute_other_views(
    qtbot, qapp, loaded_csv, tmp_path, monkeypatch,
):
    """Seeding WinWert RGB onto the imported View does not rewrite other views.

    ``apply_controls_from_state`` overlays ``ViewState.colors`` onto the shared
    navigator; that is the existing per-view mechanism, not a global swatch
    rewrite. CSV-only channels and the other View's stored colors stay put.
    """
    from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs
    from tests._helpers import wwt_factory as wwt

    window = _loaded_window(qtbot, qapp, loaded_csv)
    csv_fid = _fid(window)
    csv_speed = "#aa1122"
    csv_torque = "#22aa33"
    window.navigator.set_checked_channels([(csv_fid, "speed"), (csv_fid, "torque")])
    window.navigator.set_channel_colors({
        (csv_fid, "speed"): csv_speed,
        (csv_fid, "torque"): csv_torque,
    })
    window._capture_focused_view()
    other = window.view_manager.get(0)
    other_colors = dict(other.colors)
    assert other_colors[(csv_fid, "speed")] == csv_speed
    assert other_colors[(csv_fid, "torque")] == csv_torque

    window.navigator.set_follow_prefs(FollowPrefs(False, False, False))
    monkeypatch.setattr(window._wwt_import, "_ask_layout", lambda *_a, **_k: True)
    monkeypatch.setattr(
        window._ultraview, "add_time_views_from_native_layout", lambda items: ()
    )
    monkeypatch.setattr(window, "plot_time", lambda *_a, **_k: None)
    monkeypatch.setattr(window, "_apply_active_view", lambda *_a, **_k: None)
    monkeypatch.setattr(window, "_plot_time_on_canvas", lambda *_a, **_k: None)

    window._load_one(str(wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")))
    qapp.processEvents()

    wwt_idx, wwt_state = next(
        (idx, state)
        for idx, state in enumerate(window.view_manager.views)
        if state.curve_bindings
    )
    assert wwt_idx != 0
    y_key = next(
        (binding.y_ref.fid, binding.y_ref.channel)
        for binding in wwt_state.curve_bindings
        if binding.y_ref.kind == "channel"
    )
    winwert = wwt.palette_hex(wwt.CHAN_Y_COLOR)
    assert wwt_state.colors == {y_key: winwert}
    assert dict(window.view_manager.get(0).colors) == other_colors

    window._project_view_controls(wwt_idx)
    qapp.processEvents()

    assert dict(window.view_manager.get(0).colors) == other_colors
    nav = window.navigator.get_channel_colors()
    assert nav.get((csv_fid, "torque")) == csv_torque
    assert nav.get((csv_fid, "speed")) == csv_speed
    assert nav.get(y_key) == winwert

    window._project_view_controls(0)
    qapp.processEvents()

    assert dict(window.view_manager.get(0).colors) == other_colors
    assert dict(wwt_state.colors) == {y_key: winwert}
    nav = window.navigator.get_channel_colors()
    assert nav.get((csv_fid, "torque")) == csv_torque
    assert nav.get((csv_fid, "speed")) == csv_speed


def test_legacy_exact_source_axis_is_cleared_when_its_channel_is_removed():
    from mf4_analyzer.ui.view_state import ViewState

    state = ViewState(
        name="Legacy",
        tab_color="#2d7ff9",
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "fid": "f1",
                "channel": "angle",
                "label": "Angle",
            }
        },
    )

    MainWindow._filter_time_view_state_for_removed_channels(
        state, {("f1", "angle")}
    )

    assert state.axis_opts["x_axis"] == {
        "mode": "time",
        "resolver": None,
        "fid": None,
        "channel": None,
        "label": "Angle",
    }


def test_file_and_channel_removal_filters_curve_bindings():
    from mf4_analyzer.ui.time_curve_bindings import TimeCurveBinding, TimeDataRef
    from mf4_analyzer.ui.view_state import ViewState

    record_binding = TimeCurveBinding(
        binding_id="r",
        y_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=18),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=17),
        display_name="aux",
        unit="",
        color="#000000",
        axis_id="a",
        y_range=(0.0, 1.0),
        y_tick_interval=None,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )
    channel_binding = TimeCurveBinding(
        binding_id="c",
        y_ref=TimeDataRef(kind="channel", fid="f2", channel="speed"),
        x_ref=TimeDataRef(kind="channel", fid="f2", channel="Time"),
        display_name="speed",
        unit="",
        color="#000000",
        axis_id="b",
        y_range=(0.0, 1.0),
        y_tick_interval=None,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )
    state = ViewState(
        name="Native",
        tab_color="#2d7ff9",
        attached_file_ids=["f1", "f2"],
        curve_bindings=[record_binding, channel_binding],
    )
    MainWindow._filter_time_view_state_for_removed_channels(
        state, {("f2", "speed")}
    )
    assert state.curve_bindings == [record_binding]
    MainWindow._filter_time_view_state_for_removed_fids(state, {"f1"})
    assert state.curve_bindings == []


def test_config_combo_selection_does_not_change_checked_or_replot(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "speed")])
    config = window.channel_config_store.create("动力", ["torque"])
    window._reload_channel_config_bar()
    before = _checked_pairs(window)
    replots = []
    monkeypatch.setattr(
        window,
        "_replot_canvas_for_view",
        lambda *args, **kwargs: replots.append(args),
    )

    window.navigator.channel_list.config_bar.select_config(config.config_id)

    assert _checked_pairs(window) == before
    assert replots == []


def test_save_creates_multiple_named_configs_without_applying(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "speed")])
    names = iter((("动力", True), ("振动", True)))
    monkeypatch.setattr(
        window,
        "_prompt_channel_config_name",
        lambda *_args: next(names),
    )

    assert window._save_current_channel_config() is True
    assert window._save_current_channel_config() is True

    configs = window.channel_config_store.list()
    assert [config.name for config in configs] == ["动力", "振动"]
    assert all(config.channel_names == ("speed",) for config in configs)
    assert _checked_pairs(window) == [(fid, "speed")]


def test_save_current_config_captures_display_only_channel_unit_hint(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.files[fid].channel_units["speed"] = "km/h"
    window.navigator.set_checked_channels([(fid, "speed")])
    monkeypatch.setattr(window, "_prompt_channel_config_name", lambda *_args: ("速度", True))

    assert window._save_current_channel_config() is True
    assert window.channel_config_store.list()[0].unit_hint("speed") == "km/h"


def test_save_existing_name_requires_confirmation_before_overwrite(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    existing = window.channel_config_store.create("动力", ["torque"])
    window.navigator.set_checked_channels([(fid, "speed")])
    monkeypatch.setattr(
        window,
        "_prompt_channel_config_name",
        lambda *_args: (" 动力 ", True),
    )
    monkeypatch.setattr(
        window, "_confirm_channel_config_overwrite", lambda *_args: False
    )

    assert window._save_current_channel_config() is False
    assert window.channel_config_store.get(existing.config_id).channel_names == (
        "torque",
    )

    monkeypatch.setattr(
        window, "_confirm_channel_config_overwrite", lambda *_args: True
    )
    assert window._save_current_channel_config() is True
    assert window.channel_config_store.get(existing.config_id).channel_names == (
        "speed",
    )


def test_apply_config_completely_replaces_focused_selection(
    qtbot, qapp, loaded_csv
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    window.load_file(loaded_csv)
    f0, f1 = list(window.files)
    window.navigator.set_checked_channels([(f0, "torque")])
    config = window.channel_config_store.create("转速", ["speed"])
    window._reload_channel_config_bar(config.config_id)

    assert window._apply_selected_channel_config(config.config_id) is True

    assert _checked_pairs(window) == [(f0, "speed"), (f1, "speed")]
    assert window.view_manager.get(0).checked == [
        (f0, "speed"),
        (f1, "speed"),
    ]


def test_apply_preserves_only_hidden_channels_that_remain_selected(
    qtbot, qapp, loaded_csv
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    window.load_file(loaded_csv)
    f0, f1 = list(window.files)
    window.navigator.set_checked_channels([(f0, "speed"), (f0, "torque")])
    window.navigator.set_hidden_channels([(f0, "speed"), (f0, "torque")])
    window._capture_focused_view()
    config = window.channel_config_store.create("转速", ["speed"])

    window._apply_selected_channel_config(config.config_id)

    assert window.view_manager.get(0).hidden_channels == [(f0, "speed")]
    assert window.navigator.get_hidden_channels() == [(f0, "speed")]
    assert (f1, "speed") not in window.navigator.get_hidden_channels()


def test_zero_match_preserves_state_and_emits_nothing(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "speed")])
    window.navigator.set_hidden_channels([(fid, "speed")])
    window._overlay_primary = (fid, "speed")
    window._capture_focused_view()
    config = window.channel_config_store.create("缺失", ["NotThere"])
    before = window.view_manager.get(0).to_dict()
    replots = []
    monkeypatch.setattr(
        window,
        "_replot_canvas_for_view",
        lambda *args, **kwargs: replots.append(args),
    )

    with qtbot.assertNotEmitted(window.navigator.channels_changed):
        assert window._apply_selected_channel_config(config.config_id) is False

    assert window.view_manager.get(0).to_dict() == before
    assert replots == []


def test_apply_emits_one_change_and_replots_once(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    config = window.channel_config_store.create("转速", ["speed"])
    replots = []
    monkeypatch.setattr(
        window,
        "_replot_canvas_for_view",
        lambda *args, **kwargs: replots.append(args),
    )

    with qtbot.waitSignal(window.navigator.channels_changed, timeout=200):
        assert window._apply_selected_channel_config(config.config_id) is True

    assert len(replots) == 1


def test_apply_risk_cancel_preserves_state_and_emits_nothing(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    window.navigator.set_checked_channels([(fid, "torque")])
    window._capture_focused_view()
    before = window.view_manager.get(0).to_dict()
    config = window.channel_config_store.create("转速", ["speed"])
    danger = PlotRisk(
        level=PlotRiskLevel.DANGER,
        channel_count=9,
        series_count=9,
        sample_total=9_000_000,
        max_channel_samples=1_000_000,
        filter_enabled=False,
        reasons=("too large",),
    )
    monkeypatch.setattr(
        window, "_estimate_current_time_overlay_risk", lambda *_args: danger
    )
    monkeypatch.setattr(window, "_confirm_overlay_risk", lambda *_args: False)

    with qtbot.assertNotEmitted(window.navigator.channels_changed):
        assert window._apply_selected_channel_config(config.config_id) is False

    assert window.view_manager.get(0).to_dict() == before


def test_manager_drafts_do_not_mutate_store_until_one_save(
    qtbot, qapp, monkeypatch
):
    from mf4_analyzer.ui.widgets.channel_config_manager import ChannelConfigManagerDialog

    window = _window(qtbot, qapp)
    config = window.channel_config_store.create("动力", ["speed"])
    window._reload_channel_config_bar(config.config_id)
    dialog = ChannelConfigManagerDialog(
        window.channel_config_store.list(), selected_id=config.config_id, parent=window
    )
    # The dialog is owned by ``window``. Registering both with qtbot makes
    # teardown delete the child twice after the parent closes.

    assert dialog._rename_active_to("动力分析") is True
    dialog._remove_channels(("speed",))

    assert window.channel_config_store.get(config.config_id).name == "动力"
    assert window.channel_config_store.get(config.config_id).channel_names == ("speed",)

    replots = []
    monkeypatch.setattr(window, "_replot_canvas_for_view", lambda *args: replots.append(args))
    assert window._save_channel_config_drafts(dialog, dialog.drafts) is False
    assert replots == []

    dialog._run_undo()
    assert window._save_channel_config_drafts(dialog, dialog.drafts) is True
    assert window.channel_config_store.get(config.config_id).name == "动力分析"
    assert replots == []


def test_eye_writes_only_target_view_hidden_curve_binding_ids(
    qtbot, qapp, tmp_path, monkeypatch,
):
    from dataclasses import replace

    from tests._helpers import wwt_factory as wwt
    from tests._helpers.wwt_record_tree import record_binding_count

    window = _window(qtbot, qapp)
    monkeypatch.setattr(window._wwt_import, "_ask_layout", lambda *_a, **_k: True)
    monkeypatch.setattr(window, "plot_time", lambda *_a, **_k: None)
    monkeypatch.setattr(window, "_apply_active_view", lambda *_a, **_k: None)
    window._load_one(
        str(wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt"))
    )
    qapp.processEvents()
    src = window.view_manager.get(window.view_manager.active)
    record = next(
        binding for binding in src.curve_bindings
        if binding.y_ref.kind == "wwt_record"
    )
    copied = window.view_manager.duplicate(window.view_manager.active)
    other = window.view_manager.get(copied)
    other.curve_bindings = [
        replace(binding, binding_id=f"{binding.binding_id}-v2")
        if binding.y_ref.kind == "wwt_record" else binding
        for binding in other.curve_bindings
    ]
    other.hidden_curve_binding_ids = []
    checked_before = list(src.checked)
    bindings_before = list(src.curve_bindings)
    window.view_manager.set_active(0)
    sync = getattr(window, "_sync_record_curve_tree", None)
    assert callable(sync)
    sync(src)
    qapp.processEvents()
    assert record_binding_count(window.navigator) == 1
    window._on_record_curve_visibility_toggled(src.view_id, record.binding_id, False)
    qapp.processEvents()
    assert record.binding_id in src.hidden_curve_binding_ids
    assert other.hidden_curve_binding_ids == []
    assert src.checked == checked_before
    assert src.curve_bindings == bindings_before
    window._on_record_curve_visibility_toggled(other.view_id, record.binding_id, False)
    qapp.processEvents()
    assert other.hidden_curve_binding_ids == []

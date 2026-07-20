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
    window = _window(qtbot, qapp)
    window.navigator.btn_auto_attach.click()

    window.load_file(loaded_csv)
    qapp.processEvents()

    assert window.navigator.auto_attach_enabled() is False
    assert window.view_manager.get(0).attached_file_ids == []
    assert window.navigator.get_attached_file_ids() == []


def test_auto_attach_preference_is_reused_by_new_windows(qtbot, qapp):
    first = _window(qtbot, qapp)
    first.navigator.btn_auto_attach.click()

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


def test_duplicate_view_preserves_attached_files(qtbot, qapp, loaded_csv):
    window = _loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)

    window._on_view_duplicate(0)

    assert window.view_manager.get(1).attached_file_ids == [fid]


def test_attach_targets_secondary_focused_view(qtbot, qapp, loaded_csv):
    window = _window(qtbot, qapp)
    window._on_view_new()
    window.view_manager.set_split(0)
    window.navigator.btn_auto_attach.click()
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

    window._close(fid)

    assert fid not in window.files
    for state in window.view_manager.views:
        assert state.attached_file_ids == []
        assert state.checked == []
        assert state.hidden_channels == []
        assert state.colors == {}
        assert state.overlay_primary is None


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


def test_manage_rename_and_delete_keep_stable_id_and_clear_selection(
    qtbot, qapp, monkeypatch
):
    window = _window(qtbot, qapp)
    config = window.channel_config_store.create("动力", ["speed"])
    window._reload_channel_config_bar(config.config_id)
    monkeypatch.setattr(
        window, "_prompt_channel_config_manage_action", lambda *_args: "rename"
    )
    monkeypatch.setattr(
        window,
        "_prompt_channel_config_rename",
        lambda *_args: ("动力分析", True),
    )

    assert window._manage_channel_config(config.config_id) is True
    renamed = window.channel_config_store.get(config.config_id)
    assert renamed.name == "动力分析"

    monkeypatch.setattr(
        window, "_prompt_channel_config_manage_action", lambda *_args: "delete"
    )
    monkeypatch.setattr(
        window, "_confirm_channel_config_delete", lambda *_args: True
    )
    assert window._manage_channel_config(config.config_id) is True
    assert window.channel_config_store.get(config.config_id) is None
    bar = window.navigator.channel_list.config_bar
    assert bar.selected_config_id() is None
    assert not bar.btn_apply.isEnabled()

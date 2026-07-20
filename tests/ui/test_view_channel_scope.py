from mf4_analyzer.ui.main_window import MainWindow


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

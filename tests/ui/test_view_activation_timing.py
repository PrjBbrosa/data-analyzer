"""Frozen-Windows View creation must leave the pointer event before rendering."""

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window import view_activation
from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs


def _window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_frozen_windows_time_view_activation_is_queued(qapp, qtbot, monkeypatch):
    window = _window(qtbot)
    monkeypatch.setattr(
        view_activation,
        "defer_new_view_activation_after_pointer_release",
        lambda: True,
    )
    active_events = []
    window.view_manager.active_changed.connect(active_events.append)

    window._on_view_new()

    assert len(window.view_manager.views) == 2
    assert window.view_manager.active == 0
    assert active_events == []

    qapp.processEvents()

    assert window.view_manager.active == 1
    assert active_events == [1]


def test_deferred_time_view_inherits_files_only_after_it_becomes_active(
    qapp, qtbot, monkeypatch, loaded_csv,
):
    window = _window(qtbot)
    window._load_one(loaded_csv)
    qapp.processEvents()
    fid = next(iter(window.files))
    window.navigator.set_follow_prefs(FollowPrefs(True, True, False))
    monkeypatch.setattr(
        view_activation,
        "defer_new_view_activation_after_pointer_release",
        lambda: True,
    )

    window._on_view_new()

    assert window.view_manager.active == 0
    assert window.view_manager.get(1).attached_file_ids == []

    qapp.processEvents()

    assert window.view_manager.active == 1
    assert window.view_manager.get(0).attached_file_ids == [fid]
    assert window.view_manager.get(1).attached_file_ids == [fid]


def test_frozen_windows_analysis_view_activation_is_queued(qapp, qtbot, monkeypatch):
    window = _window(qtbot)
    monkeypatch.setattr(
        view_activation,
        "defer_new_view_activation_after_pointer_release",
        lambda: True,
    )
    manager = window.analysis_managers["fft"]
    active_events = []
    manager.active_changed.connect(active_events.append)

    window._on_analysis_new("fft")

    assert len(manager.views) == 2
    assert manager.active == 0
    assert active_events == []

    qapp.processEvents()

    assert manager.active == 1
    assert active_events == [1]


def test_deferred_analysis_view_inherits_files_only_after_it_becomes_active(
    qapp, qtbot, monkeypatch, loaded_csv,
):
    window = _window(qtbot)
    window._load_one(loaded_csv)
    qapp.processEvents()
    fid = next(iter(window.files))
    window.navigator.set_follow_prefs(FollowPrefs(True, True, False))
    monkeypatch.setattr(
        view_activation,
        "defer_new_view_activation_after_pointer_release",
        lambda: True,
    )
    manager = window.analysis_managers["fft"]

    window._on_analysis_new("fft")

    assert manager.active == 0
    assert manager.get(1).attached_file_ids == []

    qapp.processEvents()

    assert manager.active == 1
    assert manager.get(1).attached_file_ids == [fid]


def test_activation_deferral_requires_frozen_windows(monkeypatch):
    monkeypatch.setattr(view_activation.sys, "platform", "win32")
    monkeypatch.setattr(view_activation.sys, "frozen", True, raising=False)
    assert view_activation.defer_new_view_activation_after_pointer_release()

    monkeypatch.setattr(view_activation.sys, "frozen", False)
    assert not view_activation.defer_new_view_activation_after_pointer_release()

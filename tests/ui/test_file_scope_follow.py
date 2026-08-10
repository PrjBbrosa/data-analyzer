"""Pure prefs + decision helpers + Stage 1.1 follow wiring (items 1–3)."""
from __future__ import annotations

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window.file_scope_follow import (
    ATTACH_ON_LOAD_KEY,
    FILL_ON_MODE_ENTRY_KEY,
    INHERIT_ON_NEW_VIEW_KEY,
    FollowPrefs,
    load_follow_prefs,
    resolve_mode_entry_fill,
    resolve_new_view_template,
    save_follow_prefs,
)


class _FakeSettings:
    def __init__(self, initial=None):
        self._data = dict(initial or {})
        self.synced = 0

    def value(self, key, default=None):
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value

    def sync(self):
        self.synced += 1


def test_follow_prefs_counts():
    empty = FollowPrefs(False, False, False)
    assert empty.any_enabled() is False
    assert empty.enabled_count() == 0
    mixed = FollowPrefs(True, False, True)
    assert mixed.any_enabled() is True
    assert mixed.enabled_count() == 2


def test_resolve_new_view_template_prefers_section_then_time():
    files = {"a": 1, "b": 1, "c": 1}
    assert resolve_new_view_template(["a", "b"], ["c"], files) == ["a", "b"]
    assert resolve_new_view_template([], ["c", "a"], files) == ["c", "a"]
    assert resolve_new_view_template([], [], files) == []
    # Drop missing / duplicate while preserving first-seen order.
    assert resolve_new_view_template(
        ["a", "a", "missing", "b"], ["c"], files
    ) == ["a", "b"]


def test_resolve_mode_entry_fill_only_when_target_empty():
    files = {"a": 1, "b": 1}
    assert resolve_mode_entry_fill(["a"], ["b"], files) is None
    assert resolve_mode_entry_fill([], ["b", "a"], files) == ["b", "a"]
    assert resolve_mode_entry_fill([], [], files) == []
    assert resolve_mode_entry_fill([], ["gone"], files) == []


def test_settings_round_trip_and_legacy_key():
    settings = _FakeSettings({ATTACH_ON_LOAD_KEY: "false"})
    prefs = load_follow_prefs(settings)
    assert prefs == FollowPrefs(
        attach_on_load=False,
        inherit_on_new_view=False,
        fill_on_mode_entry=False,
    )
    save_follow_prefs(
        settings,
        FollowPrefs(True, True, False),
    )
    assert settings._data[ATTACH_ON_LOAD_KEY] is True
    assert settings._data[INHERIT_ON_NEW_VIEW_KEY] is True
    assert settings._data[FILL_ON_MODE_ENTRY_KEY] is False
    assert settings.synced == 1
    assert load_follow_prefs(settings).inherit_on_new_view is True


def _window(qtbot, qapp):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    return window


def _fid(window):
    return next(iter(window.files))


def test_item1_load_attaches_active_fft_view_not_time(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _window(qtbot, qapp)
    window.load_file(loaded_csv)
    qapp.processEvents()
    fid = _fid(window)
    time_before = list(window.view_manager.get(0).attached_file_ids)
    assert time_before == [fid]

    window._on_view_new()
    qapp.processEvents()
    assert window.view_manager.get(1).attached_file_ids == []

    window.navigator.set_follow_prefs(FollowPrefs(True, False, False))
    window._on_mode_changed("fft")
    qapp.processEvents()
    fft = window.analysis_managers["fft"]
    assert fft.get(0).attached_file_ids == []

    messages = []
    monkeypatch.setattr(
        window,
        "toast",
        lambda message, level="info": messages.append((message, level)),
    )
    window.load_file(loaded_csv)
    qapp.processEvents()
    new_fid = [f for f in window.files if f not in {fid}][-1]

    assert new_fid in fft.get(0).attached_file_ids
    assert window.view_manager.get(0).attached_file_ids == [fid]
    assert window.view_manager.get(1).attached_file_ids == []
    assert any("已加入" in msg and "频谱" in msg for msg, _ in messages)


def test_item1_off_on_analysis_page_skips_attach(qtbot, qapp, loaded_csv):
    window = _window(qtbot, qapp)
    window.navigator.set_follow_prefs(FollowPrefs(False, False, False))
    window._on_mode_changed("fft")
    qapp.processEvents()
    window.load_file(loaded_csv)
    qapp.processEvents()
    fid = _fid(window)
    assert window.view_manager.get(0).attached_file_ids == []
    assert window.analysis_managers["fft"].get(0).attached_file_ids == []
    assert fid in window.files


def test_item2_time_and_analysis_new_inherit(qtbot, qapp, loaded_csv, monkeypatch):
    window = _window(qtbot, qapp)
    window.load_file(loaded_csv)
    qapp.processEvents()
    fid = _fid(window)
    window.navigator.set_follow_prefs(FollowPrefs(False, True, False))
    messages = []
    monkeypatch.setattr(
        window,
        "toast",
        lambda message, level="info": messages.append((message, level)),
    )

    window._on_view_new()
    qapp.processEvents()
    assert window.view_manager.get(1).attached_file_ids == [fid]
    assert any("已继承 1 个文件" in msg for msg, _ in messages)

    window._on_mode_changed("fft")
    qapp.processEvents()
    fft = window.analysis_managers["fft"]
    # Seed section View so inherit prefers section over time.
    fft.get(0).attached_file_ids = [fid]
    messages.clear()
    window._on_analysis_new("fft")
    qapp.processEvents()
    assert fft.get(1).attached_file_ids == [fid]
    assert any("已继承 1 个文件" in msg for msg, _ in messages)

    # Empty section falls back to time focus.
    fft.get(1).attached_file_ids = []
    fft.set_active(1)
    window._project_analysis_attachments("fft", fft.get(1))
    messages.clear()
    window._on_analysis_new("fft")
    qapp.processEvents()
    assert fft.get(2).attached_file_ids == [fid]


def test_item2_full_manager_is_noop(qtbot, qapp, loaded_csv):
    window = _window(qtbot, qapp)
    window.load_file(loaded_csv)
    qapp.processEvents()
    window.navigator.set_follow_prefs(FollowPrefs(False, True, False))
    mgr = window.view_manager
    while len(mgr.views) < mgr.max_views:
        assert mgr.new_view() >= 0
    before = [list(v.attached_file_ids) for v in mgr.views]
    window._on_view_new()
    assert [list(v.attached_file_ids) for v in mgr.views] == before


def test_item3_fills_empty_on_mode_entry_only(
    qtbot, qapp, loaded_csv, monkeypatch
):
    window = _window(qtbot, qapp)
    window.load_file(loaded_csv)
    qapp.processEvents()
    fid = _fid(window)
    window.navigator.set_follow_prefs(FollowPrefs(False, False, True))
    messages = []
    monkeypatch.setattr(
        window,
        "toast",
        lambda message, level="info": messages.append((message, level)),
    )

    fft = window.analysis_managers["fft"]
    assert fft.get(0).attached_file_ids == []
    window._on_mode_changed("fft")
    qapp.processEvents()
    assert fft.get(0).attached_file_ids == [fid]
    assert any("已填充 1 个文件" in msg for msg, _ in messages)

    # Configured View is not overwritten on re-entry.
    fft.get(0).attached_file_ids = [fid]
    window._on_mode_changed("time")
    qapp.processEvents()
    messages.clear()
    window._on_mode_changed("fft")
    qapp.processEvents()
    assert fft.get(0).attached_file_ids == [fid]
    assert not any("已填充" in msg for msg, _ in messages)

    # Same-section tab switch to an empty View must not fill.
    fft.new_view()
    empty = fft.get(1)
    assert empty.attached_file_ids == []
    messages.clear()
    window._on_analysis_view_switched("fft", 1)
    qapp.processEvents()
    assert empty.attached_file_ids == []
    assert messages == []

    # fft → order still sources from time focus View.
    order = window.analysis_managers["order"]
    assert order.get(0).attached_file_ids == []
    messages.clear()
    window._on_mode_changed("order")
    qapp.processEvents()
    assert order.get(0).attached_file_ids == [fid]
    assert any("已填充 1 个文件" in msg for msg, _ in messages)


def test_item3_skips_while_opening_project(qtbot, qapp, loaded_csv):
    window = _window(qtbot, qapp)
    window.load_file(loaded_csv)
    qapp.processEvents()
    window.navigator.set_follow_prefs(FollowPrefs(False, False, True))
    window._opening_project = True
    window._on_mode_changed("fft")
    qapp.processEvents()
    assert window.analysis_managers["fft"].get(0).attached_file_ids == []

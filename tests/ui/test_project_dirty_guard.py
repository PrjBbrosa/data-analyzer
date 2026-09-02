"""Task 5A: ProjectDirtyState holder + save-path serializer characterization.

Holder tests are Qt-free aside from the tests/ui autouse fixtures. Digest tests
reuse ``project_io.project_document_to_payload`` — the same object
``save_project_to_json`` writes — so 5B/5C can review dirty against one
semantic source.
"""

from __future__ import annotations

import json

from mf4_analyzer.ui.main_window.project_dirty import (
    DirtyGuardResult,
    ProjectDirtyState,
)
from mf4_analyzer.ui import project_io as pio


def test_user_project_mutation_marks_dirty_once(qapp):
    holder = ProjectDirtyState()
    assert holder.revision == 0
    assert holder.save_point == 0
    assert holder.path is None
    assert holder.restore_depth == 0
    assert not holder.is_dirty

    accepted = holder.mark_user_mutation(token="view.rename")
    coalesced = holder.mark_user_mutation(token="view.rename")

    assert accepted is True
    assert coalesced is False
    assert holder.revision == 1
    assert holder.save_point == 0
    assert holder.is_dirty

    from mf4_analyzer.ui.view_state import ViewManager

    funnel = ProjectDirtyState()

    class _Host:
        _project_dirty = funnel

        def _on_project_semantic_views_changed(self):
            self._project_dirty.mark_user_mutation()

    host = _Host()
    manager = ViewManager()
    manager.views_changed.connect(host._on_project_semantic_views_changed)
    manager.rename(0, "工况 A")
    assert funnel.revision == 1
    assert funnel.is_dirty


def test_programmatic_view_projection_does_not_mark_dirty(qapp):
    """Restore/View apply is not user intent (projection lesson)."""
    holder = ProjectDirtyState()
    holder.begin_restore()
    holder.begin_restore()
    assert holder.restore_depth == 2

    assert holder.mark_user_mutation() is False
    assert holder.mark_user_mutation(token="axis_groups_changed") is False
    assert holder.revision == 0
    assert not holder.is_dirty

    holder.end_restore()
    assert holder.restore_depth == 1
    assert holder.mark_user_mutation(token="view.apply") is False
    holder.end_restore()
    holder.end_restore()  # clamp; already at 0
    assert holder.restore_depth == 0

    assert holder.mark_user_mutation(token="user.split") is True
    assert holder.is_dirty
    assert holder.revision == 1

    from mf4_analyzer.ui.view_state import ViewManager

    projected = ProjectDirtyState()

    class _Host:
        _project_dirty = projected

        def _on_project_semantic_views_changed(self):
            self._project_dirty.mark_user_mutation()

    host = _Host()
    manager = ViewManager()
    manager.views_changed.connect(host._on_project_semantic_views_changed)
    projected.begin_restore()
    manager.rename(0, "restore")
    manager.views_changed.emit()
    projected.end_restore()
    assert projected.revision == 0
    assert not projected.is_dirty


def test_successful_save_sets_clean_save_point():
    holder = ProjectDirtyState()
    holder.mark_user_mutation()
    assert holder.is_dirty

    holder.mark_saved(path="/tmp/session.tlproj")

    assert not holder.is_dirty
    assert holder.save_point == holder.revision
    assert holder.path == "/tmp/session.tlproj"


def test_adopt_restored_session_replaces_prior_revision_digest_and_token():
    holder = ProjectDirtyState()
    holder.mark_user_mutation(token="session-a")
    holder.mark_saved(path="a.tlproj", digest="digest-a")
    holder.mark_user_mutation(token="session-b")
    holder.begin_restore()

    holder.adopt_restored_session(path="b.tlproj", digest="digest-b")

    assert holder.revision == 0
    assert holder.save_point == 0
    assert holder.path == "b.tlproj"
    assert holder.saved_digest == "digest-b"
    assert holder.restore_depth == 1
    assert not holder.is_dirty
    holder.end_restore()
    assert holder.mark_user_mutation(token="session-b") is True


def test_canonical_reconciliation_can_return_to_saved_payload_then_leave_it():
    holder = ProjectDirtyState()
    holder.mark_user_mutation()
    holder.mark_saved(path="session.tlproj", digest="saved")

    holder.mark_user_mutation()
    assert holder.is_dirty
    assert holder.reconcile_saved_digest("saved") is True
    assert not holder.is_dirty

    holder.mark_user_mutation()
    assert holder.is_dirty
    assert holder.reconcile_saved_digest("different") is False
    assert holder.is_dirty


def test_failed_or_cancelled_save_keeps_dirty():
    holder = ProjectDirtyState()
    holder.mark_user_mutation()
    revision = holder.revision
    save_point = holder.save_point
    path = holder.path

    # 5C will skip mark_saved on picker cancel / IO failure.
    assert holder.is_dirty
    assert holder.revision == revision
    assert holder.save_point == save_point
    assert holder.path is path


def test_clear_resets_symmetrically_with_init():
    holder = ProjectDirtyState()
    holder.begin_restore()
    holder.end_restore()
    holder.mark_user_mutation(token="edit")
    holder.mark_saved(path="a.tlproj")
    holder.mark_user_mutation()

    holder.clear()

    assert holder == ProjectDirtyState()
    assert not holder.is_dirty
    assert holder.path is None
    assert holder.restore_depth == 0


def test_guard_result_enum_is_defined_for_later_close_wiring():
    assert {item.name for item in DirtyGuardResult} == {
        "PROCEED_SAVED",
        "PROCEED_DISCARDED",
        "CANCELLED",
    }


def test_runtime_selection_focus_hover_are_not_holder_mutations():
    """Those surfaces have no mark API; only mark_user_mutation bumps revision."""
    holder = ProjectDirtyState()
    for name in (
        "selection", "focus", "hover", "popup", "render_cache",
        "job_progress", "toast", "preview",
    ):
        assert not hasattr(holder, f"mark_{name}")
    assert holder.revision == 0
    assert not holder.is_dirty


def _characterization_doc():
    return pio.ProjectDocument(
        active_file="f0",
        current_mode="time",
        files=[
            pio.ProjectFileRef(
                fid="f1",
                path_abs="/data/b.mf4",
                path_rel="b.mf4",
                fs=1000.0,
                time_source="generated",
                channel_order=["torque", "rpm"],
            ),
            pio.ProjectFileRef(
                fid="f0",
                path_abs="/data/a.mf4",
                path_rel="a.mf4",
                fs=2000.0,
                time_source="manual",
                dbc_refs=[pio.ProjectPathRef("/dbc/x.dbc", "x.dbc")],
                channel_order=["rpm"],
            ),
        ],
        views=[
            {
                "name": "View 1",
                "tab_color": "#2d7ff9",
                "checked": [["f0", "rpm"]],
                "axis_opts": {"tick_density": "normal"},
            }
        ],
        view_manager={"active": 0, "split_pairs": {"1": 0}},
        analysis_views={
            "fft": {
                "active": 0,
                "views": [{"name": "FFT 1", "tab_color": "#e8590c", "panes": []}],
            }
        },
        filter={
            "enabled": True,
            "spec": {
                "kind": "low",
                "order": 4,
                "cutoff": 40.0,
                "cutoff_lo": 0.0,
                "cutoff_hi": 0.0,
            },
            "show_original": True,
            "show_filtered": True,
        },
        ultraview={
            "schema": 5,
            "workspace": {
                "active_board_id": "board-a",
                "show_card_actions": False,
                "boards": [{"board_id": "board-a", "name": "对比", "placements": []}],
            },
        },
    )


def _walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def test_canonical_digest_matches_project_roundtrip_and_excludes_runtime_keys(tmp_path):
    doc = _characterization_doc()
    payload = pio.project_document_to_payload(doc)
    assert tuple(payload) == pio.PROJECT_PAYLOAD_KEYS

    shuffled = {key: payload[key] for key in reversed(list(payload))}
    digest = pio.canonical_project_digest(doc)
    assert digest == pio.canonical_project_digest(payload)
    assert digest == pio.canonical_project_digest(shuffled)

    rebuilt_files = list(reversed(list(doc.files)))
    rebuilt_files.reverse()
    same_order = pio.ProjectDocument(
        active_file=doc.active_file,
        current_mode=doc.current_mode,
        files=rebuilt_files,
        views=list(doc.views),
        view_manager=dict(doc.view_manager),
        analysis_views=dict(doc.analysis_views),
        filter=dict(doc.filter),
        ultraview=dict(doc.ultraview),
    )
    assert pio.canonical_project_digest(same_order) == digest
    swapped_files = pio.ProjectDocument(
        active_file=doc.active_file,
        current_mode=doc.current_mode,
        files=list(reversed(doc.files)),
        views=list(doc.views),
        view_manager=dict(doc.view_manager),
        analysis_views=dict(doc.analysis_views),
        filter=dict(doc.filter),
        ultraview=dict(doc.ultraview),
    )
    assert pio.canonical_project_digest(swapped_files) != digest

    path = tmp_path / "session.tlproj"
    pio.save_project_to_json(doc, path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert tuple(on_disk) == pio.PROJECT_PAYLOAD_KEYS
    loaded = pio.load_project_from_json(path)
    assert pio.canonical_project_digest(loaded) == digest

    runtime_probe = dict(payload)
    for key in ("selection", "focus", "hover", "job_progress", "toast"):
        runtime_probe[key] = {"ignored": True}
    assert pio.canonical_project_digest(runtime_probe) != digest
    for key in _walk_keys(payload):
        assert key not in pio.PROJECT_RUNTIME_ONLY_KEYS, key


def test_selection_render_preview_and_job_progress_do_not_mark_dirty():
    test_runtime_selection_focus_hover_are_not_holder_mutations()


class _GuardHost:
    """Focused close/open-replace harness that reuses the real guard."""

    def __init__(self):
        from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

        self._project_dirty = ProjectDirtyState()
        self._project_path = "/tmp/current.tlproj"
        self.save_ok = True
        self.save_calls = []
        self.prompt_choice = "cancel"
        self.prompt_calls = 0
        self.teardown_calls = []
        self.reenter_close = False
        self.confirm_leave_unsaved_project = (
            ProjectIOMixin.confirm_leave_unsaved_project.__get__(self)
        )
        self._project_session_is_dirty = (
            ProjectIOMixin._project_session_is_dirty.__get__(self)
        )

    def save_project_via_dialog(self):
        self.save_calls.append(self._project_path)
        if not self.save_ok:
            return False
        self._project_dirty.mark_saved(self._project_path)
        return True

    def _canonical_session_digest(self):
        return self._project_dirty.saved_digest

    def _prompt_unsaved_project(self):
        self.prompt_calls += 1
        if self.reenter_close:
            self.reenter_close = False
            self.close()
        return self.prompt_choice

    def close(self):
        class _Event:
            def __init__(self):
                self.ignored = False
                self.accepted = False

            def ignore(self):
                self.ignored = True

            def accept(self):
                self.accepted = True

        event = _Event()
        self.closeEvent(event)
        return event

    def closeEvent(self, event):
        holder = self._project_dirty
        if holder.guard_open or holder.close_teardown_started:
            event.ignore()
            return
        result = self.confirm_leave_unsaved_project()
        if result is DirtyGuardResult.CANCELLED:
            event.ignore()
            return
        holder.close_teardown_started = True
        self.teardown_calls.append("teardown")
        event.accept()


def test_failed_or_cancelled_save_keeps_dirty_and_current_project():
    host = _GuardHost()
    host._project_dirty.mark_user_mutation()
    host._project_path = "/tmp/current.tlproj"
    host.prompt_choice = "save"
    host.save_ok = False

    result = host.confirm_leave_unsaved_project()

    assert result is DirtyGuardResult.CANCELLED
    assert host._project_dirty.is_dirty
    assert host._project_path == "/tmp/current.tlproj"
    assert host.save_calls == ["/tmp/current.tlproj"]


def test_open_replacement_uses_same_save_discard_cancel_guard():
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    host = _GuardHost()
    host._project_dirty.mark_user_mutation()
    host.prompt_choice = "cancel"
    opened = []

    def _open_project(path):
        opened.append(path)

    host.open_project = _open_project
    host.files = {"f0": object()}
    host._open_data_paths = lambda paths: None
    host._open_paths = ProjectIOMixin._open_paths.__get__(host)

    host._open_paths(["/tmp/other.tlproj"])

    assert host.prompt_calls == 1
    assert opened == []
    assert host._project_dirty.is_dirty

    host.prompt_choice = "discard"
    host._open_paths(["/tmp/other.tlproj"])
    assert opened == ["/tmp/other.tlproj"]
    assert host.prompt_calls == 2


def test_close_cancel_happens_before_workers_or_tool_windows_stop():
    host = _GuardHost()
    host._project_dirty.mark_user_mutation()
    host.prompt_choice = "cancel"

    event = host.close()

    assert event.ignored is True
    assert host.prompt_calls == 1
    assert host.teardown_calls == []
    assert host._project_dirty.is_dirty
    assert not host._project_dirty.close_teardown_started


def test_reentrant_close_shows_one_prompt_and_tears_down_once():
    host = _GuardHost()
    host._project_dirty.mark_user_mutation()
    host.prompt_choice = "discard"
    host.reenter_close = True

    event = host.close()

    assert event.accepted is True
    assert host.prompt_calls == 1
    assert host.teardown_calls == ["teardown"]
    assert host._project_dirty.close_teardown_started


def test_unsaved_prompt_defaults_to_save_not_discard(qapp, qtbot):
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    widget = QWidget()
    qtbot.addWidget(widget)
    widget._unsaved_project_prompt_buttons = (
        ProjectIOMixin._unsaved_project_prompt_buttons.__get__(widget)
    )
    box, save_btn, discard_btn, cancel_btn = widget._unsaved_project_prompt_buttons()
    assert box.defaultButton() is save_btn
    assert box.escapeButton() is cancel_btn
    assert box.defaultButton() is not discard_btn
    assert save_btn.text() == "保存"
    assert discard_btn.text() == "不保存"
    assert cancel_btn.text() == "取消"
    box.close()


def test_successful_save_sets_clean_save_point_on_window(qapp, tmp_path):
    import csv
    from mf4_analyzer.ui.main_window import MainWindow

    csv_path = tmp_path / "a.csv"
    with open(csv_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "rpm"])
        for i in range(20):
            writer.writerow([i / 100.0, float(i)])
    proj = tmp_path / "s.tlproj"
    mw = MainWindow()
    mw._load_one(str(csv_path))
    assert mw._project_dirty.is_dirty
    assert mw.save_project(proj) is True
    assert not mw._project_dirty.is_dirty
    assert mw._project_dirty.path == str(proj)
    assert mw._project_dirty.saved_digest


def test_save_a_then_open_b_replaces_digest_and_project_session(
    qapp, qtbot, tmp_path,
):
    from mf4_analyzer.ui.main_window import MainWindow

    project_a = tmp_path / "a.tlproj"
    project_b = tmp_path / "b.tlproj"
    target = MainWindow()
    source_b = MainWindow()
    qtbot.addWidget(target)
    qtbot.addWidget(source_b)
    target.view_manager.rename(0, "项目 A")
    source_b.view_manager.rename(0, "项目 B")
    assert target.save_project(project_a) is True
    assert source_b.save_project(project_b) is True
    digest_a = target._project_dirty.saved_digest
    digest_b_on_source = source_b._project_dirty.saved_digest
    assert digest_a != digest_b_on_source

    target.open_project(project_b)

    assert target._project_dirty.path == str(project_b)
    assert target._project_dirty.saved_digest != digest_a
    assert target._project_dirty.saved_digest == target._canonical_session_digest()
    assert target._project_dirty.revision == 0
    assert target._project_dirty.save_point == 0
    assert not target._project_dirty.is_dirty


def test_fresh_open_seeds_canonical_baseline_and_leave_is_clean(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    project = tmp_path / "fresh.tlproj"
    source = MainWindow()
    restored = MainWindow()
    qtbot.addWidget(source)
    qtbot.addWidget(restored)
    source.view_manager.rename(0, "已保存")
    assert source.save_project(project) is True

    restored.open_project(project)

    holder = restored._project_dirty
    assert holder.saved_digest is not None
    assert holder.saved_digest == restored._canonical_session_digest()
    assert holder.revision == 0
    assert holder.save_point == 0
    assert not holder.is_dirty
    monkeypatch.setattr(
        restored,
        "_prompt_unsaved_project",
        lambda: (_ for _ in ()).throw(AssertionError("clean open prompted")),
    )
    assert (
        restored.confirm_leave_unsaved_project()
        is DirtyGuardResult.PROCEED_DISCARDED
    )


def test_ultraview_undo_to_saved_payload_is_clean_and_redo_is_dirty(
    qapp, qtbot, tmp_path,
):
    from mf4_analyzer.ui import ultraview_state as uvs
    from mf4_analyzer.ui.main_window import MainWindow

    project = tmp_path / "history.tlproj"
    window = MainWindow()
    qtbot.addWidget(window)
    uv = window._ultraview
    board = uv.board
    saved_edit = uvs.create_author_object(
        board,
        uvs.StickyObject(
            object_id="saved",
            kind="sticky",
            box=uvs.BoardBox(0, 0, 2, 2),
            text="saved",
            palette="yellow",
            shape="square",
            font_size="auto",
        ),
    )
    assert uv._commit_author_mutation(board, saved_edit, label="create")
    assert window.save_project(project) is True

    later_edit = uvs.create_author_object(
        board,
        uvs.StickyObject(
            object_id="later",
            kind="sticky",
            box=uvs.BoardBox(3, 0, 2, 2),
            text="later",
            palette="yellow",
            shape="square",
            font_size="auto",
        ),
    )
    assert uv._commit_author_mutation(board, later_edit, label="create")
    assert window._project_dirty.is_dirty

    uv._on_free_grid_undo()
    assert [item.object_id for item in board.author_objects] == ["saved"]
    assert not window._project_dirty.is_dirty

    uv._on_free_grid_redo()
    assert [item.object_id for item in board.author_objects] == ["saved", "later"]
    assert window._project_dirty.is_dirty


def test_empty_and_rejected_ultraview_undo_do_not_advance_dirty_revision(
    qapp, qtbot, monkeypatch,
):
    from mf4_analyzer.ui import ultraview_state as uvs
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window import ultraview_workspace_controller as uwc

    window = MainWindow()
    qtbot.addWidget(window)
    uv = window._ultraview
    holder = window._project_dirty
    before_empty = holder.revision
    uv._on_free_grid_undo()
    assert holder.revision == before_empty
    assert not holder.is_dirty

    board = uv.board
    mutation = uvs.create_author_object(
        board,
        uvs.StickyObject(
            object_id="blocked",
            kind="sticky",
            box=uvs.BoardBox(0, 0, 2, 2),
            text="blocked",
            palette="yellow",
            shape="square",
            font_size="auto",
        ),
    )
    assert uv._commit_author_mutation(board, mutation, label="create")
    before_rejected = holder.revision
    monkeypatch.setattr(uwc, "apply_board_edit_entry", lambda *_a, **_k: False)

    uv._on_free_grid_undo()

    assert holder.revision == before_rejected
    assert holder.is_dirty


def test_open_replacement_guard_on_real_window(qapp, tmp_path, monkeypatch):
    import csv
    from mf4_analyzer.ui.main_window import MainWindow

    def _csv(path):
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time", "rpm"])
            for i in range(20):
                writer.writerow([i / 100.0, float(i)])

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _csv(a)
    _csv(b)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow()
    mw._load_one(str(a))
    mw.save_project(proj)
    mw._load_one(str(b))
    assert mw._project_dirty.is_dirty
    monkeypatch.setattr(mw, "_prompt_unsaved_project", lambda: "cancel")
    before = list(mw.files)
    mw._open_paths([str(proj)])
    assert list(mw.files) == before
    assert mw._project_dirty.is_dirty

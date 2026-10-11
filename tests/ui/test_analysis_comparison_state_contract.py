"""Real input-event coverage for independent analysis comparison targets."""
from __future__ import annotations

import pytest
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMenu, QToolButton
from pyqtgraph import ViewBox

from .test_analysis_view_comparison_regressions import win, prep
from .test_analysis_view_comparison import _frf_result

SECTIONS = ("fft", "fft_time", "order", "frf")


def _click_canvas(canvas, button=Qt.LeftButton, box=None):
    glw = canvas._glw
    if box is None:
        boxes = [item for item in glw.scene().items()
                 if isinstance(item, ViewBox) and item.isVisible()
                 and getattr(item, "_owner_canvas", None) is canvas]
        box = min(boxes, key=lambda item: item.sceneBoundingRect().top())
    pos = glw.mapFromScene(box.sceneBoundingRect().center())
    QTest.mouseClick(glw.viewport(), button, pos=pos)
    QApplication.processEvents()


def _shown_pair(win, section, qtbot):
    page, mgr, a, b = prep(win, section)
    a.params.update(window="hanning")
    b.params.update(window="hamming")
    if section != "frf":
        a.params.update(db_reference_mode="manual", db_reference=1.0)
        b.params.update(db_reference_mode="manual", db_reference=2.0)
    win.resize(1500, 1100)
    win.show()
    assert win.open_comparison(section, a.view_id, b.view_id)
    qtbot.wait(250)
    return page, mgr, a, b


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
def test_pending_reference_commits_to_outgoing_view_on_canvas_click(win, section, qtbot):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    ctx = win._analysis_ctx(section)
    editor = ctx.spin_db_ref
    assert not editor.keyboardTracking()
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor.lineEdit(), "3.25")
    assert editor.value() == 1.0
    _click_canvas(page.peer_cards()[0].canvas)
    assert win._comparison().focused(section) == (b.view_id, 0)
    assert a.params["db_reference"] == 3.25
    assert b.params["db_reference"] == 2.0
    assert editor.value() == 2.0
    _click_canvas(page.pane_canvas(0))
    assert editor.value() == 3.25


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
def test_save_reopen_commits_focused_peer_pending_reference(win, section, qtbot, tmp_path, monkeypatch):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    _click_canvas(page.peer_cards()[0].canvas)
    editor = win._analysis_ctx(section).spin_db_ref
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor.lineEdit(), "4.5")
    assert editor.value() == 2.0
    submissions = []
    monkeypatch.setattr(win._analysis_jobs, "submit_batch", lambda *args, **kwargs: submissions.append(args))
    path = tmp_path / "pending-peer.tlproj"
    assert win.save_project(path)
    QApplication.processEvents()
    assert submissions == []
    assert b.params["db_reference"] == 4.5
    assert a.params["db_reference"] == 1.0
    win.open_project(path)
    restored = win.analysis_managers[section].views
    assert restored[0].params["db_reference"] == 1.0
    assert restored[1].params["db_reference"] == 4.5


@pytest.mark.parametrize("section", SECTIONS)
def test_real_combo_and_numeric_edits_follow_canvas_focus(win, section, qtbot, monkeypatch):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    ctx = win._analysis_ctx(section)
    submissions = []
    monkeypatch.setattr(win._analysis_jobs, "submit_batch", lambda *args, **kwargs: submissions.append(args))
    _click_canvas(page.peer_cards()[0].canvas)
    before_a = dict(a.params)
    combo = ctx.combo_window if section == "frf" else ctx.combo_win
    combo.setCurrentIndex(combo.findData("blackman") if section == "frf" else combo.findText("blackman"))
    numeric = ctx.spin_mo if section == "order" else ctx.spin_overlap
    numeric.setFocus()
    numeric.lineEdit().selectAll()
    QTest.keyClicks(numeric.lineEdit(), "37")
    QTest.keyClick(numeric.lineEdit(), Qt.Key_Return)
    key = "max_order" if section == "order" else "overlap"
    assert ctx.current_params()["window"] == "blackman"
    _click_canvas(page.pane_canvas(0))
    assert a.params == before_a
    assert b.params["window"] == "blackman"
    assert b.params[key] == pytest.approx(37 if section == "order" else 0.37)
    assert ctx.current_params()["window"] == "hanning"
    _click_canvas(page.peer_cards()[0].canvas)
    assert numeric.value() == 37
    assert submissions == []


@pytest.mark.parametrize("section", SECTIONS)
def test_right_menu_all_visible_rows_focus_clicked_view_and_execute_zoom(win, section, qtbot):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    cards = [page._cards[0], page.peer_cards()[0]]
    for card in cards:
        if section in ("fft_time", "order"):
            card.canvas.plot_or_update_heatmap(
                matrix=np.arange(80, dtype=float).reshape(8, 10),
                x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
                amplitude_mode="amplitude", z_auto=True,
            )
        elif section == "frf":
            card.canvas.set_result(_frf_result(2.0))
    QApplication.processEvents()
    for card, state in zip(cards, (a, b)):
        boxes = sorted(
            [item for item in card.canvas._glw.scene().items()
             if isinstance(item, ViewBox) and item.isVisible()
             and getattr(item, "_owner_canvas", None) is card.canvas],
            key=lambda item: item.sceneBoundingRect().top(),
        )
        assert len(boxes) >= (3 if section == "frf" else 2)
        for box in boxes:
            page._toolbar._click_pan()
            _click_canvas(card.canvas, Qt.RightButton, box)
            menus = [widget for widget in QApplication.topLevelWidgets()
                     if isinstance(widget, QMenu) and widget.isVisible()]
            try:
                assert menus, (section, state.name, box.sceneBoundingRect())
                assert win._comparison().focused(section) == (state.view_id, 0)
                zoom = next((menu.findChild(QToolButton, "pgContextZoomButton")
                             for menu in menus if menu.findChild(QToolButton, "pgContextZoomButton")), None)
                assert zoom is not None
                QTest.mouseClick(zoom, Qt.LeftButton)
                assert card.toolbar.mode == "zoom"
            finally:
                for menu in menus:
                    menu.close()


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
def test_pending_invalid_reference_save_retains_last_valid_value(win, section, qtbot, tmp_path):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    _click_canvas(page.peer_cards()[0].canvas)
    editor = win._analysis_ctx(section).spin_db_ref
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor.lineEdit(), "0")
    assert win.save_project(tmp_path / "invalid-reference.tlproj")
    assert editor.is_error()
    assert a.params["db_reference"] == 1.0
    assert b.params["db_reference"] == 2.0


@pytest.mark.parametrize("section", SECTIONS)
def test_preset_only_changes_clicked_peer_and_does_not_compute(win, section, qtbot, monkeypatch):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    _click_canvas(page.peer_cards()[0].canvas)
    before = dict(a.params)
    ctx = win._analysis_ctx(section)
    submissions = []
    monkeypatch.setattr(win._analysis_jobs, "submit_batch", lambda *args, **kwargs: submissions.append(args))
    ctx.preset_bar._write(4, "Comparison peer", {"window": "blackman"})
    ctx.preset_bar._load(4)
    QApplication.processEvents()
    assert b.params["window"] == "blackman"
    assert a.params == before
    assert submissions == []
    _click_canvas(page.pane_canvas(0))
    assert ctx.current_params()["window"] == "hanning"


@pytest.mark.parametrize("section", SECTIONS)
def test_annotation_blank_right_click_is_delete_gesture_then_exit_restores_menu(win, section, qtbot, monkeypatch):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    card = page.peer_cards()[0]
    _click_canvas(card.canvas)
    removals = []
    card.set_annotation_enabled(True)
    assert card.canvas._remark_interaction.enabled
    _click_canvas(page.pane_canvas(0))
    assert not page._cards[0].annotation_enabled()
    assert card.annotation_enabled()
    _click_canvas(card.canvas)
    assert card.canvas._remark_interaction.enabled
    if section == "fft":
        assert win.inspector.fft_ctx.chk_remark.isChecked()
    monkeypatch.setattr(card.canvas._remark_interaction, "_remove_at_viewport_pos", removals.append)
    _click_canvas(card.canvas, Qt.RightButton)
    assert len(removals) == 1
    assert not [widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, QMenu) and widget.isVisible()]
    card.set_annotation_enabled(False)
    _click_canvas(card.canvas, Qt.RightButton)
    menus = [widget for widget in QApplication.topLevelWidgets()
             if isinstance(widget, QMenu) and widget.isVisible()]
    try:
        assert menus
        assert win._comparison().focused(section) == (b.view_id, 0)
    finally:
        for menu in menus:
            menu.close()


@pytest.mark.parametrize("section", SECTIONS)
def test_source_time_and_inspector_target_follow_real_focus_and_rename(win, section, qtbot):
    page, mgr, a, b = _shown_pair(win, section, qtbot)
    if section == "frf":
        for state, fid in zip((a, b), win.files):
            state.panes[0].input_source = (fid, "speed")
            state.panes[0].output_source = (fid, "torque")
    a.panes[0].time_range = (0.1, 0.8)
    b.panes[0].time_range = (0.2, 0.9)
    win._apply_analysis_sources(section, a)
    win._apply_analysis_time_range(section, a)
    _click_canvas(page.peer_cards()[0].canvas)
    title, _base = win.inspector._analysis_target_titles[section]
    assert title.toolTip() == f"{b.name} · 窗格 1"
    top = win.inspector.top
    assert top.spin_start.value() == pytest.approx(0.2)
    assert top.spin_end.value() == pytest.approx(0.9)
    top.spin_start.setFocus()
    top.spin_start.lineEdit().selectAll()
    QTest.keyClicks(top.spin_start.lineEdit(), "0.3")
    _click_canvas(page.pane_canvas(0))
    assert a.panes[0].time_range == pytest.approx((0.1, 0.8))
    assert b.panes[0].time_range == pytest.approx((0.3, 0.9))
    assert title.toolTip() == f"{a.name} · 窗格 1"
    _click_canvas(page.peer_cards()[0].canvas)
    assert top.spin_start.value() == pytest.approx(0.3)
    peer_idx = next(i for i, view in enumerate(mgr.views) if view is b)
    win._on_analysis_view_rename(section, peer_idx, "Peer renamed")
    assert title.toolTip() == "Peer renamed · 窗格 1"
    if section != "frf":
        assert a.panes[0].sources == [(list(win.files)[0], "speed")]
        assert b.panes[0].sources == [(list(win.files)[1], "speed")]
    else:
        assert a.panes[0].input_source == (list(win.files)[0], "speed")
        assert b.panes[0].input_source == (list(win.files)[1], "speed")


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
@pytest.mark.parametrize("after_edit", ("focus", "close", "delete"))
def test_deferred_reference_redraw_keeps_original_identity(win, section, after_edit, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import window as window_module

    page, mgr, a, b = _shown_pair(win, section, qtbot)
    _click_canvas(page.peer_cards()[0].canvas)
    pending = []
    single_shot = window_module.QTimer.singleShot

    def capture_reference_redraw(delay, callback):
        if getattr(callback, "__name__", "") == "redraw_edited_view":
            pending.append(callback)
        else:
            single_shot(delay, callback)

    monkeypatch.setattr(window_module.QTimer, "singleShot", capture_reference_redraw)
    editor = win._analysis_ctx(section).spin_db_ref
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor.lineEdit(), "6.5")
    QTest.keyClick(editor.lineEdit(), Qt.Key_Return)
    assert pending
    if after_edit == "focus":
        win.focus_comparison(section, a.view_id, 0)
    elif after_edit == "close":
        win.close_comparison(section)
    else:
        peer_idx = next(i for i, view in enumerate(mgr.views) if view is b)
        win._on_analysis_delete(section, peer_idx)
    rendered = []
    monkeypatch.setattr(win, "_render_analysis_view_from_cache", lambda section, state: rendered.append(state.view_id))
    for callback in pending:
        callback()
    assert rendered == ([b.view_id] if after_edit == "focus" else [])
    assert a.params["db_reference"] == 1.0


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
def test_reference_commit_finishes_auto_to_manual_before_deferred_redraw(win, section, qtbot, tmp_path, monkeypatch):
    page, _mgr, a, b = _shown_pair(win, section, qtbot)
    b.params["db_reference_mode"] = "auto"
    _click_canvas(page.peer_cards()[0].canvas)
    ctx = win._analysis_ctx(section)
    assert ctx.db_reference_control.mode() == "auto"
    editor = ctx.spin_db_ref
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor.lineEdit(), "7.5")
    submitted = []
    monkeypatch.setattr(win._analysis_jobs, "submit_batch", lambda *args, **kwargs: submitted.append(args))
    assert win.save_project(tmp_path / "auto-to-manual.tlproj")
    QApplication.processEvents()
    assert ctx.db_reference_control.mode() == "manual"
    assert editor.value() == 7.5
    assert b.params["db_reference_mode"] == "manual"
    assert b.params["db_reference"] == 7.5
    assert a.params["db_reference"] == 1.0
    assert submitted == []

"""UltraView compositor, clipboard, PNG export, and signal receivers."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.compositor import (
    ComposeError,
    compose_board,
    free_grid_output_size,
    image_sha256,
    output_size,
    save_composed_png,
)
from mf4_analyzer.ui.chart_stack.ultraview.preview_store import PreviewStore
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import (
    STATUS_MISSING,
    STATUS_STALE,
    UltraViewRef,
    add_ref,
    default_board,
    make_ref,
    set_free_grid_rect,
    template_to_free_grid,
    GridRect,
)
from tests.ui.ultraview_fakes import ComputeProbe
from tests.ui.test_ultraview_preview_store import _image, _meta

_COMPOSITOR = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "compositor.py"
)


def test_compositor_does_not_import_main_window_or_grab_widgets():
    source = _COMPOSITOR.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "main_window" not in alias.name
                assert alias.name != "PyQt5.QtWidgets"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "main_window" not in node.module
            assert node.module != "PyQt5.QtWidgets"
    assert "QWidget" not in source
    assert ".grab(" not in source
    assert "grab_pixmap" not in source
    assert "grab_combined" not in source


def test_compose_board_fixed_sizes_and_show_flags(qapp):
    board = default_board()
    board.name = "合成验收"
    board.layout_id = "grid_2x2"
    live = make_ref("time", "live")
    ghost = make_ref("fft", "ghost")
    add_ref(board, live)
    add_ref(board, ghost)
    store = PreviewStore()
    store.publish(live, _image(64, 48, color="#cc1122"), digest="a", meta=_meta(live, title="Live"))
    records = {live: store.get(live), ghost: None}
    statuses = {live: "fresh", ghost: STATUS_MISSING}
    one = compose_board(board, records, statuses, scale=1)
    two = compose_board(board, records, statuses, scale=2)
    assert (one.width(), one.height()) == output_size(1) == (1600, 900)
    assert (two.width(), two.height()) == output_size(2) == (3200, 1800)
    assert abs(one.devicePixelRatio() - 1.0) < 1e-6
    assert abs(two.devicePixelRatio() - 1.0) < 1e-6
    hashes = []
    for show_titles, show_sources in (
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ):
        board.show_titles = show_titles
        board.show_sources = show_sources
        hashes.append(image_sha256(compose_board(board, records, statuses, scale=1)))
    assert len(set(hashes)) == 4


def test_missing_placeholder_and_stale_keep_old_image(qapp):
    board = default_board()
    board.layout_id = "split_horizontal"
    missing = make_ref("time", "missing")
    stale = make_ref("fft", "stale")
    add_ref(board, missing)
    add_ref(board, stale)
    store = PreviewStore()
    store.publish(stale, _image(80, 40, color="#1122cc"), digest="old", meta=_meta(stale))
    records = {missing: None, stale: store.get(stale)}
    statuses = {missing: STATUS_MISSING, stale: STATUS_STALE}
    image = compose_board(board, records, statuses, scale=1)
    assert image.width() == 1600
    # 2× contain-fit must not upscale a 16×16 raw preview past 100%.
    tiny_ref = make_ref("frf", "tiny")
    board2 = default_board()
    board2.layout_id = "split_horizontal"
    add_ref(board2, tiny_ref)
    tiny = _image(16, 16, color="#ff00aa")
    store.publish(tiny_ref, tiny, digest="t", meta=_meta(tiny_ref))
    composed = compose_board(
        board2, {tiny_ref: store.get(tiny_ref)}, {tiny_ref: "fresh"}, scale=2
    )
    magenta = 0
    for y in range(composed.height()):
        for x in range(composed.width()):
            if QColor(composed.pixel(x, y)).name() == "#ff00aa":
                magenta += 1
    assert 0 < magenta <= 16 * 16


def test_free_grid_export_uses_full_logical_board_not_current_viewport(qapp):
    board = default_board()
    add_ref(board, make_ref("time", "top"))
    add_ref(board, make_ref("fft", "bottom"))
    template_to_free_grid(board)
    bottom = make_ref("fft", "bottom")
    assert set_free_grid_rect(board, bottom, GridRect(6, 16, 6, 4)) == []
    image = compose_board(board, {}, {}, scale=1)
    assert (image.width(), image.height()) == free_grid_output_size(board, 1)
    assert image.height() > 900
    assert (compose_board(board, {}, {}, scale=2).width(), compose_board(board, {}, {}, scale=2).height()) == free_grid_output_size(board, 2)


def test_output_size_is_template_aware_and_keeps_small_layout_baseline(qapp):
    from mf4_analyzer.ui.chart_stack.ultraview.layouts import (
        BASE_BOARD_SIZE,
        logical_board_size,
    )

    assert output_size(1) == (1600, 900)
    assert output_size(1, "hero_left_4") == (1600, 900)
    assert output_size(1, "grid_2x2") == (1600, 900)
    assert output_size(1, "grid_4x3") == logical_board_size("grid_4x3", BASE_BOARD_SIZE)
    assert output_size(2, "grid_3x3") == tuple(
        2 * value for value in logical_board_size("grid_3x3", BASE_BOARD_SIZE)
    )
    board = default_board()
    board.layout_id = "grid_4x3"
    image = compose_board(board, {}, {}, scale=1)
    assert (image.width(), image.height()) == output_size(1, "grid_4x3")


def test_free_grid_short_board_export_crops_trailing_whitespace(qapp):
    board = default_board()
    add_ref(board, make_ref("time", "short"))
    template_to_free_grid(board)
    image = compose_board(board, {}, {}, scale=1)
    assert image.height() < 900
    untitled = compose_board(board, {}, {}, scale=1, title=False)
    assert untitled.height() < image.height()


def test_pathological_free_grid_2x_export_is_rejected(qapp):
    board = default_board()
    add_ref(board, make_ref("time", "deep"))
    template_to_free_grid(board)
    assert set_free_grid_rect(board, make_ref("time", "deep"), GridRect(0, 40, 4, 8)) == []
    try:
        compose_board(board, {}, {}, scale=2)
        raise AssertionError("2× 48-row export should be rejected")
    except ComposeError as exc:
        assert exc.code == "export_too_large"


def test_save_png_atomic_replace_and_failure_leaves_no_empty_file(qapp, tmp_path, monkeypatch):
    board = default_board()
    image = compose_board(board, {}, {}, scale=1)
    target = tmp_path / "board.png"
    save_composed_png(image, target)
    assert target.exists() and target.stat().st_size > 0

    def _fail_save(self, *_a, **_k):
        return False

    monkeypatch.setattr(QImage, "save", _fail_save)
    broken = tmp_path / "broken.png"
    try:
        save_composed_png(image, broken)
        raise AssertionError("save should fail")
    except ComposeError as exc:
        assert exc.code == "save_failed"
    assert not broken.exists()
    leftovers = list(tmp_path.glob(".broken.png*.tmp"))
    assert leftovers == []


def test_page_signals_have_one_receiver_until_shutdown(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview
    slots = [slot for _obj, _signal, slot in uv._page_hooks]
    assert uv.copy_board_to_clipboard in slots
    assert uv._on_copy_card in slots
    assert uv.choose_and_export_png in slots
    assert uv._on_board_name in slots
    assert uv._on_free_grid_geometry in slots
    assert uv._on_free_grid_undo in slots
    compose_calls = {"n": 0}
    orig = uv._compose_board

    def wrapped(scale=1):
        compose_calls["n"] += 1
        return orig(scale)

    uv._compose_board = wrapped
    page.copy_board_requested.emit()
    assert compose_calls["n"] == 1
    uv.reset_project_state()
    page.copy_board_requested.emit()
    assert compose_calls["n"] == 2
    uv.shutdown()
    page.copy_board_requested.emit()
    page.copy_card_image_requested.emit("time", "v1")
    page.export_png_requested.emit(1)
    assert compose_calls["n"] == 2


def test_clipboard_matches_compositor_and_card_copy_touches(qapp, qtbot, tmp_path, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    time_id = str(win.view_manager.get(0).view_id)
    ref = UltraViewRef("time", time_id)
    add_ref(uv.board, ref)
    image = _image(48, 32, color="#2266aa")
    uv.store.publish(ref, image, digest="clip", meta=_meta(ref, title="Time"))
    uv.refresh_page()
    before = uv.store.get(ref).last_access
    assert uv.copy_board_to_clipboard() is True
    clip = QApplication.clipboard().image()
    composed = uv.compose_board_image(1)
    assert image_sha256(clip) == image_sha256(composed)
    assert uv.store.get(ref).last_access > before
    png = tmp_path / "out.png"
    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window.ultraview_coordinator.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(png), "PNG (*.png)"),
    )
    assert uv.choose_and_export_png(1) is True
    assert png.exists() and png.stat().st_size > 0
    probe = ComputeProbe().install(win)
    try:
        uv.compose_board_image(2)
        assert probe.compute_total == 0
        assert probe.job_total == 0
        assert probe.store_new_key_writes == 0
    finally:
        probe.restore()


def test_library_status_query_does_not_touch_lru(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    time_id = str(win.view_manager.get(0).view_id)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    time_ref = UltraViewRef("time", time_id)
    fft_ref = UltraViewRef("fft", fft_id)
    uv.store.publish(time_ref, _image(32, 24), digest="t", meta=_meta(time_ref))
    uv.store.publish(fft_ref, _image(32, 24), digest="f", meta=_meta(fft_ref))
    time_access = uv.store.get(time_ref).last_access
    fft_access = uv.store.get(fft_ref).last_access
    uv.refresh_page()
    assert uv.store.get(time_ref).last_access == time_access
    assert uv.store.get(fft_ref).last_access == fft_access
    add_ref(uv.board, time_ref)
    uv.refresh_page()
    assert uv.store.get(time_ref).last_access > time_access
    assert uv.store.get(fft_ref).last_access == fft_access


def test_free_grid_undo_redo_is_per_board_and_reset_drops_history(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    add_ref(uv.board, ref)
    uv._on_free_grid_toggled(True)
    before = uv.board.free_grid[0].rect
    uv._on_free_grid_geometry(ref.section, ref.view_id, 0, 6, 4, 3, "test")
    assert uv.board.free_grid[0].rect.row == 6
    uv._on_free_grid_undo()
    assert uv.board.free_grid[0].rect == before
    uv._on_free_grid_redo()
    assert uv.board.free_grid[0].rect.row == 6
    board_id = uv.board.board_id
    uv.reset_project_state()
    assert board_id not in uv._grid_histories


def test_free_grid_preset_collision_toasts_and_skips_history(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    add_ref(uv.board, time_ref)
    add_ref(uv.board, fft_ref)
    uv._on_free_grid_toggled(True)
    first = uv.board.free_grid[0]
    before = first.rect
    uv._on_free_grid_preset(first.ref.section, first.ref.view_id, "banner")
    assert uv.board.free_grid[0].rect == before
    assert ("目标位置与其他卡片重叠", "warning") in toasts
    history = uv._grid_histories.get(uv.board.board_id)
    assert history is None or history.undo == []


def test_free_grid_undo_clears_history_when_membership_changes(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    add_ref(uv.board, time_ref)
    uv._on_free_grid_toggled(True)
    uv._on_free_grid_geometry(time_ref.section, time_ref.view_id, 0, 6, 4, 3, "test")
    history = uv._grid_histories[uv.board.board_id]
    assert history.undo
    add_ref(uv.board, fft_ref)
    uv._after_board_mutation()
    uv._on_free_grid_undo()
    assert history.undo == []
    assert history.redo == []
    assert any("撤销记录已清除" in msg for msg, _ in toasts)

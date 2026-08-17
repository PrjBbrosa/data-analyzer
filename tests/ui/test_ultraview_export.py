"""UltraView compositor, clipboard, PNG export, and signal receivers."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.compositor import (
    BOARD_BG,
    BOARD_PADDING,
    TITLE_BAND,
    ComposeError,
    MAX_EXPORT_EDGE,
    MAX_EXPORT_PIXELS,
    compose_board,
    composed_slot_rects,
    free_grid_output_size,
    image_sha256,
    output_size,
    save_composed_png,
)
from mf4_analyzer.ui.chart_stack.ultraview.feedback import format_export_too_large
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    export_grid_metrics,
    rect_to_pixels,
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
    set_layout,
    template_to_free_grid,
    GridRect,
    GRID_COLUMNS,
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
    assert "desired_extent" not in source
    assert "expand_extent" not in source
    assert "HALO_MIN_CELLS" not in source
    assert "EDGE_PAN_BAND_PX" not in source
    assert "from .viewport" not in source
    assert "from .page" not in source


def test_compose_board_fixed_sizes_and_show_flags(qapp):
    board = default_board()
    board.name = "合成验收"
    set_layout(board, "grid_2x2")
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
    set_layout(board, "split_horizontal")
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
    set_layout(board2, "split_horizontal")
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


def test_free_grid_export_includes_far_cards_not_live_viewport(qapp):
    board = default_board()
    add_ref(board, make_ref("time", "top"))
    add_ref(board, make_ref("fft", "bottom"))
    template_to_free_grid(board)
    bottom = make_ref("fft", "bottom")
    assert set_free_grid_rect(board, bottom, GridRect(6, 16, 6, 4)) == []
    image = compose_board(board, {}, {}, scale=1)
    assert (image.width(), image.height()) == free_grid_output_size(board, 1)
    assert image.height() > 900
    two = compose_board(board, {}, {}, scale=2)
    assert (two.width(), two.height()) == free_grid_output_size(board, 2)
    assert two.width() == image.width() * 2
    assert two.height() == image.height() * 2


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
    set_layout(board, "grid_4x3")
    image = compose_board(board, {}, {}, scale=1)
    assert (image.width(), image.height()) == output_size(1, "grid_4x3")


def test_free_grid_short_board_export_crops_trailing_whitespace(qapp):
    board = default_board()
    add_ref(board, make_ref("time", "short"))
    template_to_free_grid(board)
    image = compose_board(board, {}, {}, scale=1)
    assert image.height() < 900
    assert image.width() < 1600
    untitled = compose_board(board, {}, {}, scale=1, title=False)
    assert untitled.height() < image.height()


def test_pathological_free_grid_2x_export_is_rejected(qapp):
    board = default_board()
    add_ref(board, make_ref("time", "anchor"))
    add_ref(board, make_ref("fft", "deep"))
    template_to_free_grid(board)
    assert set_free_grid_rect(board, make_ref("time", "anchor"), GridRect(0, 0, 4, 3)) == []
    assert set_free_grid_rect(board, make_ref("fft", "deep"), GridRect(0, 40, 4, 8)) == []
    width, height = free_grid_output_size(board, 2)
    assert width > MAX_EXPORT_EDGE or height > MAX_EXPORT_EDGE or width * height > MAX_EXPORT_PIXELS
    one = compose_board(board, {}, {}, scale=1)
    assert one.width() < 1600
    assert one.height() > 900
    try:
        compose_board(board, {}, {}, scale=2)
        raise AssertionError("2× tall content-union export should be rejected")
    except ComposeError as exc:
        assert exc.code == "export_too_large"
        assert exc.message == format_export_too_large(width, height)
        assert "改用 1× 或整理卡片" in exc.message
        assert str(MAX_EXPORT_EDGE) not in exc.message
        assert str(MAX_EXPORT_PIXELS) not in exc.message


def test_free_grid_export_crops_to_content_like_autofit(qapp):
    """A left-packed 2×2 must fill the PNG; the empty 12-column floor is omitted."""
    board = default_board()
    board.name = "全局对比"
    refs_and_rects = (
        (make_ref("time", "v1"), GridRect(0, 0, 4, 3)),
        (make_ref("fft", "v2"), GridRect(4, 0, 4, 3)),
        (make_ref("order", "v3"), GridRect(0, 3, 4, 3)),
        (make_ref("frf", "v4"), GridRect(4, 3, 4, 3)),
    )
    for ref, rect in refs_and_rects:
        add_ref(board, ref)
        assert set_free_grid_rect(board, ref, rect) == []
    one = compose_board(board, {}, {}, scale=1)
    two = compose_board(board, {}, {}, scale=2)
    metrics = export_grid_metrics(board.free_grid)
    expected_w = (
        2 * metrics.padding
        + 8 * metrics.column_width
        + 7 * metrics.gutter
    )
    expected_h = (
        TITLE_BAND
        + 2 * metrics.padding
        + 6 * metrics.row_height
        + 5 * metrics.gutter
    )
    assert (one.width(), one.height()) == (expected_w, expected_h)
    assert one.width() < 1600
    assert (two.width(), two.height()) == (expected_w * 2, expected_h * 2)
    rects = composed_slot_rects(board, scale=1, title=True)
    left = min(slot[0] for slot in rects.values())
    right = max(slot[0] + slot[2] for slot in rects.values())
    top = min(slot[1] for slot in rects.values())
    bottom = max(slot[1] + slot[3] for slot in rects.values())
    assert left == metrics.padding
    assert right == one.width() - metrics.padding
    assert top == TITLE_BAND + metrics.padding
    assert bottom == one.height() - metrics.padding
    assert BOARD_PADDING == metrics.padding


def test_free_grid_export_keeps_gaps_between_cards(qapp):
    """Fit-to-content crops the outer floor, not the empty cells inside the union."""
    board = default_board()
    left = make_ref("time", "left")
    right = make_ref("fft", "right")
    add_ref(board, left)
    add_ref(board, right)
    assert set_free_grid_rect(board, left, GridRect(0, 0, 4, 3)) == []
    assert set_free_grid_rect(board, right, GridRect(8, 0, 4, 3)) == []
    image = compose_board(board, {}, {}, scale=1, title=False)
    metrics = export_grid_metrics(board.free_grid)
    assert image.width() == (
        2 * metrics.padding
        + GRID_COLUMNS * metrics.column_width
        + (GRID_COLUMNS - 1) * metrics.gutter
    )
    rects = composed_slot_rects(board, scale=1, title=False)
    left_slot = rects[f"grid:{left.section}:{left.view_id}"]
    right_slot = rects[f"grid:{right.section}:{right.view_id}"]
    gap = right_slot[0] - (left_slot[0] + left_slot[2])
    assert gap == 4 * metrics.column_width + 5 * metrics.gutter


def test_base_frame_export_pixel_positions_stay_on_1600_pitch(qapp):
    board = default_board()
    left = make_ref("time", "left")
    right = make_ref("fft", "right")
    add_ref(board, left)
    add_ref(board, right)
    template_to_free_grid(board)
    assert set_free_grid_rect(board, left, GridRect(0, 0, 4, 3)) == []
    assert set_free_grid_rect(board, right, GridRect(8, 0, 4, 3)) == []
    metrics = export_grid_metrics(board.free_grid)
    assert metrics.board_width == 1600
    expected = {}
    for ref, rect in ((left, GridRect(0, 0, 4, 3)), (right, GridRect(8, 0, 4, 3))):
        x, y, width, height = rect_to_pixels(rect, metrics)
        expected[f"grid:{ref.section}:{ref.view_id}"] = (
            x,
            y + TITLE_BAND,
            width,
            height,
        )
    assert composed_slot_rects(board, scale=1, title=True) == expected
    image = compose_board(board, {}, {}, scale=1)
    assert (image.width(), image.height()) == free_grid_output_size(board, 1)
    assert image.width() == (
        2 * metrics.padding
        + GRID_COLUMNS * metrics.column_width
        + (GRID_COLUMNS - 1) * metrics.gutter
    )
    assert [item.rect for item in board.free_grid] == [
        GridRect(0, 0, 4, 3),
        GridRect(8, 0, 4, 3),
    ]


def test_negative_column_card_is_present_in_export(qapp):
    board = default_board()
    ref = make_ref("time", "signed")
    add_ref(board, ref)
    template_to_free_grid(board)
    placed = GridRect(-4, 0, 4, 3)
    assert set_free_grid_rect(board, ref, placed) == []
    store = PreviewStore()
    store.publish(ref, _image(48, 32, color="#cc1122"), digest="n", meta=_meta(ref))
    image = compose_board(board, {ref: store.get(ref)}, {ref: "fresh"}, scale=1)
    assert image.width() < 1600
    metrics = export_grid_metrics(board.free_grid)
    slot = composed_slot_rects(board, scale=1, title=True)[f"grid:{ref.section}:{ref.view_id}"]
    assert slot[0] == metrics.padding
    assert slot[0] + slot[2] == image.width() - metrics.padding
    ink = 0
    bg = BOARD_BG.rgb()
    for y in range(slot[1], slot[1] + slot[3]):
        for x in range(slot[0], slot[0] + slot[2]):
            if image.pixel(x, y) != bg:
                ink += 1
    assert ink > 0
    assert board.free_grid[0].rect == placed


def test_compositor_does_not_import_halo_or_session_extent():
    source = _COMPOSITOR.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            for alias in node.names:
                imported.append(alias.name)
    assert "content_bounds" in imported
    assert "desired_extent" not in imported
    assert "expand_extent" not in imported
    assert "HALO_MIN_CELLS" not in imported
    assert "edge_pan_velocity" not in imported


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
    assert uv._on_free_grid_group_geometry in slots
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


def test_free_grid_undo_keeps_history_when_membership_changes(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    add_ref(uv.board, time_ref)
    uv._on_free_grid_toggled(True)
    before = uv.board.free_grid[0].rect
    uv._on_free_grid_geometry(time_ref.section, time_ref.view_id, 0, 6, 4, 3, "test")
    history = uv._grid_histories[uv.board.board_id]
    assert history.undo
    add_ref(uv.board, fft_ref)
    uv._after_board_mutation()
    uv._on_free_grid_undo()
    assert uv.board.free_grid[0].rect == before
    assert history.redo
    assert not any("撤销记录已清除" in msg for msg, _ in toasts)


def test_free_grid_group_geometry_is_one_undo_entry(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    add_ref(uv.board, time_ref)
    add_ref(uv.board, fft_ref)
    uv._on_free_grid_toggled(True)
    first = uv.board.free_grid[0]
    second = uv.board.free_grid[1]
    first_before = first.rect
    second_before = second.rect
    uv._on_free_grid_group_geometry(
        (
            (
                first.ref.section,
                first.ref.view_id,
                first.rect.column,
                first.rect.row + 1,
                first.rect.column_span,
                first.rect.row_span,
            ),
            (
                second.ref.section,
                second.ref.view_id,
                second.rect.column,
                second.rect.row + 1,
                second.rect.column_span,
                second.rect.row_span,
            ),
        )
    )
    assert uv.board.free_grid[0].rect.row == first_before.row + 1
    assert uv.board.free_grid[1].rect.row == second_before.row + 1
    history = uv._grid_histories[uv.board.board_id]
    assert len(history.undo) == 1
    uv._on_free_grid_undo()
    assert uv.board.free_grid[0].rect == first_before
    assert uv.board.free_grid[1].rect == second_before
    assert len(history.redo) == 1


def test_layout_expand_and_shrink_toast_both_directions(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    board = uv.board
    set_layout(board, "grid_2x2")
    for index in range(12):
        add_ref(board, make_ref("time", f"v{index}"))
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    uv._on_layout("grid_4x3")
    assert ("已从托盘补位 8 张", "info") in toasts
    toasts.clear()
    uv._on_layout("grid_2x2")
    assert ("8 张已移入未放置", "info") in toasts


def test_export_too_large_toasts_dimensions_and_limits(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    toasts = []
    monkeypatch.setattr(win, "toast", lambda msg, level="info": toasts.append((msg, level)))
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    add_ref(uv.board, ref)
    uv._on_free_grid_toggled(True)
    extra = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    add_ref(uv.board, extra)
    assert set_free_grid_rect(uv.board, ref, GridRect(0, 0, 4, 3)) == []
    assert set_free_grid_rect(uv.board, extra, GridRect(0, 40, 4, 8)) == []
    assert uv._compose_or_toast(scale=2, action="导出 PNG") is None
    assert toasts
    message, level = toasts[-1]
    assert level == "warning"
    width, height = free_grid_output_size(uv.board, 2)
    assert format_export_too_large(width, height) in message
    assert "改用 1× 或整理卡片" in message
    assert str(MAX_EXPORT_EDGE) not in message
    assert str(MAX_EXPORT_PIXELS) not in message

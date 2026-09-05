"""``BatchPreviewDialog`` 警告条测试。

``preview_group`` 把渲染层收集到的 ``BatchPreviewResult.warnings`` 传进对话框，
但旧版 ``set_result`` 只画文件名/来源数，warnings 被悄悄吞掉——切片位置越界被
夹取这类提示用户完全看不到。这里锁定：有 warnings 时可见且已去掉机器前缀、
无 warnings 时整块隐藏、以及每一轮新生成开始（loading/cancelled）都要清空
上一轮留下的警告。
"""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.batch_types import BatchPreviewResult
from mf4_analyzer.ui.drawers.batch.preview_dialog import BatchPreviewDialog
from mf4_analyzer.ui_kit.dialog_geometry import IntRect
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet


def _make_dialog(qtbot):
    dialog = BatchPreviewDialog(None)
    qtbot.addWidget(dialog)
    return dialog


def _patch_available(monkeypatch, width: int, height: int) -> None:
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, width, height),
    )


def _pump() -> None:
    app = QApplication.instance()
    if app is None:
        return
    app.processEvents()
    app.processEvents()


def _warning_list(count: int) -> tuple[str, ...]:
    return tuple(
        f"slice.position_clamped: 警告 {index} 切片位置 {index}.000 s "
        f"超出数据范围，已取 {index}.000 s"
        for index in range(count)
    )


def _result(*, warnings=(), image_path=__file__, message: str = "") -> BatchPreviewResult:
    return BatchPreviewResult(
        image_path=image_path,
        group_id="g1",
        display_name="方向盘扭矩",
        loaded_source_count=2,
        warnings=warnings,
        status="done",
        message=message,
    )


def _visible_footer_buttons(dialog):
    buttons = (
        dialog._btn_back,
        dialog._btn_regenerate,
        dialog._btn_run_all,
        dialog._btn_cancel,
    )
    return tuple(button for button in buttons if not button.isHidden())


def _assert_footer_inside_work_area(dialog, work_w: int, work_h: int) -> None:
    frame = dialog.frameGeometry()
    work = QRect(0, 0, work_w, work_h)
    assert work.contains(frame), (frame, work)
    dialog_rect = QRect(dialog.mapToGlobal(QPoint(0, 0)), dialog.size())
    for button in _visible_footer_buttons(dialog):
        assert button.isVisible()
        top_left = button.mapToGlobal(QPoint(0, 0))
        bottom_right = button.mapToGlobal(
            QPoint(max(0, button.width() - 1), max(0, button.height() - 1))
        )
        assert frame.contains(top_left), (button.text(), top_left, frame)
        assert frame.contains(bottom_right), (button.text(), bottom_right, frame)
        assert dialog_rect.contains(top_left), (button.text(), top_left, dialog_rect)
        assert dialog_rect.contains(bottom_right), (button.text(), bottom_right, dialog_rect)
        assert work.contains(top_left), (button.text(), top_left, work)
        assert work.contains(bottom_right), (button.text(), bottom_right, work)
        assert not dialog._body_scroll.isAncestorOf(button)
        assert not dialog._scroll.isAncestorOf(button)


def test_set_result_shows_humanized_warnings(qtbot):
    dialog = _make_dialog(qtbot)
    result = BatchPreviewResult(
        image_path=__file__,  # 任意存在的文件即可，仅用于让 image_path 非空
        group_id="g1",
        display_name="方向盘扭矩",
        loaded_source_count=2,
        warnings=(
            "slice.position_clamped: 切片位置 2.000 s 超出数据范围 "
            "[5.865, 43.418] s，已取 5.865 s；2 个位置夹取后合并为 1 个",
        ),
        status="done",
    )
    dialog.set_result(result)

    assert not dialog._warnings.isHidden()
    text = dialog._warnings.text()
    assert "slice.position_clamped" not in text
    assert "切片位置 2.000 s 超出数据范围" in text
    assert "已取 5.865 s" in text


def test_set_result_hides_warnings_block_when_empty(qtbot):
    dialog = _make_dialog(qtbot)
    result = BatchPreviewResult(
        image_path=__file__,
        group_id="g1",
        display_name="方向盘扭矩",
        loaded_source_count=1,
        warnings=(),
        status="done",
    )
    dialog.set_result(result)

    assert dialog._warnings.isHidden()
    assert dialog._warnings.text() == ""


def test_set_result_dedupes_warnings_preserving_order(qtbot):
    dialog = _make_dialog(qtbot)
    result = BatchPreviewResult(
        image_path=__file__,
        group_id="g1",
        display_name="电机转速",
        loaded_source_count=3,
        warnings=(
            "slice.csv_fallback: 切片工作簿需要 xlsx 格式，当前数据格式为 CSV，"
            "本次数据文件仍为完整长表",
            "slice.csv_fallback: 切片工作簿需要 xlsx 格式，当前数据格式为 CSV，"
            "本次数据文件仍为完整长表",
            "slice.position_clamped: 切片位置 2.000 s 超出数据范围 "
            "[5.865, 43.418] s，已取 5.865 s",
        ),
        status="done",
    )
    dialog.set_result(result)

    lines = dialog._warnings.text().split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("• 切片工作簿需要 xlsx 格式")
    assert lines[1].startswith("• 切片位置 2.000 s 超出数据范围")


def test_new_generation_clears_previous_warnings(qtbot):
    dialog = _make_dialog(qtbot)
    result = BatchPreviewResult(
        image_path=__file__,
        group_id="g1",
        display_name="电机扭矩",
        loaded_source_count=1,
        warnings=("slice.position_clamped: 切片位置越界，已夹取",),
        status="done",
    )
    dialog.set_result(result)
    assert not dialog._warnings.isHidden()

    # 重新生成：loading 态先清空旧警告，不能等新结果回来才清。
    dialog.set_loading("电机扭矩 · 代表输出 1 / 1 · 将读取 1 个来源")
    assert dialog._warnings.isHidden()
    assert dialog._warnings.text() == ""

    # 取消同理，不留上一轮的警告。
    dialog.set_result(result)
    assert not dialog._warnings.isHidden()
    dialog.set_cancelled()
    assert dialog._warnings.isHidden()
    assert dialog._warnings.text() == ""


def test_set_result_without_image_still_reports_warnings(qtbot):
    """哪怕这次没能生成图片（比如组失效），已有的警告仍然值得展示。"""
    dialog = _make_dialog(qtbot)
    result = BatchPreviewResult(
        image_path=None,
        group_id="g1",
        display_name="",
        loaded_source_count=0,
        warnings=("slice.position_clamped: 切片位置越界，已夹取",),
        message="代表输出组已失效",
    )
    dialog.set_result(result)

    assert not dialog._warnings.isHidden()
    assert "切片位置越界，已夹取" in dialog._warnings.text()
    assert dialog._status.text() == "代表输出组已失效"


@pytest.mark.parametrize("warning_count", [0, 1, 30, 100])
@pytest.mark.parametrize("work", [(800, 600), (640, 360)])
def test_footer_stays_inside_injected_work_area(qtbot, monkeypatch, warning_count, work):
    work_w, work_h = work
    _patch_available(monkeypatch, work_w, work_h)
    dialog = _make_dialog(qtbot)
    warnings = _warning_list(warning_count)
    dialog.set_result(_result(warnings=warnings))
    dialog.show()
    qtbot.waitExposed(dialog)
    _pump()

    if warning_count:
        text = dialog._warnings.text()
        assert "slice.position_clamped" not in text
        assert f"警告 0 切片位置 0.000 s" in text
        assert f"警告 {warning_count - 1} 切片位置 {warning_count - 1}.000 s" in text
        assert text.count("\n") + 1 == warning_count
    else:
        assert dialog._warnings.isHidden()

    _assert_footer_inside_work_area(dialog, work_w, work_h)

    clicked = []

    def _count_run_all():
        clicked.append(True)

    dialog.run_all_requested.connect(_count_run_all)
    button = dialog._btn_run_all
    qtbot.mouseClick(button, Qt.LeftButton)
    assert clicked, (button.mapTo(dialog, button.rect().center()), dialog.rect())


def test_zero_to_hundred_to_zero_releases_old_minimum(qtbot, monkeypatch):
    _patch_available(monkeypatch, 800, 600)
    dialog = _make_dialog(qtbot)
    dialog.set_result(_result(warnings=()))
    dialog.show()
    qtbot.waitExposed(dialog)
    _pump()

    dialog.set_result(_result(warnings=_warning_list(100)))
    _pump()
    warnings_hint = dialog._warnings.sizeHint().height()
    min_at_100 = dialog.minimumHeight()
    hint_at_100 = dialog.minimumSizeHint().height()
    assert warnings_hint > 600
    _assert_footer_inside_work_area(dialog, 800, 600)

    dialog.set_result(_result(warnings=()))
    _pump()
    assert dialog._warnings.isHidden()
    assert dialog.minimumHeight() <= min_at_100
    assert dialog.minimumHeight() < warnings_hint
    assert dialog.minimumSizeHint().height() < warnings_hint
    assert dialog.minimumSizeHint().height() <= hint_at_100
    _assert_footer_inside_work_area(dialog, 800, 600)

    dialog.resize(dialog.width(), 420)
    _pump()
    assert dialog.height() <= 420
    assert dialog.height() < warnings_hint
    assert dialog.minimumHeight() < warnings_hint


def test_image_keeps_aspect_ratio_when_warnings_are_long(qtbot, monkeypatch):
    _patch_available(monkeypatch, 800, 600)
    dialog = _make_dialog(qtbot)
    dialog.set_result(_result(warnings=_warning_list(30), image_path=__file__))
    source = QPixmap(160, 80)
    source.fill(QColor("#1769e0"))
    dialog._source_pixmap = source
    dialog.show()
    qtbot.waitExposed(dialog)
    _pump()
    dialog._fit_image()
    shown = dialog._image.pixmap()
    assert shown is not None and not shown.isNull()
    assert abs(shown.width() / max(1, shown.height()) - 2.0) < 0.08
    _assert_footer_inside_work_area(dialog, 800, 600)


def test_production_qss_keeps_footer_visible(qtbot, qapp, monkeypatch):
    _patch_available(monkeypatch, 800, 600)
    old_stylesheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        dialog = _make_dialog(qtbot)
        dialog.set_result(_result(warnings=_warning_list(30)))
        dialog.show()
        qtbot.waitExposed(dialog)
        _pump()
        grabbed = dialog.grab()
        assert not grabbed.isNull()
        assert grabbed.height() == dialog.height()
        button = dialog._btn_run_all
        assert button.isVisible()
        top_left = button.mapTo(dialog, QPoint(0, 0))
        bottom_right = button.mapTo(
            dialog, QPoint(max(0, button.width() - 1), max(0, button.height() - 1)),
        )
        assert dialog.rect().contains(top_left)
        assert dialog.rect().contains(bottom_right)
        _assert_footer_inside_work_area(dialog, 800, 600)
    finally:
        qapp.setStyleSheet(old_stylesheet)

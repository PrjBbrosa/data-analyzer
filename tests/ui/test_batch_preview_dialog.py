"""``BatchPreviewDialog`` 警告条测试。

``preview_group`` 把渲染层收集到的 ``BatchPreviewResult.warnings`` 传进对话框，
但旧版 ``set_result`` 只画文件名/来源数，warnings 被悄悄吞掉——切片位置越界被
夹取这类提示用户完全看不到。这里锁定：有 warnings 时可见且已去掉机器前缀、
无 warnings 时整块隐藏、以及每一轮新生成开始（loading/cancelled）都要清空
上一轮留下的警告。
"""
from __future__ import annotations

from mf4_analyzer.batch_types import BatchPreviewResult
from mf4_analyzer.ui.drawers.batch.preview_dialog import BatchPreviewDialog


def _make_dialog(qtbot):
    dialog = BatchPreviewDialog(None)
    qtbot.addWidget(dialog)
    return dialog


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

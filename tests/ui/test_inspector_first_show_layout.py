"""Inspector 分区页首开时的表单行几何回归。

首次显示某个分析分区（页 widget 一直躺在隐藏的 QStackedWidget 里）时，
show / QSS polish / 布局在同一趟里交错：上层分配高度的预算取自
polish 前的 sizeHint 链，比 polish 后的真实需求少十几像素；QFormLayout
在总高不足时把行压到 sizeHint 以下，而 `_fit_field` 的字段控件是
Fixed 垂直策略，坚持按自身 sizeHint 渲染，于是溢出行槽、吃掉 4px
行距（修复前 offscreen 实测 host=30 vs field=32、worst gap=1）。

Qt 的 QSS polish 不触发 updateGeometry，所以这个亏空不会自愈——修复
是 Inspector.set_mode 对首次显示的页排一趟 singleShot(0) 二次布局。
本测试锁住修复后的稳定帧：字段外层 host 至少给足字段 sizeHint，
相邻行间隙不小于表单 verticalSpacing。
"""
import pytest
from PyQt5.QtWidgets import QFormLayout, QMainWindow

from mf4_analyzer.ui.inspector import Inspector


FRF_FIELD_ROWS = (
    "choice_estimator",
    "combo_window",
    "spin_t_win",
    "spin_overlap",
    "choice_nfft_mode",
    "spin_nfft",
)


@pytest.fixture
def shown_inspector(qtbot, qapp):
    # 复现产品启动路径：Fusion + 真实 QSS 先装到 app,再构建 Inspector。
    # 首开压缩 bug 的机制正是「首次 show 时 QSS polish 与布局交错」——
    # 无样式的裸 qapp 复现的是另一个度量环境。conftest 的
    # ``_isolate_app_style`` 会在测试后自动还原 app 样式。
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    win = QMainWindow()
    qtbot.addWidget(win)
    inspector = Inspector(win)
    win.setCentralWidget(inspector)
    win.resize(320, 900)
    win.show()
    qtbot.waitExposed(win)
    # 返回二元组以保住 window 的 Python 引用；只返回 inspector 会让
    # QMainWindow 被 GC，连带删除全部子控件。
    return win, inspector


def _compute_form_spacing(ctx, field_host):
    for form in ctx.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.FieldRole)
            if item is not None and item.widget() is field_host:
                return form.verticalSpacing()
    raise AssertionError("field host not found in any QFormLayout")


def test_frf_first_open_rows_keep_breathing_gaps(shown_inspector, qtbot):
    _win, inspector = shown_inspector
    inspector.set_mode("frf")
    # 修复采用 singleShot(0) 二次布局：首帧允许仍是压缩帧，验收的是
    # 事件循环转完之后用户实际看到的稳定帧。
    qtbot.wait(50)

    ctx = inspector.frf_ctx
    prev_bottom = None
    spacing = _compute_form_spacing(
        ctx, getattr(ctx, FRF_FIELD_ROWS[0]).parentWidget()
    )
    assert spacing >= 4  # _configure_form 的紧凑节奏约定

    for name in FRF_FIELD_ROWS:
        field = getattr(ctx, name)
        host = field.parentWidget()
        assert host.height() >= field.sizeHint().height(), (
            f"{name}: row host {host.height()}px starves the Fixed-height "
            f"field ({field.sizeHint().height()}px) — first-show budget was "
            "taken from the pre-polish hint chain"
        )
        top = field.mapTo(ctx, field.rect().topLeft()).y()
        if prev_bottom is not None:
            gap = top - prev_bottom
            assert gap >= spacing, (
                f"{name}: gap above is {gap}px, expected >= form "
                f"verticalSpacing {spacing}px — fields are overflowing "
                "their starved rows into the breathing gap"
            )
        prev_bottom = top + field.height()


def test_frf_reentry_stays_settled(shown_inspector, qtbot):
    """切走再切回（历史上的治愈路径）不得比首开验收更差。"""
    _win, inspector = shown_inspector
    inspector.set_mode("frf")
    qtbot.wait(50)
    inspector.set_mode("fft")
    qtbot.wait(50)
    inspector.set_mode("frf")
    qtbot.wait(50)

    ctx = inspector.frf_ctx
    prev_bottom = None
    for name in FRF_FIELD_ROWS:
        field = getattr(ctx, name)
        assert field.parentWidget().height() >= field.sizeHint().height()
        top = field.mapTo(ctx, field.rect().topLeft()).y()
        if prev_bottom is not None:
            assert top - prev_bottom >= 4
        prev_bottom = top + field.height()

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


def _assert_uniform_filter_editor_gaps(panel, editors):
    spacing = panel._form.verticalSpacing()
    gaps = []
    prev_bottom = None
    for editor in editors:
        host = editor.parentWidget()
        assert host.height() >= editor.sizeHint().height(), (
            f"{editor.objectName() or type(editor).__name__}: row host "
            f"{host.height()}px starves the Fixed-height field "
            f"({editor.sizeHint().height()}px)"
        )
        top = editor.mapTo(panel, editor.rect().topLeft()).y()
        if prev_bottom is not None:
            gap = top - prev_bottom
            assert gap >= spacing, (
                f"filter editor gap is {gap}px, expected >= form "
                f"verticalSpacing {spacing}px"
            )
            gaps.append(gap)
        prev_bottom = top + editor.height()
    assert gaps, "expected at least two visible filter editors"
    assert len(set(gaps)) == 1, (
        f"filter row gaps should match across kinds, got {gaps}"
    )


def test_time_filter_rows_keep_inspector_form_gaps(shown_inspector, qtbot):
    """滤波 类型/截止/阶数 must keep the same ``_configure_form`` gaps as
    横坐标 / 时间范围, not collapse into overlapping field borders."""
    _win, inspector = shown_inspector
    inspector.set_mode("time")
    qtbot.wait(50)

    panel = inspector.filter_panel
    form = panel._form
    assert form.horizontalSpacing() == 6
    assert form.verticalSpacing() == 4
    _assert_uniform_filter_editor_gaps(
        panel, (panel.combo_kind, panel.spin_cut, panel.combo_order),
    )


def test_time_filter_row_gaps_stay_uniform_for_every_kind(shown_inspector, qtbot):
    """低通/高通 hide the band editors; 带通/带阻 swap them in the same slot."""
    _win, inspector = shown_inspector
    inspector.set_mode("time")
    qtbot.wait(50)
    panel = inspector.filter_panel
    panel.set_enabled(True)
    qtbot.wait(20)
    for kind in ("低通", "高通", "带通", "带阻"):
        panel.set_kind(kind)
        qtbot.wait(20)
        if kind in ("带通", "带阻"):
            editors = (panel.combo_kind, panel.spin_lo, panel.combo_order)
        else:
            editors = (panel.combo_kind, panel.spin_cut, panel.combo_order)
        _assert_uniform_filter_editor_gaps(panel, editors)


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


def test_switching_to_shorter_page_drops_dead_white(shown_inspector, qtbot):
    """E4: contextual_stack sizeHint follows the current page, not the tallest.

    FRF is much taller than FFT. Without a current-page sizeHint override the
    stack keeps FRF's height after switching to FFT, leaving dead white under
    the short page. ``_settle_page`` (first-show polish heal) does not address
    this direction — both must coexist.
    """
    _win, inspector = shown_inspector
    stack = inspector.contextual_stack

    inspector.set_mode("frf")
    qtbot.wait(50)
    tall_hint = stack.sizeHint().height()
    tall_page = inspector.frf_ctx.sizeHint().height()
    assert tall_hint == tall_page

    inspector.set_mode("fft")
    qtbot.wait(50)
    short_hint = stack.sizeHint().height()
    short_page = inspector.fft_ctx.sizeHint().height()
    assert short_hint == short_page
    assert short_hint < tall_hint, (
        f"stack hint stayed tall after leaving FRF: "
        f"fft={short_hint} frf={tall_hint}"
    )

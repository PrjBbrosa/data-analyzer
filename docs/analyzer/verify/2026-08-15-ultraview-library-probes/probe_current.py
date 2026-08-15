"""UltraView View 库几何探针 —— 复现 library-geometry-and-material plan §1 的实测表。

用途：在**改动前**跑一次，与 plan §1 的数字对账；改动后再跑一次，四组输出应分别变成
plan §3.2 / §5 描述的形态。offscreen 只测排版结构，不作视觉验收（见 CLAUDE.md Gotchas）。

    TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
      .venv/bin/python docs/analyzer/verify/2026-08-15-ultraview-library-probes/probe_current.py

基线读数（main@380e5ac2，本机 Darwin 27.0.0 / Fusion / offscreen）见同目录 baseline.txt。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from PyQt5.QtCore import QSize  # noqa: E402
from PyQt5.QtWidgets import QApplication, QSizePolicy  # noqa: E402


LONG_META = "Rte_TAS_mTorsionBarTorque_xds16, Rte_TLC_mSumLimMotorTorque_xds16"


def _rows(library_row):
    """4 个时域 View + 其余四类各 1 个，复刻用户截图里的 8 个 View。"""
    rows = [
        library_row(
            section="time",
            view_id=f"t{index}",
            name=f"View {index + 1}",
            tab_color="#3B82F6",
            source_summary=LONG_META,
        )
        for index in range(4)
    ]
    rows += [
        library_row(
            section=section,
            view_id="v",
            name="View 1",
            tab_color="#3B82F6",
            source_summary="EPS_1_CRC",
        )
        for section in ("fft", "fft_time", "frf", "order")
    ]
    return rows


def _panel(widgets):
    panel = widgets.ViewLibraryPanel()
    panel.set_rows(_rows(widgets.LibraryRow))
    panel.resize(widgets.LIBRARY_DEFAULT_WIDTH, 560)
    panel.show()
    QApplication.instance().processEvents()
    return panel


def probe_overlay_jump(widgets) -> None:
    """§1.1 —— 面板 rect 随内容变化而跳。"""
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import PANEL_LIBRARY
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
    from mf4_analyzer.ui.ultraview_state import default_board

    app = QApplication.instance()
    page = UltraViewPage()
    page.resize(1280, 800)
    page.show()
    app.processEvents()
    page.set_board(default_board())
    page.set_library_rows(_rows(widgets.LibraryRow))
    app.processEvents()
    library = page.library_panel()
    page.tool_rail().panel_button(PANEL_LIBRARY).click()
    app.processEvents()

    print("§1.1 面板 rect 随内容变化（每步后显式 _apply_floating_layout）")

    def report(tag: str) -> None:
        page._apply_floating_layout()
        app.processEvents()
        rect = library.geometry()
        print(
            f"    {tag:22s} rect=({rect.x()},{rect.y()},{rect.width()},{rect.height()})"
            f"  sizeHint.h={library.sizeHint().height()}"
        )

    report("打开（展开态）")
    library._on_compact_mode_clicked()
    report("切概览")
    library._on_groups_mode_clicked()
    report("切回展开")
    library.section_headers()["time"].click()
    report("折叠时域")
    library.section_headers()["time"].click()
    report("展开时域")
    library.search_field().setText("View 1")
    app.processEvents()
    report("搜索 View 1")
    library.search_field().setText("")
    app.processEvents()
    report("清空搜索")
    page.deleteLater()


def probe_section_clipping(widgets) -> None:
    """§1.2 + §2/R3 —— 分组卡被压到自身最小高度以下。"""
    panel = _panel(widgets)
    print("\n§1.2 分组卡实渲高 vs 自身 minimumSizeHint")
    for section, frame in panel.section_widgets().items():
        actual = frame.height()
        minimum = frame.minimumSizeHint().height()
        verdict = "OK" if actual >= minimum else f"CLIPPED (-{minimum - actual})"
        print(f"    {section:9s} h={actual:4d}  minHint={minimum:4d}  {verdict}")
    print("\n§2/R3 手写公式 vs 布局自算")
    print(f"    _measured_body_height()         = {panel._measured_body_height()}")
    print(f"    _body_layout.totalMinimumSize() = {panel._body_layout.totalMinimumSize().height()}")
    print(f"    _body.sizeHint()                = {panel._body.sizeHint().height()}")
    panel.deleteLater()


def probe_catalog_balloon(widgets) -> None:
    """§1.3 + §2/R4 —— 概览卡被均分掉剩余高度。"""
    panel = _panel(widgets)
    panel._on_compact_mode_clicked()
    QApplication.instance().processEvents()
    cards = panel.catalog_cards()
    heights = [card.height() for card in cards.values()]
    hint = next(iter(cards.values())).sizeHint().height()
    print("\n§1.3 概览卡实渲高 vs sizeHint")
    print(f"    实渲 = {heights}")
    print(f"    hint = {hint}")
    panel.deleteLater()


def probe_inner_metrics(widgets) -> None:
    """§1.4 —— 与 HTML 原型对不上的内部度量。"""
    panel = _panel(widgets)
    row = panel.row_widgets()[0]
    header = panel.section_headers()["time"]
    print("\n§1.4 内部度量")
    print(f"    行外框            = {row.height()}          (HTML 单行 38 / 本 plan 目标 46)")
    print(f"    圆点左内缩        = {row._dot.geometry().x()}           (HTML 15)")
    print(f"    ＋/− 按钮         = {row._add.width()}x{row._add.height()}        (HTML 23x23)")
    print(f"    分组头外框        = {header.height()}          (HTML 32)")
    print(f"    搜索框外框        = {panel._search.height()}          (HTML 35)")
    groups = panel._mode_groups.geometry()
    compact = panel._mode_compact.geometry()
    print(
        f"    展开/概览 tab      = {groups.width()} @x{groups.x()} / {compact.width()} @x{compact.x()}"
        f"   (HTML flex:1 → 各占半宽)"
    )
    print(f"    竖滚动条宽        = {panel._scroll.verticalScrollBar().sizeHint().width()}"
          f"           (现落在分组卡右边框上)")
    panel.deleteLater()


def probe_fix_mechanics(widgets) -> None:
    """§5 Task 1-4 的三条修法在离屏上的效果，证明 plan 不是纸上谈兵。"""
    app = QApplication.instance()
    print("\n§5 修法验证（离屏）")

    panel = _panel(widgets)
    panel._body.setMinimumHeight(panel._body_layout.totalMinimumSize().height())
    app.processEvents()
    ok = all(
        frame.height() >= frame.minimumSizeHint().height()
        for frame in panel.section_widgets().values()
    )
    print(f"    Task 2 布局自算最小高 → 分组卡不再被裁: {ok}")

    panel._on_compact_mode_clicked()
    app.processEvents()
    before = [card.height() for card in panel.catalog_cards().values()]
    panel._body_layout.addStretch(1)
    panel._body.setMinimumHeight(panel._body_layout.totalMinimumSize().height())
    app.processEvents()
    after = [card.height() for card in panel.catalog_cards().values()]
    print(f"    Task 3 尾部 stretch  → 概览卡 {before} → {after}")

    before_tabs = (panel._mode_groups.width(), panel._mode_compact.width())
    for button in (panel._mode_groups, panel._mode_compact):
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    app.processEvents()
    after_tabs = (panel._mode_groups.width(), panel._mode_compact.width())
    print(f"    Task 4 Expanding    → tab 宽 {before_tabs} → {after_tabs}")
    panel.deleteLater()


def probe_constant_height(widgets) -> None:
    """§3.2 —— 把 sizeHint 换成常量后，rect 在内容变化下是否恒定。"""
    from mf4_analyzer.ui.chart_stack.ultraview.chrome import PANEL_LIBRARY
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
    from mf4_analyzer.ui.ultraview_state import default_board

    app = QApplication.instance()
    constant = 560
    original_hint = widgets.ViewLibraryPanel.sizeHint
    original_min = widgets.ViewLibraryPanel.minimumSizeHint
    widgets.ViewLibraryPanel.sizeHint = lambda self: QSize(widgets.LIBRARY_DEFAULT_WIDTH, constant)
    widgets.ViewLibraryPanel.minimumSizeHint = lambda self: QSize(280, 360)
    try:
        page = UltraViewPage()
        page.resize(1280, 800)
        page.show()
        app.processEvents()
        page.set_board(default_board())
        page.set_library_rows(_rows(widgets.LibraryRow))
        app.processEvents()
        library = page.library_panel()
        page.tool_rail().panel_button(PANEL_LIBRARY).click()
        app.processEvents()
        print(f"\n§3.2 sizeHint 换成常量 {constant} 后的 rect（跨窗口尺寸）")
        for width, height in ((1280, 800), (1280, 720), (1600, 1000), (1000, 620)):
            page.resize(width, height)
            app.processEvents()
            shots = []
            for step in ("open", "compact", "groups"):
                if step == "compact":
                    library._on_compact_mode_clicked()
                elif step == "groups":
                    library._on_groups_mode_clicked()
                page._apply_floating_layout()
                app.processEvents()
                rect = library.geometry()
                shots.append((rect.x(), rect.y(), rect.width(), rect.height()))
            stable = "恒定" if len(set(shots)) == 1 else f"仍在跳: {shots}"
            print(f"    页面 {width}x{height}: {shots[0]}  {stable}")
        page.deleteLater()
    finally:
        widgets.ViewLibraryPanel.sizeHint = original_hint
        widgets.ViewLibraryPanel.minimumSizeHint = original_min


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(app)
    from mf4_analyzer.ui.chart_stack.ultraview import widgets

    probe_overlay_jump(widgets)
    probe_section_clipping(widgets)
    probe_catalog_balloon(widgets)
    probe_inner_metrics(widgets)
    probe_fix_mechanics(widgets)
    probe_constant_height(widgets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

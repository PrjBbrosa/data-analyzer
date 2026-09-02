from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QObject, QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QHoverEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from mf4_analyzer.ui.view_state import (
    MAX_VIEWS,
    TIME_DOMAIN_MAX_VIEWS,
    ViewManager,
    ViewState,
)
from mf4_analyzer.ui.view_tabbar import (
    ViewTabBar,
    _tab_close_pixmap,
    tab_close_hit_rect,
    tab_close_visual_rect,
    tab_icon_slot_rect,
)
from mf4_analyzer.ui.widgets.view_overflow_popup import (
    PANEL_MAX_WIDTH,
    PANEL_MIN_WIDTH,
    ViewOverflowPopup,
    ViewOverflowRow,
)


def _manager_with_views(count=2, active=0):
    manager = ViewManager()
    for _ in range(count - 1):
        manager.new_view()
    if manager.active != active:
        manager.set_active(active)
    return manager


def _bar(qtbot, count=2, active=0):
    manager = _manager_with_views(count=count, active=active)
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    return manager, bar


def _tab_point(bar, idx=0):
    rect = bar.tabBar().tabRect(idx)
    return rect.center()


def test_renders_one_tab_per_view(qtbot):
    manager, bar = _bar(qtbot, count=2)

    assert bar.count() == len(manager.views)
    assert bar.tabBar().tabText(0) == "View 1"
    assert bar.tabBar().tabText(1) == "View 2"


def test_view_tabs_do_not_show_redundant_name_tooltips(qtbot):
    _manager, bar = _bar(qtbot, count=3)

    assert bar.tabBar().tabToolTip(0) == ""
    assert bar.tabBar().tabToolTip(1) == ""
    assert bar.tabBar().tabToolTip(2) == ""


def test_switching_other_tab_emits_switch_requested(qtbot):
    _manager, bar = _bar(qtbot, count=2, active=0)

    with qtbot.waitSignal(bar.switch_requested, timeout=100) as blocker:
        bar.tabBar().setCurrentIndex(1)

    assert blocker.args == [1]


def test_plus_button_emits_new_requested(qtbot):
    _manager, bar = _bar(qtbot, count=2)

    with qtbot.waitSignal(bar.new_requested, timeout=100):
        bar._on_plus_clicked()


def test_initial_management_entry_and_plus_hug_first_tab(qtbot):
    _manager, bar = _bar(qtbot, count=1)
    bar.resize(260, 28)
    bar.show()
    QApplication.processEvents()

    first_tab = bar.tabBar().tabRect(0)
    tab_right = bar.tabBar().mapTo(bar, first_tab.topRight()).x()
    entry_gap = bar._overflow.geometry().left() - tab_right - 1
    plus_gap = bar._plus.geometry().left() - bar._overflow.geometry().right() - 1

    assert entry_gap <= 3
    assert plus_gap <= 3


def test_view_tabbar_chrome_is_shared_outside_time_domain_dock():
    """Analysis section View tabs must use the same chrome as TimeDomain.

    The production bug was QSS scoped only under ``#timeViewBottomDock``, so
    ViewTabBar instances embedded in other section rows fell back to platform
    tab styling.
    """
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    required_selectors = [
        "QWidget#viewTabBar {",
        "QWidget#viewTabBar QWidget#viewSectionAnchor {",
        "QWidget#viewTabBar QLabel#viewSectionAnchorIcon {",
        "QWidget#viewTabBar QLabel#viewSectionAnchorLabel {",
        "QWidget#viewTabBar QFrame#viewSectionAnchorRule {",
        "QWidget#viewTabBar QTabBar#viewTabs {",
        "QWidget#viewTabBar QTabBar#viewTabs::tab {",
        'QWidget#viewTabBar QTabBar#viewTabs[density="compact"]::tab {',
        "QWidget#viewTabBar QTabBar#viewTabs::tab:hover {",
        "QWidget#viewTabBar QTabBar#viewTabs::tab:selected {",
        "QWidget#viewTabBar QLineEdit#viewTabRenameEditor {",
        "QWidget#viewTabBar QPushButton#viewTabPlus {",
        "QWidget#viewTabBar QPushButton#viewTabPlus:hover {",
        "QWidget#viewTabBar QPushButton#viewTabPlus:disabled {",
        "QWidget#viewTabBar QPushButton#viewTabOverflow {",
        "QWidget#viewTabBar QPushButton#viewTabOverflow:hover {",
        "QWidget#viewTabBar QPushButton#viewSplitClear {",
    ]

    for selector in required_selectors:
        assert selector in qss


def test_views_changed_rerenders_after_manager_adds_view(qtbot):
    manager, bar = _bar(qtbot, count=2)

    manager.new_view()

    assert bar.count() == 3
    assert bar.tabBar().tabText(2) == "View 3"


def test_tab_moved_emits_reorder_requested(qtbot):
    _manager, bar = _bar(qtbot, count=2)

    with qtbot.waitSignal(bar.reorder_requested, timeout=100) as blocker:
        bar.tabBar().moveTab(0, 1)

    assert blocker.args == [0, 1]


def test_tab_moved_does_not_emit_switch_requested(qtbot):
    _manager, bar = _bar(qtbot, count=3, active=0)
    switches = []
    bar.switch_requested.connect(switches.append)

    with qtbot.waitSignal(bar.reorder_requested, timeout=100):
        bar.tabBar().moveTab(0, 2)
    QApplication.processEvents()

    assert switches == []


def test_reorder_does_not_rebuild_tabbar_midflight(qtbot):
    """Regression: dragging a tab crashed because the real-app chain
    (reorder_requested -> ViewManager.reorder -> views_changed -> refresh)
    rebuilt the QTabBar (removeTab/addTab) from inside the live tabMoved,
    freeing the tab the drag still held. refresh() must skip that rebuild while
    a reorder is in flight; the bar already reflects Qt's move."""
    manager, bar = _bar(qtbot, count=3, active=0)
    # Wire the manager exactly as MainWindow does — this is what made refresh
    # run mid-drag.
    bar.reorder_requested.connect(manager.reorder)

    removed = []
    real_remove = bar.tabBar().removeTab
    bar.tabBar().removeTab = lambda i: (removed.append(i), real_remove(i))[1]

    bar.tabBar().moveTab(0, 2)
    QApplication.processEvents()

    # The destructive rebuild was skipped while reordering...
    assert removed == []
    assert bar._reordering is False
    # ...yet the reorder still took effect and bar matches the manager.
    assert [v.name for v in manager.views] == ["View 2", "View 3", "View 1"]
    assert [bar.tabBar().tabText(i) for i in range(bar.count())] == [
        "View 2",
        "View 3",
        "View 1",
    ]


def test_active_changed_syncs_current_tab_without_switch_intent(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    switches = []
    bar.switch_requested.connect(switches.append)

    manager.set_active(1)

    assert bar.tabBar().currentIndex() == 1
    assert switches == []


def test_split_cancel_button_replaces_status_text_with_context_tooltip(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    manager.set_split(1)
    bar.show()
    QApplication.processEvents()

    assert not bar._split_chip.isVisible()
    assert bar._split_chip.text() == ""
    assert bar._split_clear.isVisible()
    assert bar._split_clear.text() == "✕ 取消合并"
    assert bar._split_clear.property("variant") == "softDanger"
    assert "取消 View 1 + View 2 合并" in bar._split_clear.toolTip()
    assert "当前操作 View 1" in bar._split_clear.toolTip()
    assert bar._split_clear.accessibleName() == bar._split_clear.toolTip()

    bar.set_split_focus(True)
    assert "当前操作 View 2" in bar._split_clear.toolTip()
    assert bar._split_clear.accessibleName() == bar._split_clear.toolTip()


def test_clear_split_chip_emits_active_index(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    manager.set_split(1)

    seen = []
    bar.clear_split_requested.connect(seen.append)
    qtbot.mouseClick(bar._split_clear, Qt.LeftButton)

    assert seen == [0]


def test_split_changed_refreshes_cancel_button(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    bar.show()
    QApplication.processEvents()

    assert not bar._split_chip.isVisible()
    assert not bar._split_clear.isVisible()

    manager.set_split(1)
    QApplication.processEvents()
    assert not bar._split_chip.isVisible()
    assert bar._split_clear.isVisible()

    manager.clear_split_for(0)
    QApplication.processEvents()
    assert not bar._split_chip.isVisible()
    assert not bar._split_clear.isVisible()


def test_merge_host_tab_swatch_uses_partner_color(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    assert bar._partner_color_for(0) is None
    assert bar._partner_color_for(1) is None

    manager.set_split(1)  # active 0 becomes host containing source View 1
    QApplication.processEvents()
    assert bar._partner_color_for(0) == manager.get(1).tab_color  # host: split dot
    assert bar._partner_color_for(1) is None  # source stays solid

    manager.clear_split_for(0)
    QApplication.processEvents()
    assert bar._partner_color_for(0) is None


def test_tab_color_pixmap_split_has_both_colors_and_white_gap(qtbot):
    from mf4_analyzer.ui.view_tabbar import _tab_color_pixmap

    pix = _tab_color_pixmap("#2d7ff9", ratio=2.0, partner_color="#e8590c")
    img = pix.toImage()
    ymid = img.height() // 2
    blue = orange = white = 0
    for x in range(img.width()):
        c = img.pixelColor(x, ymid)
        if c.alpha() < 10:
            continue
        if c.blue() > 150 and c.red() < 120:
            blue += 1
        elif c.red() > 180 and c.blue() < 120:
            orange += 1
        elif c.red() > 220 and c.green() > 220 and c.blue() > 220:
            white += 1
    assert blue > 0  # own color, left
    assert orange > 0  # partner color, right
    assert white > 0  # thin white separator


def test_plus_button_disabled_at_view_cap(qtbot):
    _manager, bar = _bar(qtbot, count=MAX_VIEWS, active=0)
    plus = bar.findChild(QPushButton, "viewTabPlus")

    assert plus is not None
    assert not plus.isEnabled()


def test_refresh_fit_calls_sync_tabbar_width(qtbot):
    _manager, bar = _bar(qtbot, count=2)
    calls = []
    original = bar._sync_tabbar_width

    def wrapped():
        calls.append(True)
        original()

    bar._sync_tabbar_width = wrapped
    bar.refresh_fit()
    assert calls == [True]


def test_plus_button_follows_the_managers_own_cap_not_the_module_constant(qtbot):
    # Cap must differ from MAX_VIEWS so we prove the bar reads the instance,
    # not the module default (analysis default 12, time-domain 24).
    manager = ViewManager(max_views=4)
    for _ in range(2):
        manager.new_view()
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    plus = bar.findChild(QPushButton, "viewTabPlus")

    assert len(manager.views) == 3
    assert plus.isEnabled()

    while manager.new_view() != -1:
        pass

    assert len(manager.views) == 4
    assert not plus.isEnabled()


class _ManagerWithoutMaxViews(QObject):
    """A manager predating the per-instance cap: no ``max_views`` attribute."""

    views_changed = pyqtSignal()
    active_changed = pyqtSignal(int)
    split_changed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.views = [ViewState(name="View 1", tab_color="#2d7ff9")]
        self.active = 0

    def add(self):
        idx = len(self.views)
        self.views.append(ViewState(name=f"View {idx + 1}", tab_color="#2d7ff9"))
        self.views_changed.emit()


def test_plus_button_falls_back_to_module_cap_when_manager_has_no_max_views(qtbot):
    manager = _ManagerWithoutMaxViews()
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    plus = bar.findChild(QPushButton, "viewTabPlus")

    assert plus.isEnabled()

    while len(manager.views) < MAX_VIEWS:
        manager.add()

    assert not plus.isEnabled()


def test_plus_button_disabled_at_time_domain_instance_cap(qtbot):
    manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    while manager.new_view() != -1:
        pass
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    plus = bar.findChild(QPushButton, "viewTabPlus")

    assert len(manager.views) == TIME_DOMAIN_MAX_VIEWS
    assert not plus.isEnabled()


def test_double_click_tab_starts_inline_rename_and_return_emits(qtbot):
    _manager, bar = _bar(qtbot, count=2)

    bar._on_double_clicked(0)
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    assert editor is not None
    assert not editor.isHidden()
    editor.setText("Road load")

    with qtbot.waitSignal(bar.rename_requested, timeout=100) as blocker:
        qtbot.keyClick(editor, Qt.Key_Return)

    assert blocker.args == [0, "Road load"]
    assert not editor.isVisible()


def test_inline_rename_escape_cancels(qtbot):
    _manager, bar = _bar(qtbot, count=2)
    renamed = []
    bar.rename_requested.connect(lambda idx, text: renamed.append((idx, text)))

    bar._on_double_clicked(0)
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    qtbot.keyClick(editor, Qt.Key_Escape)

    assert renamed == []


def test_context_menu_duplicate_emits_intent(qtbot, monkeypatch):
    _manager, bar = _bar(qtbot, count=2)
    received = []
    bar.duplicate_requested.connect(received.append)

    def fake_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "复制此 View")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)

    bar._on_context_menu(_tab_point(bar, 0))

    assert received == [0]


def test_context_menu_uses_translucent_rounded_shell(qtbot, monkeypatch):
    _manager, bar = _bar(qtbot, count=2)
    captured = []

    def fake_exec(menu, *_args):
        captured.append(menu)
        return None

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)

    bar._on_context_menu(_tab_point(bar, 0))

    assert captured
    menu = captured[0]
    flags = int(menu.windowFlags())
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    assert flags & int(Qt.FramelessWindowHint)
    assert flags & int(Qt.NoDropShadowWindowHint)


def test_context_menu_color_split_and_delete_emit_once(qtbot, monkeypatch):
    actions_to_signals = [
        ("改标签颜色...", "color_requested"),
        ("删除", "delete_requested"),
    ]

    for action_text, signal_name in actions_to_signals:
        _manager, bar = _bar(qtbot, count=2)
        received = []
        getattr(bar, signal_name).connect(received.append)

        def fake_exec(menu, *_args, text=action_text):
            return next(action for action in menu.actions() if action.text() == text)

        monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)

        bar._on_context_menu(_tab_point(bar, 0))

        assert received == [0]

    _manager, bar = _bar(qtbot, count=2)
    received = []
    bar.split_requested.connect(received.append)

    def fake_split_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "与此 View 并排")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_split_exec)

    bar._on_context_menu(_tab_point(bar, 1))

    assert received == [1]


def test_context_menu_cancel_split_emits_clear_intent(qtbot, monkeypatch):
    manager, bar = _bar(qtbot, count=2, active=0)
    manager.set_split(1)
    received = []
    bar.clear_split_requested.connect(received.append)

    def fake_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "取消合并")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)

    bar._on_context_menu(_tab_point(bar, 1))

    assert received == [1]


def test_context_menu_replacing_active_split_requires_confirmation(
    qtbot, monkeypatch
):
    manager, bar = _bar(qtbot, count=3, active=0)
    manager.set_split(1)
    received = []
    bar.split_requested.connect(received.append)
    questions = []

    def fake_exec(menu, *_args):
        return next(
            action
            for action in menu.actions()
            if action.text() == "与此 View 并排（替换当前合并）"
        )

    def fake_question(*args):
        questions.append(args)
        return QMessageBox.Yes

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMessageBox.question", fake_question)

    bar._on_context_menu(_tab_point(bar, 2))

    assert questions
    assert received == [2]


def test_context_menu_replacing_active_split_cancel_keeps_current_pair(
    qtbot, monkeypatch
):
    manager, bar = _bar(qtbot, count=3, active=0)
    manager.set_split(1)
    received = []
    bar.split_requested.connect(received.append)

    def fake_exec(menu, *_args):
        return next(
            action
            for action in menu.actions()
            if action.text() == "与此 View 并排（替换当前合并）"
        )

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    monkeypatch.setattr(
        "mf4_analyzer.ui.view_tabbar.QMessageBox.question",
        lambda *_args: QMessageBox.No,
    )

    bar._on_context_menu(_tab_point(bar, 2))

    assert received == []
    assert manager.partner_for(0) == 1


def test_context_menu_rename_starts_inline_editor_and_emits_once(qtbot, monkeypatch):
    _manager, bar = _bar(qtbot, count=2)
    received = []
    bar.rename_requested.connect(lambda idx, text: received.append((idx, text)))

    def fake_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "重命名")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)

    bar._on_context_menu(_tab_point(bar, 0))
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    assert editor is not None
    editor.setText("Context name")
    qtbot.keyClick(editor, Qt.Key_Return)

    assert received == [(0, "Context name")]


def test_context_menu_delete_disabled_for_single_view(qtbot, monkeypatch):
    _manager, bar = _bar(qtbot, count=1)
    deleted = []
    bar.delete_requested.connect(deleted.append)

    def fake_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "删除")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)

    bar._on_context_menu(_tab_point(bar, 0))

    assert deleted == []


# --------------------------------------------------------------------------
# T3/T4 — width budget, compact density, overflow menu.
#
# Every width below is MEASURED off the live bar, never a literal px. A literal
# budget is how a degrade branch turns into a false green: the plan modelled a
# tab at the QSS `min-width: 58px` but a real roomy tab measures ~91px, so any
# threshold copied from the plan would sit on the wrong side of reality. See
# docs/lessons-learned/pyqt-ui/
# 2026-07-10-facts-degrade-budget-from-measured-not-literal-px.md
# Each test also asserts its own reachability premise (compact < roomy), so a
# style/font change that collapses the regimes fails loudly instead of passing
# while exercising nothing.
# --------------------------------------------------------------------------

def _wide_bar(qtbot, count):
    manager = ViewManager(max_views=64)
    while len(manager.views) < count:
        manager.new_view()
    manager.set_active(0)
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    bar.resize(4000, 28)
    bar.show()
    QApplication.processEvents()
    return manager, bar


def _measure(bar):
    """Return (roomy_px, compact_px, row_overhead_px), all measured live.

    row_overhead = the width the row spends on things that are NOT the tab
    strip (margins + the fixed + button and friends), so a caller can size the
    bar to hand the strip an exact budget.
    """
    tabs = bar.tabBar()
    bar._set_density(compact=False)
    roomy = tabs.sizeHint().width()
    overhead = bar.width() - bar._tabs_budget(include_overflow=False)
    bar._set_density(compact=True)
    compact = tabs.sizeHint().width()
    bar._set_density(compact=False)
    return roomy, compact, overhead


def _resize_to_budget(bar, budget):
    _roomy, _compact, overhead = _measure(bar)
    bar.resize(int(budget) + overhead, 28)
    QApplication.processEvents()


def _visible_overflow_rows(popup):
    return [
        row
        for row in popup.findChildren(QWidget, "viewOverflowRow")
        if row.isVisible()
    ]


def _visible_overflow_close_buttons(popup):
    return [
        btn
        for btn in popup.findChildren(QPushButton, "viewOverflowRowClose")
        if btn.isVisible()
    ]


def _open_overflow_popup(bar):
    bar._on_overflow_clicked()
    QApplication.processEvents()
    popup = bar.findChild(QWidget, "viewOverflowPopup")
    if popup is None:
        popup = bar._overflow_popup
    assert popup is not None
    assert popup.isVisible()
    return popup


def test_tab_strip_is_max_clamped_not_fixed_width(qtbot):
    """setFixedWidth told Qt the strip could never overflow, which is what kept
    the setUsesScrollButtons(True) configured in __init__ permanently inert."""
    _manager, bar = _wide_bar(qtbot, count=3)
    tabs = bar.tabBar()

    assert tabs.minimumWidth() == 0
    assert tabs.maximumWidth() == tabs.sizeHint().width()
    assert tabs.usesScrollButtons()


def test_roomy_row_shows_every_tab_with_full_names(qtbot):
    manager, bar = _wide_bar(qtbot, count=6)
    tabs = bar.tabBar()

    assert not bar.is_compact()
    assert bar.overflow_indices() == []
    assert all(tabs.isTabVisible(i) for i in range(tabs.count()))
    assert tabs.tabText(3) == manager.views[3].name


def test_ten_views_stay_flat_visible_with_zero_clicks(qtbot):
    """Spec acceptance: 10 Views must all be reachable in one click."""
    _manager, bar = _wide_bar(qtbot, count=10)
    tabs = bar.tabBar()

    assert bar.overflow_indices() == []
    assert bar._overflow.isVisible()
    assert bar._overflow.text() == "⋯"
    assert sum(tabs.isTabVisible(i) for i in range(tabs.count())) == 10


def test_view_management_entry_is_visible_and_opens_when_all_tabs_fit(qtbot):
    manager, bar = _wide_bar(qtbot, count=6)

    assert bar.overflow_indices() == []
    assert bar._overflow.isVisible()
    assert bar._overflow.text() == "⋯"
    assert bar._overflow.accessibleName() == "管理全部 View"
    assert f"管理全部 {len(manager.views)} 个 View" in bar._overflow.toolTip()

    popup = _open_overflow_popup(bar)
    assert len(_visible_overflow_rows(popup)) == len(manager.views)
    bar._close_overflow_popup()


def test_narrow_row_compacts_labels_to_ordinals_and_moves_name_to_tooltip(qtbot):
    manager, bar = _wide_bar(qtbot, count=10)
    roomy, compact, _overhead = _measure(bar)
    # Reachability premise: there must BE a band where compact fits and roomy
    # does not, otherwise this test proves nothing.
    assert compact < roomy

    _resize_to_budget(bar, (roomy + compact) // 2)

    tabs = bar.tabBar()
    assert bar.is_compact()
    assert bar.overflow_indices() == []  # compact alone was enough
    assert tabs.tabText(6) == "7"  # dot + ordinal only
    # The full name must come from the manager: the widget only holds the
    # ordinal now, so a read-back would put "7" in the tooltip.
    assert tabs.tabToolTip(6) == manager.views[6].name


def test_compact_row_without_hidden_tabs_keeps_management_entry(qtbot):
    manager, bar = _wide_bar(qtbot, count=10)
    roomy, compact, _overhead = _measure(bar)
    assert compact < roomy

    _resize_to_budget(bar, (roomy + compact) // 2)

    assert bar.is_compact()
    assert bar.overflow_indices() == []
    assert bar._overflow.isVisible()
    assert bar._overflow.text() == "⋯"
    popup = _open_overflow_popup(bar)
    assert len(_visible_overflow_rows(popup)) == len(manager.views)
    bar._close_overflow_popup()


def test_widening_the_row_restores_roomy_names_and_clears_tooltips(qtbot):
    manager, bar = _wide_bar(qtbot, count=10)
    roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, (roomy + compact) // 2)
    assert bar.is_compact()

    bar.resize(4000, 28)
    QApplication.processEvents()

    tabs = bar.tabBar()
    assert not bar.is_compact()
    assert tabs.tabText(6) == manager.views[6].name
    assert tabs.tabToolTip(6) == ""


def test_overflow_hides_tail_tabs_with_settabvisible_never_removetab(qtbot):
    """§5.5 hard constraint: six call sites treat QTabBar index == View index."""
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    tabs = bar.tabBar()

    removed = []
    real_remove = tabs.removeTab
    tabs.removeTab = lambda i: (removed.append(i), real_remove(i))[1]
    _resize_to_budget(bar, compact // 2)

    assert removed == []
    # Index identity intact: every View still owns the tab at its own index.
    assert tabs.count() == len(manager.views)
    assert bar.overflow_indices()
    for idx in range(tabs.count()):
        assert tabs.tabData(idx) == manager.views[idx].tab_color
    # The retired tabs are hidden, not gone.
    for idx in bar.overflow_indices():
        assert not tabs.isTabVisible(idx)


def test_overflow_count_matches_the_hidden_tabs(qtbot):
    _manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)

    tabs = bar.tabBar()
    hidden = [i for i in range(tabs.count()) if not tabs.isTabVisible(i)]
    assert bar.overflow_indices() == hidden
    assert bar._overflow.isVisible()
    assert bar._overflow.text() == f"»{len(hidden)}"
    assert f"另有 {len(hidden)} 个未显示" in bar._overflow.toolTip()


def test_view_management_entry_has_stable_measured_reserve(qtbot):
    _manager, bar = _wide_bar(qtbot, count=14)
    entry_width = bar._overflow.width()
    plain_budget = bar._tabs_budget(include_overflow=False)
    measured_reserve = bar._measure_management_entry_reserve()

    assert bar._overflow.minimumWidth() == measured_reserve
    bar._set_overflow(range(9))
    QApplication.processEvents()
    assert bar._overflow.text() == "»9"
    assert bar._overflow.width() == entry_width
    bar._set_overflow(range(10))
    QApplication.processEvents()
    assert bar._overflow.text() == "»10"
    assert bar._overflow.width() == entry_width
    bar._sync_tabbar_width()

    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)

    assert bar.overflow_indices()
    assert bar._overflow.width() == entry_width
    assert bar._overflow.minimumWidth() > 0
    assert bar._tabs_budget(include_overflow=True) == bar._tabs_budget(
        include_overflow=False
    )
    assert plain_budget is not None


def test_narrowing_never_hides_the_current_tab_nor_switches_views(qtbot):
    """Qt moves the selection (and emits currentChanged) when the CURRENT tab is
    hidden — so retiring it would silently switch the user's View on resize."""
    manager, bar = _wide_bar(qtbot, count=14)
    manager.set_active(13)  # last View: squarely in the tail that gets retired
    QApplication.processEvents()
    switches = []
    bar.switch_requested.connect(switches.append)
    _roomy, compact, _overhead = _measure(bar)

    _resize_to_budget(bar, compact // 2)

    tabs = bar.tabBar()
    assert bar.overflow_indices()  # premise: we really are in the overflow regime
    assert tabs.isTabVisible(13)
    assert 13 not in bar.overflow_indices()
    assert tabs.currentIndex() == 13
    assert switches == []


def test_plus_and_split_clear_stay_inside_the_bar_when_tabs_overflow(qtbot):
    """+ and the right-hand action never compress; the tab strip yields first."""
    manager, bar = _wide_bar(qtbot, count=14)
    manager.set_split(1)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)

    assert bar._split_clear.isVisible()
    assert bar.rect().contains(bar._plus.geometry())
    assert bar.rect().contains(bar._split_clear.geometry())
    assert bar.rect().contains(bar._overflow.geometry())


def test_showing_the_split_action_steals_budget_from_the_tabs_not_the_actions(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    before = len(bar.overflow_indices())

    manager.set_split(1)  # the ✕ 取消合并 button joins the row
    QApplication.processEvents()

    assert bar._split_clear.isVisible()
    assert len(bar.overflow_indices()) > before
    assert bar.rect().contains(bar._split_clear.geometry())


def test_overflow_menu_pick_emits_switch_requested_with_the_view_index(
    qtbot, monkeypatch
):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    target = bar.overflow_indices()[-1]
    target_name = manager.views[target].name
    seen = []
    bar.switch_requested.connect(seen.append)

    popup = _open_overflow_popup(bar)
    name_btn = next(
        btn
        for btn in popup.findChildren(QPushButton, "viewOverflowRowName")
        if btn.text() == target_name
    )
    qtbot.mouseClick(name_btn, Qt.LeftButton)
    QApplication.processEvents()

    # The emitted index must address the VIEW, proving setTabVisible left the
    # tab<->view index identity intact.
    assert seen == [target]


def test_overflow_menu_lists_every_view_and_checks_the_current_one(
    qtbot, monkeypatch
):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)

    popup = _open_overflow_popup(bar)
    names = [
        btn.text()
        for btn in popup.findChildren(QPushButton, "viewOverflowRowName")
    ]
    # Full names from the manager, not the ordinal the compact tab carries.
    assert names == [view.name for view in manager.views]
    chips = [
        chip
        for chip in popup.findChildren(QLabel, "viewOverflowCurrentChip")
        if chip.isVisible() and chip.text() == "当前"
    ]
    assert len(chips) == 1
    bar._close_overflow_popup()


def test_switching_to_an_overflowed_view_pulls_it_back_onto_the_strip(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    bar.switch_requested.connect(manager.set_active)  # real MainWindow wiring
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    target = bar.overflow_indices()[-1]

    bar.switch_requested.emit(target)
    QApplication.processEvents()

    assert bar.tabBar().isTabVisible(target)
    assert target not in bar.overflow_indices()
    assert bar.tabBar().currentIndex() == target


def test_compact_rename_editor_prefills_the_view_name_not_the_ordinal(qtbot):
    """The tab label is the ordinal under compact density, so seeding the editor
    from tabText() would rename the View to "7"."""
    manager, bar = _wide_bar(qtbot, count=10)
    roomy, compact, _overhead = _measure(bar)
    manager.rename(6, "Road load")
    _resize_to_budget(bar, (roomy + compact) // 2)
    assert bar.is_compact()
    assert bar.tabBar().tabText(6) == "7"  # premise: the widget holds the ordinal

    bar._on_double_clicked(6)
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")

    assert editor.text() == "Road load"


def test_reorder_relabels_compact_ordinals_after_the_drag_releases(qtbot):
    """The §5.1 guard bans refresh() mid-drag, so Qt's moveTab carries the tab
    text along and the compact ordinals stop matching their positions. The
    re-label must land on the drag's mouse release, never inside it."""
    manager, bar = _wide_bar(qtbot, count=10)
    bar.reorder_requested.connect(manager.reorder)
    roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, (roomy + compact) // 2)
    assert bar.is_compact()
    tabs = bar.tabBar()

    tabs.moveTab(0, 4)
    QApplication.processEvents()
    # Mid-drag the ordinals travel with the tab: this is the state the guard
    # leaves behind, and exactly what the release must repair.
    assert tabs.tabText(0) == "2"

    qtbot.mouseRelease(tabs, Qt.LeftButton)
    qtbot.waitUntil(lambda: tabs.tabText(0) == "1", timeout=1000)

    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        str(i + 1) for i in range(tabs.count())
    ]
    assert [v.name for v in manager.views][4] == "View 1"
    assert all(
        tabs.tabToolTip(i) == manager.views[i].name for i in range(tabs.count())
    )


# --------------------------------------------------------------------------
# Section quiet anchor — display-only sibling that steals measured budget.
# --------------------------------------------------------------------------

def _anchor_widget(bar):
    return bar.findChild(QWidget, "viewSectionAnchor")


def _section_bar(qtbot, *, section, count=2, active=0, max_views=64):
    manager = ViewManager(max_views=max_views)
    while len(manager.views) < count:
        manager.new_view()
    manager.set_active(active)
    bar = ViewTabBar(manager, section=section)
    qtbot.addWidget(bar)
    return manager, bar


def test_section_anchor_renders_known_section_identity_without_focus(qtbot):
    _manager, bar = _section_bar(qtbot, section="time", count=1)
    anchor = _anchor_widget(bar)
    label = bar.findChild(QLabel, "viewSectionAnchorLabel")
    icon = bar.findChild(QLabel, "viewSectionAnchorIcon")
    rule = bar.findChild(QFrame, "viewSectionAnchorRule")

    assert anchor is not None
    assert label is not None and label.text() == "时域"
    assert icon is not None and not icon.pixmap().isNull()
    assert icon.width() == 18 and icon.height() == 18
    assert rule is not None and rule.width() == 1
    assert rule.height() == 14
    assert anchor.height() == 26
    assert label.height() == 18
    assert icon.height() == 18
    # Icon / label share a midline (CJK pad is optical, ≤1px).
    assert abs(icon.geometry().center().y() - label.geometry().center().y()) <= 1
    assert anchor.focusPolicy() == Qt.NoFocus
    assert label.focusPolicy() == Qt.NoFocus
    assert icon.focusPolicy() == Qt.NoFocus
    assert anchor.accessibleName() == "当前区域：时域"

    _none_manager, none_bar = _bar(qtbot, count=1)
    assert _anchor_widget(none_bar) is None

    with pytest.raises(ValueError, match="section"):
        ViewTabBar(ViewManager(), section="not-a-section")


def test_section_anchor_measured_width_is_reserved_from_tabs_budget(qtbot):
    plain_manager = ViewManager()
    plain = ViewTabBar(plain_manager)
    qtbot.addWidget(plain)
    _anchored_manager, anchored = _section_bar(qtbot, section="fft", count=1)

    for bar in (plain, anchored):
        bar.resize(800, 28)
        bar.show()
    QApplication.processEvents()

    anchor = _anchor_widget(anchored)
    spacing = max(0, anchored.layout().spacing())
    expected = (
        max(anchor.sizeHint().width(), anchor.minimumSizeHint().width()) + spacing
    )
    plain_budget = plain._tabs_budget(include_overflow=False)
    anchored_budget = anchored._tabs_budget(include_overflow=False)

    assert plain_budget is not None and anchored_budget is not None
    assert plain_budget - anchored_budget == expected


def test_section_anchor_can_trigger_compact_without_changing_compact_labels(qtbot):
    _plain_manager, plain = _wide_bar(qtbot, count=10)
    _anchored_manager, anchored = _section_bar(qtbot, section="order", count=10)
    anchored.resize(4000, 28)
    anchored.show()
    QApplication.processEvents()

    roomy, compact, plain_overhead = _measure(plain)
    _a_roomy, _a_compact, anchored_overhead = _measure(anchored)
    delta = anchored_overhead - plain_overhead
    assert delta > 0
    assert compact < roomy - delta  # still a compact band after the reserve

    # Same row width that exactly fits plain roomy: anchored must drop first.
    target_width = roomy + plain_overhead
    plain.resize(int(target_width), 28)
    anchored.resize(int(target_width), 28)
    QApplication.processEvents()

    assert not plain.is_compact()
    assert anchored.is_compact()
    assert anchored.overflow_indices() == []
    tabs = anchored.tabBar()
    assert all(tabs.tabText(i) == str(i + 1) for i in range(tabs.count()))
    assert all(
        tabs.tabToolTip(i) == anchored._manager.views[i].name
        for i in range(tabs.count())
    )
    assert tabs.tabText(0) == "1"  # current stays ordinal too


def test_section_anchor_overflow_keeps_current_tail_view_and_count_exact(qtbot):
    manager, bar = _section_bar(qtbot, section="frf", count=14, active=13)
    bar.resize(4000, 28)
    bar.show()
    QApplication.processEvents()
    switches = []
    bar.switch_requested.connect(switches.append)
    _roomy, compact, _overhead = _measure(bar)

    _resize_to_budget(bar, compact // 2)

    tabs = bar.tabBar()
    hidden = [i for i in range(tabs.count()) if not tabs.isTabVisible(i)]
    assert bar.overflow_indices()
    assert tabs.isTabVisible(13)
    assert 13 not in bar.overflow_indices()
    assert tabs.currentIndex() == 13
    assert manager.active == 13
    assert bar.overflow_indices() == hidden
    assert bar._overflow.text() == f"»{len(hidden)}"
    assert switches == []
    # Tail retirement: every hidden index is from the end, skipping current.
    assert hidden == sorted(i for i in range(tabs.count()) if i != 13)[-len(hidden):]


def test_section_anchor_and_split_actions_are_both_fixed_budget_siblings(qtbot):
    manager, bar = _section_bar(qtbot, section="fft_time", count=14)
    bar.resize(4000, 28)
    bar.show()
    QApplication.processEvents()
    manager.set_split(1)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)

    assert _anchor_widget(bar).isVisible()
    assert bar._plus.isVisible()
    assert bar._overflow.isVisible()
    assert bar._split_clear.isVisible()
    assert bar.overflow_indices()
    for widget in (
        _anchor_widget(bar),
        bar._plus,
        bar._overflow,
        bar._split_clear,
    ):
        assert bar.rect().contains(widget.geometry())


def test_time_domain_cap_overflow_keeps_active_visible_and_lists_all(
    qtbot, monkeypatch
):
    manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    while len(manager.views) < TIME_DOMAIN_MAX_VIEWS:
        manager.new_view()
    last = TIME_DOMAIN_MAX_VIEWS - 1
    manager.set_active(last)
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    bar.resize(4000, 28)
    bar.show()
    QApplication.processEvents()
    switches = []
    bar.switch_requested.connect(switches.append)
    _roomy, compact, _overhead = _measure(bar)

    _resize_to_budget(bar, compact // 2)

    tabs = bar.tabBar()
    assert bar.overflow_indices()
    assert tabs.isTabVisible(last)
    assert last not in bar.overflow_indices()
    assert tabs.currentIndex() == last
    assert switches == []
    assert bar._overflow.isVisible()
    assert bar._overflow.text().startswith("»")

    popup = _open_overflow_popup(bar)
    names = [
        btn.text()
        for btn in popup.findChildren(QPushButton, "viewOverflowRowName")
    ]
    assert names == [view.name for view in manager.views]
    chips = [
        chip
        for chip in popup.findChildren(QLabel, "viewOverflowCurrentChip")
        if chip.isVisible() and chip.text() == "当前"
    ]
    assert len(chips) == 1
    bar._close_overflow_popup()


def test_time_domain_cap_reorder_duplicate_and_delete(qtbot):
    manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    while len(manager.views) < TIME_DOMAIN_MAX_VIEWS - 1:
        manager.new_view()
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    bar.reorder_requested.connect(manager.reorder)
    bar.duplicate_requested.connect(manager.duplicate)
    bar.delete_requested.connect(manager.delete_view)
    plus = bar.findChild(QPushButton, "viewTabPlus")

    assert len(manager.views) == TIME_DOMAIN_MAX_VIEWS - 1
    assert plus.isEnabled()

    names_before = [view.name for view in manager.views]
    bar.tabBar().moveTab(0, 2)
    QApplication.processEvents()
    expected = names_before[1:3] + [names_before[0]] + names_before[3:]
    assert [view.name for view in manager.views] == expected
    assert [bar.tabBar().tabText(i) for i in range(bar.count())] == expected

    bar.duplicate_requested.emit(0)
    QApplication.processEvents()
    assert len(manager.views) == TIME_DOMAIN_MAX_VIEWS
    assert manager.views[1].name.endswith("副本")
    assert not plus.isEnabled()
    assert manager.duplicate(0) == -1

    bar.delete_requested.emit(1)
    QApplication.processEvents()
    assert len(manager.views) == TIME_DOMAIN_MAX_VIEWS - 1
    assert plus.isEnabled()
    assert bar.count() == len(manager.views)


def test_section_context_menu_add_to_ultraview_emits_stable_ref(qtbot, monkeypatch):
    manager, bar = _section_bar(qtbot, section="time", count=2)
    received = []
    bar.add_to_ultraview_requested.connect(lambda s, v: received.append((s, v)))

    def fake_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "加入总览")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    bar._on_context_menu(_tab_point(bar, 1))

    assert received == [("time", str(manager.get(1).view_id))]


def test_context_menu_without_section_omits_add_to_ultraview(qtbot, monkeypatch):
    _manager, bar = _bar(qtbot, count=1)
    labels = []

    def fake_exec(menu, *_args):
        labels.extend(action.text() for action in menu.actions())
        return None

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    bar._on_context_menu(_tab_point(bar, 0))
    assert "加入总览" not in labels


def _shown_bar(qtbot, count=3, active=0):
    manager, bar = _bar(qtbot, count=count, active=active)
    bar.resize(900, 30)
    bar.show()
    QApplication.processEvents()
    return manager, bar


def _geometry_snapshot(bar):
    tabs = bar.tabBar()
    return {
        "tab_rects": [tabs.tabRect(i) for i in range(tabs.count())],
        "size_hint": tabs.sizeHint(),
        "icon_slots": [tab_icon_slot_rect(tabs, i) for i in range(tabs.count())],
        "close_targets": [tab_close_hit_rect(tabs, i) for i in range(tabs.count())],
        "rail": bar.width(),
        "tabs_max": tabs.maximumWidth(),
    }


def _hover_icon_slot(tabs, idx):
    slot = tab_close_hit_rect(tabs, idx)
    QApplication.sendEvent(
        tabs,
        QHoverEvent(QEvent.HoverMove, slot.center(), slot.center()),
    )
    QApplication.processEvents()
    return slot


def _signal_lists(bar):
    deleted, switched, renamed, reordered = [], [], [], []
    bar.delete_requested.connect(deleted.append)
    bar.switch_requested.connect(switched.append)
    bar.rename_requested.connect(lambda idx, text: renamed.append((idx, text)))
    bar.reorder_requested.connect(lambda a, b: reordered.append((a, b)))
    return deleted, switched, renamed, reordered


def test_hovering_swatch_replaces_only_icon_without_changing_tab_geometry(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=1)
    tabs = bar.tabBar()
    before = _geometry_snapshot(bar)
    slot = _hover_icon_slot(tabs, 1)
    after = _geometry_snapshot(bar)

    assert after["tab_rects"] == before["tab_rects"]
    assert after["size_hint"] == before["size_hint"]
    assert after["icon_slots"] == before["icon_slots"]
    assert after["rail"] == before["rail"]
    assert after["tabs_max"] == before["tabs_max"]
    assert tabs.hover_index() == 1
    assert slot.contains(slot.center())


def test_inactive_swatch_click_switches_without_delete(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=0)
    tabs = bar.tabBar()
    deleted, switched, renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)

    assert tabs.hover_index() == -1
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()

    assert deleted == []
    assert switched == [1]
    assert renamed == []
    assert reordered == []
    assert tabs.currentIndex() == 1
    assert tabs.hover_index() == -1


def test_switched_swatch_requires_pointer_reentry_before_close(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=0)
    tabs = bar.tabBar()
    deleted, switched, renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.sendEvent(
        tabs,
        QHoverEvent(QEvent.HoverMove, slot.center(), slot.center()),
    )
    QApplication.processEvents()

    assert tabs.currentIndex() == 1
    assert tabs.hover_index() == -1

    # A second click under an unchanged pointer is still non-destructive.
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()
    assert deleted == []

    body = tabs.tabRect(1).center()
    assert not slot.contains(body)
    QApplication.sendEvent(
        tabs,
        QHoverEvent(QEvent.HoverMove, body, slot.center()),
    )
    QApplication.sendEvent(
        tabs,
        QHoverEvent(QEvent.HoverMove, slot.center(), body),
    )
    QApplication.processEvents()
    assert tabs.hover_index() == 1

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()

    assert deleted == [1]
    assert switched == [1]
    assert renamed == []
    assert reordered == []


def test_active_close_slot_click_emits_delete_once_without_switch_or_rename(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=1)
    tabs = bar.tabBar()
    deleted, switched, renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()

    assert deleted == [1]
    assert switched == []
    assert renamed == []
    assert reordered == []
    assert bar.tabBar().currentIndex() == 1


def test_close_slot_double_click_never_enters_inline_rename_or_double_deletes(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3)
    tabs = bar.tabBar()
    deleted, switched, renamed, _reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 0)

    QTest.mouseDClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()

    assert deleted == [0]
    assert renamed == []
    assert switched == []
    assert bar.findChild(QLineEdit, "viewTabRenameEditor") is None


def test_inactive_swatch_double_click_cannot_turn_the_second_click_into_close(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=0)
    tabs = bar.tabBar()
    deleted, switched, renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QTest.mouseDClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()

    assert tabs.currentIndex() == 1
    assert tabs.hover_index() == -1
    assert deleted == []
    assert switched == [1]
    assert renamed == []
    assert reordered == []


def test_drag_from_close_slot_cancels_without_reorder(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=1)
    tabs = bar.tabBar()
    deleted, switched, _renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)
    outside = tabs.tabRect(1).center()

    QTest.mousePress(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.sendEvent(
        tabs, QHoverEvent(QEvent.HoverMove, outside, slot.center())
    )
    QTest.mouseMove(tabs, outside)
    QTest.mouseRelease(tabs, Qt.LeftButton, Qt.NoModifier, outside)
    QApplication.processEvents()

    assert deleted == []
    assert reordered == []
    assert switched == []


def test_tab_body_click_and_double_click_keep_existing_switch_and_rename_routes(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=0)
    tabs = bar.tabBar()
    deleted, switched, renamed, _reordered = _signal_lists(bar)
    body = _tab_point(bar, 1)
    slot = tab_close_hit_rect(tabs, 1)
    assert not slot.contains(body)

    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, body)
    QApplication.processEvents()
    assert switched == [1]
    assert deleted == []

    QTest.mouseDClick(tabs, Qt.LeftButton, Qt.NoModifier, _tab_point(bar, 1))
    QApplication.processEvents()
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    assert editor is not None
    assert deleted == []


def test_right_click_on_swatch_keeps_existing_context_menu(qtbot, monkeypatch):
    _manager, bar = _shown_bar(qtbot, count=2)
    labels = []

    def fake_exec(menu, *_args):
        labels.extend(action.text() for action in menu.actions())
        return None

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    bar._on_context_menu(tab_icon_slot_rect(bar.tabBar(), 0).center())

    assert "重命名" in labels
    assert "复制此 View" in labels
    assert "改标签颜色..." in labels
    assert "删除" in labels


def test_close_ink_is_centered_in_the_square_at_each_dpr():
    for dpr in (1.0, 2.0):
        pixmap = _tab_close_pixmap(dpr)
        image = pixmap.toImage()
        xs, ys = [], []
        ink = QColor("#bf3447")
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.alpha() < 80:
                    continue
                if abs(color.red() - ink.red()) < 40 and color.blue() < 120:
                    xs.append(x)
                    ys.append(y)
        assert xs and ys
        cx = (min(xs) + max(xs)) / 2 / dpr
        cy = (min(ys) + max(ys)) / 2 / dpr
        assert abs(cx - 9.0) <= 0.5
        assert abs(cy - 9.0) <= 0.5


def test_close_button_renders_as_a_large_square_instead_of_a_swatch_pill():
    for dpr in (1.0, 2.0):
        pixmap = _tab_close_pixmap(dpr)
        image = pixmap.toImage()
        assert pixmap.width() / dpr == 18
        assert pixmap.height() / dpr == 18

        pixels = []
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.alpha() >= 80:
                    pixels.append((x / dpr, y / dpr))
        assert pixels
        width = max(x for x, _y in pixels) - min(x for x, _y in pixels) + 1 / dpr
        height = max(y for _x, y in pixels) - min(y for _x, y in pixels) + 1 / dpr
        assert width >= 17
        assert height >= 17
        assert abs(width - height) <= 0.5


def test_close_visual_and_hit_target_share_one_center_without_growing_the_tab(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3)
    tabs = bar.tabBar()
    before = _geometry_snapshot(bar)
    hit = tab_close_hit_rect(tabs, 1)
    visual = tab_close_visual_rect(tabs, 1)

    assert hit.size() == QSize(20, 20)
    assert visual.size() == QSize(18, 18)
    assert hit.center() == visual.center()
    assert hit.contains(visual.topLeft())
    assert hit.contains(visual.bottomRight())

    _hover_icon_slot(tabs, 1)
    after = _geometry_snapshot(bar)
    assert after == before


def test_close_hit_target_edges_work_from_every_direction(qtbot):
    for edge in ("left", "right", "top", "bottom"):
        _manager, bar = _shown_bar(qtbot, count=3, active=1)
        tabs = bar.tabBar()
        deleted, switched, renamed, reordered = _signal_lists(bar)
        hit = _hover_icon_slot(tabs, 1)
        points = {
            "left": QPoint(hit.left(), hit.center().y()),
            "right": QPoint(hit.right(), hit.center().y()),
            "top": QPoint(hit.center().x(), hit.top()),
            "bottom": QPoint(hit.center().x(), hit.bottom()),
        }

        QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, points[edge])
        QApplication.processEvents()

        assert deleted == [1]
        assert switched == []
        assert renamed == []
        assert reordered == []


def test_rendered_close_square_is_fully_contained_by_the_hit_target(qtbot):
    _manager, bar = _shown_bar(qtbot, count=3, active=1)
    tabs = bar.tabBar()
    hit = _hover_icon_slot(tabs, 1)
    pixmap = tabs.grab()
    image = pixmap.toImage()
    dpr = pixmap.devicePixelRatioF()
    tab = tabs.tabRect(1)
    pixels = []
    for y in range(round(tab.top() * dpr), round((tab.bottom() + 1) * dpr)):
        for x in range(round(tab.left() * dpr), round((tab.right() + 1) * dpr)):
            color = QColor(image.pixel(x, y))
            if color.red() > 145 and color.red() > color.green() + 28:
                pixels.append((x / dpr, y / dpr))

    assert pixels
    left = min(x for x, _y in pixels)
    right = max(x for x, _y in pixels)
    top = min(y for _x, y in pixels)
    bottom = max(y for _x, y in pixels)
    assert left >= hit.left()
    assert right <= hit.right() + 1
    assert top >= hit.top()
    assert bottom <= hit.bottom() + 1
    assert right - left >= 16
    assert bottom - top >= 16
    assert abs((right - left) - (bottom - top)) <= 1


def test_single_view_keeps_swatch_and_has_no_actionable_close_slot(qtbot):
    _manager, bar = _shown_bar(qtbot, count=1)
    tabs = bar.tabBar()
    deleted, switched, renamed, reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 0)

    assert tabs.hover_index() == -1
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()
    assert deleted == []
    assert switched == []
    assert renamed == []
    assert reordered == []


def test_close_slot_armed_rebuild_fails_closed(qtbot):
    manager, bar = _shown_bar(qtbot, count=3, active=1)
    tabs = bar.tabBar()
    deleted, switched, _renamed, _reordered = _signal_lists(bar)
    slot = _hover_icon_slot(tabs, 1)
    QTest.mousePress(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    manager.new_view()
    QApplication.processEvents()
    QTest.mouseRelease(tabs, Qt.LeftButton, Qt.NoModifier, slot.center())
    QApplication.processEvents()
    assert deleted == []
    assert switched == []


def test_overflow_popup_lists_all_views_and_marks_current_by_view_id(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    manager.set_active(3)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    popup = _open_overflow_popup(bar)
    rows = popup.findChildren(QWidget, "viewOverflowRow")
    assert len(rows) == len(manager.views)
    current_rows = [row for row in rows if row.property("current") == "true"]
    assert len(current_rows) == 1
    assert current_rows[0].property("viewId") == manager.get(3).view_id
    bar._close_overflow_popup()


def test_popup_row_name_switches_without_emitting_delete(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    deleted, switched, _renamed, _reordered = _signal_lists(bar)
    popup = _open_overflow_popup(bar)
    target = manager.views[-1]
    name_btn = next(
        btn
        for btn in popup.findChildren(QPushButton, "viewOverflowRowName")
        if btn.text() == target.name
    )
    qtbot.mouseClick(name_btn, Qt.LeftButton)
    QApplication.processEvents()
    assert switched == [len(manager.views) - 1]
    assert deleted == []


def test_popup_row_close_emits_overflow_delete_without_switch(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    deleted, switched, _renamed, _reordered = _signal_lists(bar)
    overflow_deleted = []
    bar.overflow_delete_requested.connect(overflow_deleted.append)
    popup = _open_overflow_popup(bar)
    close_btn = _visible_overflow_close_buttons(popup)[2]
    qtbot.mouseClick(close_btn, Qt.LeftButton)
    QApplication.processEvents()
    assert overflow_deleted == [2]
    assert deleted == []
    assert switched == []
    assert bar._overflow_popup is popup
    assert popup.isVisible()


def test_popup_row_close_reprojects_and_allows_another_close(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    bar.overflow_delete_requested.connect(manager.delete_view)
    popup = _open_overflow_popup(bar)
    first_id = manager.get(2).view_id
    qtbot.mouseClick(_visible_overflow_close_buttons(popup)[2], Qt.LeftButton)
    QApplication.processEvents()
    popup = bar._overflow_popup
    assert popup is not None and popup.isVisible()
    rows = _visible_overflow_rows(popup)
    assert len(rows) == 13
    assert first_id not in [row.property("viewId") for row in rows]
    assert popup.findChild(QLabel, "viewOverflowCount").text() == "13 个"
    assert (
        popup.findChild(QPushButton, "viewOverflowCloseOthers").text()
        == "关闭其他 12 个…"
    )
    assert (
        popup.findChild(QPushButton, "viewOverflowCloseAll").text()
        == "关闭全部 13 个…"
    )
    second_id = manager.get(2).view_id
    qtbot.mouseClick(_visible_overflow_close_buttons(popup)[2], Qt.LeftButton)
    QApplication.processEvents()
    popup = bar._overflow_popup
    assert popup is not None and popup.isVisible()
    rows = _visible_overflow_rows(popup)
    assert len(rows) == 12
    assert second_id not in [row.property("viewId") for row in rows]
    assert (
        popup.findChild(QPushButton, "viewOverflowCloseOthers").text()
        == "关闭其他 11 个…"
    )
    assert (
        popup.findChild(QPushButton, "viewOverflowCloseAll").text()
        == "关闭全部 12 个…"
    )


def test_popup_stays_open_when_row_close_clears_overflow(qtbot):
    _reference_manager, reference = _wide_bar(qtbot, count=3)
    compact_three = _measure(reference)[1]
    manager, bar = _wide_bar(qtbot, count=4)
    _roomy, compact_four, _overhead = _measure(bar)
    assert compact_three < compact_four
    _resize_to_budget(bar, (compact_three + compact_four) // 2)
    assert bar.overflow_indices()

    bar.overflow_delete_requested.connect(manager.delete_view)
    popup = _open_overflow_popup(bar)
    qtbot.mouseClick(_visible_overflow_close_buttons(popup)[-1], Qt.LeftButton)
    QApplication.processEvents()

    assert bar.overflow_indices() == []
    assert bar._overflow.text() == "⋯"
    assert bar._overflow_popup is popup
    assert popup.isVisible()
    assert len(_visible_overflow_rows(popup)) == 3


def test_overflow_popup_omits_help_copy_and_paints_list_separators(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    popup.populate(
        [
            ViewOverflowRow(
                view_id="a",
                name="View 1",
                ordinal=1,
                color="#2d7ff9",
                partner_color=None,
                current=True,
                closable=True,
            ),
            ViewOverflowRow(
                view_id="b",
                name="View 2",
                ordinal=2,
                color="#e8590c",
                partner_color=None,
                current=False,
                closable=True,
            ),
        ]
    )
    assert popup.findChild(QLabel, "viewOverflowHelp") is None
    assert popup.findChild(QLabel, "viewOverflowBulkHint") is None
    assert popup.findChild(QLabel, "viewOverflowInfoIcon") is None
    popup._apply_panel_size(max(popup._fitted_width, PANEL_MIN_WIDTH))
    popup.show()
    QApplication.processEvents()
    well = popup.findChild(QWidget, "viewOverflowListWell")
    surface = popup.findChild(QFrame, "viewOverflowSurface")
    image = well.grab().toImage()
    mid_y = image.height() // 2
    mid_x = image.width() // 2
    dpr = image.devicePixelRatio()
    margins = well.contentsMargins()
    separator = QColor("#c9d5e3")

    def _has_separator(x, y, x_band=None, y_band=None):
        x_band = round(2 * dpr) if x_band is None else x_band
        y_band = round(2 * dpr) if y_band is None else y_band
        for dy in range(-y_band, y_band + 1):
            py = max(0, min(image.height() - 1, y + dy))
            for dx in range(-x_band, x_band + 1):
                px = max(0, min(image.width() - 1, x + dx))
                color = QColor(image.pixel(px, py))
                if all(
                    abs(channel - expected) <= 12
                    for channel, expected in (
                        (color.red(), separator.red()),
                        (color.green(), separator.green()),
                        (color.blue(), separator.blue()),
                    )
                ):
                    return True
        return False

    def _separator_y_near(edge_y):
        for dy in range(0, round(2 * dpr) + 1):
            for y in {edge_y - dy, edge_y + dy}:
                if 0 <= y < image.height() and _has_separator(
                    mid_x, y, x_band=1, y_band=0
                ):
                    return y
        return None

    def _separator_x_near(edge_x):
        for dx in range(0, round(2 * dpr) + 1):
            for x in {edge_x - dx, edge_x + dx}:
                if 0 <= x < image.width() and _has_separator(
                    x, mid_y, x_band=0, y_band=1
                ):
                    return x
        return None

    top_y = _separator_y_near(0)
    bottom_y = _separator_y_near(image.height() - 1)
    left_x = _separator_x_near(0)
    right_x = _separator_x_near(image.width() - 1)

    assert surface is not None
    assert well.mapTo(surface, QPoint(0, 0)).x() == 0
    assert well.width() == surface.width()
    # A one-pixel paint guard protects every stroke from the scroll child while
    # keeping the body frame on the same x-coordinate as the outer shell.
    assert (
        margins.left(),
        margins.top(),
        margins.right(),
        margins.bottom(),
    ) == (1, 1, 1, 1)
    assert top_y is not None
    assert bottom_y is not None
    assert left_x is not None
    assert right_x is not None
    for x in (left_x, right_x):
        for y in (top_y, bottom_y):
            assert _has_separator(
                x, y, x_band=round(dpr), y_band=round(dpr)
            ), (
                f"separator corner missing at ({x}, {y})"
            )
    popup.hide()


def test_popup_bulk_buttons_emit_typed_intents_and_never_mutate_manager(qtbot):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    others, alls = [], []
    bar.close_others_requested.connect(others.append)
    bar.close_all_requested.connect(lambda: alls.append(True))
    before = [view.view_id for view in manager.views]
    popup = _open_overflow_popup(bar)
    qtbot.mouseClick(popup.findChild(QPushButton, "viewOverflowCloseOthers"), Qt.LeftButton)
    QApplication.processEvents()
    assert others == [manager.get(0).view_id]
    assert [view.view_id for view in manager.views] == before
    qtbot.wait(300)
    _resize_to_budget(bar, compact // 2)
    popup = _open_overflow_popup(bar)
    qtbot.mouseClick(popup.findChild(QPushButton, "viewOverflowCloseAll"), Qt.LeftButton)
    QApplication.processEvents()
    assert alls == [True]
    assert [view.view_id for view in manager.views] == before


def test_popup_single_view_disables_all_close_actions(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    popup.populate(
        [
            ViewOverflowRow(
                view_id="only",
                name="View 1",
                ordinal=1,
                color="#2d7ff9",
                partner_color=None,
                current=True,
                closable=False,
            )
        ]
    )
    close_btn = popup.findChild(QPushButton, "viewOverflowRowClose")
    others = popup.findChild(QPushButton, "viewOverflowCloseOthers")
    close_all = popup.findChild(QPushButton, "viewOverflowCloseAll")
    assert not close_btn.isEnabled()
    assert not others.isEnabled()
    assert not close_all.isEnabled()
    assert close_btn.toolTip() == "至少保留一个 View"
    assert others.toolTip() == "至少保留一个 View"


def test_single_view_management_popup_disables_all_close_actions(qtbot):
    _manager, bar = _wide_bar(qtbot, count=1)

    assert bar.overflow_indices() == []
    assert bar._overflow.isVisible()
    assert bar._overflow.text() == "⋯"
    popup = _open_overflow_popup(bar)
    row_close = _visible_overflow_close_buttons(popup)[0]
    others = popup.findChild(QPushButton, "viewOverflowCloseOthers")
    close_all = popup.findChild(QPushButton, "viewOverflowCloseAll")
    assert not row_close.isEnabled()
    assert not others.isEnabled()
    assert not close_all.isEnabled()
    assert "0 个" not in others.text()
    assert "0 个" not in close_all.text()


def test_popup_bulk_labels_project_exact_counts_and_dialog_ellipsis(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    others = popup.findChild(QPushButton, "viewOverflowCloseOthers")
    close_all = popup.findChild(QPushButton, "viewOverflowCloseAll")

    popup.populate(_overflow_rows(6))
    assert others.text() == "关闭其他 5 个…"
    assert close_all.text() == "关闭全部 6 个…"

    popup.populate(_overflow_rows(3))
    assert others.text() == "关闭其他 2 个…"
    assert close_all.text() == "关闭全部 3 个…"

    popup.populate(_overflow_rows(1))
    assert others.text() == "关闭其他"
    assert close_all.text() == "关闭全部"
    assert not others.isEnabled()
    assert not close_all.isEnabled()


def test_popup_escape_outside_click_and_destroy_restore_trigger_state(qtbot):
    _manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    popup = _open_overflow_popup(bar)
    assert bar._overflow.property("expanded") == "true"
    QTest.keyClick(popup, Qt.Key_Escape)
    QApplication.processEvents()
    assert bar._overflow_popup is None or not bar._overflow_popup.isVisible()
    assert bar._overflow.property("expanded") in ("false", False, None)


@pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Return])
def test_view_management_entry_keyboard_opens_and_escape_restores_focus(qtbot, key):
    _manager, bar = _wide_bar(qtbot, count=6)
    assert bar.overflow_indices() == []
    bar._overflow.setFocus(Qt.TabFocusReason)

    QTest.keyClick(bar._overflow, key)
    QApplication.processEvents()
    popup = bar._overflow_popup
    assert popup is not None and popup.isVisible()

    QTest.keyClick(popup, Qt.Key_Escape)
    QApplication.processEvents()
    assert bar._overflow_popup is None or not bar._overflow_popup.isVisible()
    assert bar._overflow.hasFocus()


def _overflow_rows(count, name_fmt="View {i}"):
    return [
        ViewOverflowRow(
            view_id=f"v{i}",
            name=name_fmt.format(i=i + 1),
            ordinal=i + 1,
            color="#2d7ff9",
            partner_color=None,
            current=i == 0,
            closable=True,
        )
        for i in range(count)
    ]


def test_overflow_popup_width_sits_between_footer_floor_and_name_ceiling(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    popup.populate(_overflow_rows(6))
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(40, 80, 40, 22)
    host.show()
    popup.show_at(host)
    QApplication.processEvents()
    assert PANEL_MIN_WIDTH <= popup.width() <= PANEL_MAX_WIDTH
    assert popup.width() <= 300
    others = popup.findChild(QPushButton, "viewOverflowCloseOthers")
    close_all = popup.findChild(QPushButton, "viewOverflowCloseAll")
    assert others.height() == 24
    assert close_all.height() == 24
    assert others.width() >= 100
    assert close_all.width() >= 100
    popup.hide()

    popup.populate(
        _overflow_rows(4, name_fmt="方向盘扭矩 / 电机转速 overlay {i}")
    )
    popup.show_at(host)
    QApplication.processEvents()
    assert PANEL_MIN_WIDTH <= popup.width() <= PANEL_MAX_WIDTH
    name = next(
        btn
        for btn in popup.findChildren(QPushButton, "viewOverflowRowName")
        if btn.isVisible()
    )
    assert name.toolTip().startswith("方向盘扭矩")
    popup.hide()


def test_overflow_popup_long_names_elide_without_hiding_close_column(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(40, 80, 40, 22)
    host.show()
    popup.populate(
        _overflow_rows(
            14,
            name_fmt=(
                "WinWert {i} · Wheel input torque Symmetry / steering-system "
                "endurance validation / left-and-right comparison"
            ),
        )
    )

    popup.show_at(host)
    QApplication.processEvents()

    viewport = popup._scroll.viewport()
    horizontal = popup._scroll.horizontalScrollBar()
    assert horizontal.maximum() == 0
    assert popup._list_host.width() == viewport.width()

    close_buttons = _visible_overflow_close_buttons(popup)
    close_lefts = []
    for close in close_buttons:
        rect = close.rect().translated(close.mapTo(viewport, QPoint(0, 0)))
        assert rect.left() >= viewport.rect().left()
        assert rect.right() <= viewport.rect().right()
        close_lefts.append(rect.left())
    assert len(set(close_lefts)) == 1

    names = [
        button
        for button in popup.findChildren(QPushButton, "viewOverflowRowName")
        if button.isVisible()
    ]
    assert all(button.text() != button.property("fullName") for button in names)
    assert all(button.toolTip() == button.property("fullName") for button in names)
    popup.hide()


def test_close_column_does_not_shift_when_scrollbar_is_idle(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(40, 80, 40, 22)
    host.show()
    popup.populate(_overflow_rows(24))
    popup.show_at(host)
    QApplication.processEvents()
    many_x = _visible_overflow_close_buttons(popup)[0].mapTo(popup, QPoint(0, 0)).x()
    popup.populate(_overflow_rows(4))
    QApplication.processEvents()
    few_x = _visible_overflow_close_buttons(popup)[0].mapTo(popup, QPoint(0, 0)).x()
    assert many_x == few_x
    assert popup.width() == PANEL_MIN_WIDTH or popup.width() >= PANEL_MIN_WIDTH
    popup.hide()


def test_reproject_restores_hover_on_close_button_under_cursor(qtbot, monkeypatch):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    popup.populate(_overflow_rows(4))
    popup.show()
    popup._apply_panel_size(popup._fitted_width or PANEL_MIN_WIDTH)
    QApplication.processEvents()
    first = _visible_overflow_close_buttons(popup)[0]
    cursor = first.mapToGlobal(first.rect().center())
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: cursor))
    popup.populate(_overflow_rows(3))
    QApplication.processEvents()
    qtbot.wait(20)
    hit = popup._chrome_at(cursor)
    assert hit is not None
    assert hit.objectName() == "viewOverflowRowClose"
    assert hit.isVisible()
    assert hit._hovered is True
    image = hit.grab().toImage()
    sample = QColor(image.pixel(image.width() // 2, 4))
    # Hover fill is #fff0f2, not idle white and not the × glyph at center.
    assert sample.red() >= 240
    assert 220 <= sample.green() <= 248
    popup.hide()


def test_popup_clamps_to_available_screen_and_keeps_footer_visible(qtbot, monkeypatch):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    rows = [
        ViewOverflowRow(
            view_id=f"v{i}",
            name=f"View {i + 1}",
            ordinal=i + 1,
            color="#2d7ff9",
            partner_color=None,
            current=i == 0,
            closable=True,
        )
        for i in range(24)
    ]
    popup.populate(rows)
    from PyQt5.QtCore import QRect

    monkeypatch.setattr(
        ViewOverflowPopup,
        "_available_geometry_for",
        lambda _self, _anchor: QRect(0, 0, 400, 280),
    )
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(20, 200, 50, 22)
    host.show()
    popup.show_at(host)
    QApplication.processEvents()
    geo = popup.geometry()
    assert geo.left() >= 8
    assert geo.right() <= 400 - 8
    assert geo.top() >= 8
    assert geo.bottom() <= 280 - 8
    footer = popup.findChild(QWidget, "viewOverflowFooter")
    assert footer is not None
    assert footer.isVisible()
    popup.hide()


def test_popup_round_surface_paints_an_opaque_center(qtbot):
    popup = ViewOverflowPopup()
    qtbot.addWidget(popup)
    popup.populate(
        [
            ViewOverflowRow(
                view_id="a",
                name="View 1",
                ordinal=1,
                color="#2d7ff9",
                partner_color=None,
                current=True,
                closable=True,
            ),
            ViewOverflowRow(
                view_id="b",
                name="View 2",
                ordinal=2,
                color="#e8590c",
                partner_color=None,
                current=False,
                closable=True,
            ),
        ]
    )
    popup._apply_panel_size(max(popup._fitted_width, PANEL_MIN_WIDTH))
    popup.show()
    QApplication.processEvents()
    from mf4_analyzer.ui_kit.popup_shell import POPUP_SHELL_FLAGS

    assert popup.testAttribute(Qt.WA_TranslucentBackground)
    assert int(popup.windowFlags()) & int(POPUP_SHELL_FLAGS) == int(POPUP_SHELL_FLAGS)
    surface = popup.findChild(QFrame, "viewOverflowSurface")
    header = popup.findChild(QWidget, "viewOverflowHeader")
    footer = popup.findChild(QWidget, "viewOverflowFooter")
    image = surface.grab().toImage()
    x = min(image.width() // 2, max(24, image.width() - 24))
    y = header.geometry().bottom() + 6
    if footer is not None:
        y = min(y, max(header.geometry().bottom() + 2, footer.geometry().top() - 6))
    sample = QColor(image.pixel(x, y))
    assert sample.alpha() == 255
    assert sample.red() > 230 and sample.green() > 230 and sample.blue() > 230
    popup.hide()


def test_section_bars_share_the_overflow_popup(qtbot):
    for section in ("time", "fft", "fft_time", "frf", "order"):
        _manager, bar = _section_bar(qtbot, section=section, count=14)
        bar.resize(4000, 30)
        bar.show()
        QApplication.processEvents()
        _roomy, compact, _overhead = _measure(bar)
        _resize_to_budget(bar, compact // 2)
        popup = _open_overflow_popup(bar)
        assert popup.objectName() == "viewOverflowPopup"
        assert popup.findChild(QLabel, "viewOverflowTitle").text() == "全部 View"
        bar._close_overflow_popup()


def test_ctrl_tab_cycles_current_section_views_and_f2_renames(qtbot):
    manager, bar = _bar(qtbot, count=3, active=0)
    bar.show()
    QApplication.processEvents()
    ids = [view.view_id for view in manager.views]
    switched = []
    bar.switch_requested.connect(switched.append)
    tabs = bar.tabBar()
    tabs.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()

    qtbot.keyClick(tabs, Qt.Key_Tab, Qt.ControlModifier)
    QApplication.processEvents()
    assert switched == [1]
    assert tabs.currentIndex() == 1
    assert [view.view_id for view in manager.views] == ids

    qtbot.keyClick(tabs, Qt.Key_Tab, Qt.ControlModifier | Qt.ShiftModifier)
    QApplication.processEvents()
    assert switched[-1] == 0
    assert tabs.currentIndex() == 0

    qtbot.keyClick(tabs, Qt.Key_F2)
    QApplication.processEvents()
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    assert editor is not None
    assert not editor.isHidden()
    assert editor.text() == manager.views[0].name
    assert editor.text() == bar._view_name(0)


def test_alt_up_down_reorders_current_view_by_stable_index(qtbot):
    manager, bar = _bar(qtbot, count=3, active=1)
    bar.show()
    QApplication.processEvents()
    ids = [view.view_id for view in manager.views]
    bar.reorder_requested.connect(manager.reorder)
    tabs = bar.tabBar()
    tabs.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()

    qtbot.keyClick(tabs, Qt.Key_Down, Qt.AltModifier)
    QApplication.processEvents()
    assert [view.view_id for view in manager.views] == [ids[0], ids[2], ids[1]]
    assert manager.views[manager.active].view_id == ids[1]

    qtbot.keyClick(tabs, Qt.Key_Up, Qt.AltModifier)
    QApplication.processEvents()
    assert [view.view_id for view in manager.views] == ids
    assert manager.views[manager.active].view_id == ids[1]

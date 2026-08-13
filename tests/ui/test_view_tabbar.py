from pathlib import Path

import pytest
from PyQt5.QtCore import QObject, Qt, pyqtSignal
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

from mf4_analyzer.ui.view_state import MAX_VIEWS, ViewManager, ViewState
from mf4_analyzer.ui.view_tabbar import ViewTabBar


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


def test_initial_plus_button_hugs_first_tab(qtbot):
    _manager, bar = _bar(qtbot, count=1)
    bar.resize(260, 28)
    bar.show()
    QApplication.processEvents()

    first_tab = bar.tabBar().tabRect(0)
    tab_right = bar.tabBar().mapTo(bar, first_tab.topRight()).x()
    gap = bar._plus.geometry().left() - tab_right - 1

    assert gap <= 3


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


def test_plus_button_follows_the_managers_own_cap_not_the_module_constant(qtbot):
    # Cap must differ from MAX_VIEWS so we prove the bar reads the instance,
    # not the module default (both are 12 in the product today).
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
    assert not bar._overflow.isVisible()
    assert sum(tabs.isTabVisible(i) for i in range(tabs.count())) == 10


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

    def fake_exec(menu, *_args):
        return next(a for a in menu.actions() if a.text() == target_name)

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    bar._on_overflow_clicked()

    # The emitted index must address the VIEW, proving setTabVisible left the
    # tab<->view index identity intact.
    assert seen == [target]


def test_overflow_menu_lists_every_view_and_checks_the_current_one(
    qtbot, monkeypatch
):
    manager, bar = _wide_bar(qtbot, count=14)
    _roomy, compact, _overhead = _measure(bar)
    _resize_to_budget(bar, compact // 2)
    captured = {}

    def fake_exec(menu, *_args):
        captured["menu"] = menu
        return None

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    bar._on_overflow_clicked()

    actions = captured["menu"].actions()
    # Full names from the manager, not the ordinal the compact tab carries.
    assert [a.text() for a in actions] == [v.name for v in manager.views]
    assert [a.isChecked() for a in actions].count(True) == 1
    assert actions[bar.tabBar().currentIndex()].isChecked()


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

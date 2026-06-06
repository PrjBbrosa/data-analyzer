from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLineEdit, QMessageBox, QPushButton

from mf4_analyzer.ui.view_state import MAX_VIEWS, ViewManager
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


def test_split_status_chip_visible_for_active_pair(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    manager.set_split(1)
    bar.show()
    QApplication.processEvents()

    assert bar._split_chip.isVisible()
    assert "View 1" in bar._split_chip.text()
    assert "View 2" in bar._split_chip.text()
    assert "当前操作 View 1" in bar._split_chip.text()

    bar.set_split_focus(True)
    assert "当前操作 View 2" in bar._split_chip.text()


def test_clear_split_chip_emits_active_index(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    manager.set_split(1)

    seen = []
    bar.clear_split_requested.connect(seen.append)
    qtbot.mouseClick(bar._split_clear, Qt.LeftButton)

    assert seen == [0]


def test_split_changed_refreshes_status_chip(qtbot):
    manager, bar = _bar(qtbot, count=2, active=0)
    bar.show()
    QApplication.processEvents()

    assert not bar._split_chip.isVisible()

    manager.set_split(1)
    QApplication.processEvents()
    assert bar._split_chip.isVisible()

    manager.clear_split_for(0)
    QApplication.processEvents()
    assert not bar._split_chip.isVisible()


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

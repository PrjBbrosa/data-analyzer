"""QuickRef control for the bottom chart-hint bar."""

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.quickref_panel import QuickRefPanel


def test_quickref_bottom_hints_toggle_notifies_host(qtbot):
    changed = []
    panel = QuickRefPanel(
        bottom_hints_visible=True,
        set_bottom_hints_visible=changed.append,
    )
    qtbot.addWidget(panel)

    assert panel._bottom_hints_toggle.isChecked()
    panel._bottom_hints_toggle.click()

    assert changed == [False]
    assert not panel._bottom_hints_toggle.isChecked()


def test_quickref_bottom_hints_toggle_hides_and_persists(qapp, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QLabel, QToolButton

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    qapp.processEvents()

    assert window.status_hints_visible()
    assert not window._status_hint_bar.isHidden()

    window.toggle_quickref_panel()
    panel = window._quickref_panel
    panel._bottom_hints_toggle.click()
    qapp.processEvents()

    assert not window.status_hints_visible()
    bar = window._status_hint_bar
    assert not bar.isHidden()
    quickref = bar.findChild(
        QToolButton, "chartHintQuickrefButton", Qt.FindDirectChildrenOnly
    )
    context = bar.findChild(QLabel, "chartHintContext", Qt.FindDirectChildrenOnly)
    discovery = bar.findChild(
        QLabel, "chartHintDiscovery", Qt.FindDirectChildrenOnly
    )
    assert quickref is not None and quickref.isVisible()
    assert context is not None and context.isVisible()
    assert discovery is not None and discovery.isVisible()
    assert context.styleSheet() == "color: transparent;"
    assert discovery.styleSheet() == "color: transparent;"
    quickref_rect = quickref.geometry()
    bar_rect = bar.rect()
    assert quickref_rect.top() >= bar_rect.top()
    assert quickref_rect.bottom() <= bar_rect.bottom()

    # The existing ``?`` entry is the only recovery route. Close the panel so
    # clicking it proves it can reopen the setting without a second button.
    panel.hide()
    quickref.click()
    qapp.processEvents()
    assert panel.isVisible()
    assert not panel._bottom_hints_toggle.isChecked()
    panel._bottom_hints_toggle.click()
    qapp.processEvents()
    assert window.status_hints_visible()
    assert not window._status_hint_bar.isHidden()

    panel._bottom_hints_toggle.click()
    qapp.processEvents()
    assert not window.status_hints_visible()

    # A section switch replaces the hint-bar widget; the hidden preference must
    # still apply to its text while retaining its original ``?`` entry.
    window.chart_stack.set_mode("fft")
    qapp.processEvents()
    bar = window._status_hint_bar
    assert not bar.isHidden()
    quickref = bar.findChild(
        QToolButton, "chartHintQuickrefButton", Qt.FindDirectChildrenOnly
    )
    context = bar.findChild(QLabel, "chartHintContext", Qt.FindDirectChildrenOnly)
    discovery = bar.findChild(
        QLabel, "chartHintDiscovery", Qt.FindDirectChildrenOnly
    )
    assert quickref is not None and quickref.isVisible()
    assert context is not None and context.isVisible()
    assert discovery is not None and discovery.isVisible()
    assert context.styleSheet() == "color: transparent;"
    assert discovery.styleSheet() == "color: transparent;"

    restored = MainWindow()
    qtbot.addWidget(restored)
    assert not restored.status_hints_visible()
    restored_bar = restored._status_hint_bar
    assert not restored_bar.isHidden()
    restored_quickref = restored_bar.findChild(
        QToolButton, "chartHintQuickrefButton", Qt.FindDirectChildrenOnly
    )
    assert restored_quickref is not None

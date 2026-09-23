"""Command-registry wiring for「扩展管理…」. No Tk window."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAction, QMainWindow, QStyleOptionToolButton

from mf4_analyzer.ui.command_registry import CommandId, object_name_for
from mf4_analyzer.ui.hints import all_hints
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window.command_coordinator import (
    CommandCoordinator,
    extension_import_offers_manager,
)


class _Host(QMainWindow):
    def __init__(self):
        super().__init__()
        self.calls = []

    def open_extension_manager(self):
        self.calls.append("open_extension_manager")


def test_manage_extensions_action_uses_bound_method(qapp):
    host = _Host()
    coord = CommandCoordinator(host)
    action = coord.action(CommandId.MANAGE_EXTENSIONS)
    assert isinstance(action, QAction)
    assert action.objectName() == object_name_for(CommandId.MANAGE_EXTENSIONS)
    assert action.text() == "扩展管理…"
    action.trigger()
    qapp.processEvents()
    assert host.calls == ["open_extension_manager"]


def test_extension_hint_is_hidden():
    assert all(item.id != "file.extension_manager" for item in all_hints())


def test_status_help_opens_manual_without_extension_dropdown(qapp, qtbot, monkeypatch):
    from mf4_analyzer import help as help_module

    opened = []

    def open_guide(name):
        opened.append(name)
        return True

    monkeypatch.setattr(help_module, "open_guide", open_guide)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qapp.processEvents()
    button = window._help_btn
    assert button.menu() is None
    option = QStyleOptionToolButton()
    button.initStyleOption(option)
    assert not option.features & QStyleOptionToolButton.MenuButtonPopup
    assert button.toolTip() == "软件说明"
    qtbot.mouseClick(button, Qt.LeftButton)
    assert opened == ["manual"]


def test_component_reason_offers_manager_from_availability():
    class Avail:
        reason_code = "COMPONENT_INCOMPATIBLE"

    class Exc(Exception):
        availability = Avail()

    assert extension_import_offers_manager(Exc())

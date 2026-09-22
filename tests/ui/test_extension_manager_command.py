"""Command-registry wiring for「扩展管理…」. No Tk window."""
from __future__ import annotations

from PyQt5.QtWidgets import QAction, QMainWindow

from mf4_analyzer.ui.command_registry import CommandId, object_name_for
from mf4_analyzer.ui.hints import all_hints, hint_display_width, HINT_MAX_WIDTH
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


def test_extension_hint_fits_footer_budget():
    hint = next(item for item in all_hints() if item.id == "file.extension_manager")
    assert hint_display_width(hint.text) <= HINT_MAX_WIDTH
    assert "扩展管理" in hint.text


def test_component_reason_offers_manager_from_availability():
    class Avail:
        reason_code = "COMPONENT_INCOMPATIBLE"

    class Exc(Exception):
        availability = Avail()

    assert extension_import_offers_manager(Exc())

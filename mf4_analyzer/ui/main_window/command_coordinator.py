"""MainWindow owner of global QActions and compact-toolbar wiring.

The registry stays Qt-metadata-only. This coordinator owns the *live* QActions
and connects them to existing named slots. It does not copy project IO, and it
does not register chart-camera or View-identity shortcuts (those stay on their
Task 3 / Task 4 owners).
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtWidgets import QAction, QApplication

from ...ui_kit.widgets import SearchField
from ..command_registry import (
    CommandId,
    bindings_for,
    metadata_for,
    object_name_for,
    tooltip_for,
)

# Window-scoped commands whose shortcuts this coordinator may install.
# Chart camera and View cycling stay unregistered here so they cannot fight
# the chart card (Alt+Left) or steal View identity (Ctrl+Tab / F2).
_INSTALL_WINDOW_SHORTCUTS = frozenset({
    CommandId.OPEN_PROJECT,
    CommandId.OPEN_RECENT,
    CommandId.SAVE_PROJECT,
    CommandId.SAVE_PROJECT_AS,
    CommandId.QUIT,
    CommandId.FIND,
    CommandId.QUICK_REFERENCE,
})

class CommandCoordinator(QObject):
    """One QAction per global command, owned by the host window."""

    def __init__(self, host, parent=None):
        super().__init__(parent if parent is not None else host)
        self._host = host
        self._actions: dict[CommandId, QAction] = {}
        self._toolbar_bound = False
        self._quit_published = False
        self._build_actions()
        self._connect_host_slots()
        self._claim_quickref_shortcut()

    def action(self, command_id: CommandId) -> QAction:
        return self._actions[command_id]

    def actions(self) -> dict[CommandId, QAction]:
        return dict(self._actions)

    def _build_actions(self) -> None:
        host = self._host
        for command_id in CommandId:
            meta = metadata_for(command_id)
            action = QAction(meta.label, host)
            action.setObjectName(object_name_for(command_id))
            action.setToolTip(tooltip_for(command_id))
            action.setStatusTip(meta.help_text)
            if command_id in _INSTALL_WINDOW_SHORTCUTS:
                seqs = bindings_for(command_id)
                if seqs:
                    action.setShortcuts(seqs)
                    action.setShortcutContext(Qt.WindowShortcut)
            if command_id in (CommandId.UNDO, CommandId.REDO, CommandId.QUIT):
                action.setEnabled(False)
            if command_id == CommandId.QUIT:
                # Keep macOS from promoting this to a working app-menu Quit
                # before Task 5's dirty guard exists.
                action.setMenuRole(QAction.NoRole)
            self._actions[command_id] = action
            if command_id in _INSTALL_WINDOW_SHORTCUTS:
                # A parented QAction does not participate in shortcut
                # dispatch until a widget owns it. Register only the live
                # window commands; contextual registry entries remain inert
                # metadata/actions and never become invisible dead commands.
                host.addAction(action)

    def _connect_host_slots(self) -> None:
        self._actions[CommandId.OPEN_PROJECT].triggered.connect(self._on_open)
        self._actions[CommandId.OPEN_RECENT].triggered.connect(self._on_open_recent)
        self._actions[CommandId.SAVE_PROJECT].triggered.connect(self._on_save)
        self._actions[CommandId.SAVE_PROJECT_AS].triggered.connect(self._on_save_as)
        self._actions[CommandId.FIND].triggered.connect(self._on_find)
        self._actions[CommandId.QUICK_REFERENCE].triggered.connect(
            self._on_quick_reference
        )
        # Quit stays disconnected until MainWindow.publish_quit after the
        # dirty guard exists. Undo/Redo stay disconnected until Task 3
        # routes them to the active edit owner.

    def publish_quit(self, slot) -> None:
        """Enable Quit and connect it after the dirty guard is installed.

        FakeHost T1 tests never call this, so they keep seeing a disabled,
        unhooked Quit action.
        """
        if getattr(self, "_quit_published", False):
            return
        action = self._actions[CommandId.QUIT]
        action.triggered.connect(slot)
        action.setEnabled(True)
        action.setMenuRole(QAction.QuitRole)
        self._quit_published = True

    def _on_open(self, checked=False) -> None:
        method = getattr(self._host, "open_files_or_project", None)
        if callable(method):
            method()

    def _on_open_recent(self, checked=False) -> None:
        toolbar = getattr(self._host, "toolbar", None)
        if toolbar is None:
            return
        show = getattr(toolbar, "show_recent_popup", None)
        if callable(show):
            show()

    def _on_save(self, checked=False) -> None:
        method = getattr(self._host, "save_project_via_dialog", None)
        if callable(method):
            method()

    def _on_save_as(self, checked=False) -> None:
        method = getattr(self._host, "save_project_as_via_dialog", None)
        if callable(method):
            method()

    def _on_find(self, checked=False) -> None:
        """Focus the active search surface, else open QuickRef's search."""
        focus = QApplication.focusWidget()
        host = self._host
        search_window = focus.window() if focus is not None else host
        for search in search_window.findChildren(SearchField):
            if search.isVisible():
                search.setFocus(Qt.ShortcutFocusReason)
                search.selectAll()
                return
        panel = getattr(host, "_quickref_panel", None)
        if panel is not None and panel.isVisible():
            self._focus_quickref_search(panel)
            return
        toggle = getattr(host, "toggle_quickref_panel", None)
        if callable(toggle):
            toggle()
        panel = getattr(host, "_quickref_panel", None)
        if panel is not None:
            self._focus_quickref_search(panel)

    def _on_quick_reference(self, checked=False) -> None:
        toggle = getattr(self._host, "toggle_quickref_panel", None)
        if callable(toggle):
            toggle()

    @staticmethod
    def _focus_quickref_search(panel) -> None:
        search = getattr(panel, "_search", None)
        if search is None:
            return
        search.setFocus(Qt.ShortcutFocusReason)
        if hasattr(search, "selectAll"):
            search.selectAll()

    def _claim_quickref_shortcut(self) -> None:
        """Drop the legacy ``?`` QShortcut so only its QAction owns it."""
        shortcut = getattr(self._host, "_quickref_shortcut", None)
        if shortcut is None:
            return
        shortcut.setEnabled(False)

    def bind_toolbar(self, toolbar=None) -> None:
        """Point toolbar file chips at the same QActions the menus use."""
        if self._toolbar_bound:
            return
        if toolbar is None:
            toolbar = getattr(self._host, "toolbar", None)
        if toolbar is None:
            return
        bind = getattr(toolbar, "bind_command_actions", None)
        if callable(bind):
            bind(
                self._actions[CommandId.OPEN_PROJECT],
                self._actions[CommandId.SAVE_PROJECT],
                self._actions[CommandId.SAVE_PROJECT_AS],
                self._actions[CommandId.OPEN_RECENT],
            )
        self._toolbar_bound = True

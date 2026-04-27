"""Drop-in replacement for QComboBox that supports type-to-filter search.

Usage:
    cb = SearchableComboBox(parent)
    cb.addItems(channel_names)

The completer matches anywhere in the string (substring), case-insensitive.
After every model change (addItem, addItems, clear, insertItem) the completer
is re-bound to the live model so its filter stays correct.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QCompleter


class SearchableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(self)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)
        self._rebind_completer_model()

    def _rebind_completer_model(self):
        c = self.completer()
        if c is not None:
            c.setModel(self.model())

    # Methods that mutate the item set: re-bind after each.
    def addItem(self, *args, **kwargs):
        super().addItem(*args, **kwargs)
        self._rebind_completer_model()

    def addItems(self, items):
        super().addItems(items)
        self._rebind_completer_model()

    def insertItem(self, *args, **kwargs):
        super().insertItem(*args, **kwargs)
        self._rebind_completer_model()

    def insertItems(self, *args, **kwargs):
        super().insertItems(*args, **kwargs)
        self._rebind_completer_model()

    def clear(self):
        super().clear()
        self._rebind_completer_model()

    def setCurrentText(self, text):
        """Drop-in compatible: when ``text`` matches an existing item, also
        update ``currentIndex`` (default ``QComboBox.setCurrentText`` only sets
        the line-edit text on editable combos, leaving the index stale)."""
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            super().setCurrentText(text)

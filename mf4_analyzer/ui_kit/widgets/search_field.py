"""One shared search-input primitive for Analyzer and Cockpit surfaces."""
from __future__ import annotations

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QLineEdit

from ..control_style import CONTROL_HEIGHTS
from ..icons import ensure_icon_cache


class SearchField(QLineEdit):
    """A base-track search input with cached leading icon and clear affordance."""

    _cached_search_icon: QIcon | None = None

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setProperty("role", "search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setFixedHeight(CONTROL_HEIGHTS["base"])
        self.addAction(self._search_icon(), QLineEdit.LeadingPosition)

    @classmethod
    def _search_icon(cls) -> QIcon:
        if cls._cached_search_icon is None:
            icon_path = ensure_icon_cache()["ICON_SEARCH"]
            cls._cached_search_icon = QIcon(icon_path)
        return cls._cached_search_icon

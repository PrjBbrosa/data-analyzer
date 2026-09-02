"""One shared search-input primitive for Analyzer and Cockpit surfaces."""
from __future__ import annotations

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QLineEdit, QToolButton

from ..control_style import CONTROL_HEIGHTS
from ..icons import Icons

_ICON_PX = 14
_SIDE_PAD = 6
_BUTTON_PX = 18


class SearchField(QLineEdit):
    """A base-track search input with crisp, vertically centered icons.

    Qt's stock clear button and ``addAction`` side widgets both mis-align on
    Windows inside the 32px base track, and the old 12px qtawesome magnifier
    looked coarse. This control paints its own leading/trailing tool buttons
    and reserves text margins so the glyphs stay on the optical midline.

    Esc is layered: non-empty text clears and stays focused; empty text emits
    ``escape_requested`` so the host can close and restore opener focus.
    Return/Enter is consumed here so a parent ``QDialog`` default button is
    not clicked (QLineEdit otherwise ignores Return after emitting
    ``returnPressed``).
    """

    escape_requested = pyqtSignal()

    _cached_search_icon: QIcon | None = None
    _cached_clear_icon: QIcon | None = None

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setProperty("role", "search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(False)
        self.setFixedHeight(CONTROL_HEIGHTS["base"])

        self._search_button = self._make_side_button(
            self._search_icon(), decorative=True,
        )
        self._clear_button = self._make_side_button(
            self._clear_icon(), decorative=False,
        )
        self._clear_button.hide()
        self._clear_button.clicked.connect(self.clear)
        self._clear_button.setToolTip("清除")
        self.textChanged.connect(self._sync_clear_button)
        self._apply_text_margins()

    def _make_side_button(self, icon: QIcon, *, decorative: bool) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("searchFieldIconButton")
        button.setIcon(icon)
        button.setIconSize(QSize(_ICON_PX, _ICON_PX))
        button.setFixedSize(_BUTTON_PX, _BUTTON_PX)
        button.setFocusPolicy(Qt.NoFocus)
        button.setCursor(Qt.ArrowCursor)
        button.setAutoRaise(True)
        if decorative:
            button.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        return button

    def _apply_text_margins(self) -> None:
        left = _SIDE_PAD + _BUTTON_PX
        right = _SIDE_PAD + _BUTTON_PX
        self.setTextMargins(left, 0, right, 0)

    def _sync_clear_button(self, text: str) -> None:
        self._clear_button.setVisible(bool(text))
        self._relayout_side_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_side_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout_side_buttons()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key == Qt.Key_Escape:
            self._handle_escape()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            # QLineEdit emits returnPressed then ignores Return, which lets a
            # parent QDialog click its default button. Consume it in the search
            # domain: hosts may still listen to returnPressed for next-match.
            super().keyPressEvent(event)
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_escape(self) -> None:
        if self.text():
            self.clear()
            return
        self.escape_requested.emit()

    def _relayout_side_buttons(self) -> None:
        y = max(0, (self.height() - _BUTTON_PX) // 2)
        self._search_button.move(_SIDE_PAD, y)
        self._clear_button.move(
            max(_SIDE_PAD, self.width() - _SIDE_PAD - _BUTTON_PX), y,
        )

    @classmethod
    def _search_icon(cls) -> QIcon:
        if cls._cached_search_icon is None:
            cls._cached_search_icon = Icons.search()
        return cls._cached_search_icon

    @classmethod
    def _clear_icon(cls) -> QIcon:
        if cls._cached_clear_icon is None:
            cls._cached_clear_icon = Icons.clear_field()
        return cls._cached_clear_icon

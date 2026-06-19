"""Central QComboBox popup chrome and sizing.

QComboBox popups are rendered in a top-level private container
(``QComboBoxPrivateContainer``). Styling only the inner item view is not
enough: the native popup window can draw an opaque square frame or shadow for
one frame before the rounded list paints. This module prepares the popup
window, list view, viewport background, and width from one application-level
event filter so individual combo call sites do not carry popup policy.
"""
from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QComboBox, QFrame


_SHELL_FLAGS = Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
_MAX_QWIDGET_SIZE = 16777215

_POPUP_VIEW_QSS = """
QAbstractItemView {
    padding: 4px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background-color: #ffffff;
    outline: none;
    selection-background-color: transparent;
    selection-color: #111827;
}
QAbstractItemView::item {
    min-height: 24px;
    padding: 4px 8px;
    border: none;
    border-radius: 6px;
    background-color: #ffffff;
    color: #111827;
}
QAbstractItemView::item:hover,
QAbstractItemView::item:selected {
    border: none;
    border-radius: 6px;
    background-color: #1769e0;
    color: #ffffff;
}
"""


def _apply_shell(window):
    """Apply a transparent, frameless shell to a popup window once."""
    if window is None or window.testAttribute(Qt.WA_TranslucentBackground):
        return False
    window.setWindowFlags(window.windowFlags() | _SHELL_FLAGS)
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    window.setStyleSheet(
        "QComboBoxPrivateContainer, QFrame { "
        "border: none; background: transparent; }"
    )
    return True


def _int_property(widget, name):
    value = widget.property(name)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _apply_view_chrome(view):
    if view is None:
        return
    view.setFrameShape(QFrame.NoFrame)
    view.setLineWidth(0)
    view.setMidLineWidth(0)
    view.setAttribute(Qt.WA_StyledBackground, True)
    if view.styleSheet() != _POPUP_VIEW_QSS:
        view.setStyleSheet(_POPUP_VIEW_QSS)

    viewport = view.viewport()
    if viewport is not None:
        palette = viewport.palette()
        white = QColor("#ffffff")
        palette.setColor(QPalette.Base, white)
        palette.setColor(QPalette.Window, white)
        viewport.setPalette(palette)
        viewport.setAutoFillBackground(True)
        viewport.setStyleSheet("background-color: #ffffff;")


def _sync_popup_width(combo, view):
    if combo is None or view is None:
        return
    fixed = _int_property(combo, "popupWidth")
    if fixed is not None:
        view.setMinimumWidth(fixed)
        view.setMaximumWidth(fixed)
        return

    minimum = _int_property(combo, "popupMinWidth")
    maximum = _int_property(combo, "popupMaxWidth")
    width = max(1, combo.width())
    if minimum is None and maximum is None:
        view.setMinimumWidth(width)
        view.setMaximumWidth(width)
        return
    if minimum is not None:
        width = max(width, minimum)
    view.setMinimumWidth(width)
    if maximum is not None:
        view.setMaximumWidth(max(width, maximum))
    else:
        view.setMaximumWidth(_MAX_QWIDGET_SIZE)


def _popup_views(combo):
    views = []
    view = combo.view()
    if view is not None:
        views.append(view)
    completer = combo.completer()
    if completer is not None:
        popup = completer.popup()
        if popup is not None and popup not in views:
            views.append(popup)
    return views


def prepare_combo_popup(combo):
    """Prepare popup shell, first-frame background, and width.

    Dynamic properties:
    - ``popupWidth`` fixes the popup width.
    - ``popupMinWidth`` and ``popupMaxWidth`` bound the popup width.
    """
    if not isinstance(combo, QComboBox):
        return combo
    for view in _popup_views(combo):
        _apply_view_chrome(view)
        _apply_shell(view.window())
        _sync_popup_width(combo, view)
    return combo


class _ComboPopupShellFilter(QObject):
    """Application event filter that prepares every combo dropdown."""

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type in (
            QEvent.Polish,
            QEvent.Show,
            QEvent.MouseButtonPress,
            QEvent.FocusIn,
        ):
            if isinstance(obj, QComboBox):
                prepare_combo_popup(obj)
        if event_type == QEvent.Show:
            if obj.metaObject().className() == "QComboBoxPrivateContainer":
                if _apply_shell(obj):
                    obj.show()
        return False


_filter_ref = []


def install_combo_popup_shell(app):
    """Install the combo-popup shell filter on ``app`` idempotently."""
    if _filter_ref:
        return _filter_ref[0]
    filt = _ComboPopupShellFilter(app)
    app.installEventFilter(filt)
    _filter_ref.append(filt)
    return filt

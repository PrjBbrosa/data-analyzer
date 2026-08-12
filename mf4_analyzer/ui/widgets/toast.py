"""Floating non-blocking acknowledgement toast."""
from PyQt5.QtCore import Qt, QPropertyAnimation, QTimer
from PyQt5.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel

from ...ui_kit.qt_lifecycle import as_weak_callable


class Toast(QFrame):
    """Floating non-blocking acknowledgement toast.

    One toast at a time per parent: a new message replaces the current one
    instead of stacking, which keeps the bottom edge of the window clean and
    matches user expectation that "the latest action wins". Levels map to
    accent colors (info/success/warning/error) defined in style.qss.
    """

    _HOLD_MS = {'info': 3500, 'success': 3500, 'warning': 5000, 'error': 7000}

    #: Final fallback clearance when no host-derived margin is available
    #: (construct-time estimate / headless hosts without chrome). Prefer a
    #: ``margin_provider`` or ``set_bottom_margin`` from real neighbor heights
    #: at display time — see MainWindow / BatchSheet / MarkupEditor.
    DEFAULT_BOTTOM_MARGIN = 100

    def __init__(self, parent=None, *, bottom_margin=None, margin_provider=None):
        super().__init__(parent)
        # Explicit pin (BatchSheet historically passed footer+gap once). ``None``
        # means "resolve via provider, else DEFAULT_BOTTOM_MARGIN".
        self._bottom_margin_override = (
            None if bottom_margin is None else int(bottom_margin)
        )
        # Bound-method providers must not keep the host alive past Qt teardown
        # (BatchSheet→Toast→bound method→BatchSheet cycle → zombie wrapper).
        self._margin_provider = as_weak_callable(margin_provider)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(10)
        self._icon = QLabel(self)
        self._icon.setObjectName("toastIcon")
        self._msg = QLabel("", self)
        self._msg.setObjectName("toastText")
        self._msg.setTextFormat(Qt.PlainText)
        lay.addWidget(self._icon)
        lay.addWidget(self._msg)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(180)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.hide()

    _GLYPHS = {
        'info': '✓',
        'success': '✓',
        'warning': '!',
        'error': '✕',
    }

    def set_bottom_margin(self, margin):
        """Pin clearance in px, or ``None`` to resume provider / default."""
        self._bottom_margin_override = None if margin is None else int(margin)
        if self.isVisible():
            self._reposition()

    def set_margin_provider(self, provider):
        """Callable returning clearance px at show/reposition time."""
        self._margin_provider = as_weak_callable(provider)
        if self.isVisible():
            self._reposition()

    def _resolved_bottom_margin(self):
        if self._bottom_margin_override is not None:
            return max(0, int(self._bottom_margin_override))
        provider = self._margin_provider
        if callable(provider):
            try:
                value = provider()
            except Exception:
                value = None
            if value is not None:
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    pass
        return self.DEFAULT_BOTTOM_MARGIN

    def show_message(self, text, level='info'):
        level = level if level in self._HOLD_MS else 'info'
        self.setProperty('level', level)
        self._icon.setProperty('level', level)
        # Re-polish to reapply QSS based on new property value.
        self.style().unpolish(self); self.style().polish(self)
        self._icon.style().unpolish(self._icon); self._icon.style().polish(self._icon)
        self._icon.setText(self._GLYPHS[level])
        self._msg.setText(text)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        # Drop any leftover fade-out → hide connection so this fade-in
        # doesn't get auto-dismissed when it reaches full opacity.
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._hide_timer.start(self._HOLD_MS[level])

    def _fade_out(self):
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(self.hide)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - self._resolved_bottom_margin()
        self.move(max(8, x), max(8, y))

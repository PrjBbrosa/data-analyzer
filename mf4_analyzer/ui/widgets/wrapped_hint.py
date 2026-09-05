"""A wrapped hint keeps enough vertical space at its current width."""
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QFrame


class WrappedHintFrame(QFrame):
    """Propagate width-dependent content height as a non-clippable minimum.

    Form layouts may otherwise shrink a wrapped label toward its one-line
    minimum. Recompute on layout/font/style changes and actual resizes, so a
    wider row can also release previously required space. No delayed timer or
    fixed pixel height is needed.
    """

    def event(self, event):
        result = super().event(event)
        if event.type() in (
            QEvent.Resize, QEvent.Show, QEvent.LayoutRequest,
            QEvent.FontChange, QEvent.ApplicationFontChange, QEvent.StyleChange,
        ):
            layout = self.layout()
            if layout is not None and layout.hasHeightForWidth():
                required = max(
                    layout.minimumSize().height(),
                    layout.totalHeightForWidth(self.width()),
                )
                if required != self.minimumHeight():
                    self.setMinimumHeight(required)
                    self.updateGeometry()
        return result

"""Collapsible parameter section widget for inspector contextuals."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ._helpers import _preset_settings, _settings_bool


class _CollapsibleParamSection(QWidget):
    """Merged preset + advanced-params section for contextual inspectors."""

    def __init__(
        self,
        title,
        settings_key,
        *,
        settings=None,
        default_expanded=False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("inspectorParamSection")
        self._settings = settings if settings is not None else _preset_settings()
        self._settings_key = settings_key
        self._expanded = _settings_bool(
            self._settings,
            self._settings_key,
            default_expanded,
        )
        self._body_widget = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        header = QWidget(self)
        header.setObjectName("inspectorParamHeader")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.setSpacing(6)

        self.btn_collapser = QToolButton(header)
        self.btn_collapser.setObjectName("inspectorCollapser")
        self.btn_collapser.setCheckable(True)
        self.btn_collapser.setAutoRaise(True)
        self.btn_collapser.setText(title)
        self.btn_collapser.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_collapser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        try:
            self.btn_collapser.setStyleSheet(
                "QToolButton#inspectorCollapser { "
                "  text-align: left; padding: 4px 6px; font-weight: 600; "
                "  border: none; background: transparent; "
                "}"
                "QToolButton#inspectorCollapser:hover { background: #eef2f7; }"
            )
        except Exception:  # pragma: no cover - defensive on Qt style failures
            pass
        self.btn_collapser.toggled.connect(self.set_expanded)
        header_lay.addWidget(self.btn_collapser, 1)

        self._summary = QLabel("", header)
        self._summary.setObjectName("inspectorParamSummary")
        self._summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._summary.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._summary.setStyleSheet(
            "QLabel#inspectorParamSummary { color: #64748b; font-size: 11px; }"
        )
        header_lay.addWidget(self._summary, 0)
        root.addWidget(header)

        self._persistent_host = QWidget(self)
        self._persistent_host.setObjectName("inspectorParamPersistentHost")
        self._persistent_lay = QVBoxLayout(self._persistent_host)
        self._persistent_lay.setContentsMargins(0, 0, 0, 0)
        self._persistent_lay.setSpacing(4)
        root.addWidget(self._persistent_host)

        self._body = QFrame(self)
        self._body.setObjectName("inspectorParamBody")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(0)
        root.addWidget(self._body)

        self._sync_expanded(persist=False)

    def set_summary(self, text):
        self._summary.setText(str(text))

    def summary_text(self):
        return self._summary.text()

    def add_persistent(self, widget):
        self._persistent_lay.addWidget(widget)

    def set_body(self, widget):
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)
        self._body_widget = widget
        self._body_lay.addWidget(widget)
        widget.setVisible(self._expanded)
        self._body.setVisible(self._expanded)

    def is_expanded(self):
        return bool(self._expanded)

    def set_expanded(self, expanded):
        expanded = bool(expanded)
        if self._expanded == expanded:
            self._sync_expanded(persist=True)
            return
        self._expanded = expanded
        self._sync_expanded(persist=True)

    def _sync_expanded(self, *, persist):
        self.btn_collapser.blockSignals(True)
        self.btn_collapser.setChecked(self._expanded)
        self.btn_collapser.blockSignals(False)
        self.btn_collapser.setArrowType(
            Qt.DownArrow if self._expanded else Qt.RightArrow
        )
        self._body.setVisible(self._expanded)
        if self._body_widget is not None:
            self._body_widget.setVisible(self._expanded)
        if persist:
            self._settings.setValue(self._settings_key, self._expanded)

"""Collapsible parameter section widget for inspector contextuals."""
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPointF, QSize, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap, QPolygonF, QRegion
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWIDGETSIZE_MAX,
    QWidget,
)

from mf4_analyzer.ui_kit.motion import (
    POLICY_OFF,
    ValueDriver,
    duration_ms,
    resolve_policy,
)

from ._helpers import _preset_settings, _settings_bool

_EATEN_INPUT_EVENTS = frozenset(
    {
        QEvent.MouseButtonPress,
        QEvent.MouseButtonRelease,
        QEvent.MouseButtonDblClick,
        QEvent.MouseMove,
        QEvent.Wheel,
        QEvent.HoverEnter,
        QEvent.HoverMove,
        QEvent.HoverLeave,
        QEvent.Enter,
        QEvent.Leave,
        QEvent.ContextMenu,
        QEvent.TabletPress,
        QEvent.TabletRelease,
        QEvent.TabletMove,
    }
)


class _BodyInputShield(QWidget):
    """Eats pointer hits without changing descendant enabled state."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("inspectorParamBodyInputShield")
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def event(self, event):
        if event.type() in _EATEN_INPUT_EVENTS:
            event.accept()
            return True
        return super().event(event)


class _ElidedSummaryLabel(QLabel):
    """Header summary that yields width and paints an elided full string."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self):
        return super().sizeHint()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        elided = self.fontMetrics().elidedText(
            self.text(), Qt.ElideRight, max(0, self.width()),
        )
        painter.drawText(
            self.rect(), int(self.alignment() | Qt.TextSingleLine), elided,
        )


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
        self._motion_policy = POLICY_OFF
        self._motion_target_height = None
        self._presented_openness = 1.0 if self._expanded else 0.0
        self._arrow_degrees = 90.0 if self._expanded else 0.0
        self._input_shielded = False
        self._saved_focus_policies = []
        self._rebasing_clock = False

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

        self._summary = _ElidedSummaryLabel("", header)
        self._summary.setObjectName("inspectorParamSummary")
        self._summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._summary.setMinimumWidth(0)
        self._summary.setStyleSheet(
            "QLabel#inspectorParamSummary { color: #64748b; font-size: 11px; }"
        )
        header_lay.addWidget(self._summary, 1)
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

        self._input_shield = _BodyInputShield(self._body)
        self._body.installEventFilter(self)
        self._openness_driver = ValueDriver(self, on_value=self._on_openness)

        self._sync_expanded(persist=False)

    def motion_policy(self):
        return self._motion_policy

    def set_motion_policy(self, policy):
        self._motion_policy = resolve_policy(policy)
        self._snap_presentation()

    def set_summary(self, text):
        text = str(text)
        self._summary.setText(text)
        self._summary.setToolTip(text if text else "")

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
        self._motion_target_height = None
        if self._openness_driver.is_active() or self._motion_policy.interpolates():
            self._snap_presentation()
            return
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

    def hideEvent(self, event):
        if self._openness_driver.is_active():
            self._snap_presentation()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        old = event.oldSize()
        if (
            self._openness_driver.is_active()
            and old.width() >= 0
            and old.width() != event.size().width()
        ):
            self._snap_presentation()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and self._openness_driver.is_active():
            self._snap_presentation()

    def eventFilter(self, watched, event):
        if watched is self._body and event.type() == QEvent.Resize:
            self._sync_shield_geometry()
        return False

    def _sync_expanded(self, *, persist):
        self.btn_collapser.blockSignals(True)
        self.btn_collapser.setChecked(self._expanded)
        self.btn_collapser.blockSignals(False)
        if persist:
            self._settings.setValue(self._settings_key, self._expanded)
        if not self._motion_policy.interpolates():
            self._snap_presentation()
            return
        self._present_interpolated()

    def _snap_presentation(self):
        intended = 1.0 if self._expanded else 0.0
        self._openness_driver.snap(intended)

    def _present_interpolated(self):
        intended = 1.0 if self._expanded else 0.0
        current = self._openness_driver.current()
        if current is None:
            current = self._presented_openness
            self._openness_driver.snap(current)
            if abs(float(current) - intended) < 1e-9:
                return
        if self._openness_driver.target() == intended and (
            self._openness_driver.is_active() or current == intended
        ):
            return
        if self._expanded:
            self._prepare_expand()
            name = "collapse_expand"
        else:
            self._prepare_collapse()
            name = "collapse_collapse"
        self._rebase_clock()
        self._openness_driver.go(
            intended,
            duration_ms=duration_ms(name, self._motion_policy),
        )

    def _prepare_expand(self):
        self._set_body_input_blocked(False)
        self._ensure_body_shown()
        self._layout_body_at_target_width()
        self._motion_target_height = self._natural_body_height()
        self._apply_openness_frame(self._current_openness())

    def _prepare_collapse(self):
        self._transfer_focus_from_body()
        self._ensure_body_shown()
        if self._motion_target_height is None:
            self._motion_target_height = self._natural_body_height()
        self._set_body_input_blocked(True)
        self._apply_openness_frame(self._current_openness())

    def _current_openness(self):
        current = self._openness_driver.current()
        if current is None:
            return self._presented_openness
        return float(current)

    def _rebase_clock(self):
        clock = self._openness_driver.clock()
        if self._openness_driver.is_active():
            self._openness_driver.stop_and_keep()
        if clock.currentTime() == 0:
            return
        current = self._current_openness()
        self._rebasing_clock = True
        clock.stop()
        clock.setStartValue(current)
        clock.setEndValue(current)
        clock.setDuration(1)
        clock.setCurrentTime(0)
        self._rebasing_clock = False

    def _ensure_body_shown(self):
        self._body.setVisible(True)
        if self._body_widget is not None:
            self._body_widget.setVisible(True)

    def _layout_body_at_target_width(self):
        width = self._body.width()
        if width <= 0:
            width = max(self.width(), 1)
            self._body.resize(width, max(self._body.height(), 0))
        root = self.layout()
        if root is not None:
            root.activate()
        self._body_lay.activate()

    def _natural_body_height(self):
        width = self._body.width()
        if width <= 0:
            width = max(self.width(), 1)
        if self._body.hasHeightForWidth():
            return max(0, int(self._body.heightForWidth(width)))
        return max(0, int(self._body.sizeHint().height()))

    def _on_openness(self, value):
        if self._rebasing_clock:
            return
        openness = float(value)
        self._apply_openness_frame(openness)
        if self._openness_driver.is_active():
            return
        intended = 1.0 if self._expanded else 0.0
        current = self._openness_driver.current()
        if current is None:
            return
        if abs(float(current) - intended) < 1e-9:
            self._settle_presentation()

    def _apply_openness_frame(self, openness):
        openness = max(0.0, min(1.0, float(openness)))
        self._presented_openness = openness
        if self._expanded or openness > 0.0:
            self._ensure_body_shown()
        natural = self._motion_target_height
        if natural is None:
            natural = self._natural_body_height()
        clip = int(round(openness * natural))
        if (
            self._motion_target_height is not None
            or self._openness_driver.is_active()
            or 0.0 < openness < 1.0
        ):
            self._apply_clip_height(clip)
        self._apply_arrow_degrees(openness * 90.0)

    def _apply_clip_height(self, height):
        clip = max(0, int(height))
        self._body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._body.setMinimumHeight(clip)
        self._body.setMaximumHeight(clip)
        if clip <= 0:
            self._body.clearMask()
        else:
            self._body.setMask(QRegion(0, 0, max(self._body.width(), 1), clip))
        self.updateGeometry()

    def _release_clip_height(self):
        self._body.clearMask()
        self._body.setMinimumHeight(0)
        self._body.setMaximumHeight(QWIDGETSIZE_MAX)
        self._body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.updateGeometry()

    def _apply_arrow_degrees(self, degrees):
        degrees = max(0.0, min(90.0, float(degrees)))
        self._arrow_degrees = degrees
        if degrees <= 0.5:
            self.btn_collapser.setIcon(QIcon())
            self.btn_collapser.setArrowType(Qt.RightArrow)
            return
        if degrees >= 89.5:
            self.btn_collapser.setIcon(QIcon())
            self.btn_collapser.setArrowType(Qt.DownArrow)
            return
        self.btn_collapser.setArrowType(Qt.NoArrow)
        self.btn_collapser.setIcon(self._make_arrow_icon(degrees))

    def _make_arrow_icon(self, degrees):
        dpr = max(1.0, float(self.devicePixelRatioF()))
        logical = 12
        side = max(12, int(round(logical * dpr)))
        pixmap = QPixmap(side, side)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(logical / 2.0, logical / 2.0)
        painter.rotate(degrees)
        color = self.btn_collapser.palette().color(
            self.btn_collapser.foregroundRole()
        )
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        span = 3.5
        painter.drawPolygon(
            QPolygonF(
                (
                    QPointF(-span * 0.4, -span),
                    QPointF(-span * 0.4, span),
                    QPointF(span, 0.0),
                )
            )
        )
        painter.end()
        return QIcon(pixmap)

    def _settle_presentation(self):
        self._motion_target_height = None
        self._set_body_input_blocked(False)
        self._release_clip_height()
        self.btn_collapser.setIcon(QIcon())
        self.btn_collapser.setArrowType(
            Qt.DownArrow if self._expanded else Qt.RightArrow
        )
        self._arrow_degrees = 90.0 if self._expanded else 0.0
        self._presented_openness = 1.0 if self._expanded else 0.0
        self._body.setVisible(self._expanded)
        if self._body_widget is not None:
            self._body_widget.setVisible(self._expanded)

    def _transfer_focus_from_body(self):
        focus = QApplication.focusWidget()
        if focus is None or sip.isdeleted(focus):
            return
        if focus is self._body or self._body.isAncestorOf(focus):
            self.btn_collapser.setFocus(Qt.OtherFocusReason)

    def _set_body_input_blocked(self, blocked):
        blocked = bool(blocked)
        if blocked == self._input_shielded:
            return
        if blocked:
            self._saved_focus_policies = []
            for widget in self._body_focus_targets():
                self._saved_focus_policies.append((widget, widget.focusPolicy()))
                widget.setFocusPolicy(Qt.NoFocus)
            self._input_shielded = True
            self._input_shield.show()
            self._sync_shield_geometry()
            return
        for widget, policy in self._saved_focus_policies:
            if not sip.isdeleted(widget):
                widget.setFocusPolicy(policy)
        self._saved_focus_policies = []
        self._input_shielded = False
        self._input_shield.hide()

    def _body_focus_targets(self):
        widgets = [self._body]
        widgets.extend(self._body.findChildren(QWidget))
        return [
            widget
            for widget in widgets
            if widget is not self._input_shield and not sip.isdeleted(widget)
        ]

    def _sync_shield_geometry(self):
        if not self._input_shielded:
            return
        self._input_shield.setGeometry(self._body.rect())
        self._input_shield.raise_()

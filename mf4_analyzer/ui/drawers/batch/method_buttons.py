"""Method-selector button group + dynamic per-method parameter form.

Exposes exactly five method buttons — ``time``, ``fft``, ``fft_time``,
``frf``, ``order_time``. ``order_rpm`` was removed by upstream commit ``cfb301b``
and ``order_track`` was removed 2026-04-28; ``batch.BatchRunner.SUPPORTED_METHODS``
no longer accepts either, and ``fft_time`` was added in Wave 3a so the UI
selection stays in lock-step with the dispatcher (see
``signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md``).

The dynamic parameter form swaps QFormLayout rows on ``set_method`` per
spec §3.3 (minus the dropped ``order_rpm`` / ``order_track`` columns).
At the end of ``set_method`` we re-run the visibility helper once to seed
the initial state — required by
``pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md``.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QButtonGroup, QComboBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox,
    QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from ...widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons
from ...widgets.pill_switch import PillSwitch
from ....ui_kit.widgets.segmented_choice import SegmentedChoice


_METHODS: tuple[tuple[str, str], ...] = (
    ("time", "时域"),
    ("fft", "频谱"),
    ("fft_time", "时频"),
    ("order_time", "阶次"),
    ("frf", "频响"),
)


def _make_method_zone_divider(parent: QWidget) -> QFrame:
    """Create one compact boundary marker for the batch method zone."""
    divider = QFrame(parent)
    divider.setObjectName("BatchMethodZoneDivider")
    divider.setFixedSize(8, 16)
    tick = QFrame(divider)
    tick.setObjectName("BatchMethodZoneDividerTick")
    tick.setFixedSize(3, 8)
    tick.move(2, 4)
    return divider


class MethodButtonGroup(QWidget):
    """Five equal-width analysis-mode buttons emitting ``methodChanged(str)``."""

    methodChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchMethodGroup")
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        outer = QHBoxLayout(self)
        # Keep the markers inside the batch column's surface; at zero margin
        # their hairlines land on the clip edge and look uneven.
        outer.setContentsMargins(6, 0, 6, 0)
        outer.setSpacing(12)

        segment = QWidget(self)
        segment.setObjectName("BatchMethodSegment")
        lay = QHBoxLayout(segment)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        left_divider = _make_method_zone_divider(self)
        right_divider = _make_method_zone_divider(self)
        outer.addWidget(left_divider, 0, Qt.AlignVCenter)
        outer.addWidget(segment, 1)
        outer.addWidget(right_divider, 0, Qt.AlignVCenter)

        self._mode_segment = segment
        self._mode_zone_dividers = (left_divider, right_divider)
        self._mode_active_dots: dict[str, QFrame] = {}
        for key, label in _METHODS:
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn.setProperty("batchMethod", key)
            btn.clicked.connect(
                lambda _checked, k=key: self._on_button_clicked(k)
            )
            self._group.addButton(btn)
            self._buttons[key] = btn
            lay.addWidget(btn, 1)
            dot = QFrame(btn)
            dot.setObjectName("BatchMethodActiveDot")
            dot.setFixedSize(6, 6)
            dot.hide()
            self._mode_active_dots[key] = dot
        # Default to FFT.
        self._current = "fft"
        self._buttons["fft"].setChecked(True)
        self._sync_mode_active_dots()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._sync_mode_active_dots()

    def _sync_mode_active_dots(self) -> None:
        for key, button in self._buttons.items():
            dot = self._mode_active_dots[key]
            dot.move(max(0, button.width() - dot.width() - 5), 4)
            dot.setVisible(button.isChecked())

    def _on_button_clicked(self, method: str) -> None:
        """Apply a user selection only when it changes the active method."""
        if method != self._current:
            self.set_method(method)

    def set_method(self, method: str) -> None:
        if method not in self._buttons:
            return
        btn = self._buttons[method]
        if not btn.isChecked():
            btn.setChecked(True)
        if method == self._current:
            # Still emit on explicit set so callers/tests observe the call.
            self._sync_mode_active_dots()
            self.methodChanged.emit(method)
            return
        self._current = method
        self._sync_mode_active_dots()
        self.methodChanged.emit(method)

    def current_method(self) -> str:
        return self._current


# ---------------------------------------------------------------------------
# Dynamic parameter form
# ---------------------------------------------------------------------------
_WINDOWS: tuple[str, ...] = (
    "hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop",
)
_WEIGHTINGS: tuple[str, ...] = ("None", "A")
_BINARY_CHOICE_FIELDS = frozenset({
    "estimator", "nfft_mode", "weighting", "magnitude_scale",
    "frequency_scale", "phase_mode",
    # Time-domain binary editors share the same one-click SegmentedChoice
    # surface as FRF display toggles / 切片维度.
    "render_layout", "x_source", "x_origin",
})
_FRF_ESTIMATION_FIELDS = (
    "estimator", "window", "t_win_s", "overlap", "nfft_mode", "nfft",
)
_FRF_DISPLAY_FIELDS = (
    "magnitude_scale", "frequency_scale", "phase_mode",
    "coherence_threshold", "fade_low_coherence",
)


# Per-method visible field set, taken verbatim from spec §3.3 minus the
# removed ``order_rpm`` column.
_METHOD_FIELDS: dict[str, tuple[str, ...]] = {
    "time": (
        "render_grouping_cards", "render_layout", "x_source", "x_channel",
        "x_origin",
    ),
    "fft": (
        "window", "nfft_mode", "nfft", "t_win_s", "overlap",
        "avg_mode", "avg_overlap", "amplitude_definition", "weighting",
    ),
    "fft_time": (
        "window", "nfft_mode", "nfft", "t_win_s", "overlap",
        "weighting",
    ),
    "frf": (
        "estimator", "window", "t_win_s", "overlap",
        "nfft_mode", "nfft", "magnitude_scale",
        "frequency_scale", "phase_mode", "coherence_threshold",
        "fade_low_coherence",
    ),
    "order_time": (
        "window", "nfft_mode", "nfft", "max_order", "order_res", "time_res",
        "samples_per_rev", "weighting",
    ),
}


def _set_form_row_visible(form, field_widget: QWidget, visible: bool) -> None:
    """Show or hide both halves of one Qt 5 form row."""
    setter = getattr(form, "set_field_visible", None)
    if callable(setter):
        setter(field_widget, visible)
        return
    field_widget.setVisible(visible)
    label = form.labelForField(field_widget)
    if label is not None:
        label.setVisible(visible)


class _GroupingCard(QPushButton):
    """Self-painted semantic preview for one time-render grouping mode."""

    _COLORS = ("#1769e0", "#0ea5a4", "#f97316", "#8b5cf6")

    def __init__(self, label: str, mode: str, parent=None) -> None:
        super().__init__(label, parent)
        self._mode = mode
        self._title = label.splitlines()[0]
        self._source_count = 0
        self._signal_count = 0
        self._show_explanation = True
        self.setCheckable(True)
        self.setObjectName("BatchGroupingCard")
        self.setMinimumHeight(132)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def set_counts(self, source_count: int, signal_count: int) -> None:
        self._source_count = max(0, int(source_count))
        self._signal_count = max(0, int(signal_count))
        self.update()

    def set_title(self, text: str) -> None:
        self.setText(str(text))
        self._title = str(text).splitlines()[0]
        self.update()

    def set_compact_mode(self, compact: bool) -> None:
        self._show_explanation = not bool(compact)
        self.setMinimumHeight(112 if compact else 132)
        self.updateGeometry()
        self.update()

    def formula_text(self) -> str:
        sources = self._source_count
        signals = self._signal_count
        if self._mode == "none":
            return f"{sources} × {signals} → {sources * signals} 张"
        if self._mode == "source":
            return f"{sources} 个数据源 → {sources} 张"
        return f"{signals} 个信号 → {signals} 张"

    def explanation_text(self) -> str:
        if self._mode == "none":
            return "每张：1 个数据源 + 1 个信号"
        if self._mode == "source":
            return "固定 F1，合并 S1 / S2 / S3"
        return "固定 S1，对比 F1 / F2 / F3"

    def wave_semantics(self) -> str:
        return {
            "none": "source-signal-pairs",
            "source": "fixed-source-vary-signal",
            "channel": "fixed-signal-vary-source",
        }[self._mode]

    def preview_row_labels(self) -> tuple[str, ...]:
        """Return the split-screen row identities shown in the mini chart."""
        return {
            "none": (),
            # One data-source page keeps its different signal categories apart.
            "source": ("S1", "S2", "S3"),
            # One signal page compares that signal across data sources.
            "channel": ("F1", "F2", "F3"),
        }[self._mode]

    @staticmethod
    def _wave_path(rect: QRectF, phase: float = 0.0, offset: float = 0.0) -> QPainterPath:
        path = QPainterPath()
        for index in range(25):
            ratio = index / 24.0
            x = rect.left() + ratio * rect.width()
            y = (
                rect.center().y() + offset
                + math.sin(ratio * math.pi * 4.0 + phase) * rect.height() * 0.24
                + math.sin(ratio * math.pi * 9.0 + phase * 0.7) * rect.height() * 0.08
            )
            if index == 0:
                path.moveTo(QPointF(x, y))
            else:
                path.lineTo(QPointF(x, y))
        return path

    @staticmethod
    def _step_path(rect: QRectF) -> QPainterPath:
        """A deliberately non-sinusoidal signal category for the source card."""
        points = (
            (0.00, 0.68), (0.24, 0.68), (0.24, 0.24), (0.44, 0.24),
            (0.44, 0.68), (0.69, 0.68), (0.69, 0.24), (0.87, 0.24),
            (0.87, 0.68), (1.00, 0.68),
        )
        path = QPainterPath()
        for index, (x_ratio, y_ratio) in enumerate(points):
            point = QPointF(
                rect.left() + x_ratio * rect.width(),
                rect.top() + y_ratio * rect.height(),
            )
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        return path

    @staticmethod
    def _vibration_path(rect: QRectF) -> QPainterPath:
        """A dense vibration trace, distinct from the smooth and step lanes."""
        path = QPainterPath()
        for index in range(33):
            ratio = index / 32.0
            x = rect.left() + ratio * rect.width()
            y = (
                rect.center().y()
                + math.sin(ratio * math.tau * 11.0) * rect.height() * 0.30
            )
            if index == 0:
                path.moveTo(QPointF(x, y))
            else:
                path.lineTo(QPointF(x, y))
        return path

    def _draw_frame(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#c9d6e5"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 2, 2)
        painter.setPen(QPen(QColor("#e3e9f1"), 1))
        painter.drawLine(
            QPointF(rect.left() + 4, rect.center().y()),
            QPointF(rect.right() - 4, rect.center().y()),
        )

    def _draw_wave_preview(self, painter: QPainter, rect: QRectF) -> None:
        if self._mode == "none":
            gap = 4.0
            cell_w = (rect.width() - gap) / 2.0
            cell_h = (rect.height() - gap) / 2.0
            for index in range(4):
                row, column = divmod(index, 2)
                cell = QRectF(
                    rect.left() + column * (cell_w + gap),
                    rect.top() + row * (cell_h + gap), cell_w, cell_h,
                )
                self._draw_frame(painter, cell)
                painter.setPen(QPen(QColor(self._COLORS[index]), 1.5))
                painter.drawPath(self._wave_path(cell.adjusted(4, 3, -4, -3), index * 0.7))
            return

        self._draw_frame(painter, rect)
        painter.setFont(QFont(self.font().family(), 6, QFont.Bold))
        tag = "F1" if self._mode == "source" else "S1"
        painter.setPen(QPen(QColor("#c8dbf7"), 1))
        painter.setBrush(QColor("#eaf2ff"))
        tag_rect = QRectF(rect.left() + 4, rect.top() + 4, 19, 11)
        painter.drawRoundedRect(tag_rect, 2, 2)
        painter.setPen(QColor("#0f56bd"))
        painter.drawText(tag_rect, Qt.AlignCenter, tag)

        rows_top = rect.top() + 17
        row_height = (rect.bottom() - rows_top - 2) / 3.0
        # These lanes are strokes, not areas. QPainter fills a QPainterPath
        # with the current brush, so say so explicitly rather than relying on
        # whatever brush the frame or a legend dot happened to leave behind.
        painter.setBrush(Qt.NoBrush)
        if self._mode == "source":
            for index, label in enumerate(self.preview_row_labels()):
                if index:
                    painter.setPen(QPen(QColor("#d8e2ee"), 0.8, Qt.DotLine))
                    divider_y = rows_top + index * row_height
                    painter.drawLine(
                        QPointF(rect.left() + 4, divider_y),
                        QPointF(rect.right() - 4, divider_y),
                    )
                row_top = rows_top + index * row_height
                painter.setPen(QColor("#607087"))
                painter.drawText(
                    QRectF(rect.left() + 4, row_top, 14, row_height),
                    Qt.AlignLeft | Qt.AlignVCenter, label,
                )
                wave_rect = QRectF(
                    rect.left() + 18, row_top + 1, rect.width() - 23, row_height - 2,
                )
                painter.setPen(QPen(QColor(self._COLORS[index]), 1.45))
                if index == 0:
                    painter.drawPath(self._wave_path(wave_rect, 0.0))
                elif index == 1:
                    painter.drawPath(self._step_path(wave_rect))
                else:
                    painter.drawPath(self._vibration_path(wave_rect))
            return

        for index, label in enumerate(self.preview_row_labels()):
            legend_x = rect.right() - 51 + index * 17
            painter.setBrush(QColor(self._COLORS[index]))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(legend_x, rect.top() + 9), 2, 2)
            painter.setPen(QColor("#607087"))
            painter.drawText(QRectF(legend_x + 3, rect.top() + 4, 15, 9), Qt.AlignLeft, label)
        # The legend dots above are filled, so drop their brush before stroking
        # the lanes; otherwise every lane is flooded with the last dot's colour.
        painter.setBrush(Qt.NoBrush)
        for index, _label in enumerate(self.preview_row_labels()):
            if index:
                painter.setPen(QPen(QColor("#d8e2ee"), 0.8, Qt.DotLine))
                divider_y = rows_top + index * row_height
                painter.drawLine(
                    QPointF(rect.left() + 4, divider_y),
                    QPointF(rect.right() - 4, divider_y),
                )
            wave_rect = QRectF(
                rect.left() + 5, rows_top + index * row_height + 1,
                rect.width() - 10, row_height - 2,
            )
            pen = QPen(QColor(self._COLORS[index]), 1.45)
            painter.setPen(pen)
            painter.drawPath(self._wave_path(wave_rect, index * 0.13))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        option = QStyleOptionButton()
        option.initFrom(self)
        option.text = ""
        if self.isChecked():
            option.state |= QStyle.State_On
        self.style().drawControl(QStyle.CE_PushButton, option, painter, self)

        content = QRectF(self.rect()).adjusted(8, 7, -8, -7)
        radio_rect = QRectF(content.left(), content.top() + 1, 13, 13)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#1769e0" if self.isChecked() else "#9caec4"), 1))
        painter.drawEllipse(radio_rect)
        if self.isChecked():
            painter.setBrush(QColor("#1769e0"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(radio_rect.adjusted(3, 3, -3, -3))

        painter.setPen(QColor("#0f56bd" if self.isChecked() else "#172033"))
        painter.setFont(QFont(self.font().family(), 9, QFont.Bold))
        painter.drawText(
            QRectF(content.left() + 18, content.top(), content.width() - 18, 16),
            Qt.AlignLeft | Qt.AlignVCenter, self._title,
        )

        wave_top = content.top() + 22
        wave_height = 52 if self._show_explanation else 47
        self._draw_wave_preview(
            painter, QRectF(content.left(), wave_top, content.width(), wave_height),
        )
        painter.setPen(QColor("#0f56bd"))
        painter.setFont(QFont("Menlo", 8, QFont.Bold))
        formula_top = wave_top + wave_height + 4
        painter.drawText(
            QRectF(content.left(), formula_top, content.width(), 14),
            Qt.AlignLeft | Qt.AlignVCenter, self.formula_text(),
        )
        if self._show_explanation:
            painter.setPen(QColor("#64748b"))
            painter.setFont(QFont(self.font().family(), 7))
            painter.drawText(
                QRectF(content.left(), formula_top + 15, content.width(), 13),
                Qt.AlignLeft | Qt.AlignVCenter, self.explanation_text(),
            )
        painter.end()


class _GroupingCards(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, _GroupingCard] = {}
        for mode, label in (
            ("none", "每项单独\n每任务一张"),
            ("source", "按数据源\n每文件一张"),
            ("channel", "按信号\n每信号一张"),
        ):
            button = _GroupingCard(label, mode, self)
            button.clicked.connect(lambda _checked=False, m=mode: self.set_mode(m))
            self._group.addButton(button)
            layout.addWidget(button, 1)
            self._buttons[mode] = button
        self.set_mode("none", emit=False)

    def set_context(self, method: str) -> None:
        labels = (
            {
                "none": "每对一张",
                "source": "按来源叠加",
                "channel": "按输入/输出对叠加",
            }
            if str(method) == "frf"
            else {
                "none": "每项单独\n每任务一张",
                "source": "按数据源\n每文件一张",
                "channel": "按信号\n每信号一张",
            }
        )
        for mode, button in self._buttons.items():
            button.set_title(labels[mode])

    def set_counts(self, source_count: int, signal_count: int) -> None:
        for button in self._buttons.values():
            button.set_counts(source_count, signal_count)

    def set_compact_mode(self, compact: bool) -> None:
        for button in self._buttons.values():
            button.set_compact_mode(compact)

    def set_mode(self, mode: str, *, emit: bool = True) -> None:
        if mode not in self._buttons:
            mode = "none"
        self._buttons[mode].setChecked(True)
        if emit:
            self.changed.emit(mode)

    def mode(self) -> str:
        return next(
            (mode for mode, button in self._buttons.items() if button.isChecked()),
            "none",
        )


class _GridFormAdapter:
    """Compatibility view over the two-column parameter layout.

    Historical tests and a few dependency-visibility helpers use the small
    QFormLayout inspection surface (`rowCount`, `indexOf`, `labelForField`).
    The visible renderer is now a QGridLayout, but keeping this adapter avoids
    coupling parameter semantics to the geometry migration.
    """

    def __init__(self, owner: "DynamicParamForm") -> None:
        self._owner = owner

    def rowCount(self) -> int:  # noqa: N802 - Qt-compatible surface
        return len(self._owner._active_fields)

    def indexOf(self, widget: QWidget) -> int:  # noqa: N802
        name = self._owner._name_by_widget.get(widget)
        try:
            return self._owner._active_fields.index(name)
        except (ValueError, TypeError):
            return -1

    def labelForField(self, widget: QWidget):  # noqa: N802
        name = self._owner._name_by_widget.get(widget)
        return self._owner._field_labels.get(name)

    def set_field_visible(self, widget: QWidget, visible: bool) -> None:
        name = self._owner._name_by_widget.get(widget)
        host = self._owner._field_hosts.get(name)
        if host is not None:
            host.setVisible(bool(visible))
        visible_widget = self._owner._visible_widgets.get(name, widget)
        if visible_widget is not widget:
            # SegmentedChoice (and other hosts) own the painted surface; the
            # bound combo must stay hidden even while the row is shown.
            widget.hide()
            visible_widget.setVisible(bool(visible))
        else:
            widget.setVisible(bool(visible))
        label = self._owner._field_labels.get(name)
        if label is not None:
            label.setVisible(bool(visible))


class DynamicParamForm(QWidget):
    """Two-column parameter grid whose fields swap per analysis method."""

    paramsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(8)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self._active_fields: list[str] = []
        self._name_by_widget: dict[QWidget, str] = {}
        self._field_hosts: dict[str, QWidget] = {}
        self._field_labels: dict[str, QLabel] = {}
        self._form = _GridFormAdapter(self)
        self._frf_estimation_title = QLabel("FRF 估计参数", self)
        self._frf_estimation_title.setObjectName("BatchParamColumnTitle")
        self._frf_display_title = QLabel("显示设置", self)
        self._frf_display_title.setObjectName("BatchParamColumnTitle")

        # rpm_factor is owned by InputPanel (Wave 2 Task 5) — no entry
        # here on purpose; if a future preset injects an unmapped key it
        # would surface as a KeyError rather than silently rendering as
        # an extra row.
        self._labels: dict[str, str] = {
            "window": "窗函数",
            "estimator": "估计器",
            "magnitude_scale": "幅值",
            "frequency_scale": "频率轴",
            "phase_mode": "相位",
            "coherence_threshold": "相干阈值",
            "fade_low_coherence": "低相干淡化",
            "nfft_mode": "NFFT 模式",
            "nfft": "NFFT",
            "t_win_s": "窗长",
            "max_order": "最大阶次",
            "order_res": "阶次分辨率",
            "time_res": "时间分辨率",
            "overlap": "重叠率",
            "weighting": "频率加权",
            "avg_mode": "平均模式",
            "avg_overlap": "平均重叠",
            "amplitude_definition": "幅值定义",
            "samples_per_rev": "每转样本",
            "render_grouping_cards": "图片分组",
            "render_layout": "图内布局",
            "x_source": "X 轴来源",
            "x_channel": "X 通道",
            "x_origin": "时间原点",
        }

        self._widgets: dict[str, QWidget] = {}

        self._w_estimator = QComboBox(self)
        self._w_estimator.addItem("H1", "h1")
        self._w_estimator.addItem("H2", "h2")
        self._w_estimator.setItemData(
            0, "H1：适合输出端噪声主导的测量（Pxy / Pxx）。", Qt.ToolTipRole,
        )
        self._w_estimator.setItemData(
            1, "H2：适合输入端噪声主导的测量（Pyy / conj(Pxy)）。", Qt.ToolTipRole,
        )
        self._w_estimator.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["estimator"] = self._w_estimator

        # window — QComboBox
        self._w_window = QComboBox(self)
        self._w_window.addItems(_WINDOWS)
        self._w_window.currentIndexChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["window"] = self._w_window

        self._w_nfft_mode = QComboBox(self)
        self._w_nfft_mode.addItem("Auto", "auto")
        self._w_nfft_mode.addItem("Fixed", "fixed")
        self._w_nfft_mode.currentIndexChanged.connect(self._sync_nfft_mode)
        self._w_nfft_mode.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["nfft_mode"] = self._w_nfft_mode

        # weighting — mirrors the single-analysis contextual panels.
        self._w_weighting = QComboBox(self)
        self._w_weighting.addItems(_WEIGHTINGS)
        self._w_weighting.setToolTip(
            "A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL"
        )
        self._w_weighting.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["weighting"] = self._w_weighting

        # nfft — QSpinBox
        self._w_nfft = no_buttons(QSpinBox(self))
        self._w_nfft.setRange(64, 1 << 20)
        self._w_nfft.setValue(1024)
        self._w_nfft.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["nfft"] = self._w_nfft

        self._w_magnitude_scale = QComboBox(self)
        self._w_magnitude_scale.addItem("dB", "db")
        self._w_magnitude_scale.addItem("线性", "linear")
        self._w_magnitude_scale.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["magnitude_scale"] = self._w_magnitude_scale

        self._w_frequency_scale = QComboBox(self)
        self._w_frequency_scale.addItem("对数", "log")
        self._w_frequency_scale.addItem("线性", "linear")
        self._w_frequency_scale.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["frequency_scale"] = self._w_frequency_scale

        self._w_phase_mode = QComboBox(self)
        self._w_phase_mode.addItem("展开", "unwrapped")
        self._w_phase_mode.addItem("包裹", "wrapped")
        self._w_phase_mode.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["phase_mode"] = self._w_phase_mode

        self._w_coherence_threshold = no_buttons(CompactDoubleSpinBox(self))
        self._w_coherence_threshold.setRange(0.0, 1.0)
        self._w_coherence_threshold.setDecimals(2)
        self._w_coherence_threshold.setSingleStep(0.05)
        self._w_coherence_threshold.setValue(0.8)
        self._w_coherence_threshold.valueChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["coherence_threshold"] = self._w_coherence_threshold

        self._w_fade_low_coherence = PillSwitch(
            self,
            object_name="batchFrfFadeToggle",
            accessible_name="低相干淡化",
        )
        self._w_fade_low_coherence.setChecked(True)
        self._w_fade_low_coherence.toggled.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["fade_low_coherence"] = self._w_fade_low_coherence

        self._w_t_win_s = no_buttons(CompactDoubleSpinBox(self))
        self._w_t_win_s.setRange(0.001, 3600.0)
        self._w_t_win_s.setDecimals(3)
        self._w_t_win_s.setValue(1.5)
        self._w_t_win_s.setSuffix(" s")
        self._w_t_win_s.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["t_win_s"] = self._w_t_win_s

        # max_order
        self._w_max_order = no_buttons(CompactDoubleSpinBox(self))
        self._w_max_order.setRange(0.0, 1000.0)
        self._w_max_order.setDecimals(2)
        self._w_max_order.setValue(20.0)
        self._w_max_order.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["max_order"] = self._w_max_order

        # order_res
        self._w_order_res = no_buttons(CompactDoubleSpinBox(self))
        self._w_order_res.setRange(0.001, 100.0)
        self._w_order_res.setDecimals(3)
        self._w_order_res.setValue(0.05)
        self._w_order_res.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["order_res"] = self._w_order_res

        # time_res
        self._w_time_res = no_buttons(CompactDoubleSpinBox(self))
        self._w_time_res.setRange(0.001, 100.0)
        self._w_time_res.setDecimals(3)
        self._w_time_res.setValue(0.1)
        self._w_time_res.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["time_res"] = self._w_time_res

        # overlap — QDoubleSpinBox 0..0.95
        self._w_overlap = no_buttons(CompactDoubleSpinBox(self))
        self._w_overlap.setRange(0.0, 0.95)
        self._w_overlap.setSingleStep(0.05)
        self._w_overlap.setDecimals(2)
        self._w_overlap.setValue(0.5)
        self._w_overlap.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["overlap"] = self._w_overlap

        self._w_avg_mode = QComboBox(self)
        self._w_avg_mode.addItems(["单帧", "线性平均", "峰值保持"])
        self._w_avg_mode.currentTextChanged.connect(self._sync_avg_mode)
        self._w_avg_mode.currentTextChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["avg_mode"] = self._w_avg_mode

        self._w_avg_overlap = no_buttons(QSpinBox(self))
        self._w_avg_overlap.setRange(0, 95)
        self._w_avg_overlap.setValue(50)
        self._w_avg_overlap.setSuffix(" %")
        self._w_avg_overlap.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["avg_overlap"] = self._w_avg_overlap

        self._w_amplitude_definition = QComboBox(self)
        self._w_amplitude_definition.addItem("算法默认", "native")
        self._w_amplitude_definition.addItem("Peak", "peak")
        self._w_amplitude_definition.addItem("RMS", "rms")
        self._w_amplitude_definition.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["amplitude_definition"] = self._w_amplitude_definition

        self._w_samples_per_rev = no_buttons(QSpinBox(self))
        self._w_samples_per_rev.setRange(2, 1 << 20)
        self._w_samples_per_rev.setValue(256)
        self._w_samples_per_rev.valueChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["samples_per_rev"] = self._w_samples_per_rev

        self._w_render_group_by = QComboBox(self)
        self._w_render_group_by.addItem("每任务", "none")
        self._w_render_group_by.addItem("按数据源", "source")
        self._w_render_group_by.addItem("按通道", "channel")
        self._w_render_group_by.currentIndexChanged.connect(
            self._sync_render_group_by
        )
        self._w_render_group_by.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._grouping_cards = _GroupingCards(self)
        self._grouping_cards.changed.connect(self._on_grouping_card_changed)
        self._widgets["render_grouping_cards"] = self._grouping_cards

        self._w_render_layout = QComboBox(self)
        self._w_render_layout.addItem("叠加", "overlay")
        self._w_render_layout.addItem("分屏", "subplot")
        self._w_render_layout.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["render_layout"] = self._w_render_layout

        self._w_x_source = QComboBox(self)
        self._w_x_source.addItem("时间", "time")
        self._w_x_source.addItem("通道", "channel")
        self._w_x_source.currentIndexChanged.connect(self._sync_x_source)
        self._w_x_source.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["x_source"] = self._w_x_source

        self._w_x_channel = QComboBox(self)
        self._w_x_channel.addItem("请选择", "")
        self._w_x_channel.currentIndexChanged.connect(
            self._on_x_channel_changed
        )
        self._widgets["x_channel"] = self._w_x_channel
        self._x_channel_candidates_initialized = False
        self._pending_x_channel = ""
        self._x_channel_validation = ""

        self._w_x_origin = QComboBox(self)
        self._w_x_origin.addItem("从零开始", "zero")
        self._w_x_origin.addItem("绝对时间", "absolute")
        self._w_x_origin.currentIndexChanged.connect(
            lambda *_: self.paramsChanged.emit()
        )
        self._widgets["x_origin"] = self._w_x_origin

        for combo in (
            self._w_render_group_by,
            self._w_render_layout,
            self._w_x_source,
            self._w_x_channel,
            self._w_x_origin,
        ):
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        # Compatibility value holder only.  The three semantic waveform
        # cards are the sole visible editor for render_group_by; leaving this
        # unparented-to-layout combo visible makes Qt place it at (0, 0),
        # where it overlaps the first spectral parameter label.
        self._w_render_group_by.hide()

        self._choice_widgets: dict[str, SegmentedChoice] = {}
        self._visible_widgets: dict[str, QWidget] = {}
        self._name_by_widget = {
            widget: name for name, widget in self._widgets.items()
        }
        for name, widget in self._widgets.items():
            host = QWidget(self)
            host.setObjectName("BatchParamCell")
            host.setMinimumWidth(0)
            host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            cell = QVBoxLayout(host)
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(4)
            label = QLabel(self._labels[name], host)
            label.setObjectName("BatchParamLabel")
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            cell.addWidget(label)
            if name in _BINARY_CHOICE_FIELDS:
                choice = SegmentedChoice(host)
                if name == "phase_mode":
                    choice.bind(widget, labels=("展开", "±180°"))
                else:
                    choice.bind(widget)
                choice.setMinimumWidth(0)
                choice.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                self._choice_widgets[name] = choice
                setattr(self, f"_choice_{name}", choice)
                visible_widget = choice
            elif name == "fade_low_coherence":
                # Keep the 44×24 switch centred on the shared 32px field
                # track, so its left edge and row rhythm match the
                # single-analysis FRF display controls.
                switch_host = QWidget(host)
                switch_host.setObjectName("BatchFrfSwitchField")
                switch_host.setFixedHeight(32)
                switch_lay = QHBoxLayout(switch_host)
                switch_lay.setContentsMargins(0, 0, 0, 0)
                switch_lay.addWidget(widget, 0, Qt.AlignLeft | Qt.AlignVCenter)
                switch_lay.addStretch(1)
                visible_widget = switch_host
            else:
                widget.setParent(host)
                visible_widget = widget
            cell.addWidget(visible_widget)
            self._visible_widgets[name] = visible_widget
            self._field_hosts[name] = host
            self._field_labels[name] = label

        # Track current method so set_method works idempotently.
        self._current = "fft"
        self._render_for("fft")
        self._sync_nfft_mode()
        self._sync_avg_mode()
        self._sync_render_group_by()
        self._sync_x_source()

    # ------------------------------------------------------------------
    def set_method(self, method: str, *, emit: bool = True) -> None:
        if method not in _METHOD_FIELDS:
            return
        self._current = method
        self._configure_nfft_mode_for_method(method)
        self._grouping_cards.set_context(method)
        self._render_for(method)
        if emit:
            # Init-sync per the conditional-visibility-init-sync lesson: do
            # not rely on a downstream signal to seed visible state; emit
            # once for direct form users.  The AnalysisPanel method-change
            # transaction emits its completed method state instead.
            self.paramsChanged.emit()

    def set_grouping_counts(self, *, source_count: int, signal_count: int) -> None:
        self._grouping_cards.set_counts(source_count, signal_count)

    def set_compact_mode(self, compact: bool) -> None:
        self._grouping_cards.set_compact_mode(compact)

    def visible_field_names(self) -> set[str]:
        out: set[str] = set()
        for name, w in self._widgets.items():
            if not self._field_hosts[name].isHidden() and self._form.indexOf(w) >= 0:
                out.add(name)
        return out

    def _sync_nfft_mode(self, *_args) -> None:
        self._w_nfft.setEnabled(
            self._w_nfft_mode.currentData() in {"fixed", "manual"}
        )

    def _configure_nfft_mode_for_method(self, method: str) -> None:
        current = str(self._w_nfft_mode.currentData() or "auto")
        manual = current in {"fixed", "manual"}
        previous = self._w_nfft_mode.blockSignals(True)
        try:
            self._w_nfft_mode.clear()
            self._w_nfft_mode.addItem("自动" if method == "frf" else "Auto", "auto")
            self._w_nfft_mode.addItem(
                "手动" if method == "frf" else "Fixed",
                "manual" if method == "frf" else "fixed",
            )
            self._w_nfft_mode.setCurrentIndex(1 if manual else 0)
        finally:
            self._w_nfft_mode.blockSignals(previous)
        self._choice_nfft_mode.refresh_from_bound_combo()
        self._sync_nfft_mode()

    def _sync_avg_mode(self, *_args) -> None:
        self._w_avg_overlap.setEnabled(self._w_avg_mode.currentText() != "单帧")

    def _sync_render_group_by(self, *_args) -> None:
        self._grouping_cards.set_mode(
            str(self._w_render_group_by.currentData() or "none"), emit=False,
        )
        enabled = self._w_render_group_by.currentData() != "none"
        self._w_render_layout.setEnabled(enabled)
        choice = self._choice_widgets.get("render_layout")
        if choice is not None:
            choice.setEnabled(enabled)

    def _on_grouping_card_changed(self, mode: str) -> None:
        index = self._w_render_group_by.findData(str(mode))
        if index >= 0:
            self._w_render_group_by.setCurrentIndex(index)

    def _sync_x_source(self, *_args) -> None:
        if self._current != "time":
            _set_form_row_visible(self._form, self._w_x_channel, False)
            _set_form_row_visible(self._form, self._w_x_origin, False)
            return
        use_channel = self._w_x_source.currentData() == "channel"
        _set_form_row_visible(self._form, self._w_x_channel, use_channel)
        _set_form_row_visible(self._form, self._w_x_origin, not use_channel)

    def _on_x_channel_changed(self, *_args) -> None:
        selected = str(self._w_x_channel.currentData() or "")
        if selected:
            self._pending_x_channel = selected
            self._x_channel_validation = ""
        else:
            self._pending_x_channel = ""
            if (
                self._current == "time"
                and self._w_x_source.currentData() == "channel"
            ):
                self._x_channel_validation = "请选择 X 通道"
        self.paramsChanged.emit()

    def x_channel_validation_message(self) -> str:
        return self._x_channel_validation

    def set_x_channel_candidates(
        self,
        common: Sequence[str],
        partial: Mapping[str, str],
        *,
        partial_selectable: Sequence[str] = (),
    ) -> None:
        """Replace the X-channel universe and enable eligible partial rows."""
        selected = str(
            self._w_x_channel.currentData() or self._pending_x_channel or ""
        )
        common_names = tuple(dict.fromkeys(
            str(name) for name in common if str(name)
        ))
        selectable_partial_names = frozenset(
            str(name) for name in partial_selectable if str(name)
        )
        partial_items = tuple(
            (str(name), str(suffix))
            for name, suffix in partial.items()
            if str(name) and str(name) not in common_names
        )
        valid_names = frozenset(common_names) | {
            name for name, _suffix in partial_items
            if name in selectable_partial_names
        }

        previous = self._w_x_channel.blockSignals(True)
        try:
            self._w_x_channel.clear()
            self._w_x_channel.addItem("请选择", "")
            for name in common_names:
                self._w_x_channel.addItem(name, name)
            for name, suffix in partial_items:
                self._w_x_channel.addItem(f"{name} {suffix}".strip(), name)
                item = self._w_x_channel.model().item(
                    self._w_x_channel.count() - 1
                )
                if item is not None and name not in selectable_partial_names:
                    item.setEnabled(False)

            index = self._w_x_channel.findData(selected)
            valid = bool(selected) and selected in valid_names
            self._w_x_channel.setCurrentIndex(index if valid else 0)
        finally:
            self._w_x_channel.blockSignals(previous)

        self._x_channel_candidates_initialized = True
        if selected and not valid:
            self._pending_x_channel = ""
            self._x_channel_validation = (
                f"X 通道 {selected} 不是所有已加载数据源的共同通道"
            )
            self.paramsChanged.emit()
        elif valid:
            self._pending_x_channel = selected
            self._x_channel_validation = ""

    def get_params(self) -> dict:
        if self._current == "time":
            params: dict = {}
            group_by = str(self._w_render_group_by.currentData() or "none")
            if group_by != "none":
                params["render_group_by"] = group_by
                layout = str(self._w_render_layout.currentData() or "overlay")
                if layout != "overlay":
                    params["render_layout"] = layout
            x_source = str(self._w_x_source.currentData() or "time")
            if x_source != "time":
                params["x_source"] = x_source
                channel = str(
                    self._w_x_channel.currentData()
                    or self._pending_x_channel
                    or ""
                )
                if channel:
                    params["x_channel"] = channel
            else:
                origin = str(self._w_x_origin.currentData() or "zero")
                if origin != "zero":
                    params["x_origin"] = origin
            return params
        params: dict = {}
        if "estimator" in self.visible_field_names():
            params["estimator"] = str(self._w_estimator.currentData() or "h1")
        if "window" in self.visible_field_names():
            params["window"] = self._w_window.currentText()
        if "nfft" in self.visible_field_names():
            mode = str(self._w_nfft_mode.currentData() or "auto")
            params["nfft_mode"] = mode
            params["nfft"] = (
                int(self._w_nfft.value()) if mode in {"fixed", "manual"} else None
            )
        if "t_win_s" in self.visible_field_names():
            params["t_win_s"] = float(self._w_t_win_s.value())
        if "max_order" in self.visible_field_names():
            params["max_order"] = float(self._w_max_order.value())
        if "order_res" in self.visible_field_names():
            params["order_res"] = float(self._w_order_res.value())
        if "time_res" in self.visible_field_names():
            params["time_res"] = float(self._w_time_res.value())
        if "overlap" in self.visible_field_names():
            params["overlap"] = float(self._w_overlap.value())
        if "weighting" in self.visible_field_names():
            params["weighting"] = self._w_weighting.currentText()
        if "avg_mode" in self.visible_field_names():
            params["avg_mode"] = self._w_avg_mode.currentText()
        if "avg_overlap" in self.visible_field_names():
            params["avg_overlap"] = int(self._w_avg_overlap.value())
        if "amplitude_definition" in self.visible_field_names():
            params["amplitude_definition"] = str(
                self._w_amplitude_definition.currentData() or "native"
            )
        if "samples_per_rev" in self.visible_field_names():
            params["samples_per_rev"] = int(self._w_samples_per_rev.value())
        if "magnitude_scale" in self.visible_field_names():
            params["magnitude_scale"] = str(
                self._w_magnitude_scale.currentData() or "db"
            )
        if "frequency_scale" in self.visible_field_names():
            params["frequency_scale"] = str(
                self._w_frequency_scale.currentData() or "log"
            )
        if "phase_mode" in self.visible_field_names():
            params["phase_mode"] = str(
                self._w_phase_mode.currentData() or "unwrapped"
            )
        if "coherence_threshold" in self.visible_field_names():
            params["coherence_threshold"] = float(
                self._w_coherence_threshold.value()
            )
        if "fade_low_coherence" in self.visible_field_names():
            params["fade_low_coherence"] = bool(
                self._w_fade_low_coherence.isChecked()
            )
        return params

    def apply_params(self, params: dict) -> None:
        if not params:
            return
        for key, combo in (
            ("estimator", self._w_estimator),
            ("magnitude_scale", self._w_magnitude_scale),
            ("frequency_scale", self._w_frequency_scale),
            ("phase_mode", self._w_phase_mode),
        ):
            if key in params:
                index = combo.findData(str(params[key]).lower())
                if index >= 0:
                    combo.setCurrentIndex(index)
        for key, combo in (
            ("render_group_by", self._w_render_group_by),
            ("render_layout", self._w_render_layout),
            ("x_source", self._w_x_source),
            ("x_origin", self._w_x_origin),
        ):
            if key in params:
                index = combo.findData(str(params[key]))
                if index >= 0:
                    combo.setCurrentIndex(index)
        if "x_channel" in params:
            channel = str(params.get("x_channel") or "")
            index = self._w_x_channel.findData(channel)
            item = self._w_x_channel.model().item(index) if index >= 0 else None
            if index >= 0 and item is not None and item.isEnabled():
                self._w_x_channel.setCurrentIndex(index)
                self._pending_x_channel = channel
                self._x_channel_validation = ""
            elif channel and not self._x_channel_candidates_initialized:
                self._pending_x_channel = channel
            elif channel:
                self._pending_x_channel = ""
                self._x_channel_validation = (
                    f"X 通道 {channel} 不是所有已加载数据源的共同通道"
                )
        # window (string)
        if "window" in params:
            txt = str(params["window"])
            idx = self._w_window.findText(txt)
            if idx >= 0:
                self._w_window.setCurrentIndex(idx)
        if "nfft_mode" in params or "nfft" in params:
            raw_nfft = params.get("nfft")
            raw_mode = str(params.get("nfft_mode", "") or "").lower()
            auto = raw_mode in {"auto", "自动"} or raw_nfft in {
                None, "", "auto", "自动",
            }
            mode = "auto" if auto else (
                "manual" if self._current == "frf" else "fixed"
            )
            index = self._w_nfft_mode.findData(mode)
            if index >= 0:
                self._w_nfft_mode.setCurrentIndex(index)
            if not auto:
                try:
                    self._w_nfft.setValue(int(raw_nfft))
                except (TypeError, ValueError):
                    pass
            self._sync_nfft_mode()
        if "t_win_s" in params:
            try:
                self._w_t_win_s.setValue(float(params["t_win_s"]))
            except (TypeError, ValueError):
                pass
        for key, widget in (
            ("max_order", self._w_max_order),
            ("order_res", self._w_order_res),
            ("time_res", self._w_time_res),
        ):
            if key in params:
                try:
                    widget.setValue(float(params[key]))
                except (TypeError, ValueError):
                    pass
        if "overlap" in params:
            try:
                value = float(params["overlap"])
                self._w_overlap.setValue(value / 100.0 if value > 1.0 else value)
            except (TypeError, ValueError):
                pass
        if "coherence_threshold" in params:
            try:
                self._w_coherence_threshold.setValue(
                    float(params["coherence_threshold"])
                )
            except (TypeError, ValueError):
                pass
        if "fade_low_coherence" in params:
            self._w_fade_low_coherence.setChecked(
                bool(params["fade_low_coherence"])
            )
        if "weighting" in params:
            txt = str(params["weighting"])
            idx = self._w_weighting.findText(txt)
            if idx >= 0:
                self._w_weighting.setCurrentIndex(idx)
        if "avg_mode" in params:
            idx = self._w_avg_mode.findText(str(params["avg_mode"]))
            if idx >= 0:
                self._w_avg_mode.setCurrentIndex(idx)
        if "avg_overlap" in params:
            try:
                value = float(params["avg_overlap"])
                self._w_avg_overlap.setValue(
                    int(round(value * 100.0 if 0.0 <= value <= 1.0 else value))
                )
            except (TypeError, ValueError):
                pass
        if "amplitude_definition" in params:
            idx = self._w_amplitude_definition.findData(
                str(params["amplitude_definition"]).lower()
            )
            if idx >= 0:
                self._w_amplitude_definition.setCurrentIndex(idx)
        if "samples_per_rev" in params:
            try:
                self._w_samples_per_rev.setValue(int(params["samples_per_rev"]))
            except (TypeError, ValueError):
                pass
        self._sync_avg_mode()
        self._sync_render_group_by()
        self._sync_x_source()

    def set_weighting_options(self, options) -> None:
        values = [str(item) for item in (options or ()) if str(item)]
        if not values:
            values = list(_WEIGHTINGS)
        current = self._w_weighting.currentText()
        self._w_weighting.blockSignals(True)
        try:
            self._w_weighting.clear()
            self._w_weighting.addItems(values)
            target = current if current in values else (
                "None" if "None" in values else values[0]
            )
            idx = self._w_weighting.findText(target)
            if idx >= 0:
                self._w_weighting.setCurrentIndex(idx)
        finally:
            self._w_weighting.blockSignals(False)
        self._choice_weighting.refresh_from_bound_combo()

    # ------------------------------------------------------------------
    def _render_for(self, method: str) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        for host in self._field_hosts.values():
            host.hide()
        self._frf_estimation_title.hide()
        self._frf_display_title.hide()
        self._active_fields = list(_METHOD_FIELDS[method])

        if method == "frf":
            # FRF has two stable semantic columns instead of interleaving
            # calculation and display controls by row.  The display controls
            # now mirror the single-analysis card as one vertical group.
            self._frf_estimation_title.show()
            self._frf_display_title.show()
            self._grid.addWidget(self._frf_estimation_title, 0, 0)
            self._grid.addWidget(self._frf_display_title, 0, 1)
            for row, name in enumerate(_FRF_ESTIMATION_FIELDS, start=1):
                host = self._field_hosts[name]
                widget = self._widgets[name]
                visible_widget = self._visible_widgets[name]
                visible_widget.setHidden(False)
                if visible_widget is not widget:
                    if name in _BINARY_CHOICE_FIELDS:
                        widget.hide()
                    else:
                        widget.show()
                host.setHidden(False)
                self._field_labels[name].show()
                self._grid.addWidget(host, row, 0)
            for row, name in enumerate(_FRF_DISPLAY_FIELDS, start=1):
                host = self._field_hosts[name]
                widget = self._widgets[name]
                visible_widget = self._visible_widgets[name]
                visible_widget.setHidden(False)
                if visible_widget is not widget:
                    if name in _BINARY_CHOICE_FIELDS:
                        widget.hide()
                    else:
                        widget.show()
                host.setHidden(False)
                self._field_labels[name].show()
                self._grid.addWidget(host, row, 1)
            self._sync_nfft_mode()
            return

        row = 0
        column = 0
        for name in self._active_fields:
            host = self._field_hosts[name]
            widget = self._widgets[name]
            visible_widget = self._visible_widgets[name]
            visible_widget.setHidden(False)
            if visible_widget is not widget:
                widget.hide()
            host.setHidden(False)
            if name == "render_grouping_cards":
                # The semantic cards are the block itself, not a field next to
                # a narrow form label. Their own titles explain each choice.
                self._field_labels[name].hide()
                self._grid.addWidget(host, row, 0, 1, 2)
                row += 1
                column = 0
                continue
            if name in {"x_channel", "x_origin"}:
                # The time-origin and custom-channel editors are two semantic
                # variants of one dependent X-axis slot.  Keep both hosts in
                # the same right-column grid cell; _sync_x_source() makes
                # exactly one visible without moving the active editor left.
                self._field_labels[name].show()
                self._grid.addWidget(host, row, 1)
                continue
            self._field_labels[name].show()
            self._grid.addWidget(host, row, column)
            column += 1
            if column == 2:
                row += 1
                column = 0
        # Hide widgets not in this method's set so isHidden() honestly
        # reflects visibility for tests / snapshot diffs (per the
        # conditional-visibility paired-field-children lesson).
        active = set(_METHOD_FIELDS[method])
        for name, widget in self._widgets.items():
            if name not in active:
                widget.setHidden(True)
                self._visible_widgets[name].setHidden(True)
                self._field_hosts[name].setHidden(True)
        self._sync_nfft_mode()
        self._sync_avg_mode()
        self._sync_render_group_by()
        self._sync_x_source()

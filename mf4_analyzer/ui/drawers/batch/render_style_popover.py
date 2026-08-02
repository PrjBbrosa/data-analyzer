"""Tick-density and text-size popover for the batch output column.

Visually this is the batch twin of the time-domain chart's 刻度密度 popover
(``mf4_analyzer.ui.chart_stack.toolbar._TickDensityPopover``): it reuses that
popover's object names so the shipped ``style.qss`` block
(``QFrame#TickDensitySurface`` …) styles it without a second rule set. It is a
separate class rather than a shared one because the two surfaces answer
different questions — the chart one retunes what is on screen right now, this
one carries a third row (text size) and presets tuned for a 1920×1080 export —
and because generalizing the chart popover would put the main chart toolbar in
the blast radius of a batch-panel change.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QVBoxLayout,
)

from ....batch_render_style import (
    MAX_FONT_SCALE, MAX_TICK_DENSITY_X, MAX_TICK_DENSITY_Y,
    MIN_FONT_SCALE, MIN_TICK_DENSITY_X, MIN_TICK_DENSITY_Y,
    TICK_DENSITY_PRESETS, RenderStyle,
)
from ....ui_kit.popup_shell import apply_popup_shell


def _percent(scale: float) -> int:
    return int(round(float(scale) * 100.0))


class RenderStylePopover(QFrame):
    """Edit ``RenderStyle`` (tick density + text scale) for batch exports."""

    style_changed = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("TickDensityPopover")
        apply_popup_shell(self)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedWidth(268)
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._surface = QFrame(self)
        self._surface.setObjectName("TickDensitySurface")
        lay = QVBoxLayout(self._surface)
        lay.setContentsMargins(11, 11, 11, 11)
        lay.setSpacing(9)
        root.addWidget(self._surface)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("刻度与字体", self._surface)
        title.setObjectName("tickDensityTitle")
        scope = QLabel("导出图片", self._surface)
        scope.setObjectName("tickDensityScope")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(scope)
        lay.addLayout(title_row)

        self._preset_host = QFrame(self._surface)
        self._preset_host.setObjectName("tickDensityPresetHost")
        preset_lay = QHBoxLayout(self._preset_host)
        preset_lay.setContentsMargins(0, 0, 0, 0)
        preset_lay.setSpacing(6)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        self._preset_buttons: dict[str, QPushButton] = {}
        for label, x_value, y_value in TICK_DENSITY_PRESETS:
            button = QPushButton(label, self._preset_host)
            button.setObjectName("tickDensityPresetButton")
            button.setCheckable(True)
            button.setProperty("role", "tick-density-preset")
            button.clicked.connect(
                lambda _checked=False, x=x_value, y=y_value: self._on_preset(x, y)
            )
            self._preset_group.addButton(button)
            self._preset_buttons[label] = button
            preset_lay.addWidget(button)
        lay.addWidget(self._preset_host)

        default = RenderStyle()
        self._x_row, self._slider_x, self._spin_x = self._build_row(
            "X", MIN_TICK_DENSITY_X, MAX_TICK_DENSITY_X, default.tick_density_x, 1,
        )
        self._y_row, self._slider_y, self._spin_y = self._build_row(
            "Y", MIN_TICK_DENSITY_Y, MAX_TICK_DENSITY_Y, default.tick_density_y, 1,
        )
        self._font_row, self._slider_font, self._spin_font = self._build_row(
            "字号",
            _percent(MIN_FONT_SCALE),
            _percent(MAX_FONT_SCALE),
            _percent(default.font_scale),
            5,
            suffix="%",
            width=52,
        )
        lay.addWidget(self._x_row)
        lay.addWidget(self._y_row)
        lay.addWidget(self._font_row)

        self._reset_btn = QPushButton(
            f"恢复默认 {default.tick_density_x} / {default.tick_density_y}"
            f" · {_percent(default.font_scale)}%",
            self._surface,
        )
        self._reset_btn.setObjectName("tickDensityResetButton")
        self._reset_btn.clicked.connect(
            lambda: self.set_style(RenderStyle(), emit=True)
        )
        lay.addWidget(self._reset_btn)

        for widget in (
            self._slider_x, self._spin_x,
            self._slider_y, self._spin_y,
            self._slider_font, self._spin_font,
        ):
            widget.valueChanged.connect(self._on_editor_changed)

        self.set_style(default, emit=False)

    def hideEvent(self, event):  # noqa: N802 (Qt API)
        # A Qt.Popup also closes on any click outside itself, which the opener
        # never hears about; without this its toggle button would stay lit.
        super().hideEvent(event)
        self.closed.emit()

    # ------------------------------------------------------------------
    def _build_row(self, label, minimum, maximum, value, step, *, suffix="", width=38):
        row = QFrame(self._surface)
        row.setObjectName("tickDensityAxisRow")
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(0)
        axis_label = QLabel(label, row)
        axis_label.setObjectName("tickDensityAxisLabel")
        slider = QSlider(Qt.Horizontal, row)
        slider.setObjectName("tickDensitySlider")
        slider.setRange(minimum, maximum)
        slider.setSingleStep(step)
        slider.setPageStep(step * 2)
        slider.setValue(value)
        spin = QSpinBox(row)
        spin.setObjectName("tickDensitySpin")
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        spin.setFixedWidth(width)
        grid.addWidget(axis_label, 0, 0)
        grid.addWidget(slider, 0, 1)
        grid.addWidget(spin, 0, 2)
        return row, slider, spin

    def _on_preset(self, x_value: int, y_value: int) -> None:
        self.set_style(
            RenderStyle(
                tick_density_x=x_value,
                tick_density_y=y_value,
                font_scale=self.style().font_scale,
            ),
            emit=True,
        )

    def _on_editor_changed(self, *_args) -> None:
        if self._updating:
            return
        self.set_style(
            RenderStyle(
                tick_density_x=self._spin_x.value(),
                tick_density_y=self._spin_y.value(),
                font_scale=self._spin_font.value() / 100.0,
            ),
            emit=True,
        )

    # ------------------------------------------------------------------
    def style(self) -> RenderStyle:
        return RenderStyle(
            tick_density_x=self._spin_x.value(),
            tick_density_y=self._spin_y.value(),
            font_scale=self._spin_font.value() / 100.0,
        )

    def set_style(self, style: RenderStyle, *, emit: bool = False) -> None:
        if self._updating:
            return
        self._updating = True
        widgets = (
            (self._slider_x, style.tick_density_x),
            (self._spin_x, style.tick_density_x),
            (self._slider_y, style.tick_density_y),
            (self._spin_y, style.tick_density_y),
            (self._slider_font, _percent(style.font_scale)),
            (self._spin_font, _percent(style.font_scale)),
        )
        blocked = [widget.blockSignals(True) for widget, _value in widgets]
        try:
            for widget, value in widgets:
                widget.setValue(value)
        finally:
            for (widget, _value), previous in zip(widgets, blocked):
                widget.blockSignals(previous)
            self._updating = False
        self._sync_preset_checks(style)
        if emit:
            self.style_changed.emit(style)

    def _sync_preset_checks(self, style: RenderStyle) -> None:
        current = (int(style.tick_density_x), int(style.tick_density_y))
        self._preset_group.setExclusive(False)
        try:
            for label, x_value, y_value in TICK_DENSITY_PRESETS:
                self._preset_buttons[label].setChecked((x_value, y_value) == current)
        finally:
            self._preset_group.setExclusive(True)


__all__ = ["RenderStylePopover"]

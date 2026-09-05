"""Chart options dialog: per-axes appearance and scaling controls."""
import numpy as np

from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from ...ui_kit.dialog_button_defaults import set_unique_default_button
from ...ui_kit.dialog_geometry import fit_window, nudge_into_work_area
from .._axis_handle import make_handle
from .._color_utils import is_color_like as _is_color_like
from .._color_utils import to_hex as _to_hex
from ..pg_canvas.heatmap_canvas import SUPPORTED_HEATMAP_COLORMAPS
from ..widgets.compact_spinbox import CompactDoubleSpinBox


class ChartOptionsDialog(QDialog):
    """Inspector-styled lightweight chart options dialog for one axes."""

    SCALE_TO_TEXT = {
        "linear": "线性",
        "log": "对数",
    }
    TEXT_TO_SCALE = {v: k for k, v in SCALE_TO_TEXT.items()}

    def __init__(self, parent, axis_or_handle):
        super().__init__(parent)
        # Runtime callers pass an existing pyqtgraph AxisHandle. make_handle()
        # keeps the public constructor guarded and rejects raw renderer objects.
        self.handle = make_handle(axis_or_handle)
        # Compatibility alias for older custom handles that expose an
        # axes-like object. Current built-in pyqtgraph handles leave this None.
        self.ax = getattr(self.handle, "axes", None)
        self._lines = self._editable_lines()
        self._mappables = self._editable_mappables()
        self.setObjectName("ChartOptionsDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("图表选项")
        self.setMinimumWidth(430)
        self._applied = False
        self._invalid_axes: list[str] = []
        self._initial = self._read_axes()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(3)
        title = QLabel("图表选项", self)
        title.setObjectName("chartOptionsTitle")
        subtitle = QLabel(self._target_summary(), self)
        subtitle.setObjectName("chartOptionsSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("chartOptionsTabs")
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.setDocumentMode(True)
        tab_bar = self.tabs.tabBar()
        tab_bar.setExpanding(False)
        tab_bar.setDrawBase(False)
        tab_bar.setAutoFillBackground(False)
        tab_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.tabs.addTab(self._scrollable_tab(self._axes_tab()), "坐标轴")
        self.tabs.addTab(self._scrollable_tab(self._appearance_tab()), "图形")
        self.tabs.addTab(self._scrollable_tab(self._legend_tab()), "图例")
        root.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.addStretch(1)
        self.btn_reset = QPushButton("重置", self)
        self.btn_cancel = QPushButton("取消", self)
        self.btn_apply = QPushButton("应用", self)
        self.btn_ok = QPushButton("确定", self)
        self.btn_apply.setProperty("role", "primary")
        self.btn_ok.setProperty("role", "primary")
        for btn in (self.btn_reset, self.btn_cancel, self.btn_apply, self.btn_ok):
            actions.addWidget(btn)
        root.addLayout(actions)

        self.btn_reset.clicked.connect(self.reset_fields)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self.apply_changes)
        self.btn_ok.clicked.connect(self._accept_with_apply)
        set_unique_default_button(self.btn_ok, self)
        self.chk_x_auto.toggled.connect(self._sync_auto_fields)
        self.chk_y_auto.toggled.connect(self._sync_auto_fields)
        self.chk_color_auto.toggled.connect(self._sync_auto_fields)
        self.combo_curve.currentIndexChanged.connect(self._sync_curve_color)
        self.btn_curve_color.clicked.connect(self._choose_curve_color)
        self.reset_fields()
        self._geometry_fitted = False
        self._fit_to_available_height()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._geometry_fitted:
            self._fit_to_available_height()
            self._geometry_fitted = True
        else:
            nudge_into_work_area(
                self, parent=self.parentWidget(), content_minimum=(240, 200),
            )

    def _scrollable_tab(self, page):
        scroll = QScrollArea(self)
        scroll.setObjectName("chartOptionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setWidget(page)
        return scroll

    def _fit_to_available_height(self):
        hint = self.sizeHint()
        fit_window(
            self,
            (max(hint.width(), 430), hint.height()),
            parent=self.parentWidget(),
            content_minimum=(430, 240),
            clamp_width_to_parent=True,
        )

    def _target_summary(self):
        # ``get_label`` is intentionally outside the AxisHandle protocol.
        # Custom handles with an axes-like object may still provide it; normal
        # pyqtgraph handles fall through to the title or "当前图".
        title = self.handle.get_title()
        if not title and self.ax is not None:
            title = self.ax.get_label()
        title = title or "当前图"
        return f"目标：{title}"

    def _axes_tab(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        lay.addWidget(self._basic_group())
        lay.addWidget(self._axis_group("X 轴", "x"))
        lay.addWidget(self._axis_group("Y 轴", "y"))
        lay.addStretch(1)
        return page

    def _appearance_tab(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)
        lay.addWidget(self._curve_group())
        lay.addWidget(self._mappable_group())
        lay.addStretch(1)
        return page

    def _legend_tab(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)
        group = self._group_frame("图例")
        form = QVBoxLayout(group)
        form.setContentsMargins(10, 8, 10, 10)
        form.setSpacing(8)
        title = QLabel("图例", group)
        title.setObjectName("chartOptionsGroupTitle")
        form.addWidget(title)
        self.chk_legend = QCheckBox("重新生成自动图例", group)
        form.addWidget(self.chk_legend)
        lay.addWidget(group)
        lay.addStretch(1)
        return page

    def _basic_group(self):
        group = self._group_frame("基础信息")
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel("基础信息", group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self.edit_title = QLineEdit(group)
        form.addRow("标题", self.edit_title)
        box.addLayout(form)
        self.chk_grid = QCheckBox("显示网格线", group)
        box.addWidget(self.chk_grid)
        return group

    def _axis_group(self, group_title, axis):
        group = self._group_frame(group_title)
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel(group_title, group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        spin_min = self._spin(group)
        spin_max = self._spin(group)
        edit_label = QLineEdit(group)
        combo_scale = QComboBox(group)
        combo_scale.addItems(["线性", "对数"])
        chk_auto = QCheckBox("自动范围", group)

        form.addRow("最小值", spin_min)
        form.addRow("最大值", spin_max)
        form.addRow("标签", edit_label)
        form.addRow("刻度", combo_scale)
        box.addLayout(form)
        box.addWidget(chk_auto)

        setattr(self, f"spin_{axis}_min", spin_min)
        setattr(self, f"spin_{axis}_max", spin_max)
        setattr(self, f"edit_{axis}_label", edit_label)
        setattr(self, f"combo_{axis}_scale", combo_scale)
        setattr(self, f"chk_{axis}_auto", chk_auto)
        return group

    def _curve_group(self):
        group = self._group_frame("曲线")
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel("曲线", group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.combo_curve = QComboBox(group)
        for i, line in enumerate(self._lines):
            label = line.get_label()
            if not label or label.startswith("_"):
                label = f"曲线 {i + 1}"
            self.combo_curve.addItem(label)
        if not self._lines:
            self.combo_curve.addItem("无可编辑曲线")
            self.combo_curve.setEnabled(False)

        self.edit_curve_color = QLineEdit(group)
        self.edit_curve_color.setPlaceholderText("#1769e0")
        self.btn_curve_color = QPushButton("选择", group)
        color_row = QWidget(group)
        color_lay = QHBoxLayout(color_row)
        color_lay.setContentsMargins(0, 0, 0, 0)
        color_lay.setSpacing(6)
        color_lay.addWidget(self.edit_curve_color, stretch=1)
        color_lay.addWidget(self.btn_curve_color)
        if not self._lines:
            self.edit_curve_color.setEnabled(False)
            self.btn_curve_color.setEnabled(False)

        form.addRow("对象", self.combo_curve)
        form.addRow("颜色", color_row)
        box.addLayout(form)
        return group

    def _mappable_group(self):
        group = self._group_frame("色图与色阶")
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel("色图与色阶", group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.chk_color_auto = QCheckBox("自动色阶范围", group)
        self.combo_cmap = QComboBox(group)
        self.combo_cmap.addItems(SUPPORTED_HEATMAP_COLORMAPS)
        self.spin_color_min = self._spin(group)
        self.spin_color_max = self._spin(group)

        form.addRow("色图", self.combo_cmap)
        form.addRow("最小值", self.spin_color_min)
        form.addRow("最大值", self.spin_color_max)
        box.addLayout(form)
        box.addWidget(self.chk_color_auto)

        if not self._mappables:
            self.chk_color_auto.setEnabled(False)
            self.combo_cmap.setEnabled(False)
            self.spin_color_min.setEnabled(False)
            self.spin_color_max.setEnabled(False)
        return group

    def _group_frame(self, _title):
        frame = QFrame(self)
        frame.setObjectName("chartOptionsGroup")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        return frame

    def _spin(self, parent):
        spin = CompactDoubleSpinBox(parent)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setRange(-1e15, 1e15)
        spin.setDecimals(6)
        return spin

    def _read_axes(self):
        xlo, xhi = self.handle.get_xlim()
        ylo, yhi = self.handle.get_ylim()
        try:
            grid_visible = bool(self.handle.is_grid_enabled())
        except AttributeError:
            grid_visible = False
        try:
            x_scale_raw = self.handle.get_xscale()
        except AttributeError:
            x_scale_raw = "linear"
        try:
            y_scale_raw = self.handle.get_yscale()
        except AttributeError:
            y_scale_raw = "linear"
        # Fallbacks for older/custom handles that do not yet expose the full
        # state surface.
        if self.ax is not None and not hasattr(self.handle, "is_grid_enabled"):
            grid_lines = list(self.ax.xaxis.get_gridlines()) + list(self.ax.yaxis.get_gridlines())
            grid_visible = any(line.get_visible() for line in grid_lines)
        if self.ax is not None and not hasattr(self.handle, "get_xscale"):
            x_scale_raw = self.ax.get_xscale()
        if self.ax is not None and not hasattr(self.handle, "get_yscale"):
            y_scale_raw = self.ax.get_yscale()
        if hasattr(self.handle, "is_autorange"):
            x_auto = bool(self.handle.is_autorange("x"))
            y_auto = bool(self.handle.is_autorange("y"))
        else:
            x_auto = False
            y_auto = False
        line = self._current_line()
        line_color = self._line_color_text(line) if line is not None else ""
        mappable = self._current_mappable()
        if mappable is not None:
            cmin, cmax = mappable.get_clim()
            cmap = mappable.get_cmap().name
        else:
            cmin, cmax = 0.0, 1.0
            cmap = SUPPORTED_HEATMAP_COLORMAPS[0]
        return {
            "title": self.handle.get_title(),
            "x_min": float(xlo),
            "x_max": float(xhi),
            "x_label": self.handle.get_xlabel(),
            "x_scale": self.SCALE_TO_TEXT.get(x_scale_raw, x_scale_raw),
            "x_auto": x_auto,
            "y_min": float(ylo),
            "y_max": float(yhi),
            "y_label": self.handle.get_ylabel(),
            "y_scale": self.SCALE_TO_TEXT.get(y_scale_raw, y_scale_raw),
            "y_auto": y_auto,
            "grid": grid_visible,
            "legend": False,
            "curve_index": 0,
            "curve_color": line_color,
            "color_min": float(cmin),
            "color_max": float(cmax),
            "color_auto": False,
            "cmap": cmap,
        }

    def reset_fields(self):
        d = self._initial
        self.edit_title.setText(d["title"])
        self.spin_x_min.setValue(d["x_min"])
        self.spin_x_max.setValue(d["x_max"])
        self.edit_x_label.setText(d["x_label"])
        self.combo_x_scale.setCurrentText(d["x_scale"])
        self.chk_x_auto.setChecked(d["x_auto"])
        self.spin_y_min.setValue(d["y_min"])
        self.spin_y_max.setValue(d["y_max"])
        self.edit_y_label.setText(d["y_label"])
        self.combo_y_scale.setCurrentText(d["y_scale"])
        self.chk_y_auto.setChecked(d["y_auto"])
        self.chk_grid.setChecked(d["grid"])
        self.chk_legend.setChecked(d["legend"])
        self.combo_curve.setCurrentIndex(d["curve_index"] if self._lines else 0)
        self.edit_curve_color.setText(d["curve_color"])
        self.combo_cmap.setCurrentText(d["cmap"])
        self.spin_color_min.setValue(d["color_min"])
        self.spin_color_max.setValue(d["color_max"])
        self.chk_color_auto.setChecked(d["color_auto"])
        self._sync_auto_fields()

    def apply_changes(self):
        # Reset per-apply error collector; repeated clicks must not carry
        # invalid-axis state from a previous attempt.
        self._invalid_axes = []
        self.handle.set_title(self.edit_title.text())
        self._apply_axis(
            axis="x",
            auto=self.chk_x_auto.isChecked(),
            vmin=self.spin_x_min.value(),
            vmax=self.spin_x_max.value(),
            label=self.edit_x_label.text(),
            scale_text=self.combo_x_scale.currentText(),
        )
        self._apply_axis(
            axis="y",
            auto=self.chk_y_auto.isChecked(),
            vmin=self.spin_y_min.value(),
            vmax=self.spin_y_max.value(),
            label=self.edit_y_label.text(),
            scale_text=self.combo_y_scale.currentText(),
        )
        if self.chk_grid.isChecked() != self._initial.get("grid", False):
            self.handle.grid(self.chk_grid.isChecked())
        if self.chk_legend.isChecked() and hasattr(self.handle, "rebuild_legend"):
            self.handle.rebuild_legend()
        elif self.chk_legend.isChecked() and self.ax is not None:
            handles, labels = self.ax.get_legend_handles_labels()
            pairs = [(h, l) for h, l in zip(handles, labels) if l and not l.startswith("_")]
            if pairs:
                handles, labels = zip(*pairs)
                self.ax.legend(handles, labels)
        self._apply_appearance()
        self.handle.request_redraw()
        if self._invalid_axes:
            # Log scale + non-positive range: scale switch and label/legend
            # changes still landed (user may want them), but the manual range
            # was rejected and the axis fell back to autoscale. Surface that
            # to the user; do NOT mark _applied so the OK path can refuse to
            # close.
            QMessageBox.warning(
                self,
                "范围非法",
                "对数刻度下 X/Y 范围必须 > 0",
            )
            self._applied = False
            self._focus_first_invalid_axis()
            return
        self._applied = True

    def was_applied(self):
        return self._applied

    def _apply_axis(self, *, axis, auto, vmin, vmax, label, scale_text):
        scale = self.TEXT_TO_SCALE.get(scale_text, "linear")
        if axis == "x":
            setter_scale = self.handle.set_xscale
            setter_lim = self.handle.set_xlim
            setter_label = self.handle.set_xlabel
        else:
            setter_scale = self.handle.set_yscale
            setter_lim = self.handle.set_ylim
            setter_label = self.handle.set_ylabel

        setter_scale(scale)
        if auto:
            self.handle.autoscale(axis=axis)
        else:
            if scale == "log" and (float(vmin) <= 0 or float(vmax) <= 0):
                # Defer hard error to the apply() aggregator: collect axis,
                # fall back to autoscale so the chart stays in a usable state
                # rather than silently keeping a stale range.
                self._invalid_axes.append(axis)
                self.handle.autoscale(axis=axis)
            else:
                setter_lim(float(vmin), float(vmax))
        setter_label(label)

    def _editable_lines(self):
        # ``handle.get_lines()`` already filters out invisible lines and
        # returns ``LineHandle`` wrappers.
        return list(self.handle.get_lines())

    def _editable_mappables(self):
        # ``handle.get_mappables()`` returns the same set the legacy
        # ``ax.images + ax.collections`` walk produced. For TimeDomain
        # this is empty (design §5.3), which correctly disables the
        # ColorMap/ColorScale group below.
        return list(self.handle.get_mappables())

    def _current_line(self):
        if not self._lines:
            return None
        idx = max(0, min(self.combo_curve.currentIndex(), len(self._lines) - 1)) \
            if hasattr(self, "combo_curve") else 0
        return self._lines[idx]

    def _current_mappable(self):
        return self._mappables[0] if self._mappables else None

    def _line_color_text(self, line):
        try:
            return _to_hex(line.get_color())
        except ValueError:
            return str(line.get_color())

    def _sync_curve_color(self):
        line = self._current_line()
        if line is not None:
            self.edit_curve_color.setText(self._line_color_text(line))

    def _sync_auto_fields(self):
        for axis in ("x", "y"):
            auto = getattr(self, f"chk_{axis}_auto").isChecked()
            getattr(self, f"spin_{axis}_min").setEnabled(not auto)
            getattr(self, f"spin_{axis}_max").setEnabled(not auto)
        color_enabled = bool(self._mappables) and not self.chk_color_auto.isChecked()
        self.spin_color_min.setEnabled(color_enabled)
        self.spin_color_max.setEnabled(color_enabled)

    def _choose_curve_color(self):
        initial = self.edit_curve_color.text().strip()
        initial_color = (
            QColor(_to_hex(initial))
            if _is_color_like(initial)
            else QColor("#1769e0")
        )
        color = QColorDialog.getColor(
            initial_color,
            self,
            "选择颜色",
        )
        if color.isValid():
            self.edit_curve_color.setText(color.name())

    def _apply_appearance(self):
        line = self._current_line()
        color = self.edit_curve_color.text().strip()
        if line is not None and color and _is_color_like(color):
            line.set_color(color)
            self._sync_curve_axis_color(line, color)

        mappable = self._current_mappable()
        if mappable is None:
            return
        mappable.set_cmap(self.combo_cmap.currentText())
        if self.chk_color_auto.isChecked():
            arr = mappable.get_array()
            if arr is not None:
                data = np.asarray(arr, dtype=float)
                finite = data[np.isfinite(data)]
                if finite.size:
                    mappable.set_clim(float(np.min(finite)), float(np.max(finite)))
        else:
            mappable.set_clim(
                float(self.spin_color_min.value()),
                float(self.spin_color_max.value()),
            )

    def _sync_curve_axis_color(self, line, color):
        sync = getattr(self.handle, "sync_line_axis_color", None)
        if callable(sync):
            sync(line, color)

        # Older custom handles may expose an axes-like raw line for
        # canvas/inside-label sync paths. Built-in pyqtgraph handles perform
        # their sync in ``handle.sync_line_axis_color`` above.
        raw_line = getattr(line, "line", line)
        ax = getattr(raw_line, "axes", None) or self.ax
        if ax is None:
            return

        canvas = getattr(ax.figure, "canvas", None)
        channel_name = self._channel_name_for_line(canvas, raw_line)
        if channel_name is None:
            return

        channel_data = getattr(canvas, "channel_data", None)
        if isinstance(channel_data, dict) and channel_name in channel_data:
            t, sig, _old_color, unit = channel_data[channel_name]
            channel_data[channel_name] = (t, sig, color, unit)

        for artist in getattr(canvas, "_inside_channel_label_artists", []):
            if artist.get_gid() != channel_name:
                continue
            artist.set_color(color)
            patch = artist.get_bbox_patch()
            if patch is not None:
                patch.set_edgecolor(color)

    def _axis_side_for_line(self, ax):
        canvas = getattr(ax.figure, "canvas", None)
        axes_list = getattr(canvas, "axes_list", [])
        if getattr(canvas, "_overlay_mode", False) and axes_list and ax is not axes_list[0]:
            return 'right'
        label_pos = getattr(ax.yaxis, "get_label_position", lambda: "left")()
        tick_pos = getattr(ax.yaxis, "get_ticks_position", lambda: "left")()
        if label_pos == 'right' or tick_pos == 'right':
            return 'right'
        return 'left'

    def _channel_name_for_line(self, canvas, line):
        if canvas is None:
            return None
        for name, (_ax, channel_line) in getattr(canvas, "_channel_lines", {}).items():
            if channel_line is line:
                return name
        return None

    def _focus_first_invalid_axis(self):
        if not self._invalid_axes:
            return
        axis = self._invalid_axes[0]
        self.tabs.setCurrentIndex(0)
        field = getattr(self, f"spin_{axis}_min", None)
        if field is not None:
            field.setFocus(Qt.OtherFocusReason)

    def _accept_with_apply(self):
        self.apply_changes()
        # If apply rejected (e.g. log + non-positive range), keep the dialog
        # open so the user can correct the input.
        if self._invalid_axes:
            return
        self.accept()

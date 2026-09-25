"""Chart options dialog: per-axes appearance and scaling controls."""
from functools import partial
import math
import re

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
from PyQt5.QtGui import QColor, QValidator

from ...ui_kit.dialog_button_defaults import set_unique_default_button
from ...ui_kit.dialog_geometry import fit_window, nudge_into_work_area
from .._axis_handle import make_handle
from .._color_utils import is_color_like as _is_color_like
from .._color_utils import to_hex as _to_hex
from ..pg_canvas.heatmap_canvas import SUPPORTED_HEATMAP_COLORMAPS
from ..widgets.compact_spinbox import CompactDoubleSpinBox


_NUMBER_RE = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$"
)
_PARTIAL_NUMBER_RE = re.compile(
    r"^[+-]?(?:\d+\.?\d*|\.\d+)?(?:[eE][+-]?\d*)?$"
)
_LOG_DISABLED_TIP = "热图没有对数映射。开启对数会让坐标轴、像素、切片和读数脱节。"
_CURVE_DISABLED_TIP = "当前没有可编辑曲线。"
_LEGEND_DISABLED_TIP = "当前图没有线条，或不支持重新生成图例。"
_COLOR_DISABLED_TIP = "当前图没有色阶。"
_SHARED_AXIS_NOTE = "标题与网格属于整张图，X 为共享轴，Y 与曲线属于当前轴。"


def _parse_chart_number(text):
    raw = str(text).strip().replace(" ", "")
    if not raw or _NUMBER_RE.fullmatch(raw) is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _format_chart_number(value):
    number = float(value)
    if not math.isfinite(number):
        return "nan" if math.isnan(number) else ("inf" if number > 0 else "-inf")
    if number == 0.0:
        return "0.0"
    magnitude = abs(number)
    text = f"{number:.8g}" if magnitude < 1e-4 or magnitude >= 1e6 else f"{number:.12g}"
    lower = text.lower()
    if "e" in lower:
        mantissa, exponent = lower.split("e", 1)
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}e{int(exponent)}"
    if "." not in text:
        return text + ".0"
    return text


class _ChartFloatSpin(CompactDoubleSpinBox):
    """Chart-options float field. Unedited commits keep the original float."""

    def __init__(self, parent=None):
        # Qt calls textFromValue during QDoubleSpinBox setup, before the
        # rest of this constructor runs.
        self._source = None
        self._user_edited = False
        self._edited_text = None
        self._loading = True
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setRange(-1e15, 1e15)
        self.setDecimals(6)
        self._loading = False
        self.lineEdit().textEdited.connect(self._on_text_edited)

    def set_source_value(self, value):
        number = float(value)
        self._loading = True
        self.blockSignals(True)
        self._user_edited = False
        self._edited_text = None
        self._source = number
        super().setValue(number)
        self.blockSignals(False)
        self._loading = False

    def value_for_commit(self):
        if self._user_edited and self._edited_text is not None:
            parsed = _parse_chart_number(self._edited_text)
            if parsed is not None:
                return float(parsed)
        if self._source is not None and not self._user_edited:
            return float(self._source)
        return float(self.value())

    def textFromValue(self, value):  # noqa: N802
        if not getattr(self, "_user_edited", False) and getattr(self, "_source", None) is not None:
            return _format_chart_number(self._source)
        return _format_chart_number(float(value))

    def valueFromText(self, text):  # noqa: N802
        parsed = _parse_chart_number(text)
        if parsed is None:
            return float(self.value())
        return float(parsed)

    def validate(self, text, pos):  # noqa: N802
        raw = str(text).strip()
        if raw and _parse_chart_number(raw) is not None:
            return QValidator.Acceptable, text, pos
        if _PARTIAL_NUMBER_RE.fullmatch(raw or ""):
            return QValidator.Intermediate, text, pos
        return QValidator.Invalid, text, pos

    def setValue(self, value):  # noqa: N802
        if self._loading:
            super().setValue(value)
            return
        super().setValue(value)
        if self._edited_text:
            return
        if self._source is not None and not self._user_edited:
            decimals = int(self.decimals())
            rounded = round(float(self._source), decimals)
            tolerance = 10 ** (-decimals)
            if (
                abs(float(value) - rounded) <= tolerance
                and abs(float(self._source) - rounded) > 0
            ):
                return
        self._user_edited = True
        self._edited_text = None

    def _on_text_edited(self, text):
        if self._loading:
            return
        self._user_edited = True
        self._edited_text = text


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
        self.setAttribute(Qt.WA_AlwaysShowToolTips, True)
        self._ever_applied = False
        self._last_apply_ok = False
        self._invalid_axes: list[str] = []
        self._loading = True
        self._opened = self._read_axes()
        # Older tests still read the open snapshot under this name.
        self._initial = self._opened
        self._committed = dict(self._opened)
        self._curve_opened = self._capture_curve_colors()
        self._curve_drafts = dict(self._curve_opened)
        self._curve_committed = dict(self._curve_opened)
        self._curve_combo_index = 0
        self._color_policy_dirty = False
        self._range_axes_edited = set()

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
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(subtitle)
        if self._shares_x_axis():
            shared = QLabel(_SHARED_AXIS_NOTE, self)
            shared.setObjectName("chartOptionsSharedNote")
            shared.setWordWrap(True)
            header.addWidget(shared)
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
        self.btn_reset = QPushButton("恢复打开时设置", self)
        self.btn_reset.setToolTip("恢复打开对话框时的设置，不是出厂默认。应用后才改图。")
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
        self.chk_color_auto.toggled.connect(self._note_color_policy)
        self.combo_curve.currentIndexChanged.connect(self._on_curve_changed)
        self.btn_curve_color.clicked.connect(self._choose_curve_color)
        self.spin_color_min.valueChanged.connect(self._note_color_policy)
        self.spin_color_max.valueChanged.connect(self._note_color_policy)
        self.spin_color_min.lineEdit().textEdited.connect(self._note_color_policy)
        self.spin_color_max.lineEdit().textEdited.connect(self._note_color_policy)
        self.reset_fields()
        self._range_axes_edited = set()
        self._color_policy_dirty = False
        for axis in ("x", "y"):
            getattr(self, f"chk_{axis}_auto").toggled.connect(partial(self._note_range_edit, axis))
            getattr(self, f"spin_{axis}_min").valueChanged.connect(partial(self._note_range_edit, axis))
            getattr(self, f"spin_{axis}_max").valueChanged.connect(partial(self._note_range_edit, axis))
            getattr(self, f"spin_{axis}_min").lineEdit().textEdited.connect(
                partial(self._note_range_edit, axis)
            )
            getattr(self, f"spin_{axis}_max").lineEdit().textEdited.connect(
                partial(self._note_range_edit, axis)
            )
        self._loading = False
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
        reader = getattr(self.handle, "chart_options_target_text", None)
        if callable(reader):
            text = str(reader() or "").strip()
            if text:
                return text if text.startswith("目标") else f"目标：{text}"
        title = str(self.handle.get_title() or "").strip()
        if not title and self.ax is not None:
            getter = getattr(self.ax, "get_label", None)
            if callable(getter):
                title = str(getter() or "").strip()
        if title:
            return f"目标：{title}"
        xlabel = str(self.handle.get_xlabel() or "").strip()
        ylabel = str(self.handle.get_ylabel() or "").strip()
        if xlabel or ylabel:
            return f"目标：{xlabel or 'X'} / {ylabel or 'Y'}"
        return "目标：未命名坐标轴"

    def _shares_x_axis(self):
        probe = getattr(self.handle, "shares_x_axis", None)
        if not callable(probe):
            return False
        return bool(probe())

    def _axis_supports_log(self, axis):
        probe = getattr(self.handle, "supports_log_scale", None)
        if not callable(probe):
            return True
        try:
            return bool(probe(axis))
        except TypeError:
            return bool(probe())

    def _legend_supported(self):
        probe = getattr(self.handle, "supports_legend_rebuild", None)
        if callable(probe):
            supported = bool(probe())
        else:
            supported = bool(self._lines)
        return supported and bool(self._lines)

    def _apply_capability_locks(self):
        for axis in ("x", "y"):
            combo = getattr(self, f"combo_{axis}_scale")
            if self._axis_supports_log(axis):
                combo.setEnabled(True)
                combo.setToolTip("")
            else:
                combo.setEnabled(False)
                combo.setToolTip(_LOG_DISABLED_TIP)
        if not self._lines:
            for widget in (self.combo_curve, self.edit_curve_color, self.btn_curve_color):
                widget.setEnabled(False)
                widget.setToolTip(_CURVE_DISABLED_TIP)
        if not self._legend_supported():
            self.chk_legend.setEnabled(False)
            self.chk_legend.setToolTip(_LEGEND_DISABLED_TIP)
        if not self._mappables:
            for widget in (
                self.chk_color_auto, self.combo_cmap,
                self.spin_color_min, self.spin_color_max,
            ):
                widget.setEnabled(False)
                widget.setToolTip(_COLOR_DISABLED_TIP)

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
        return _ChartFloatSpin(parent)

    def _read_axis_limits(self, axis):
        # Engineering limits are the dialog contract. Until every handle
        # exposes them, fall back to the legacy view-box getter.
        getter = getattr(self.handle, f"get_engineering_{axis}lim", None)
        if callable(getter):
            lo, hi = getter()
            return float(lo), float(hi)
        if axis == "x":
            lo, hi = self.handle.get_xlim()
        else:
            lo, hi = self.handle.get_ylim()
        return float(lo), float(hi)

    def _write_axis_limits(self, axis, lo, hi):
        setter = getattr(self.handle, f"set_engineering_{axis}lim", None)
        if callable(setter):
            setter(float(lo), float(hi))
            return
        if axis == "x":
            self.handle.set_xlim(float(lo), float(hi))
        else:
            self.handle.set_ylim(float(lo), float(hi))

    def _read_axes(self):
        xlo, xhi = self._read_axis_limits("x")
        ylo, yhi = self._read_axis_limits("y")
        read_policy = getattr(self.handle, "analysis_range_policy", None)
        policy = read_policy() if callable(read_policy) else None
        if policy is not None:
            if not policy.get("x_auto", policy.get("autoscale", True)):
                xlo, xhi = policy.get("x_min", xlo), policy.get("x_max", xhi)
            if not policy.get("y_auto", True):
                ylo, yhi = policy.get("y_min", ylo), policy.get("y_max", yhi)
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
        color_auto = False
        if mappable is not None:
            cmin, cmax = mappable.get_clim()
            cmap = mappable.get_cmap().name
            auto_reader = getattr(mappable, "is_color_auto", None)
            if callable(auto_reader):
                color_auto = bool(auto_reader())
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
            "color_auto": color_auto,
            "cmap": cmap,
        }

    def reset_fields(self):
        self._loading = True
        d = self._opened
        self.edit_title.setText(d["title"])
        self.spin_x_min.set_source_value(d["x_min"])
        self.spin_x_max.set_source_value(d["x_max"])
        self.edit_x_label.setText(d["x_label"])
        self.combo_x_scale.setCurrentText(d["x_scale"])
        self.chk_x_auto.setChecked(d["x_auto"])
        self.spin_y_min.set_source_value(d["y_min"])
        self.spin_y_max.set_source_value(d["y_max"])
        self.edit_y_label.setText(d["y_label"])
        self.combo_y_scale.setCurrentText(d["y_scale"])
        self.chk_y_auto.setChecked(d["y_auto"])
        self.chk_grid.setChecked(d["grid"])
        self.chk_legend.setChecked(False)
        self._curve_drafts = dict(self._curve_opened)
        index = d["curve_index"] if self._lines else 0
        self._curve_combo_index = index
        self.combo_curve.setCurrentIndex(index)
        self.combo_cmap.setCurrentText(d["cmap"])
        self.spin_color_min.set_source_value(d["color_min"])
        self.spin_color_max.set_source_value(d["color_max"])
        self.chk_color_auto.setChecked(bool(d["color_auto"]))
        self._show_curve_color(index)
        self._color_policy_dirty = False
        self._range_axes_edited = set()
        self._loading = False
        self._sync_auto_fields()
        self._apply_capability_locks()

    def _note_range_edit(self, axis, _value=None):
        if self._loading:
            return
        self._range_axes_edited.add(axis)

    def _note_color_policy(self, _value=None):
        if self._loading:
            return
        self._color_policy_dirty = True

    def apply_changes(self):
        self._invalid_axes = []
        self._last_apply_ok = False
        self._error_focus = None
        errors = self._collect_errors()
        if errors:
            QMessageBox.warning(self, "图表选项", "\n".join(errors))
            self._focus_first_invalid_axis()
            return
        # Unchanged applies still reapply the analysis range policy. That
        # decision is separate from the last committed appearance diff.
        appearance_dirty = self._appearance_dirty()
        range_edited = set(self._range_axes_edited)
        self._commit_valid_draft(appearance_dirty, range_edited)
        self._last_apply_ok = True
        self._ever_applied = True
        self._range_axes_edited.clear()
        self._color_policy_dirty = False

    def was_applied(self):
        return self._ever_applied

    def _collect_errors(self):
        errors = []
        self._error_focus = None
        for axis in ("x", "y"):
            self._validate_manual_range(axis, errors)
        self._validate_colors(errors)
        self._validate_color_scale(errors)
        return errors

    def _validate_manual_range(self, axis, errors):
        spin_min = getattr(self, f"spin_{axis}_min")
        spin_max = getattr(self, f"spin_{axis}_max")
        if not spin_min.isEnabled() or not spin_max.isEnabled():
            return
        if axis not in self._range_axes_edited and not self._scale_changed(axis):
            return
        min_name, max_name = {
            "x": ("X 最小值", "X 最大值"),
            "y": ("Y 最小值", "Y 最大值"),
        }[axis]
        lo = self._finite_spin_value(spin_min, min_name, errors)
        hi = self._finite_spin_value(spin_max, max_name, errors)
        if lo is None or hi is None:
            self._invalid_axes.append(axis)
            self._remember_focus(spin_min)
            return
        log_mode = self._scale_changed(axis) or self._draft_scale(axis) == "log"
        log_active = (
            log_mode
            and self._axis_supports_log(axis)
            and getattr(self, f"combo_{axis}_scale").isEnabled()
            and self._draft_scale(axis) == "log"
        )
        invalid = False
        if log_active and lo <= 0:
            errors.append(f"{min_name}在对数刻度下必须大于 0")
            invalid = True
        if log_active and hi <= 0:
            errors.append(f"{max_name}在对数刻度下必须大于 0")
            invalid = True
        if lo >= hi:
            errors.append(f"{min_name}必须小于 {max_name}")
            invalid = True
        if invalid:
            self._invalid_axes.append(axis)
            self._remember_focus(spin_min)

    def _finite_spin_value(self, spin, label, errors):
        if spin._user_edited and spin._edited_text is not None:
            parsed = _parse_chart_number(spin._edited_text)
            if parsed is None:
                errors.append(f"{label}必须是有限数")
                return None
            return float(parsed)
        value = spin.value_for_commit()
        if not math.isfinite(value):
            errors.append(f"{label}必须是有限数")
            return None
        return float(value)

    def _validate_colors(self, errors):
        if not self._lines or not self.edit_curve_color.isEnabled():
            return
        self._stash_curve_draft()
        for ident, draft in self._curve_drafts.items():
            if draft == self._curve_committed.get(ident, ""):
                continue
            if draft and not _is_color_like(draft):
                errors.append("颜色不是合法颜色")
                self._remember_focus(self.edit_curve_color)
                return

    def _validate_color_scale(self, errors):
        if not self._mappables or not self._color_policy_dirty:
            return
        if not self.spin_color_min.isEnabled() or not self.spin_color_max.isEnabled():
            return
        lo = self._finite_spin_value(self.spin_color_min, "色阶最小值", errors)
        hi = self._finite_spin_value(self.spin_color_max, "色阶最大值", errors)
        if lo is None or hi is None:
            self._remember_focus(self.spin_color_min)
            return
        if lo >= hi:
            errors.append("色阶最小值必须小于色阶最大值")
            self._remember_focus(self.spin_color_min)

    def _remember_focus(self, widget):
        if self._error_focus is None and widget is not None:
            self._error_focus = widget

    def _scale_changed(self, axis):
        combo = getattr(self, f"combo_{axis}_scale")
        if not combo.isEnabled():
            return False
        return combo.currentText() != self._committed.get(f"{axis}_scale")

    def _draft_scale(self, axis):
        text = getattr(self, f"combo_{axis}_scale").currentText()
        return self.TEXT_TO_SCALE.get(text, "linear")

    def _has_analysis_policy(self):
        reader = getattr(self.handle, "analysis_range_policy", None)
        if not callable(reader):
            return False
        return reader() is not None

    def _appearance_dirty(self):
        committed = self._committed
        if self.edit_title.text().strip() != str(committed.get("title") or "").strip():
            return True
        if self.edit_x_label.text() != committed.get("x_label"):
            return True
        if self.edit_y_label.text() != committed.get("y_label"):
            return True
        if self._scale_changed("x") or self._scale_changed("y"):
            return True
        if self.chk_grid.isChecked() != bool(committed.get("grid")):
            return True
        if self.chk_legend.isEnabled() and self.chk_legend.isChecked():
            return True
        if self._curve_colors_dirty():
            return True
        if self._mappables and self.combo_cmap.isEnabled():
            if self.combo_cmap.currentText() != committed.get("cmap"):
                return True
        if self._color_policy_dirty:
            return True
        return False

    def _commit_valid_draft(self, appearance_dirty, range_edited):
        self._commit_title()
        has_policy = self._has_analysis_policy()
        for axis in ("x", "y"):
            scale_changed = self._scale_changed(axis)
            self._commit_scale(axis)
            self._commit_label(axis)
            self._commit_range(
                axis,
                has_policy=has_policy,
                range_edited=range_edited,
                scale_changed=scale_changed,
            )
        self._commit_grid()
        self._commit_curves()
        self._commit_cmap()
        self._commit_color_policy()
        if self.chk_legend.isEnabled() and self.chk_legend.isChecked():
            self._rebuild_legend()
            self._loading = True
            self.chk_legend.setChecked(False)
            self._loading = False
        self._commit_analysis_policy(appearance_dirty, range_edited, has_policy)
        self.handle.request_redraw()
        self._refresh_spin_sources()

    def _commit_title(self):
        title = self.edit_title.text().strip()
        if title == str(self._committed.get("title") or "").strip():
            return
        self.handle.set_title(title)
        self._committed["title"] = title

    def _commit_scale(self, axis):
        if not self._scale_changed(axis):
            return
        scale = self._draft_scale(axis)
        if axis == "x":
            self.handle.set_xscale(scale)
        else:
            self.handle.set_yscale(scale)
        self._committed[f"{axis}_scale"] = getattr(self, f"combo_{axis}_scale").currentText()

    def _commit_label(self, axis):
        text = getattr(self, f"edit_{axis}_label").text()
        if text == self._committed.get(f"{axis}_label"):
            return
        if axis == "x":
            self.handle.set_xlabel(text)
        else:
            self.handle.set_ylabel(text)
        self._committed[f"{axis}_label"] = text

    def _commit_range(self, axis, *, has_policy, range_edited, scale_changed):
        edited = axis in range_edited
        if has_policy and not edited:
            return
        if not edited and not scale_changed:
            return
        auto = getattr(self, f"chk_{axis}_auto").isChecked()
        self._committed[f"{axis}_auto"] = auto
        if auto:
            self.handle.autoscale(axis=axis)
            return
        lo = getattr(self, f"spin_{axis}_min").value_for_commit()
        hi = getattr(self, f"spin_{axis}_max").value_for_commit()
        self._write_axis_limits(axis, lo, hi)
        self._committed[f"{axis}_min"] = float(lo)
        self._committed[f"{axis}_max"] = float(hi)

    def _commit_grid(self):
        checked = self.chk_grid.isChecked()
        if checked == bool(self._committed.get("grid")):
            return
        self.handle.grid(checked)
        self._committed["grid"] = checked

    def _commit_curves(self):
        if not self._lines or not self.edit_curve_color.isEnabled():
            return
        self._stash_curve_draft()
        for line in self._lines:
            ident = self._curve_identity(line)
            draft = self._curve_drafts.get(ident, "")
            if not draft or draft == self._curve_committed.get(ident, ""):
                continue
            line.set_color(draft)
            self._sync_curve_axis_color(line, draft)
            self._curve_committed[ident] = draft

    def _commit_cmap(self):
        if not self._mappables or not self.combo_cmap.isEnabled():
            return
        name = self.combo_cmap.currentText()
        if name == self._committed.get("cmap"):
            return
        self._current_mappable().set_cmap(name)
        self._committed["cmap"] = name

    def _commit_color_policy(self):
        if not self._mappables or not self._color_policy_dirty:
            return
        mappable = self._current_mappable()
        if mappable is None:
            return
        auto = self.chk_color_auto.isChecked()
        lo = float(self.spin_color_min.value_for_commit())
        hi = float(self.spin_color_max.value_for_commit())
        policy = getattr(mappable, "apply_color_policy", None)
        if callable(policy):
            policy(bool(auto), lo, hi)
        elif not auto:
            mappable.set_clim(lo, hi)
        self._committed["color_auto"] = bool(auto)
        self._committed["color_min"] = lo
        self._committed["color_max"] = hi

    def _commit_analysis_policy(self, appearance_dirty, range_edited, has_policy):
        if not has_policy:
            return
        apply_policy = getattr(self.handle, "apply_analysis_range_policy", None)
        if not callable(apply_policy):
            return
        if range_edited:
            axes = set(range_edited)
        elif not appearance_dirty:
            axes = {"x", "y"}
        else:
            return
        policies = {}
        for axis in axes:
            auto = getattr(self, f"chk_{axis}_auto").isChecked()
            lo = getattr(self, f"spin_{axis}_min").value_for_commit()
            hi = getattr(self, f"spin_{axis}_max").value_for_commit()
            policies[axis] = (auto, (lo, hi))
        if policies:
            apply_policy(policies)

    def _refresh_spin_sources(self):
        self._loading = True
        for axis in ("x", "y"):
            for end in ("min", "max"):
                spin = getattr(self, f"spin_{axis}_{end}")
                spin.set_source_value(spin.value_for_commit())
        if self._mappables:
            self.spin_color_min.set_source_value(self.spin_color_min.value_for_commit())
            self.spin_color_max.set_source_value(self.spin_color_max.value_for_commit())
        self._loading = False

    def _rebuild_legend(self):
        if hasattr(self.handle, "rebuild_legend"):
            self.handle.rebuild_legend()
            return
        if self.ax is None:
            return
        handles, labels = self.ax.get_legend_handles_labels()
        pairs = [(h, label) for h, label in zip(handles, labels) if label and not label.startswith("_")]
        if pairs:
            handles, labels = zip(*pairs)
            self.ax.legend(handles, labels)

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

    def _capture_curve_colors(self):
        colors = {}
        for line in self._lines:
            colors[self._curve_identity(line)] = self._line_color_text(line)
        return colors

    def _curve_identity(self, line):
        for name in ("composite_key", "channel_key"):
            probe = getattr(line, name, None)
            if not callable(probe):
                continue
            try:
                key = probe()
            except (TypeError, ValueError, AttributeError):
                key = None
            if key not in (None, ""):
                return ("channel", key)
        resolver = getattr(self.handle, "_composite_key_for_line", None)
        owner = getattr(self.handle, "_owner_canvas", None)
        if callable(resolver):
            try:
                key = resolver(owner, line)
            except (TypeError, ValueError, AttributeError):
                key = None
            if key not in (None, ""):
                return ("channel", key)
        curve = getattr(line, "plot_data_item", None)
        if curve is None:
            curve = line
        return ("curve", id(curve))

    def _stash_curve_draft(self):
        line = self._current_line()
        if line is None or not self.edit_curve_color.isEnabled():
            return
        self._curve_drafts[self._curve_identity(line)] = self.edit_curve_color.text().strip()

    def _curve_colors_dirty(self):
        if not self._lines or not self.edit_curve_color.isEnabled():
            return False
        self._stash_curve_draft()
        return any(
            draft != self._curve_committed.get(ident, "")
            for ident, draft in self._curve_drafts.items()
        )

    def _show_curve_color(self, index):
        if not self._lines:
            return
        idx = max(0, min(int(index), len(self._lines) - 1))
        ident = self._curve_identity(self._lines[idx])
        text = self._curve_drafts.get(ident, self._line_color_text(self._lines[idx]))
        self.edit_curve_color.setText(text)

    def _on_curve_changed(self, index):
        if self._loading:
            return
        prev = self._curve_combo_index
        if (
            self._lines
            and prev is not None
            and prev != index
            and 0 <= prev < len(self._lines)
        ):
            ident = self._curve_identity(self._lines[prev])
            self._curve_drafts[ident] = self.edit_curve_color.text().strip()
        self._curve_combo_index = index
        self._show_curve_color(index)

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
            self._stash_curve_draft()

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
        field = self._error_focus
        if self._invalid_axes:
            axis = self._invalid_axes[0]
            field = getattr(self, f"spin_{axis}_min", field)
            self.tabs.setCurrentIndex(0)
        elif field is self.edit_curve_color or field in (
            self.spin_color_min, self.spin_color_max,
        ):
            self.tabs.setCurrentIndex(1)
        if field is not None:
            field.setFocus(Qt.OtherFocusReason)

    def _accept_with_apply(self):
        self.apply_changes()
        if not self._last_apply_ok:
            return
        self.accept()

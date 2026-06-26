"""Right-click context-menu helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import qtawesome as qta
from PyQt5.QtCore import QSize, Qt, QSettings
from PyQt5.QtWidgets import (
    QAction,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from mf4_analyzer.ui.pg_canvas._shared import show_major_grid_left_bottom_only


_PG_CONTEXT_ACTIONS = {
    "ViewBox options": ("视图选项", "配置当前图表的视图范围和坐标轴。"),
    "View All": ("查看全部", "回到完整数据范围，等同于顶部工具栏的重置视图。"),
    "X axis": ("X 轴范围", "设置横轴范围。"),
    "Y axis": ("Y 轴范围", "设置纵轴范围。"),
    "Mouse Mode": ("鼠标模式", "切换图面左键拖动时的默认行为。"),
    "3 button": ("三键模式", "左键平移；右键或组合鼠标手势用于缩放。"),
    "1 button": ("单键模式", "左键框选缩放；适合临时放大一个局部区域。"),
    "Plot Options": ("绘图选项", "pyqtgraph 原生高级绘图开关；日常看曲线通常不用改。"),
    "Transforms": ("变换", "对曲线做对数、导数、FFT、去均值等显示变换。"),
    "Downsample": ("降采样", "大数据曲线的显示抽稀选项，影响绘制速度和视觉细节。"),
    "Average": ("平均", "显示多条曲线时的平均相关选项。"),
    "Alpha": ("透明度", "调整曲线透明度。"),
    "Grid": ("网格", "显示或隐藏 X/Y 网格线，并调整不透明度。"),
    "Points": ("点显示", "控制是否显示采样点标记。"),
    "Export...": ("导出...", "打开 pyqtgraph 导出窗口，可导出图片、SVG、CSV 等。"),
}

_PG_CONTEXT_WIDGETS = {
    "Mouse Enabled": ("鼠标交互", "允许这个坐标轴响应鼠标拖动和缩放。"),
    "Auto": ("自动", "根据当前数据自动调整范围。"),
    "Manual": ("手动", "手动输入当前坐标轴的最小值和最大值。"),
    "Link Axis:": ("关联坐标轴:", "让当前坐标轴跟随另一个视图同步。"),
    "Auto Pan Only": ("仅自动平移", "自动跟随数据中心，但不自动改变缩放比例。"),
    "Visible Data Only": ("仅可见数据", "自动缩放时只参考另一个方向可见范围内的数据。"),
    "Invert Axis": ("反转坐标轴", "反转这个坐标轴的显示方向。"),
    "Log X": ("X 对数", "把 X 轴按对数方式显示。"),
    "Log Y": ("Y 对数", "把 Y 轴按对数方式显示。"),
    "dy/dx": ("导数 dy/dx", "显示曲线的一阶导数。"),
    "Y vs. Y'": ("Y 对 Y'", "用另一条曲线作为横轴显示关系图。"),
    "Power Spectrum (FFT)": ("功率谱 (FFT)", "把曲线转换为频域功率谱显示。"),
    "Subtract Mean": ("去均值", "显示前先减去曲线平均值。"),
    "Clip to View": ("仅绘制可见范围", "只绘制当前视图里的数据，可提高大数据交互速度。"),
    "Max Traces:": ("最大曲线数:", "限制同时显示的曲线数量。"),
    "Downsample": ("降采样", "按指定倍率抽稀后再绘制。"),
    "Peak": ("峰值", "保留每段数据的最小/最大值，视觉细节较好但较慢。"),
    "Mean": ("均值", "每段数据取平均值后绘制。"),
    "Subsample": ("抽样", "每段只取一个样本，最快但细节最少。"),
    "Forget hidden traces": ("忘记隐藏曲线", "超过最大曲线数后释放隐藏曲线数据以节省内存。"),
    "Show X Grid": ("显示 X 网格", "显示横向时间网格线。"),
    "Show Y Grid": ("显示 Y 网格", "显示纵向数值网格线。"),
    "Opacity": ("不透明度", "调整网格或图元的不透明度。"),
}

_PG_MENU_REMOVE_TEXTS = frozenset({
    "Plot Options", "绘图选项",
    "Export...", "导出...", "导出…",
    "Mouse Mode", "鼠标模式", "鼠标操作",
})

_PG_AXIS_FORM_HIDE_OBJECTS = frozenset({
    "label",
    "linkCombo",
    "invertCheck",
    "autoPanCheck",
    "visibleOnlyCheck",
    "autoRadio",
    "autoPercentSpin",
    "mouseCheck",
})
_PG_AXIS_FORM_HIDE_TEXTS = frozenset({"Mouse Enabled", "鼠标交互"})

_PG_MOUSE_MODE_PAN = "pan"
_PG_MOUSE_MODE_ZOOM = "zoom"
_PG_MOUSE_MODE_LABELS = {
    _PG_MOUSE_MODE_PAN: ("平移", "左键拖动平移视图（与顶部工具栏的平移一致）。"),
    _PG_MOUSE_MODE_ZOOM: ("框选", "左键拖出矩形框选放大（与顶部工具栏的框选缩放一致）。"),
}
_PG_MOUSE_MODE_ICONS = {
    _PG_MOUSE_MODE_PAN: "mdi.cursor-move",
    _PG_MOUSE_MODE_ZOOM: "mdi.magnify-plus-outline",
}
_PG_ICON_COLOR = "#374151"
_PG_ICON_ACTIVE = "#2563eb"
_INLINE_TRACK_WIDTH = 72
_INLINE_MIDDLE_WIDTH = 24
_INLINE_LABEL_WIDTH = 40
_INLINE_CONTROL_HEIGHT = 30

_DEFAULT_CUSTOM_ACTION = "copy_image"
_CUSTOM_ACTION_SETTINGS_KEY = "chartContext/customAction"
_CUSTOM_ACTION_ORDER = [
    "copy_image", "home", "back", "forward", "y_fit", "view_all", "export",
]
_CUSTOM_ACTION_LABELS = {
    "copy_image": "复制为图片",
    "home": "重置视图",
    "back": "上一步视图",
    "forward": "下一步视图",
    "y_fit": "Y适应",
    "view_all": "全图",
    "export": "导出图片",
}
_CUSTOM_ACTION_ICONS = {
    "copy_image": "mdi.content-copy",
    "home": "mdi.home",
    "back": "mdi.arrow-left",
    "forward": "mdi.arrow-right",
    "y_fit": "mdi.arrow-expand-vertical",
    "view_all": "mdi.fit-to-page-outline",
    "export": "mdi.content-save-outline",
}
_CUSTOM_ACTION_CONTROLLER_METHODS = {
    "home": "home",
    "back": "back",
    "forward": "forward",
    "export": "save_figure",
}


def _load_custom_action(settings=None):
    settings = settings if settings is not None else QSettings()
    value = settings.value(_CUSTOM_ACTION_SETTINGS_KEY, _DEFAULT_CUSTOM_ACTION)
    text = str(value or "").strip()
    if text not in _CUSTOM_ACTION_ORDER:
        return _DEFAULT_CUSTOM_ACTION
    return text


def _save_custom_action(action_id, settings=None):
    if action_id not in _CUSTOM_ACTION_ORDER:
        return
    settings = settings if settings is not None else QSettings()
    settings.setValue(_CUSTOM_ACTION_SETTINGS_KEY, action_id)


def _resolve_custom_action(
    action_id, *, controller, view_all_handler, y_autofit_handler, copy_image_handler
):
    """Return a 0-arg callable for ``action_id`` in this context, or None if unavailable."""
    if action_id == "copy_image":
        return copy_image_handler if callable(copy_image_handler) else None
    if action_id == "view_all":
        return view_all_handler if callable(view_all_handler) else None
    if action_id == "y_fit":
        return y_autofit_handler if callable(y_autofit_handler) else None
    method = _CUSTOM_ACTION_CONTROLLER_METHODS.get(action_id)
    if method is not None and controller is not None:
        fn = getattr(controller, method, None)
        return fn if callable(fn) else None
    return None

_MOUSE_MODE_TOGGLE_QSS = (
    "QWidget#pgMouseModeToggleRow {"
    " background: transparent;"
    "}"
    "QToolButton {"
    " border: 1px solid transparent;"
    " border-radius: 5px;"
    " background: transparent;"
    " padding: 2px;"
    " margin: 0px;"
    "}"
    "QToolButton:hover {"
    " background: #f1f5f9;"
    "}"
    "QToolButton:checked {"
    " background: #e8f0ff;"
    " border: 1px solid #2563eb;"
    "}"
)

_INLINE_PANEL_QSS = (
    "QWidget#pgContextInlinePanel {"
    " background: transparent;"
    "}"
    "QLabel#pgContextInlineLabel {"
    " color: #94a3b8;"
    " font-size: 12px;"
    " font-weight: 600;"
    " background: transparent;"
    "}"
    "QPushButton, QLineEdit, QToolButton {"
    " border: 1px solid #d6e0ec;"
    " border-radius: 8px;"
    " background: #ffffff;"
    " color: #334155;"
    " padding: 0px 4px;"
    "}"
    "QPushButton:hover, QToolButton:hover {"
    " background: #f8fafc;"
    "}"
    "QToolButton:checked {"
    " background: #e8f0ff;"
    " border-color: #2563eb;"
    " color: #2563eb;"
    "}"
    "QToolButton:disabled {"
    " color: #94a3b8;"
    " background: #f1f5f9;"
    " border-color: #d6e0ec;"
    "}"
    "QLineEdit {"
    " color: #111827;"
    " selection-background-color: #bfdbfe;"
    "}"
)


def _sync_mouse_mode_toggle_buttons(buttons, current):
    """Reflect the toolbar mode on the compact menu row."""
    if len(buttons) < 2:
        return
    group = buttons[0].group()
    previous_exclusive = None
    if group is not None:
        previous_exclusive = group.exclusive()
        group.setExclusive(False)
    buttons[0].setChecked(current == _PG_MOUSE_MODE_ZOOM)
    buttons[1].setChecked(current == _PG_MOUSE_MODE_PAN)
    if group is not None:
        group.setExclusive(previous_exclusive)


def _clean_menu_text(text):
    return (text or "").replace("&", "").strip()


def _apply_context_widget_i18n(widget):
    """Localize the X/Y axis form AND hide the out-of-scope rows."""
    if widget is None:
        return
    for child in widget.findChildren(QWidget):
        obj_name = child.objectName()
        if obj_name in _PG_AXIS_FORM_HIDE_OBJECTS or isinstance(child, QComboBox):
            try:
                child.setVisible(False)
            except Exception:
                pass
            continue
        if isinstance(child, QGroupBox):
            title = _clean_menu_text(child.title())
            translated = _PG_CONTEXT_ACTIONS.get(title) or _PG_CONTEXT_WIDGETS.get(title)
            if translated is not None:
                child.setTitle(translated[0])
                child.setToolTip("")
            continue
        if not isinstance(child, (QCheckBox, QRadioButton, QLabel)):
            continue
        text = _clean_menu_text(child.text())
        if text in _PG_AXIS_FORM_HIDE_TEXTS:
            try:
                child.setVisible(False)
            except Exception:
                pass
            continue
        translated = _PG_CONTEXT_WIDGETS.get(text)
        if translated is None:
            continue
        child.setText(translated[0])
        child.setToolTip("")
    min_text = widget.findChild(QLineEdit, "minText")
    max_text = widget.findChild(QLineEdit, "maxText")
    if min_text is not None and max_text is not None:
        QWidget.setTabOrder(min_text, max_text)


def _style_pg_context_menu(menu):
    if menu is None:
        return
    try:
        menu.setObjectName("pgContextMenu")
        menu.setToolTipsVisible(False)
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
    except Exception:
        pass


def _localize_pg_context_actions(actions):
    """Localize a flat action list."""
    for action in list(actions or []):
        if action is None or action.isSeparator():
            continue
        text = _clean_menu_text(action.text())
        translated = _PG_CONTEXT_ACTIONS.get(text)
        if translated is not None:
            action.setText(translated[0])
        action.setToolTip("")
        sub = action.menu()
        if sub is not None:
            if translated is not None:
                sub.setTitle(translated[0])
            _localize_pg_context_menu(sub)
        try:
            _apply_context_widget_i18n(action.defaultWidget())
        except Exception:
            pass


def _localize_pg_context_menu(menu):
    """Localize a menu in place WITHOUT trimming."""
    if menu is None:
        return
    _style_pg_context_menu(menu)
    title = _clean_menu_text(menu.title())
    translated = _PG_CONTEXT_ACTIONS.get(title)
    if translated is not None:
        menu.setTitle(translated[0])
        try:
            menu.menuAction().setText(translated[0])
        except Exception:
            pass
    try:
        menu.menuAction().setToolTip("")
    except Exception:
        pass
    _localize_pg_context_actions(menu.actions())


def _find_top_level_action(menu, *texts):
    """Return the first top-level QAction whose cleaned text matches."""
    wanted = set(texts)
    for action in menu.actions():
        if _clean_menu_text(action.text()) in wanted:
            return action
    return None


def _route_view_all_action(menu, handler):
    """Route the native View All action through the canvas Home reset."""
    action = _find_top_level_action(menu, "查看全部", "View All")
    if action is None or handler is None:
        return
    try:
        action.triggered.disconnect()
    except (TypeError, RuntimeError):
        pass

    def _trigger(_checked=False):
        try:
            handler()
        except Exception:
            pass

    action.triggered.connect(_trigger)


def _format_range_value(value):
    """Format ViewBox range values for compact inline editing."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    if abs(value) >= 1000 or (0 < abs(value) < 0.01):
        return f"{value:.3g}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _view_range(view_box, axis):
    ranges = view_box.viewRange()
    idx = 1 if axis == "y" else 0
    lo, hi = ranges[idx]
    return float(lo), float(hi)


def _axis_grid_enabled(plot_item, side):
    try:
        axis = plot_item.getAxis(side)
        return bool(getattr(axis, "grid", False))
    except Exception:
        return False


class _PgContextInlinePanel(QWidget):
    """First-level context-menu controls for pyqtgraph plot navigation."""

    def __init__(
        self,
        menu,
        plot_item,
        controller,
        *,
        view_all_handler=None,
        y_autofit_handler=None,
        allow_y_grid=True,
        view_box=None,
    ):
        super().__init__(menu)
        self._menu = menu
        self._plot_item = plot_item
        self._view_box = (
            view_box if view_box is not None else getattr(plot_item, "vb", None)
        )
        self._controller = controller
        self._view_all_handler = view_all_handler
        self._y_autofit_handler = y_autofit_handler
        self._allow_y_grid = bool(allow_y_grid)
        self._grid_state = {
            "x": _axis_grid_enabled(plot_item, "bottom") if plot_item else False,
            "y": (
                _axis_grid_enabled(plot_item, "left")
                or _axis_grid_enabled(plot_item, "right")
            ) if plot_item else False,
        }
        if not self._allow_y_grid:
            self._grid_state["y"] = False

        self.setObjectName("pgContextInlinePanel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet(_INLINE_PANEL_QSS)

        layout = QGridLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(6)
        layout.setColumnMinimumWidth(0, _INLINE_TRACK_WIDTH)
        layout.setColumnMinimumWidth(1, _INLINE_MIDDLE_WIDTH)
        layout.setColumnMinimumWidth(2, _INLINE_TRACK_WIDTH)
        layout.setColumnMinimumWidth(3, 8)
        layout.setColumnMinimumWidth(4, _INLINE_LABEL_WIDTH)
        for col in range(5):
            layout.setColumnStretch(col, 0)

        self._build_mouse_row(layout, 0)
        self._build_view_row(layout, 1)
        self._build_range_row(layout, 2, "x")
        self._build_range_row(layout, 3, "y")
        self._build_grid_row(layout, 4)

    def _add_label(self, layout, row, text):
        label = QLabel(text, self)
        label.setObjectName("pgContextInlineLabel")
        label.setFixedWidth(_INLINE_LABEL_WIDTH)
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(label, row, 4)
        return label

    def _make_text_button(self, text, object_name):
        button = QPushButton(text, self)
        button.setObjectName(object_name)
        button.setFixedSize(_INLINE_TRACK_WIDTH, _INLINE_CONTROL_HEIGHT)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip("")
        return button

    def _make_tool_button(self, mode):
        label, _tip = _PG_MOUSE_MODE_LABELS[mode]
        button = QToolButton(self)
        button.setObjectName(
            "pgContextZoomButton"
            if mode == _PG_MOUSE_MODE_ZOOM
            else "pgContextPanButton"
        )
        button.setIcon(qta.icon(
            _PG_MOUSE_MODE_ICONS[mode],
            color=_PG_ICON_COLOR,
            color_on=_PG_ICON_ACTIVE,
        ))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setFixedSize(32, _INLINE_CONTROL_HEIGHT)
        button.setToolTip(label)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _build_mouse_row(self, layout, row):
        zoom_button = self._make_tool_button(_PG_MOUSE_MODE_ZOOM)
        pan_button = self._make_tool_button(_PG_MOUSE_MODE_PAN)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(zoom_button)
        group.addButton(pan_button)

        try:
            current = self._controller.current_mouse_mode()
        except Exception:
            current = None
        _sync_mouse_mode_toggle_buttons([zoom_button, pan_button], current)

        zoom_button.clicked.connect(
            lambda _checked=False: self._select_mouse_mode(_PG_MOUSE_MODE_ZOOM)
        )
        pan_button.clicked.connect(
            lambda _checked=False: self._select_mouse_mode(_PG_MOUSE_MODE_PAN)
        )
        if self._controller is None:
            zoom_button.setEnabled(False)
            pan_button.setEnabled(False)

        layout.addWidget(zoom_button, row, 0, alignment=Qt.AlignCenter)
        layout.addWidget(pan_button, row, 2, alignment=Qt.AlignCenter)
        self._add_label(layout, row, "鼠标")

    def _select_mouse_mode(self, mode):
        if self._controller is None:
            return
        try:
            setter = getattr(self._controller, "set_mouse_mode_broadcast", None)
            if callable(setter):
                setter(mode)
            elif mode == _PG_MOUSE_MODE_ZOOM:
                self._controller.set_zoom_mode()
            else:
                self._controller.set_pan_mode()
        except Exception:
            pass
        self._close_menu()

    def _build_view_row(self, layout, row):
        y_fit = self._make_text_button("Y适应", "pgContextYFitButton")
        view_all = self._make_text_button("全图", "pgContextViewAllButton")
        y_fit.setEnabled(callable(self._y_autofit_handler))
        view_all.setEnabled(callable(self._view_all_handler))
        y_fit.clicked.connect(lambda _checked=False: self._run_handler(
            self._y_autofit_handler,
            close=True,
        ))
        view_all.clicked.connect(lambda _checked=False: self._run_handler(
            self._view_all_handler,
            close=True,
        ))
        layout.addWidget(y_fit, row, 0)
        layout.addWidget(view_all, row, 2)
        self._add_label(layout, row, "查看")

    def _make_range_edit(self, object_name):
        edit = QLineEdit(self)
        edit.setObjectName(object_name)
        edit.setAlignment(Qt.AlignCenter)
        edit.setFixedSize(_INLINE_TRACK_WIDTH, _INLINE_CONTROL_HEIGHT)
        edit.setToolTip("")
        return edit

    def _build_range_row(self, layout, row, axis):
        label = "X范围" if axis == "x" else "Y范围"
        prefix = "X" if axis == "x" else "Y"
        min_edit = self._make_range_edit(f"pgContext{prefix}MinEdit")
        max_edit = self._make_range_edit(f"pgContext{prefix}MaxEdit")
        dash = QLabel("—", self)
        dash.setAlignment(Qt.AlignCenter)
        dash.setFixedWidth(_INLINE_MIDDLE_WIDTH)
        dash.setStyleSheet("background: transparent; color: #94a3b8;")

        self._refresh_range_edits(axis, min_edit, max_edit)
        min_edit.editingFinished.connect(
            lambda axis=axis, lo=min_edit, hi=max_edit: self._apply_range(axis, lo, hi)
        )
        max_edit.editingFinished.connect(
            lambda axis=axis, lo=min_edit, hi=max_edit: self._apply_range(axis, lo, hi)
        )
        min_edit.returnPressed.connect(
            lambda axis=axis, lo=min_edit, hi=max_edit: self._apply_range(axis, lo, hi)
        )
        max_edit.returnPressed.connect(
            lambda axis=axis, lo=min_edit, hi=max_edit: self._apply_range(axis, lo, hi)
        )

        layout.addWidget(min_edit, row, 0)
        layout.addWidget(dash, row, 1)
        layout.addWidget(max_edit, row, 2)
        self._add_label(layout, row, label)

    def _refresh_range_edits(self, axis, min_edit, max_edit):
        if self._view_box is None:
            min_edit.setText("0")
            max_edit.setText("0")
            return
        try:
            lo, hi = _view_range(self._view_box, axis)
        except Exception:
            lo, hi = 0.0, 0.0
        min_edit.setText(_format_range_value(lo))
        max_edit.setText(_format_range_value(hi))

    def _apply_range(self, axis, min_edit, max_edit):
        if self._view_box is None:
            return
        try:
            lo = float(min_edit.text())
            hi = float(max_edit.text())
        except (TypeError, ValueError):
            self._refresh_range_edits(axis, min_edit, max_edit)
            return
        if hi <= lo:
            self._refresh_range_edits(axis, min_edit, max_edit)
            return
        try:
            if axis == "x":
                self._view_box.setXRange(lo, hi, padding=0)
            else:
                self._view_box.setYRange(lo, hi, padding=0)
        except Exception:
            pass
        self._refresh_range_edits(axis, min_edit, max_edit)

    def _make_grid_chip(self, axis):
        chip = QToolButton(self)
        chip.setObjectName(
            "pgContextGridXChip" if axis == "x" else "pgContextGridYChip"
        )
        chip.setText(axis.upper())
        chip.setToolButtonStyle(Qt.ToolButtonTextOnly)
        chip.setCheckable(True)
        chip.setFixedSize(48, _INLINE_CONTROL_HEIGHT)
        chip.setToolTip("")
        chip.setCursor(Qt.PointingHandCursor)
        chip.setChecked(bool(self._grid_state[axis]))
        if axis == "y" and not self._allow_y_grid:
            chip.setChecked(False)
            chip.setEnabled(False)
        return chip

    def _build_grid_row(self, layout, row):
        x_chip = self._make_grid_chip("x")
        y_chip = self._make_grid_chip("y")
        x_chip.toggled.connect(lambda checked: self._set_grid("x", checked))
        y_chip.toggled.connect(lambda checked: self._set_grid("y", checked))
        layout.addWidget(x_chip, row, 0, alignment=Qt.AlignCenter)
        layout.addWidget(y_chip, row, 2, alignment=Qt.AlignCenter)
        self._add_label(layout, row, "网格")

    def _set_grid(self, axis, checked):
        if axis == "y" and not self._allow_y_grid:
            self._grid_state["y"] = False
            return
        self._grid_state[axis] = bool(checked)
        if self._plot_item is None:
            return
        try:
            show_major_grid_left_bottom_only(
                self._plot_item,
                x=self._grid_state["x"],
                y=self._grid_state["y"] if self._allow_y_grid else False,
                alpha=0.28,
            )
        except Exception:
            pass

    def _run_handler(self, handler, *, close=False):
        if callable(handler):
            try:
                handler()
            except Exception:
                pass
        if close:
            self._close_menu()

    def _close_menu(self):
        try:
            self._menu.close()
        except Exception:
            pass


_CUSTOM_ACTION_QSS = (
    "QWidget#pgContextCustomActionButton { background: transparent; }"
    "QToolButton#pgContextCustomActionMain {"
    " border: 1px solid #d6e0ec; border-radius: 7px;"
    " background: #ffffff; padding: 0px; }"
    "QToolButton#pgContextCustomActionMain:hover {"
    " border-color: #0b7af3; background: #f3f7ff; }"
    "QToolButton#pgContextCustomActionMain:disabled {"
    " border-color: #e5eaf2; background: #f8fafc; }"
    "QToolButton#pgContextCustomActionCaret {"
    " border: none; background: transparent; color: #64748b; padding: 0px; }"
)


class _PgCustomActionButton(QWidget):
    """Third mouse-row slot: runs one bound execute-type action; ``▾`` rebinds."""

    def __init__(
        self, parent, *, menu, controller, view_all_handler,
        y_autofit_handler, copy_image_handler, settings=None,
    ):
        super().__init__(parent)
        self.setObjectName("pgContextCustomActionButton")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet(_CUSTOM_ACTION_QSS)
        self._menu = menu
        self._controller = controller
        self._view_all_handler = view_all_handler
        self._y_autofit_handler = y_autofit_handler
        self._copy_image_handler = copy_image_handler
        self._settings = settings
        self._action_id = _load_custom_action(settings)
        self._list_host = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._main = QToolButton(self)
        self._main.setObjectName("pgContextCustomActionMain")
        self._main.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._main.setIconSize(QSize(18, 18))
        self._main.setFixedSize(32, _INLINE_CONTROL_HEIGHT)
        self._main.setCursor(Qt.PointingHandCursor)
        self._main.clicked.connect(self._on_main_clicked)
        self._caret = QToolButton(self)
        self._caret.setObjectName("pgContextCustomActionCaret")
        self._caret.setText("▾")
        self._caret.setFixedSize(14, _INLINE_CONTROL_HEIGHT)
        self._caret.setCursor(Qt.PointingHandCursor)
        self._caret.setToolTip("更换动作")
        self._caret.clicked.connect(self._toggle_action_list)
        lay.addWidget(self._main)
        lay.addWidget(self._caret)
        self._refresh_main()

    def current_action_id(self):
        return self._action_id

    def _resolve(self, action_id):
        return _resolve_custom_action(
            action_id, controller=self._controller,
            view_all_handler=self._view_all_handler,
            y_autofit_handler=self._y_autofit_handler,
            copy_image_handler=self._copy_image_handler,
        )

    def _refresh_main(self):
        icon_name = _CUSTOM_ACTION_ICONS.get(self._action_id)
        label = _CUSTOM_ACTION_LABELS.get(self._action_id, "")
        handler = self._resolve(self._action_id)
        if icon_name:
            self._main.setIcon(qta.icon(icon_name, color=_PG_ICON_COLOR))
            self._main.setText("")
        else:
            self._main.setText("+")
        self._main.setToolTip(label)
        self._main.setEnabled(handler is not None)

    def _on_main_clicked(self, _checked=False):
        handler = self._resolve(self._action_id)
        if callable(handler):
            try:
                handler()
            except Exception:
                pass
        try:
            self._menu.close()
        except Exception:
            pass

    def _toggle_action_list(self, _checked=False):
        if self._list_host is not None:
            self._collapse_action_list()
            return
        self._expand_action_list()

    def _expand_action_list(self):
        host = QWidget(self.parent() or self)
        host.setObjectName("pgContextActionList")
        host.setAttribute(Qt.WA_TranslucentBackground, True)
        host.setAutoFillBackground(False)
        host.setStyleSheet(
            "QWidget#pgContextActionList { background: transparent; }"
            "QToolButton { border: 1px solid transparent; border-radius: 6px;"
            " background: #ffffff; color: #334155; text-align: left;"
            " padding: 4px 8px; font-size: 13px; }"
            "QToolButton:hover { background: #f3f7ff; }"
            "QToolButton:checked { color: #2563eb; }"
            "QToolButton:disabled { color: #b8c2d0; }"
        )
        col = QVBoxLayout(host)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(2)
        for action_id in _CUSTOM_ACTION_ORDER:
            item = QToolButton(host)
            item.setObjectName(f"pgContextActionItem_{action_id}")
            item.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            icon_name = _CUSTOM_ACTION_ICONS.get(action_id)
            if icon_name:
                item.setIcon(qta.icon(icon_name, color=_PG_ICON_COLOR))
                item.setIconSize(QSize(16, 16))
            item.setText(_CUSTOM_ACTION_LABELS.get(action_id, action_id))
            item.setCheckable(True)
            item.setChecked(action_id == self._action_id)
            item.setEnabled(self._resolve(action_id) is not None)
            item.setCursor(Qt.PointingHandCursor)
            item.clicked.connect(
                lambda _c=False, aid=action_id: self._rebind(aid)
            )
            col.addWidget(item)
        self._list_host = host
        # Inline placement inside the panel's grid layout (no nested QMenu / popup).
        self._insert_list_into_panel(host)
        host.show()

    def _insert_list_into_panel(self, host):
        panel = self.parent()
        layout = panel.layout() if panel is not None else None
        if layout is None:
            host.setParent(self)
            return
        row = layout.rowCount()
        layout.addWidget(host, row, 0, 1, 3)

    def _collapse_action_list(self):
        if self._list_host is not None:
            self._list_host.setParent(None)
            self._list_host.deleteLater()
            self._list_host = None

    def _rebind(self, action_id):
        self._action_id = action_id
        _save_custom_action(action_id, self._settings)
        self._refresh_main()
        self._collapse_action_list()


def _make_inline_context_panel_action(
    menu,
    plot_item,
    controller,
    *,
    view_all_handler=None,
    y_autofit_handler=None,
    allow_y_grid=True,
    view_box=None,
):
    panel = _PgContextInlinePanel(
        menu,
        plot_item,
        controller,
        view_all_handler=view_all_handler,
        y_autofit_handler=y_autofit_handler,
        allow_y_grid=allow_y_grid,
        view_box=view_box,
    )
    action = QWidgetAction(menu)
    action.setDefaultWidget(panel)
    return action


def _build_grid_submenu(menu, plot_item, *, allow_y_grid=True):
    """Build a top-level grid submenu with X/Y grid toggles."""
    grid_menu = QMenu(menu)
    _style_pg_context_menu(grid_menu)
    grid_menu.setTitle("网格")

    def _axis_grid_enabled(side):
        try:
            axis = plot_item.getAxis(side)
            return bool(getattr(axis, "grid", False))
        except Exception:
            return False

    state = {
        "x": _axis_grid_enabled("bottom"),
        "y": _axis_grid_enabled("left") or _axis_grid_enabled("right"),
    }
    if not allow_y_grid:
        state["y"] = False

    act_x = QAction("显示 X 网格", grid_menu)
    act_y = QAction("显示 Y 网格", grid_menu)
    act_x.setCheckable(True)
    act_y.setCheckable(True)
    act_x.setChecked(state["x"])
    act_y.setChecked(state["y"])
    act_y.setEnabled(bool(allow_y_grid))
    for act in (act_x, act_y):
        act.setToolTip("")

    def _apply_grid():
        try:
            show_major_grid_left_bottom_only(
                plot_item,
                x=state["x"],
                y=state["y"] if allow_y_grid else False,
                alpha=0.28,
            )
        except Exception:
            pass

    def _on_x(checked):
        state["x"] = bool(checked)
        _apply_grid()

    def _on_y(checked):
        if not allow_y_grid:
            state["y"] = False
            return
        state["y"] = bool(checked)
        _apply_grid()

    act_x.toggled.connect(_on_x)
    act_y.toggled.connect(_on_y)
    grid_menu.addAction(act_x)
    grid_menu.addAction(act_y)
    return grid_menu


def _add_mouse_mode_toggle_row(menu, controller):
    """Insert the compact top shortcut row without exposing axis mouseCheck."""
    if controller is None:
        return None

    for action in menu.actions():
        if isinstance(action, QWidgetAction):
            widget = action.defaultWidget()
            if widget is not None and widget.objectName() == "pgMouseModeToggleRow":
                try:
                    current = controller.current_mouse_mode()
                    buttons = widget.findChildren(QToolButton)
                    _sync_mouse_mode_toggle_buttons(buttons, current)
                except Exception:
                    pass
                return action

    try:
        current = controller.current_mouse_mode()
    except Exception:
        current = None

    row = QWidget(menu)
    row.setObjectName("pgMouseModeToggleRow")
    row.setAttribute(Qt.WA_TranslucentBackground, True)
    row.setAutoFillBackground(False)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(10, 4, 10, 4)
    layout.setSpacing(6)

    def _make_button(mode):
        label, _tip = _PG_MOUSE_MODE_LABELS[mode]
        icon = qta.icon(
            _PG_MOUSE_MODE_ICONS[mode],
            color=_PG_ICON_COLOR,
            color_on=_PG_ICON_ACTIVE,
        )
        btn = QToolButton(row)
        btn.setIcon(icon)
        btn.setIconSize(QSize(18, 18))
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setCheckable(True)
        btn.setAutoRaise(True)
        btn.setFixedSize(30, 26)
        btn.setToolTip(label)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    btn_zoom = _make_button(_PG_MOUSE_MODE_ZOOM)
    btn_pan = _make_button(_PG_MOUSE_MODE_PAN)

    group = QButtonGroup(row)
    group.setExclusive(True)
    group.addButton(btn_zoom)
    group.addButton(btn_pan)

    _sync_mouse_mode_toggle_buttons([btn_zoom, btn_pan], current)
    row.setStyleSheet(_MOUSE_MODE_TOGGLE_QSS)

    def _select_zoom(_checked=False):
        try:
            setter = getattr(controller, "set_mouse_mode_broadcast", None)
            if callable(setter):
                setter(_PG_MOUSE_MODE_ZOOM)
            else:
                controller.set_zoom_mode()
        except Exception:
            pass
        try:
            menu.close()
        except Exception:
            pass

    def _select_pan(_checked=False):
        try:
            setter = getattr(controller, "set_mouse_mode_broadcast", None)
            if callable(setter):
                setter(_PG_MOUSE_MODE_PAN)
            else:
                controller.set_pan_mode()
        except Exception:
            pass
        try:
            menu.close()
        except Exception:
            pass

    btn_zoom.clicked.connect(_select_zoom)
    btn_pan.clicked.connect(_select_pan)

    layout.addWidget(btn_zoom)
    layout.addWidget(btn_pan)
    layout.addStretch(1)

    widget_action = QWidgetAction(menu)
    widget_action.setDefaultWidget(row)
    menu.addAction(widget_action)
    return widget_action


def _add_y_autofit_action(menu, handler):
    """Add a top-level Y-axis auto-fit action wired to ``handler``."""
    if handler is None:
        return None
    existing = _find_top_level_action(menu, "Y 轴自适应")
    if existing is not None:
        return existing
    action = QAction("Y 轴自适应", menu)
    action.setToolTip("")

    def _trigger(_checked=False):
        try:
            handler()
        except Exception:
            pass

    action.triggered.connect(_trigger)
    menu.addAction(action)
    return action


def _reorder_top_level_actions(menu, desired_texts, *, pinned_first=None):
    """Reorder menu top-level actions by cleaned text, preserving action objects."""
    all_actions = list(menu.actions())
    by_text = {}
    for act in all_actions:
        if act.isSeparator():
            continue
        by_text.setdefault(_clean_menu_text(act.text()), act)
    ordered = []
    seen = set()
    if pinned_first is not None and pinned_first in all_actions:
        ordered.append(pinned_first)
        seen.add(id(pinned_first))
    for text in desired_texts:
        act = by_text.get(text)
        if act is not None and id(act) not in seen:
            ordered.append(act)
            seen.add(id(act))
    for act in all_actions:
        if act.isSeparator() or id(act) in seen:
            continue
        ordered.append(act)
        seen.add(id(act))
    for act in all_actions:
        menu.removeAction(act)
    for act in ordered:
        menu.addAction(act)


def redesign_pg_context_menu(
    menu,
    plot_item,
    controller,
    *,
    view_all_handler=None,
    y_autofit_handler=None,
    allow_y_grid=True,
    keep_plot_options=False,
    view_box=None,
):
    """Reshape the assembled pyqtgraph context menu."""
    if menu is None:
        return
    _localize_pg_context_menu(menu)

    for action in list(menu.actions()):
        if action.isSeparator():
            menu.removeAction(action)
            continue
        text = _clean_menu_text(action.text())
        if keep_plot_options and text in ("Plot Options", "绘图选项"):
            continue
        menu.removeAction(action)

    inline_action = _make_inline_context_panel_action(
        menu,
        plot_item,
        controller,
        view_all_handler=view_all_handler,
        y_autofit_handler=y_autofit_handler,
        allow_y_grid=allow_y_grid,
        view_box=view_box,
    )
    actions = list(menu.actions())
    if actions:
        menu.insertAction(actions[0], inline_action)
    else:
        menu.addAction(inline_action)
    _strip_redundant_separators(menu)


def _strip_redundant_separators(menu):
    """Remove leading/trailing/double separators left by action removal."""
    actions = list(menu.actions())
    while actions and actions[0].isSeparator():
        menu.removeAction(actions[0])
        actions = list(menu.actions())
    while actions and actions[-1].isSeparator():
        menu.removeAction(actions[-1])
        actions = list(menu.actions())
    prev_sep = False
    for action in list(menu.actions()):
        if action.isSeparator():
            if prev_sep:
                menu.removeAction(action)
            prev_sep = True
        else:
            prev_sep = False


__all__ = [
    "_clean_menu_text",
    "_apply_context_widget_i18n",
    "_style_pg_context_menu",
    "_localize_pg_context_actions",
    "_localize_pg_context_menu",
    "_find_top_level_action",
    "_route_view_all_action",
    "_build_grid_submenu",
    "_add_mouse_mode_toggle_row",
    "_add_y_autofit_action",
    "_reorder_top_level_actions",
    "redesign_pg_context_menu",
    "_strip_redundant_separators",
]

"""Right-click context-menu helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import qtawesome as qta
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (
    QAction,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QRadioButton,
    QToolButton,
    QWidget,
    QWidgetAction,
)


_PG_CONTEXT_ACTIONS = {
    "ViewBox options": ("视图选项", "配置当前图表的视图范围、坐标轴和鼠标交互。"),
    "View All": ("查看全部", "回到完整数据范围，等同于顶部工具栏的重置视图。"),
    "X axis": ("X 轴范围", "设置横轴范围、自动缩放、鼠标交互。"),
    "Y axis": ("Y 轴范围", "设置纵轴范围、自动缩放、鼠标交互。"),
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
})

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
            plot_item.showGrid(
                x=state["x"],
                y=state["y"] if allow_y_grid else False,
                alpha=0.28,
            )
        except Exception:
            pass
        # pyqtgraph's showGrid -> updateGrid lights the grid on ALL FOUR
        # built-in axes. The canvases install boundary-suppressing
        # _BoundaryGridAxisItem only on left+bottom and deliberately keep
        # top+right grid OFF (plain AxisItems re-draw the boundary line and
        # double every grid line during zoom — heatmap_canvas.py:613-614,
        # line_canvas.py:145-146). This shared menu must preserve that
        # policy, so re-disable top+right after every showGrid toggle.
        for _side in ("top", "right"):
            try:
                _ax = plot_item.getAxis(_side)
            except Exception:
                _ax = None
            if _ax is None:
                continue
            try:
                _ax.setGrid(False)
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
    """Insert an inline icon-only box-zoom/pan toggle row."""
    if controller is None:
        return None

    for _act in menu.actions():
        if isinstance(_act, QWidgetAction):
            _w = _act.defaultWidget()
            if _w is not None and _w.objectName() == "pgMouseModeToggleRow":
                try:
                    _cur = controller.current_mouse_mode()
                    _zoom = _cur == _PG_MOUSE_MODE_ZOOM
                    _btns = _w.findChildren(QToolButton)
                    if len(_btns) >= 2:
                        _btns[0].setChecked(_zoom)
                        _btns[1].setChecked(not _zoom)
                except Exception:
                    pass
                return _act

    current = None
    try:
        current = controller.current_mouse_mode()
    except Exception:
        current = None
    is_zoom = current == _PG_MOUSE_MODE_ZOOM

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

    btn_zoom.setChecked(is_zoom)
    btn_pan.setChecked(not is_zoom)

    row.setStyleSheet(_MOUSE_MODE_TOGGLE_QSS)

    def _select_zoom(_checked=False):
        try:
            controller.set_zoom_mode()
        except Exception:
            pass
        try:
            menu.close()
        except Exception:
            pass

    def _select_pan(_checked=False):
        try:
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
):
    """Reshape the assembled pyqtgraph context menu."""
    if menu is None:
        return
    _localize_pg_context_menu(menu)
    _route_view_all_action(menu, view_all_handler)

    for action in list(menu.actions()):
        if action.isSeparator():
            continue
        text = _clean_menu_text(action.text())
        if keep_plot_options and text in ("Plot Options", "绘图选项"):
            continue
        if text in _PG_MENU_REMOVE_TEXTS:
            menu.removeAction(action)

    toggle_row = _add_mouse_mode_toggle_row(menu, controller)
    _add_y_autofit_action(menu, y_autofit_handler)

    if plot_item is not None and _find_top_level_action(menu, "网格") is None:
        grid_menu = _build_grid_submenu(
            menu,
            plot_item,
            allow_y_grid=allow_y_grid,
        )
        menu.addMenu(grid_menu)

    _reorder_top_level_actions(
        menu,
        ("Y 轴自适应", "查看全部", "X 轴范围", "Y 轴范围", "绘图选项", "网格"),
        pinned_first=toggle_row,
    )
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

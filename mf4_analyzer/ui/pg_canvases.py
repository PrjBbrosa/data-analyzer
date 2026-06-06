"""Pyqtgraph-backed TimeDomain canvas (Task 5 of the migration plan).

Implements design §5.1, §5.2, §5.4, §5.5 of
``docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md``.

``TimeDomainCanvasPG`` is the production time-domain renderer
(``ChartStack`` constructs it as ``canvas_time``). Its compatibility
surface mirrors ``mf4_analyzer.ui.canvases.TimeDomainCanvas`` so callers
see the same signals, attributes, and methods regardless of backend.

Architecture
------------
The canvas is a ``QWidget`` (not a direct ``pg.GraphicsLayoutWidget``
subclass) so it can carry pyqtSignals AND expose ``grab_pixmap()`` /
``grab()`` without battling Qt's metaclass rules. Internally it owns a
single ``pg.GraphicsLayoutWidget`` and one ``pg.PlotItem`` per subplot. The
production performance path follows the current visible-render pipeline:

    set_xlim → positions_envelope → visible PlotDataItem.setData

The older custom ``QPainterPath``/``QPixmap`` helpers remain only for
standalone geometry parity tests. They are not run from the pan refresh
hot path because no visible painter consumes their output.

Lessons honored
---------------
- ``pyqt-ui/2026-04-25-cache-invalidation-event-conditional``: the
  curve-layer cache compares a ``_last_range_key`` per channel against
  the incoming key; repeated flushes with the same xlim do NOT inflate
  the cache.
- ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``:
  ``_flush_pending_refresh`` drains AFTER the mutation. The
  ``sigXRangeChanged`` callback re-schedules the QTimer; ``set_xlim``
  → flush ordering is preserved by routing both through the same
  ``_refresh_visible_data`` method.
- ``signal-processing/2026-04-25-envelope-cache-bucket-width-quantization``:
  the range key is ``(channel, bucketed_lo, bucketed_hi,
  bucketed_pixel_width)`` where the quantum is ``span / pixel_width``
  (one pixel), matching ``TimeDomainCanvas._envelope_cached``.
- ``signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface``:
  ``positions_envelope`` is called from ``_refresh_visible_data`` on the
  hot path, NOT just a helper.
- ``pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt``: ``grab_pixmap``
  falls back to ``QWidget.grab()`` and finally to a degenerate-rect
  null-safe pixmap.
- Design Risk Register R7: ``os.environ.setdefault('PYQTGRAPH_QT_LIB',
  'PyQt5')`` runs BEFORE ``import pyqtgraph`` so the Qt-binding probe
  cannot drift to PySide.
"""
from __future__ import annotations

# R7: pin the Qt binding before pyqtgraph runs its own probe. Setdefault
# (not setitem) so the user can override this from the environment when
# debugging.
import os as _os
_os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

import logging
import json
import math
import time as _time
from collections import OrderedDict
from contextlib import contextmanager
from typing import Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import (
    QEasingCurve,
    QEvent,
    QTimer,
    QVariantAnimation,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QFont,
    QFontDatabase,
    QFontInfo,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QCheckBox,
    QComboBox,
    QGraphicsItem,
    QGroupBox,
    QLabel,
    QMenu,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.signal._envelope_cutils import positions_envelope
from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
    PgAxisHandle,
    _PgLineHandle,
)
from mf4_analyzer.ui.canvases import (
    _format_dual_html,
    _format_single_cursor_channel_html,
    _interp_cursor_value,
    _is_monotonic_array,
    _compact_axis_label,
    _middle_ellipsis,
    _split_prefixed_label,
    build_envelope,
)


_log = logging.getLogger(__name__)


def _view_state_channel_key(data_id, name):
    stable_data_id = None if data_id is None else str(data_id)
    return json.dumps(
        [stable_data_id, str(name)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


_TARGET_X_TICK_NICE_FACTORS = (1.0, 2.0, 2.5, 5.0, 10.0)
_TARGET_X_TICK_MIN_GAP_PX = 10.0
_TARGET_X_TICK_EDGE_PAD_PX = 2.0
_TARGET_X_TICK_MIN_COUNT = 3


# Idle-AA density budget (Fix C, 2026-05-31 overlay-aa-interaction-fixes;
# RECALIBRATED 2026-05-31 against the end-to-end grab()-repaint-frame
# harness — superseding the original 12000/16000, which never gated the
# measured-slow overlay).
#
# TWO BUDGETS, because subplot and overlay have fundamentally different
# per-frame economics (measured offscreen-raster grab() of the real
# GraphicsLayoutWidget; the AA-on minus AA-off DELTA isolates the actual
# antialiasing cost from the offscreen layout overhead, and is linear in
# the per-frame drawn-point SUM):
#
#   overlay sum  4000 → AA delta +10.2 ms   (≈ the ~10 ms target)
#   overlay sum  6000 → AA delta +16.6 ms   (2 curves, still affordable)
#   overlay sum  9000 → AA delta +31.3 ms   (3 curves, too slow → gate OFF)
#   overlay sum 12000 → AA delta +48.2 ms
#   overlay sum 15000 → AA delta +69.0 ms   (5 curves, the reported-slow case)
#
# OVERLAY metric = SUM of drawn points across ALL curves: overlay's aux
# ViewBoxes fully overlap at one full-plot rect, so a single draw_idle /
# _glw.update re-rasterizes every overlaid curve as ONE region. (Per-VB
# grouping under-counted overlay because each overlay curve lives on its
# OWN aux ViewBox — distinct objects, overlapping geometry — so the MAX
# saw only one curve. See the DeviceCoordinateCache lesson.) The overlay
# budget is tight so dense overlays (≥3 curves ≈ sum ≥ 9000, > ~30 ms)
# fall to AA-off; a light 2-curve overlay (sum ≤ 6000) still gets AA.
_AA_OVERLAY_SEGMENT_ON = 5000
_AA_OVERLAY_SEGMENT_OFF = 7000
_OVERLAY_GRID_ALPHA = 0.28        # 与 X 轴格线保持一致的透明度
#
# SUBPLOT/SINGLE metric = MAX over rows of that row's drawn points: the
# rows are disjoint device rectangles, AND subplot curves carry a
# DeviceCoordinateCache (Fix D, subplot-only) so an AA-on cached frame is
# ~0.3–0.9 ms at ANY width — measured 5×6000 subplot AA-on+cache = 0.86 ms
# vs 25.3 ms uncached. The subplot budget is therefore GENEROUS so a single
# maximized / 4K curve always qualifies: a 4K-wide single curve emits a
# ~7700-pt envelope (positions_envelope ≈ 2× plot-area pixel width), so OFF
# must sit well above that or issue 1 (AA off after maximize) regresses.
_AA_SUBPLOT_SEGMENT_ON = 10000
_AA_SUBPLOT_SEGMENT_OFF = 12000
#
# Back-compat aliases (legacy single-budget names; the instance still
# exposes _AA_SEGMENT_ON/_OFF, defaulted to the subplot pair, so existing
# tests/tools that poke the old attribute names keep working).
_AA_SEGMENT_ON = _AA_SUBPLOT_SEGMENT_ON
_AA_SEGMENT_OFF = _AA_SUBPLOT_SEGMENT_OFF


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


# ---------------------------------------------------------------------------
# Right-click context-menu redesign (design §A–§D,
# docs/superpowers/specs/2026-05-30-timedomain-context-menu-redesign-design.md,
# 方案 A · 常用优先).
#
# We KEEP pyqtgraph's native QMenu and reshape it after it is assembled:
#   - localize the surviving items (reuse the i18n dicts above),
#   - TRIM every advanced/duplicate/export entry,
#   - PROMOTE a top-level 网格 ▸ submenu (X/Y grid toggles),
#   - RENAME 鼠标模式 to toolbar vocabulary (平移 / 框选) and route it
#     through the SAME mouse-mode controller the top toolbar uses,
#   - turn tooltips OFF so floating help no longer covers the 二级表单.
#
# Final top-level menu (in order):
#   查看全部 · X 轴范围 ▸ · Y 轴范围 ▸ · 鼠标操作 ▸ · 网格 ▸
# ---------------------------------------------------------------------------

# Native pyqtgraph action texts (post-i18n) that must be REMOVED entirely from
# the assembled menu. Matched on the cleaned, possibly-translated label.
_PG_MENU_REMOVE_TEXTS = frozenset({
    "Plot Options", "绘图选项",
    "Export...", "导出...", "导出…",
})

_PG_CHART_FONT_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "Segoe UI",
    "PingFang SC",
    "Noto Sans CJK SC",
)
_PG_CHART_FONT_CACHE = {}
_OVERLAY_AXIS_LABEL_MIN_CHARS = 12
_OVERLAY_AXIS_LABEL_FALLBACK_CHARS = 22
_OVERLAY_AXIS_LABEL_VERTICAL_PADDING_PX = 32.0


def _pg_chart_font(point_size=9):
    """Return the explicit font used by pyqtgraph axis/scene text.

    pyqtgraph text lives in QGraphicsItems, so it does not reliably inherit
    QWidget QSS font-family rules. Prefer common UI Chinese fonts, then fall
    back to the QApplication font.
    """
    cache_key = int(point_size)
    cached = _PG_CHART_FONT_CACHE.get(cache_key)
    if cached is not None:
        return QFont(cached)
    try:
        families = set(QFontDatabase().families())
    except Exception:
        families = set()
    for family in _PG_CHART_FONT_FAMILIES:
        font = QFont(family, point_size)
        if family in families:
            _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
            return font
        if families:
            continue
        try:
            info = QFontInfo(font)
            resolved = info.family()
            if info.exactMatch() or resolved in _PG_CHART_FONT_FAMILIES:
                _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
                return font
        except Exception:
            _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
            return font
    app = QApplication.instance()
    font = QFont(app.font() if app is not None else QFont())
    font.setPointSize(point_size)
    _PG_CHART_FONT_CACHE[cache_key] = QFont(font)
    return font


def _apply_pg_axis_font(axis, point_size=9):
    if axis is None:
        return
    font = _pg_chart_font(point_size)
    try:
        axis.setStyle(tickFont=font)
    except Exception:
        pass
    label = getattr(axis, "label", None)
    if label is not None:
        try:
            label.setFont(font)
        except Exception:
            pass


def _apply_pg_text_item_font(item, point_size=9):
    if item is None:
        return
    font = _pg_chart_font(point_size)
    target = getattr(item, "textItem", item)
    try:
        target.setFont(font)
    except Exception:
        pass

# Native axis-form child object names to HIDE. Link Axis / Invert and the
# low-frequency auto-pan / visible-only toggles are out of scope per design A;
# the whole 自动 row (auto radio + 100% percentage spin) is dropped per user
# request — it duplicated 查看全部 / Home and only ate menu space.
_PG_AXIS_FORM_HIDE_OBJECTS = frozenset({
    "label",            # "Link Axis:" caption
    "linkCombo",
    "invertCheck",
    "autoPanCheck",
    "visibleOnlyCheck",
    "autoRadio",        # "自动" radio
    "autoPercentSpin",  # the "100%" auto-range percentage box
})

# Mouse-mode submenu vocabulary (toolbar words, NOT 三键/单键 黑话). The two
# entries map to the toolbar's pan / zoom (box-select) modes.
_PG_MOUSE_MODE_PAN = "pan"
_PG_MOUSE_MODE_ZOOM = "zoom"
_PG_MOUSE_MODE_LABELS = {
    _PG_MOUSE_MODE_PAN: ("平移", "左键拖动平移视图（与顶部工具栏的平移一致）。"),
    _PG_MOUSE_MODE_ZOOM: ("框选", "左键拖出矩形框选放大（与顶部工具栏的框选缩放一致）。"),
}

# ---------------------------------------------------------------------------
# Hi-DPI copy/save render (spec §E).
#
# The toolbar 复制为图片 / 保存图片 buttons render the scene at a HIGHER
# scale so the bitmap is DPI-independent and crisp (matplotlib was sharp
# because it rendered at figure DPI, not screen pixels). To keep export
# fast and not slow normal use, the magnification is CAPPED:
#
#   effective_scale = clamp(requested, 1.0, _HIDPI_MAX_WIDTH / base_width)
#
# i.e. we never downscale (floor 1×) and we never let the output width
# exceed _HIDPI_MAX_WIDTH px. For a typical ~1200px workspace a 2× request
# yields ~2400px; a very wide canvas is throttled so width tops out near
# 2560px. One consistent rule, applied in both copy and save paths.
# ---------------------------------------------------------------------------
_HIDPI_COPY_SCALE = 2.0
_HIDPI_MAX_WIDTH = 2560


def _capped_hidpi_scale(base_width, requested=_HIDPI_COPY_SCALE):
    """Return the effective magnification for a hi-DPI render.

    Clamps ``requested`` to ``[1.0, _HIDPI_MAX_WIDTH / base_width]`` so the
    result never downscales below 1× and the rendered width never exceeds
    ``_HIDPI_MAX_WIDTH``. A non-positive ``base_width`` (degenerate widget)
    falls back to 1× rather than dividing by zero.
    """
    try:
        bw = float(base_width)
    except (TypeError, ValueError):
        return 1.0
    if bw <= 0:
        return 1.0
    eff = max(1.0, float(requested))
    cap = _HIDPI_MAX_WIDTH / bw
    if cap < 1.0:
        # Canvas is already wider than the ceiling — do not magnify (1×),
        # but never downscale the source.
        return 1.0
    return min(eff, cap)


def _clean_menu_text(text):
    return (text or "").replace("&", "").strip()


def _apply_context_widget_i18n(widget):
    """Localize the X/Y axis form AND hide the out-of-scope rows.

    Reuses the surviving translations (鼠标交互 / 自动 / 手动) and drops the
    Link Axis / Invert / Auto Pan / Visible Only widgets per design A. The
    widgets are hidden (not deleted) so pyqtgraph's own updateState bindings
    that still reference them never AttributeError.
    """
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
        # Design B: no floating tooltips on the surviving form controls.
        child.setToolTip("")


def _style_pg_context_menu(menu):
    if menu is None:
        return
    try:
        menu.setObjectName("pgContextMenu")
        # Design B: tooltips OFF so the floating help no longer covers the
        # second-level axis form. This is also the occlusion bug fix.
        menu.setToolTipsVisible(False)
        # The QSS border-radius renders the menu BODY with transparent corners,
        # but macOS still paints a square native drop-shadow around the popup's
        # bounding rect — the residual right angles. Disable the native shadow
        # + frame so only the rounded surface shows. Keep the existing flags
        # (incl. Qt.Popup, so dismiss/positioning behaviour is unchanged) and
        # re-assert translucency AFTER, since changing window flags can recreate
        # the platform window and drop the attribute.
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
    except Exception:
        pass


def _localize_pg_context_actions(actions):
    """Localize a flat action list. Used for the scene contextMenu (before
    trimming) and recursively for surviving submenus."""
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
    """Localize a menu in place WITHOUT trimming. Kept for the X/Y axis
    submenus (whose forms still need translating) and the initial pass over
    freshly-built ViewBox menus before the assembled menu is reshaped."""
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
    """Return the first top-level QAction in ``menu`` whose cleaned text
    matches any of ``texts`` (translated or english), else None."""
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
    """Build (or rebuild) a top-level 网格 ▸ submenu with X/Y grid toggles.

    The native Grid control is buried inside Plot Options (which design A
    removes), so we promote it to its own first-class submenu. In overlay
    mode there is no canonical Y grid, so callers pass ``allow_y_grid=False``
    and the Y action is shown disabled while all toggles preserve y=False.
    """
    grid_menu = QMenu(menu)
    # Route through the shared styler so this hand-built submenu gets the
    # SAME objectName + toolTips-off + WA_TranslucentBackground as the
    # top-level menu — without translucency its rounded corners would leave
    # an opaque square frame.
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


def _reshape_mouse_mode_submenu(menu, controller):
    """Rename the native 鼠标模式 submenu to toolbar vocabulary and route it
    through the shared mouse-mode ``controller`` (design D, single source of
    truth). Returns the reshaped submenu action, or None if absent.

    The native submenu holds the pyqtgraph "3 button"/"1 button" actions in a
    QActionGroup bound to ``ViewBox.setMouseMode``. We REPLACE its contents
    with 平移 / 框选 actions whose checkmarks reflect ``controller.current``
    and whose triggers call ``controller.set_pan``/``set_zoom`` — the same
    entry the top toolbar uses, so menu and toolbar never disagree.
    """
    mouse_action = _find_top_level_action(menu, "鼠标模式", "Mouse Mode", "鼠标操作")
    if mouse_action is None:
        return None
    sub = mouse_action.menu()
    if sub is None:
        return None
    mouse_action.setText("鼠标操作")
    mouse_action.setToolTip("")
    sub.setTitle("鼠标操作")
    # Same shared styler as the grid submenu: objectName + toolTips-off +
    # WA_TranslucentBackground so the rounded corners don't leave a box.
    _style_pg_context_menu(sub)
    # Wipe the native 三键/单键 actions; rebuild with toolbar words.
    for old in list(sub.actions()):
        sub.removeAction(old)
    group = QActionGroup(sub)
    group.setExclusive(True)
    pan_label, pan_tip = _PG_MOUSE_MODE_LABELS[_PG_MOUSE_MODE_PAN]
    zoom_label, zoom_tip = _PG_MOUSE_MODE_LABELS[_PG_MOUSE_MODE_ZOOM]
    act_pan = QAction(pan_label, group)
    act_zoom = QAction(zoom_label, group)
    for act in (act_pan, act_zoom):
        act.setCheckable(True)
        act.setToolTip("")
    current = None
    if controller is not None:
        try:
            current = controller.current_mouse_mode()
        except Exception:
            current = None
    # Default the checkmark to pan when idle so the menu always shows a state.
    act_pan.setChecked(current != _PG_MOUSE_MODE_ZOOM)
    act_zoom.setChecked(current == _PG_MOUSE_MODE_ZOOM)

    def _select_pan(_checked=False):
        if controller is not None:
            try:
                controller.set_pan_mode()
            except Exception:
                pass

    def _select_zoom(_checked=False):
        if controller is not None:
            try:
                controller.set_zoom_mode()
            except Exception:
                pass

    act_pan.triggered.connect(_select_pan)
    act_zoom.triggered.connect(_select_zoom)
    sub.addAction(act_pan)
    sub.addAction(act_zoom)
    return mouse_action


def redesign_pg_context_menu(
    menu,
    plot_item,
    controller,
    *,
    view_all_handler=None,
    allow_y_grid=True,
):
    """Reshape the ASSEMBLED pyqtgraph context ``menu`` per design §A–§D.

    Called from ``_ModifierWheelViewBox.raiseContextMenu`` AFTER
    ``scene().addParentContextMenus`` has appended Plot Options + Export, so
    every removable entry is present and the trim happens once on the final
    surface (not a parallel rebuild).

    Order of operations:
      1. localize + tooltip-off the whole tree,
      2. remove Plot Options / Export,
      3. reshape 鼠标模式 → 鼠标操作 (toolbar-synced),
      4. promote a 网格 ▸ submenu,
      5. drop any orphaned trailing/leading separators.
    """
    if menu is None:
        return
    _localize_pg_context_menu(menu)
    _route_view_all_action(menu, view_all_handler)

    # (2) Remove advanced / export entries entirely.
    for action in list(menu.actions()):
        if action.isSeparator():
            continue
        if _clean_menu_text(action.text()) in _PG_MENU_REMOVE_TEXTS:
            menu.removeAction(action)

    # (3) Mouse-mode submenu → toolbar vocabulary + shared controller.
    _reshape_mouse_mode_submenu(menu, controller)

    # (4) Promote a top-level 网格 ▸ submenu (only once per menu instance).
    if plot_item is not None and _find_top_level_action(menu, "网格") is None:
        grid_menu = _build_grid_submenu(
            menu,
            plot_item,
            allow_y_grid=allow_y_grid,
        )
        menu.addMenu(grid_menu)

    # (5) Collapse separators that the removals left dangling.
    _strip_redundant_separators(menu)


def _strip_redundant_separators(menu):
    """Remove leading/trailing/double separators left by action removal."""
    actions = list(menu.actions())
    # Drop leading separators.
    while actions and actions[0].isSeparator():
        menu.removeAction(actions[0])
        actions = list(menu.actions())
    # Drop trailing separators.
    while actions and actions[-1].isSeparator():
        menu.removeAction(actions[-1])
        actions = list(menu.actions())
    # Collapse consecutive separators.
    prev_sep = False
    for action in list(menu.actions()):
        if action.isSeparator():
            if prev_sep:
                menu.removeAction(action)
            prev_sep = True
        else:
            prev_sep = False


# ---------------------------------------------------------------------------
# ViewBox subclass with modifier-aware wheel dispatch (T6 requirement 4).
#
# Pyqtgraph 0.14 ViewBox.wheelEvent ignores keyboard modifiers (verified by
# grepping .venv/lib/python3.12/site-packages/pyqtgraph/graphicsItems/
# ViewBox/ViewBox.py:1297-1316 — no `modifiers()` reference). We subclass
# so we can dispatch on Ctrl/Shift/no-modifier without monkey-patching the
# base class.
# ---------------------------------------------------------------------------


class _ModifierWheelViewBox(pg.ViewBox):
    """ViewBox that consults Qt keyboard modifiers on wheel events.

    Behavior matches canvases.py:_on_scroll exactly:

    - Ctrl + wheel  → zoom X (preserve Y)
    - Shift + wheel → zoom Y (preserve X)
    - plain wheel   → pan Y  (preserve X span)
    """

    def __init__(self, *args, owner_canvas=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Weak-ref-style backref to the canvas; the canvas does NOT store
        # the ViewBox so this stays well-defined.
        self._owner_canvas = owner_canvas
        _localize_pg_context_menu(getattr(self, "menu", None))

    def raiseContextMenu(self, ev):
        menu = self.getMenu(ev)
        if menu is None:
            return
        try:
            self.scene().addParentContextMenus(self, menu, ev)
        except Exception:
            pass
        # Reshape the ASSEMBLED menu (after Plot Options + Export were
        # appended) per design A–D. The owner canvas resolves the PlotItem +
        # shared mouse-mode controller; falls back to a bare localize if the
        # canvas backref is gone.
        owner = self._owner_canvas
        if owner is not None and hasattr(owner, "context_menu_requested"):
            owner.context_menu_requested.emit()
        if owner is not None and hasattr(owner, "_redesign_context_menu_for_viewbox"):
            try:
                owner._redesign_context_menu_for_viewbox(self, menu)
            except Exception:
                _localize_pg_context_menu(menu)
        else:
            _localize_pg_context_menu(menu)
        try:
            menu.popup(ev.screenPos().toPoint())
        except Exception:
            pass

    def wheelEvent(self, ev, axis=None):
        # Route through the canvas's central dispatch so the test surface
        # (_handle_wheel_dispatch) and the live UI share one code path.
        owner = self._owner_canvas
        if owner is None:
            super().wheelEvent(ev, axis=axis)
            return
        try:
            delta = float(ev.delta())
            modifiers = ev.modifiers()
            scene_pos = ev.scenePos()
            data_pos = self.mapSceneToView(scene_pos)
            x_pos = float(data_pos.x())
            y_pos = float(data_pos.y())
        except Exception:
            super().wheelEvent(ev, axis=axis)
            return
        consumed = owner._handle_wheel_dispatch(
            delta=delta, modifiers=modifiers, x_pos=x_pos, y_pos=y_pos,
            view_box=self,
        )
        if consumed:
            ev.accept()
        else:
            super().wheelEvent(ev, axis=axis)

    def mouseDragEvent(self, ev, axis=None):
        """Drop AA the instant a box-zoom rubber band begins.

        Fix B (2026-05-31 overlay-aa-interaction-fixes): the base
        ``ViewBox.mouseDragEvent`` only changes the view range on
        ``ev.isFinish()`` in RectMode — the whole rubber-band drag never
        passes through ``_on_xrange_changed`` (the AA-off chokepoint), so
        if AA was on when the drag started every frame re-rasterizes all
        curves and the box-zoom stutters/freezes. We hook ONLY the
        RectMode + LeftButton + full-2D (``axis is None``) start to flip
        AA off and stop the idle timer; the held-down drag is then kept
        AA-off by the idle gate's ``mouseButtons() != NoButton`` check, so
        a single drop at ``isStart`` suffices. ``isFinish`` re-arms via the
        base class's ``showAxRect → setRange → sigXRangeChanged →
        _on_xrange_changed`` chain, so we do NOT re-schedule here.

        Every branch MUST delegate to ``super()`` or box-zoom / pan / the
        right-button zoom and single-axis drags themselves break (Risk R1
        in the design).
        """
        owner = self._owner_canvas
        try:
            is_rect_left_2d = (
                owner is not None
                and ev.button() == Qt.LeftButton
                and self.state.get("mouseMode") == pg.ViewBox.RectMode
                and axis is None
            )
        except Exception:
            is_rect_left_2d = False
        if is_rect_left_2d:
            try:
                if ev.isStart():
                    owner.disable_interactive_quality()
            except Exception:
                pass
        super().mouseDragEvent(ev, axis=axis)
        # Overlay box-zoom (2026-06-06 grid-redraw-after-zoom): the base
        # RectMode finish ignores ``mouseEnabled`` and pulls the X-master Y
        # off [0, 1], collapsing the fixed k/N graticule to 2-3 lines. After
        # the rubber band lands on the X-master, re-lock its Y to [0, 1] and
        # redirect the box's Y span onto the selected channel.
        if is_rect_left_2d:
            try:
                is_xmaster = (
                    getattr(owner, "_overlay_mode", False)
                    and getattr(owner, "_x_master_handle", None) is not None
                    and owner._x_master_handle.view_box is self
                )
                if is_xmaster and ev.isFinish():
                    owner._apply_overlay_box_zoom_y()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Overlay Y-snap helper.
# ---------------------------------------------------------------------------


def _snap_y_to_divisions(y: float, n: int) -> float:
    """Round ``y`` to the nearest k/n grid boundary.

    Pure function — stateless and safe to call from tests.
    """
    return round(y * n) / n


_NICE_STEP_MANTISSAS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8]


def _nice_per_div(raw):
    """Return the smallest nice step that is >= ``raw``.

    Nice steps use _NICE_STEP_MANTISSAS x 10^k. Invalid, non-finite, and
    non-positive inputs return None so callers can choose a local fallback.
    """
    try:
        value = float(raw)
    except Exception:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    exp = math.floor(math.log10(value))
    base = 10.0 ** exp
    mantissa = value / base
    for step in _NICE_STEP_MANTISSAS:
        if step >= mantissa - 1e-9:
            return step * base
    return 10.0 * base


def _adjacent_nice_step(step, direction):
    """Return the neighboring nice step below/above ``step``."""
    current = _nice_per_div(step)
    if current is None:
        return None
    exponent = math.floor(math.log10(current))
    candidates = []
    for exp in range(exponent - 2, exponent + 3):
        base = 10.0 ** exp
        for mantissa in _NICE_STEP_MANTISSAS:
            candidates.append(mantissa * base)
    candidates = sorted(set(candidates))
    tol = max(abs(current) * 1e-9, 1e-12)
    if direction < 0:
        lower = [value for value in candidates if value < current - tol]
        return lower[-1] if lower else current / 10.0
    higher = [value for value in candidates if value > current + tol]
    return higher[0] if higher else current * 10.0


def _fmt_tick(value):
    """Format a graticule tick compactly enough for narrow overlay axes."""
    try:
        value = float(value)
    except Exception:
        return ""
    if not math.isfinite(value):
        return ""
    if value != 0.0 and (abs(value) >= 1e6 or abs(value) < 1e-4):
        return f"{value:.2e}"
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return f"{int(rounded)}"
    return f"{value:g}"


def _frame_to_nice(lo, hi, n):
    """Expand ``[lo, hi]`` into ``n`` nice, equal graticule divisions.

    Returns ``(bottom, top, ticks)`` where ``ticks`` has ``n + 1`` entries and
    the returned frame contains the requested window.
    """
    try:
        lo = float(lo)
        hi = float(hi)
    except Exception:
        lo, hi = 0.0, 0.0
    if hi < lo:
        lo, hi = hi, lo
    n = max(1, int(n))
    span = hi - lo
    if not math.isfinite(span) or span <= 0:
        center = (lo + hi) / 2.0
        if not math.isfinite(center):
            center = 0.0
        span = max(abs(center), 1.0)
        lo = center - span / 2.0
        hi = center + span / 2.0
    per_div = _nice_per_div(span / n) or (span / n)
    bottom = math.floor(lo / per_div) * per_div
    top = bottom + n * per_div
    guard = 0
    while top < hi - max(abs(per_div) * 1e-9, 1e-12) and guard < 64:
        per_div = _nice_per_div(per_div * 1.000001) or (per_div * 2.0)
        bottom = math.floor(lo / per_div) * per_div
        top = bottom + n * per_div
        guard += 1
    ticks = [bottom + k * per_div for k in range(n + 1)]
    return bottom, top, ticks


# ---------------------------------------------------------------------------
# Curve-layer cache key quantization (signal-processing/
# 2026-04-25-envelope-cache-bucket-width-quantization).
# ---------------------------------------------------------------------------


def _quantize_range_key(
    channel: str,
    xlim: Tuple[float, float],
    pixel_width: int,
) -> Tuple[str, int, int, int]:
    """Return the bucket-quantized cache key for one curve frame.

    The quantum is ``span / pixel_width`` so two xlims that differ by
    less than one pixel collapse to the same key — the envelope output
    is literally identical for those frames.
    """
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1
    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    span = x1 - x0
    quantum = (span / pixel_width) if span > 0 else 1.0
    if quantum <= 0:
        quantum = 1.0
    qx0 = int(round(x0 / quantum))
    qx1 = int(round(x1 / quantum))
    return (channel, qx0, qx1, int(pixel_width))


# ---------------------------------------------------------------------------
# TimeDomainCanvasPG
# ---------------------------------------------------------------------------


class TimeDomainCanvasPG(QWidget):
    """Pyqtgraph-backed drop-in for ``canvases.TimeDomainCanvas``."""

    # Signal contract (design §3.1 — frozen by W0 contract test).
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    span_selected = pyqtSignal(float, float)
    overlay_channel_selected = pyqtSignal(object)
    overlay_y_needs_selection = pyqtSignal()
    context_menu_requested = pyqtSignal()
    xrange_changed = pyqtSignal(float, float)
    visible_range_changed = pyqtSignal()

    # Mirror TimeDomainCanvas constants so callers see the same surface.
    MAX_PTS = 8000

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- inner widget tree ------------------------------------------
        # GraphicsLayoutWidget is the host for one or more PlotItem rows.
        # We keep it as a child rather than subclassing so this widget
        # itself can carry pyqtSignals without metaclass conflicts.
        self._glw = pg.GraphicsLayoutWidget(self)
        # Quiet background to match the matplotlib CHART_FACE; the actual
        # chart surface stays white.
        self._glw.setBackground("#ffffff")
        # Enlarge the drawing area: pyqtgraph's central layout defaults to a
        # 9px outer gutter + 8px inter-row spacing, which is wasted chrome.
        # Axis tick text lives in each PlotItem's own reserved band (not this
        # outer margin), so tightening it grows the plot without clipping
        # labels. Set once here — it survives plot_channels rebuilds.
        self._glw.ci.setContentsMargins(2, 2, 2, 2)
        self._glw.ci.setSpacing(2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._glw)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._glw.setMouseTracking(True)
        self._gpu_render_requested = False
        self._gpu_render_on = False
        self._gpu_viewport_filter_target = None

        # --- public state (design §5.5 compat seams) --------------------
        # axes_list is a list of PgAxisHandle (one per visible channel
        # in subplot mode, one shared in single/overlay mode).
        self.axes_list = []
        # _channel_lines is {name: (axis_facade, line_facade)} parity
        # with TimeDomainCanvas — used by ChartOptionsDialog and color sync.
        self._channel_lines = {}
        # View-state range restore needs a non-colliding key when two files
        # expose the same display channel name. Keep this separate so legacy
        # hover/selection/options paths can continue using _channel_lines.
        self._channel_view_state_lines = {}
        # channel_data is the raw post-range-filter dict — STAYS RAW.
        # get_statistics reads this; the envelope cache never feeds it.
        self.channel_data = {}
        # Parallel data_id dict (kept separate per design §4.2).
        self._channel_data_id = {}
        # Per-channel monotonicity cache, populated once per
        # plot_channels build. Used in _refresh_visible_data so the hot
        # path skips np.diff(t).
        self._channel_is_monotonic = {}
        # The "primary" axis facade — its sigXRangeChanged drives the
        # viewport-aware envelope refresh. Set after plot_channels.
        self._primary_xaxis_ax = None

        # --- cursor / dual-cursor state (matches TimeDomainCanvas) -----
        self._cursor_visible = False
        self._dual = False
        self._ax = None  # cursor A x-position
        self._bx = None  # cursor B x-position
        self._placing = "A"
        self._refresh = True
        self._last_t = 0

        # --- viewport refresh wiring ------------------------------------
        # 40 ms ≈ 25 FPS coalesce window, matching TimeDomainCanvas.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self._refresh_visible_data)
        self._refresh_pending = False
        # --- Auto Idle AA wiring ----------------------------------------
        # Curves stay AA-off while the user is interacting. After the
        # viewport settles, a short single-shot timer restores crisp static
        # curves by flipping PlotCurveItem.opts['antialias'] only.
        self._idle_aa_on = False
        self._idle_aa_timer = QTimer(self)
        self._idle_aa_timer.setSingleShot(True)
        self._idle_aa_timer.setInterval(150)
        self._idle_aa_timer.timeout.connect(self.try_enable_idle_quality)
        # Density budget for idle AA (Fix C, 2026-05-31; RECALIBRATED against
        # the end-to-end grab() repaint-frame harness). Two budgets, branched
        # on _overlay_mode in _idle_aa_density_ok:
        #   * OVERLAY: metric = SUM of drawn points across ALL curves (they
        #     overlap at one full-plot rect → repaint as one region). Tight
        #     budget so a dense ≥3-curve overlay (sum ≥ 9000, measured > ~30 ms
        #     AA-on) gates OFF while a light 2-curve overlay (sum ≤ 6000) keeps
        #     AA. This is the UNCACHED path the gate must govern.
        #   * SUBPLOT/SINGLE: metric = MAX over rows of that row's drawn points
        #     (disjoint rects). Subplot curves carry a DeviceCoordinateCache
        #     (Fix D, subplot-only) so an AA-on cached frame is ~0.3–0.9 ms at
        #     ANY width; the budget is generous so a single maximized / 4K
        #     curve (~7700-pt envelope) always gets AA (fixes issue 1).
        # ON/OFF are real-hardware tunables; module defaults above carry the
        # measured frame-ms justification. Legacy _AA_SEGMENT_ON/_OFF are kept
        # as aliases of the subplot pair so existing tools/tests still work.
        self._AA_OVERLAY_SEGMENT_ON = _AA_OVERLAY_SEGMENT_ON
        self._AA_OVERLAY_SEGMENT_OFF = _AA_OVERLAY_SEGMENT_OFF
        self._AA_SUBPLOT_SEGMENT_ON = _AA_SUBPLOT_SEGMENT_ON
        self._AA_SUBPLOT_SEGMENT_OFF = _AA_SUBPLOT_SEGMENT_OFF
        self._AA_SEGMENT_ON = _AA_SEGMENT_ON
        self._AA_SEGMENT_OFF = _AA_SEGMENT_OFF
        self._idle_aa_density_allowed = False
        # Cold-start dead-band fix: until the first decision (and after a
        # resize / rebuild reset) the density gate seeds via the OFF
        # threshold instead of inheriting the pessimistic initial False, so
        # a single wide curve no longer sticks AA-off forever.
        self._idle_aa_density_seeded = False
        # --- resize re-arm debounce (Fix C) -----------------------------
        # A 40 ms single-shot (mirrors _refresh_timer's coalesce window)
        # so dragging the window border does not recompute the envelope on
        # every intermediate size; it fires once the resize settles.
        self._resize_settle_timer = QTimer(self)
        self._resize_settle_timer.setSingleShot(True)
        self._resize_settle_timer.setInterval(40)
        self._resize_settle_timer.timeout.connect(self._on_resize_settled)
        # The sigXRangeChanged connections so we can drop them on
        # rebuild (pyqtgraph analogue of the matplotlib callbacks
        # lifecycle lesson). We connect on EVERY subplot ViewBox (not
        # just the primary) because pyqtgraph's setXLink is intentionally
        # NOT used — any user-driven xlim mutation can originate from
        # any subplot, so we must propagate from source -> siblings
        # explicitly. List of (view_box, partial_handler) pairs.
        self._xrange_conns: list = []

        # --- curve-layer pixmap cache (design §5.2) ---------------------
        # Keyed by (channel_name, bucketed_lo, bucketed_hi, bucketed_pixel_width).
        # Value: ("painter_path", QPainterPath, QPixmap). Production
        # rendering blits the cached pixmap; cursor/span/overlay overlays
        # draw AFTER blit. PlotDataItem.setData remains the fallback path
        # for the initial bind only — pan/refresh goes through this cache.
        self._curve_path_cache: "OrderedDict[Tuple[str, int, int, int], Tuple]" = (
            OrderedDict()
        )
        self._curve_path_cache_capacity = 64
        # Per-channel "last range key" so a re-flush with no xlim change
        # is a no-op (pyqt-ui/2026-04-25-cache-invalidation-event-conditional).
        self._last_range_key: dict = {}

        # --- compatibility seams expected by main_window / chart_stack --
        # span_selector kept as None so existing main_window code
        # (`canvas.span_selector = ...`) does not AttributeError.
        self.span_selector = None
        self._span_callback = None

        # --- chart-options dialog wiring (parity with matplotlib path) --
        # Remembered axis for the toolbar 图表选项 button when no subplot
        # is under the cursor (mirrors canvases.py:_open_chart_options_for_axes
        # `_chart_options_ax`). Double-click resolves the subplot under the
        # cursor; the toolbar button falls back to this / the primary axis.
        self._chart_options_ax = None
        # Re-entry guard for the double-click → modal dialog path. A fast
        # double-click on a popover/modal could otherwise open it twice
        # (pyqt-ui/2026-04-26-popover-accept-deactivate-race). Flipped True
        # for the duration of the dialog's exec_ and cleared in finally.
        self._chart_options_opening = False
        # Double-click dispatch: a double-click over a subplot opens the
        # chart-options dialog for THAT subplot's axis (parity with
        # canvases.py:1370 `button == 1 and dblclick`). We use a QWidget
        # event filter on the GraphicsLayoutWidget's viewport rather than
        # the GraphicsScene's `sigMouseClicked` because the scene's click
        # pipeline (sendClickEvent → mouseReleaseEvent) does not deliver
        # under ``QT_QPA_PLATFORM=offscreen`` via ``QTest.mouseDClick``,
        # whereas plain QWidget ``QEvent.MouseButtonDblClick`` delivery
        # does. The filter maps the viewport pixel to a scene position so
        # the subplot hit-test stays accurate.
        self._install_viewport_event_filter()

        # --- T6: overlay-mode selection + per-channel emphasis ----------
        # Mirrors canvases.py:_apply_overlay_selection_style (lw 1.0 / 1.8;
        # alpha 0.42 / 1.0). Stored per channel so test/UI can probe.
        self._overlay_mode = False
        self._selected_overlay_channel = None
        # Per-channel default emphasis: (line_width, alpha). Default
        # state mirrors matplotlib's "no selection" line: lw=1.05,
        # alpha=None (treated as 1.0). De-emphasised state is
        # (1.0, 0.42); selected is (1.8, 1.0).
        self._overlay_default_lw = 1.5
        self._overlay_default_alpha = 1.0
        self._overlay_selected_lw = 2.6
        self._overlay_selected_alpha = 1.0
        self._overlay_de_emphasised_lw = 1.35
        self._overlay_de_emphasised_alpha = 0.42

        # Pixel pick radius for overlay nearest-curve hit-test. Mirrors
        # canvases.py:_overlay_pick_radius_px = 12.0 (the matplotlib
        # reference). Used by _select_overlay_channel_from_scene_pos.
        self._overlay_pick_radius_px = 12.0

        # Horizontal spacing (px) inserted between the stacked overlay right
        # axes via PlotItem.layout.setHorizontalSpacing so each rotated
        # channel name clears the next axis's tick numbers. Each AxisItem's
        # rotated label overhangs ~5px past its declared width(), so this
        # must exceed that overhang to leave a visible gap. Replaces the old
        # ``setWidth(44)`` HARD CLAMP (it jammed wide-number axes instead of
        # acting as a floor); overlay axes now auto-size to their tick text.
        self._overlay_axis_column_spacing = 12

        # Selected-channel Y-drag bookkeeping: (start_y_px, (lo, hi)).
        # _begin_overlay_y_drag_at captures, _apply_overlay_y_drag_at
        # consumes. ChartStack/MainWindow wire mouse events to these.
        self._overlay_y_drag_start = None
        # True for the duration of a live mouse-driven Y-drag so the
        # eventFilter knows MouseMove is a drag (Problem 2). Cleared on
        # release. While True the X-master ViewBox's mouse pan is disabled
        # so the curve Y-drag does not fight the default ViewBox pan.
        self._overlay_dragging = False
        # Drag-release snap animation: glide the channel to the nice
        # graticule over ``_snap_anim_ms`` instead of jumping instantly
        # (2026-06-06 release-snap smoothing). ms<=0 → synchronous snap.
        self._snap_anim = None
        self._snap_anim_ms = 150
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._overlay_view_sync_conns = []
        # Overlay Y grid/tick graticule. The inspector Y density spin drives
        # this value directly in overlay mode.
        self._overlay_divisions = 8
        self._overlay_grid_lines: list = []
        # The X-master axis handle in overlay mode. Its ViewBox owns the
        # shared X range, the default mouse-pan, and the scene geometry
        # anchor; NO curves are attached to it (every channel — including
        # the first/left one — lives on its own aux ViewBox). In
        # subplot/single mode this stays None and _primary_xaxis_ax is
        # axes_list[0] as before.
        self._x_master_handle = None

        # T6 requirement 1: subplot inside-label bookkeeping. Mirrors
        # canvases.py:_apply_inside_channel_labels — when bbox overlap
        # would clip outer ylabels, flip them to an inside-axes TextItem.
        self._inside_label_items = []
        self._inside_label_handles = []
        self._inside_label_conns = []
        # Cache the last subplot label specs so a resize-driven recheck
        # can re-place labels without re-walking the plot.
        self._subplot_label_specs = []

        # Inspector tick-density defaults mirror PersistentTop defaults.
        self._tick_density = (10, 8)

        # Cursor line scene items. In single mode _cursor_line_items is the
        # live hover line on each subplot. In dual mode _cursor_a_items and
        # _cursor_b_items hold the placed A/B cursors.
        self._cursor_line_items = []
        self._cursor_a_items = []
        self._cursor_b_items = []
        self._dual_cursor_extreme_markers = []

        # Bug 3: post-rebuild callbacks. plot_channels builds NEW ViewBoxes
        # (default PanMode), so any owner that pins a mouse mode (the
        # toolbar's pan/zoom state) must re-apply it to the fresh ViewBoxes.
        # Private (not a W0 signal) so the contract surface is unchanged;
        # _ChartCard registers toolbar.apply_current_mouse_mode here.
        self._replot_callbacks: list = []

        # Design D: shared mouse-mode controller (single source of truth). The
        # right-click 鼠标操作 submenu and the top toolbar BOTH drive the same
        # object so their pan/box-select state can never disagree. The toolbar
        # registers itself via register_mouse_mode_controller; until then this
        # stays None and the menu items are inert (no parallel mode path).
        self._mouse_mode_controller = None

    # ------------------------------------------------------------------
    # Public surface (signal/method names frozen by W0 contract tests).
    # ------------------------------------------------------------------

    def plot_channels(self, ch_list, mode="overlay", xlabel="Time (s)"):
        """Build the chart for ``ch_list``.

        Row shape (legacy or preferred):

        - ``(name, visible, t, sig, color, unit)`` — legacy
        - ``(name, visible, t, sig, color, unit, data_id)`` — preferred

        ``data_id`` is required for the curve-layer cache to key entries
        per-source-file; rows without it route through the slow path.
        """
        self.disable_interactive_quality()
        self.clear()

        vis = []
        for row in ch_list:
            if not row[1]:
                continue
            if len(row) >= 7:
                name, _, t, sig, color, unit, data_id = row[:7]
            else:
                name, _, t, sig, color, unit = row[:6]
                data_id = None
            vis.append((name, t, sig, color, unit, data_id))

        if not vis:
            return

        overlay_mode = (mode == "overlay" and len(vis) >= 2)
        subplot_mode = (mode == "subplot" and len(vis) > 1)
        self._overlay_mode = overlay_mode  # parity attr name with TimeDomainCanvas

        if subplot_mode:
            for i, (name, t, sig, color, unit, data_id) in enumerate(vis):
                pi = self._add_plot_item(row=i, col=0)
                handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
                self.axes_list.append(handle)
                self._bind_channel(
                    handle, name, t, sig, color, unit, data_id,
                    xlabel=xlabel if i == len(vis) - 1 else None,
                )
                self._configure_subplot_bottom_axis(handle, is_bottom=(i == len(vis) - 1))
            # NOTE: we intentionally do NOT call ``setXLink`` here.
            # Pyqtgraph's linked-view propagation uses screen-geometry
            # interpolation (ViewBox.linkedViewChanged) which produces a
            # small per-subplot shift when the subplots' screen widths
            # differ (the bottommost subplot owns the x-axis label
            # gutter). For an analytical app the linked range MUST be
            # exact, so we propagate explicitly via _propagate_xlim_to_siblings
            # on every sigXRangeChanged tick from the primary.
            # Subplot labels need bbox-overlap-driven inside/outside flip.
            # vis[i] is (name, t, sig, color, unit, data_id); color at idx 3.
            self._subplot_label_specs = [
                (self.axes_list[i], vis[i][0], vis[i][3])
                for i in range(len(vis))
            ]
            # Apply once now; resize re-checks via resizeEvent.
            self._recheck_subplot_label_placement()
            # Each subplot's left AxisItem auto-sizes to its OWN tick-label
            # text width, so rows with wider numeric labels push their
            # plot-area left edge further right than narrower rows — the
            # shared time grid then looks skewed between rows. Range is
            # already exact via _propagate_xlim_to_siblings; here we only fix
            # geometry by unifying every left axis to the widest one so all
            # plot-area left edges land at the same screen x.
            self._unify_subplot_left_axis_widths()
        elif overlay_mode:
            # Overlay: one PlotItem whose MAIN ViewBox is demoted to an
            # X-master / mouse-capture-only surface (NO curves attached),
            # plus one dedicated aux ViewBox + Y axis PER channel. This is
            # the symmetric layout — the first/left channel is no longer
            # special-cased onto the shared main ViewBox, so its Y drag no
            # longer fights X-padding the way it did when it owned the
            # geometry/X/mouse anchor simultaneously. Channel 1 binds the
            # LEFT axis; channels 2..N bind successive right axes. Mirrors
            # the original matplotlib twinx stack: every channel owns an
            # independent Y axis while all share X.
            pi = self._add_plot_item(row=0, col=0)
            # X-master handle wraps the main ViewBox; never enters
            # axes_list and never carries a curve.
            self._x_master_handle = PgAxisHandle(
                plot_item=pi,
                owner_canvas=self,
                allow_y_grid=False,
            )
            # Channel 1 → dedicated aux ViewBox bound to the LEFT axis.
            first_handle = self._add_overlay_axis_handle(pi, 0)
            self.axes_list.append(first_handle)
            self._bind_channel(first_handle, *vis[0], xlabel=xlabel)
            # Channels 2..N → dedicated aux ViewBoxes bound to right axes.
            for idx, (name, t, sig, color, unit, data_id) in enumerate(vis[1:], start=1):
                handle = self._add_overlay_axis_handle(pi, idx)
                self.axes_list.append(handle)
                self._bind_channel(handle, name, t, sig, color, unit, data_id, xlabel=xlabel)
            # Apply default emphasis state (no selection).
            self._apply_overlay_emphasis()
            # Grid: in overlay the built-in left + right axes are linked to
            # DIFFERENT per-channel ViewBoxes (independent Y ranges) and each
            # drew its own horizontal grid at its OWN ticks in its OWN channel
            # pen color (see _apply_pg_axis_style) → multiple non-coincident,
            # multi-colored Y grids. There is no canonical Y range to grid, so
            # show ONLY the single shared X grid (the bottom axis) and disable
            # the Y grid. subplot/single keep both grids (one Y range each).
            # Idempotent: re-running on rebuild just re-asserts x-only.
            try:
                pi.showGrid(x=True, y=False, alpha=0.28)
            except Exception:
                pass
            self._build_overlay_y_grid()
        else:
            # Single channel.
            pi = self._add_plot_item(row=0, col=0)
            handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
            self.axes_list.append(handle)
            name, t, sig, color, unit, data_id = vis[0]
            self._bind_channel(handle, name, t, sig, color, unit, data_id, xlabel=xlabel)

        for handle in self.axes_list:
            self._attach_axis_handle_callbacks(handle)

        # Primary X-axis owner. Subplot/single mode: it is axes_list[0]
        # and we listen on EVERY axis ViewBox (origin-aware propagation;
        # see _on_xrange_changed). Overlay mode: it is the dedicated
        # X-master ViewBox (which is NOT in axes_list because no channel
        # curve lives on it); we listen on the X-master AND every aux
        # channel ViewBox so a pan from any of them propagates the exact
        # range to all the others.
        if self.axes_list:
            if self._overlay_mode and self._x_master_handle is not None:
                self._primary_xaxis_ax = self._x_master_handle
                self._connect_xrange_listener(self._x_master_handle)
            else:
                self._primary_xaxis_ax = self.axes_list[0]
            for handle in self.axes_list:
                self._connect_xrange_listener(handle)
            self._set_xrange_to_data_union()
            self._emit_xrange_changed()
            if self._overlay_mode:
                self._sync_overlay_aux_viewboxes()
                self._connect_overlay_view_sync()

        self._refresh = True
        self._apply_tick_density_to_all_axes()
        if self._overlay_mode:
            self._repin_overlay_channel_ticks()
        self._unify_subplot_bottom_axis_heights()
        # Tick density and data-union X seeding can change AxisItem geometry
        # after the early subplot label pass. Re-pin once at the end of build
        # so the first rendered frame already has one shared X grid.
        self._unify_subplot_left_axis_widths()

        # Bug 3: notify owners that fresh ViewBoxes exist so they can
        # re-apply pinned interaction state (toolbar pan/zoom mode). Runs
        # last so callbacks see the fully-built axes_list / x_master.
        self._run_replot_callbacks()
        if bool(getattr(self, "_gpu_render_requested", False)) != bool(getattr(self, "_gpu_render_on", False)):
            self._apply_gpu_viewport()
        self.disable_interactive_quality()
        self.schedule_idle_quality()

    def register_replot_callback(self, callback):
        """Register a zero-arg ``callback`` invoked after every
        ``plot_channels`` rebuild. Idempotent; ignores duplicates.

        Used by ``_ChartCard`` to re-apply the toolbar's current mouse mode
        to the freshly-built ViewBoxes (Bug 3). Private hook — not part of
        the W0 signal contract.
        """
        if callable(callback) and callback not in self._replot_callbacks:
            self._replot_callbacks.append(callback)

    def _run_replot_callbacks(self):
        for callback in list(self._replot_callbacks):
            try:
                callback()
            except Exception:
                pass

    def register_mouse_mode_controller(self, controller):
        """Register the shared mouse-mode ``controller`` (design D).

        ``controller`` must expose ``current_mouse_mode()`` returning
        ``'pan'`` / ``'zoom'`` / ``''`` plus ``set_pan_mode()`` and
        ``set_zoom_mode()``. ``_ChartCard`` registers the
        ``PgNavigationToolbar`` here so the right-click 鼠标操作 submenu and the
        toolbar share ONE state machine — selecting a menu item updates the
        toolbar (and its ViewBoxes/icons), and opening the menu reflects the
        toolbar's current mode in the checkmark.
        """
        self._mouse_mode_controller = controller

    def _plot_item_for_view_box(self, view_box):
        """Return the PlotItem that owns ``view_box`` (or None).

        In single/subplot mode each ViewBox is the PlotItem's own view; in
        overlay mode the right-axis aux ViewBoxes share the X-master
        PlotItem, so we map any aux ViewBox back to that PlotItem.
        """
        for handle in list(self.axes_list):
            if getattr(handle, "view_box", None) is view_box:
                return getattr(handle, "plot_item", None)
        master = self._x_master_handle
        if master is not None and getattr(master, "view_box", None) is view_box:
            return getattr(master, "plot_item", None)
        # Overlay aux ViewBoxes all render onto the X-master PlotItem.
        if view_box in self._overlay_aux_viewboxes and master is not None:
            return getattr(master, "plot_item", None)
        if master is not None:
            return getattr(master, "plot_item", None)
        if self.axes_list:
            return getattr(self.axes_list[0], "plot_item", None)
        return None

    def _redesign_context_menu_for_viewbox(self, view_box, menu):
        """Reshape the assembled right-click ``menu`` of ``view_box`` per the
        design (delegated from ``_ModifierWheelViewBox.raiseContextMenu`` so
        the canvas can supply the PlotItem + shared mouse-mode controller)."""
        plot_item = self._plot_item_for_view_box(view_box)
        redesign_pg_context_menu(
            menu,
            plot_item,
            self._mouse_mode_controller,
            view_all_handler=self.reset_view_to_data_extents,
            allow_y_grid=not self._overlay_mode,
        )

    def _add_plot_item(self, *, row, col):
        """Add a PlotItem hosted by our ``_ModifierWheelViewBox``.

        Mirrors ``GraphicsLayoutWidget.addPlot`` but injects the custom
        ViewBox so wheel events route through ``_handle_wheel_dispatch``
        (T6 requirement 4). Also installs a ``sigMouseClicked`` hook on
        the scene for blank-click deselect in overlay mode.
        """
        vb = _ModifierWheelViewBox(owner_canvas=self)
        vb.setBorder(
            pg.mkPen(
                color=PG_AXIS_NEUTRAL_COLOR,
                width=PG_AXIS_NEUTRAL_WIDTH,
            )
        )
        pi = self._glw.addPlot(row=row, col=col, viewBox=vb)
        _localize_pg_context_menu(getattr(vb, "menu", None))
        _localize_pg_context_menu(getattr(pi, "ctrlMenu", None))
        _localize_pg_context_actions(getattr(pi.scene(), "contextMenu", []))
        try:
            pi.showGrid(x=True, y=True, alpha=0.28)
        except Exception:
            pass
        for axis_name in ("left", "right", "bottom"):
            try:
                axis = pi.getAxis(axis_name)
                axis.enableAutoSIPrefix(False)
                _apply_pg_axis_font(axis)
                axis.setPen(
                    pg.mkPen(
                        color=PG_AXIS_NEUTRAL_COLOR,
                        width=PG_AXIS_NEUTRAL_WIDTH,
                    )
                )
            except Exception:
                pass
        return pi

    def _add_overlay_axis_handle(self, primary_plot, index):
        """Create one dedicated Y axis/ViewBox for an overlay channel.

        Symmetric layout (Problem 3): EVERY channel — including the
        first — gets its own aux ViewBox so its Y drag never fights the
        X-master's padding.

        - ``index == 0`` → channel 1 binds the built-in LEFT axis.
        - ``index >= 1`` → every right channel appends a FRESH right
          ``AxisItem`` into contiguous layout columns starting at col 3,
          leaving the PlotItem's built-in right-axis column (col 2) EMPTY.
          We deliberately do NOT reuse the built-in right axis for channel
          2: the standard right-axis column abuts the ViewBox and pyqtgraph
          suppresses ``setHorizontalSpacing`` across that col 2→col 3
          boundary, so a built-in-right + appended-right mix leaves the
          first pair overlapping while the rest are spaced. Routing every
          right channel through contiguous appended columns makes the
          inter-axis spacing uniform so no rotated name butts against the
          neighbour's tick numbers.

        All aux ViewBoxes share the X-master plot's scene geometry and X
        range and have their OWN mouse pan disabled so the main (X-master)
        ViewBox stays the sole mouse-capture surface.
        """
        aux_vb = _ModifierWheelViewBox(owner_canvas=self)
        _localize_pg_context_menu(getattr(aux_vb, "menu", None))
        if index == 0:
            # Channel 1: bind the existing LEFT axis to the aux ViewBox so
            # the left axis tracks this channel's independent Y range.
            try:
                primary_plot.showAxis("left")
            except Exception:
                pass
            axis_item = primary_plot.getAxis("left")
        else:
            # Channels 2..N: fresh appended right axes at contiguous columns
            # (index 1 → col 3, index 2 → col 4, ...). Col 2 (built-in right)
            # stays unused so layout spacing applies uniformly to every pair.
            axis_item = pg.AxisItem("right")
            try:
                axis_item.enableAutoSIPrefix(False)
            except Exception:
                pass
            _apply_pg_axis_font(axis_item)
            try:
                primary_plot.layout.addItem(axis_item, 2, 2 + index)
            except Exception:
                pass
            try:
                axis_item.setZValue(-10000)
            except Exception:
                pass
            # Reserve horizontal spacing between every stacked right axis so
            # each rotated channel name clears the next axis's tick numbers.
            try:
                primary_plot.layout.setHorizontalSpacing(
                    self._overlay_axis_column_spacing
                )
            except Exception:
                pass
        try:
            primary_plot.scene().addItem(aux_vb)
        except Exception:
            pass
        try:
            axis_item.linkToView(aux_vb)
        except Exception:
            pass
        # Aux ViewBoxes are display-only overlays: the X-master ViewBox is
        # the mouse-pan surface. Disabling mouse here keeps the overlapping
        # aux ViewBoxes from stealing the pan drag (Problem 3 "mouse-
        # capture only" demotion of the main ViewBox).
        try:
            aux_vb.setMouseEnabled(x=False, y=False)
        except Exception:
            pass
        self._overlay_aux_viewboxes.append(aux_vb)
        self._overlay_aux_axes.append(axis_item)
        handle = PgAxisHandle(
            plot_item=primary_plot,
            view_box=aux_vb,
            axis_item=axis_item,
            owner_canvas=self,
            allow_y_grid=False,
        )
        return handle

    def plot_channels_preserving_xlim(self, ch_list, mode="overlay", xlabel="Time (s)"):
        """Rebuild the chart with ``ch_list``/``mode`` while preserving
        the current primary xlim across the teardown→build cycle.

        T6 requirement 5: mirrors the pattern at main_window.py:382-448
        BUT keeps the capture/restore INSIDE the canvas — per the brief,
        MainWindow should not be involved in the mode-switch path of the
        pyqtgraph canvas. The tangent-only guard at main_window.py:430
        is NOT re-derived here (out of scope per defensive-gate
        ``codex-confirmed-issue-list-means-remaining-scope`` annotations).
        """
        cur_xlim = self._capture_primary_xlim()
        self.plot_channels(ch_list, mode=mode, xlabel=xlabel)
        if cur_xlim is not None:
            self._restore_primary_xlim(cur_xlim)

    def _capture_primary_xlim(self):
        ax = self._primary_xaxis_ax
        if ax is None:
            return None
        try:
            lo, hi = ax.get_xlim()
        except Exception:
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (float(lo), float(hi))

    def _restore_primary_xlim(self, xlim):
        ax = self._primary_xaxis_ax
        if ax is None:
            return
        new_lo, new_hi = xlim
        try:
            ax.set_xlim(float(new_lo), float(new_hi))
        except Exception:
            return
        self._sync_x_axis_item_range(ax, new_lo, new_hi)
        self._propagate_xlim_to_siblings(source=ax)
        # Order per pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before:
        # mutate, then flush. set_xlim above fired sigXRangeChanged and
        # scheduled the 40 ms debounced QTimer; drain it synchronously
        # so the post-switch frame is the high-detail envelope.
        try:
            self._flush_pending_refresh()
        except Exception:
            pass

    def get_visible_xlim(self):
        """Return the current visible X range, or None before any plot."""
        return self._capture_primary_xlim()

    def restore_visible_xlim(self, xlim):
        """Restore visible X through the existing synchronized restore path."""
        if xlim is not None:
            self._restore_primary_xlim(xlim)

    def get_visible_ylims(self):
        """Return per-channel visible Y ranges keyed for ViewState storage."""
        out = {}
        for key, pair in (
            getattr(self, "_channel_view_state_lines", None) or {}
        ).items():
            try:
                out[key] = pair[0].get_ylim()
            except Exception:
                continue
        return out

    def restore_visible_ylims(self, ylims):
        """Restore per-channel Y ranges; silently skip missing channels."""
        view_state_lines = getattr(self, "_channel_view_state_lines", None) or {}
        legacy_lines = getattr(self, "_channel_lines", None) or {}
        changed = False
        for name, ylim in (ylims or {}).items():
            pair = view_state_lines.get(name) or legacy_lines.get(name)
            if pair is None:
                continue
            try:
                pair[0].set_ylim(*ylim)
                changed = True
            except Exception:
                continue
        if changed:
            self.visible_range_changed.emit()

    def _sync_x_axis_item_range(self, handle, lo, hi):
        try:
            axis = handle.x_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        try:
            axis.setRange(float(lo), float(hi))
        except Exception:
            return
        try:
            axis.update()
        except Exception:
            pass

    def _bind_channel(self, axis_handle, name, t, sig, color, unit, data_id, *, xlabel=None):
        """Attach one channel to ``axis_handle``.

        Initial bind installs a ``PlotDataItem`` on either the PlotItem's
        primary ViewBox or an overlay auxiliary ViewBox. Subsequent pan/
        zoom refreshes feed the visible item with the current envelope.
        """
        pi = axis_handle.plot_item
        if pi is None:
            return
        # Downsample once for the static bind so we don't ship 100k
        # points into Qt's painter on construction. The fallback uses
        # build_envelope's xlim=None full-range contract — purely a
        # smoke-render path; the cache populates on first set_xlim.
        try:
            xlim = axis_handle.get_xlim()
        except Exception:
            xlim = None
        bind_t, bind_s = build_envelope(
            np.asarray(t),
            np.asarray(sig),
            xlim=None,
            pixel_width=self._initial_bind_pixel_width(axis_handle),
            is_monotonic=None,
        )
        pen = pg.mkPen(color=color, width=self._overlay_default_lw)
        primary_vb = pi.getViewBox() if hasattr(pi, "getViewBox") else None
        target_vb = axis_handle.view_box
        if target_vb is not None and target_vb is not primary_vb:
            pdi = pg.PlotDataItem(bind_t, bind_s, pen=pen, name=name)
            try:
                target_vb.addItem(pdi)
            except Exception:
                pass
            add_line_item = getattr(axis_handle, "add_line_item", None)
            if callable(add_line_item):
                add_line_item(pdi)
        else:
            pdi = pi.plot(bind_t, bind_s, pen=pen, name=name)
        # Store the raw arrays + parallel dicts; channel_data stays RAW
        # so get_statistics is unaffected by envelope output.
        t_arr = np.asarray(t)
        sig_arr = np.asarray(sig)
        self.channel_data[name] = (t_arr, sig_arr, color, unit)
        self._channel_data_id[name] = data_id
        line_handle = _PgLineHandle(pdi, label_fallback=name)
        self._channel_lines[name] = (axis_handle, line_handle)
        self._channel_view_state_lines[
            _view_state_channel_key(data_id, name)
        ] = (axis_handle, line_handle)
        # Cache monotonicity once per build (parity with F-1 follow-up).
        self._channel_is_monotonic[name] = _is_monotonic_array(t_arr)

        # Y-axis label uses the channel's color so the overlay/subplot
        # visual cue matches the matplotlib renderer.
        try:
            if self._overlay_mode:
                # Bug 1: pyqtgraph's AxisItem.setLabel renders text as HTML
                # and IGNORES "\n", so the _compact_axis_label newline (for
                # "[prefix] longname") produced one long unbroken rotated
                # label that ran over the tick numbers and the next axis.
                # Use a single-line label, but size the ellipsis budget from
                # the current axis height instead of hard-capping every overlay
                # channel at 22 chars. Tall charts can show the full name while
                # short charts still fall back to a bounded middle ellipsis.
                label = self._overlay_axis_label(axis_handle, name, unit)
            else:
                compact = _compact_axis_label(name, unit, max_chars=20)
                label = f"{compact}" + (f" ({unit})" if unit else "")
            axis_handle.set_ylabel(label)
            _apply_pg_axis_font(axis_handle.y_axis_item())
        except Exception:
            pass
        if self._overlay_mode:
            self._configure_overlay_axis_geometry(axis_handle)
        self._apply_pg_axis_style(axis_handle, color)
        if xlabel is not None:
            try:
                axis_handle.set_xlabel(xlabel)
                _apply_pg_axis_font(axis_handle.x_axis_item())
            except Exception:
                pass

    def _overlay_axis_label(self, axis_handle, name, unit):
        base = str(name).replace("\n", " ")
        suffix = f" ({unit})" if unit else ""
        max_chars = self._overlay_axis_label_max_chars(axis_handle, base, suffix)
        compact = _middle_ellipsis(base, max_chars=max_chars)
        return f"{compact}{suffix}"

    def _overlay_axis_label_max_chars(self, axis_handle, base, suffix):
        """Return the largest label budget that fits the rotated Y axis."""
        text = str(base)
        if not text:
            return _OVERLAY_AXIS_LABEL_FALLBACK_CHARS

        available = self._overlay_axis_label_available_height(axis_handle)
        if available <= 0:
            return min(len(text), _OVERLAY_AXIS_LABEL_FALLBACK_CHARS)

        metrics = QFontMetrics(_pg_chart_font(9))

        def text_width(value):
            try:
                return float(metrics.horizontalAdvance(value))
            except AttributeError:  # pragma: no cover - older Qt fallback
                return float(metrics.width(value))

        full_label = f"{text}{suffix}"
        if text_width(full_label) <= available:
            return len(text)

        low = min(_OVERLAY_AXIS_LABEL_MIN_CHARS, len(text))
        high = len(text)
        best = low
        while low <= high:
            mid = (low + high) // 2
            candidate = f"{_middle_ellipsis(text, max_chars=mid)}{suffix}"
            if text_width(candidate) <= available:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return max(_OVERLAY_AXIS_LABEL_MIN_CHARS, min(best, len(text)))

    def _overlay_axis_label_available_height(self, axis_handle):
        heights = []
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is not None:
            try:
                h = float(axis.size().height())
                if h > 0:
                    heights.append(h)
            except Exception:
                pass
            try:
                h = float(axis.sceneBoundingRect().height())
                if h > 0:
                    heights.append(h)
            except Exception:
                pass
        vb = getattr(axis_handle, "view_box", None)
        if vb is not None:
            try:
                h = float(vb.sceneBoundingRect().height())
                if h > 0:
                    heights.append(h)
            except Exception:
                pass
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                h = float(viewport.height())
                if h > 0:
                    heights.append(h)
        except Exception:
            pass
        if not heights:
            return 0.0
        return max(0.0, max(heights) - _OVERLAY_AXIS_LABEL_VERTICAL_PADDING_PX)

    def _refresh_overlay_axis_labels(self):
        if not self._overlay_mode or not self._channel_lines:
            return
        for name, (handle, _line) in self._channel_lines.items():
            row = self.channel_data.get(name)
            unit = row[3] if row is not None else ""
            color = row[2] if row is not None else PG_AXIS_NEUTRAL_COLOR
            try:
                handle.set_ylabel(self._overlay_axis_label(handle, name, unit))
                _apply_pg_axis_font(handle.y_axis_item())
                self._configure_overlay_axis_geometry(handle)
                self._apply_pg_axis_style(handle, color)
            except Exception:
                pass

    def _apply_pg_axis_style(self, axis_handle, color):
        """Keep grid/axis lines neutral while tick text follows the channel."""
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        _apply_pg_axis_font(axis)
        try:
            axis.setPen(
                pg.mkPen(color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH)
            )
        except Exception:
            pass
        try:
            axis.setTextPen(pg.mkPen(color=color))
        except Exception:
            pass

    def _channel_name_for_handle(self, handle):
        for name, (candidate, _line) in self._channel_lines.items():
            if candidate is handle:
                return name
        return None

    def _sync_pg_channel_color(self, channel_name, color):
        row = self.channel_data.get(channel_name)
        if row is not None:
            self.channel_data[channel_name] = (row[0], row[1], color, row[3])
        for handle, item in zip(self._inside_label_handles, self._inside_label_items):
            if self._channel_name_for_handle(handle) != channel_name:
                continue
            try:
                item.setColor(pg.mkColor(color))
                item.border = pg.mkPen(color=color, width=0.8)
                item.update()
            except Exception:
                pass
        self.draw_idle()

    def _configure_overlay_axis_geometry(self, axis_handle):
        """Overlay-only axis geometry so the rotated label clears the ticks.

        Measures:
        - ``enableAutoSIPrefix(False)`` so pyqtgraph does not append a
          ``(x0.001)`` scale chip that overlaps the channel label.
        - ``setWidth(None)`` so the AxisItem AUTO-SIZES to fit its own tick
          text. The previous ``setWidth(44)`` was documented as a "floor"
          but ``AxisItem.setWidth(w)`` is a HARD CLAMP — wide-number axes
          (e.g. -2600 / 1400) were jammed to 44px and their numbers crammed
          against the label. Real inter-axis clearance is provided by
          ``setHorizontalSpacing`` between the stacked right axes
          (``_add_overlay_axis_handle``), not by a per-axis width pin.
        """
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        try:
            axis.enableAutoSIPrefix(False)
        except Exception:
            pass
        # Release any inherited width pin so the axis auto-sizes to its own
        # tick-text width; the rotated name then never crams against ticks.
        try:
            axis.setWidth(None)
        except Exception:
            pass

    def _initial_bind_pixel_width(self, axis_handle=None) -> int:
        """Return a first-frame envelope width close to the visible plot width."""
        widths = []
        if axis_handle is not None:
            vb = getattr(axis_handle, "view_box", None)
            if vb is not None:
                try:
                    w = int(vb.sceneBoundingRect().width())
                    if w > 1:
                        widths.append(w)
                except Exception:
                    pass
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                w = int(viewport.width())
                if w > 1:
                    widths.append(w)
        except Exception:
            pass
        if not widths:
            return self.MAX_PTS
        return max(1, min(self.MAX_PTS, max(widths)))

    def _configure_subplot_bottom_axis(self, axis_handle, *, is_bottom):
        pi = axis_handle.plot_item
        if pi is None:
            return
        try:
            bottom = pi.getAxis("bottom")
        except Exception:
            bottom = None
        if bottom is None:
            return
        try:
            bottom.setStyle(showValues=bool(is_bottom))
            _apply_pg_axis_font(bottom)
        except Exception:
            pass
        if not is_bottom:
            try:
                bottom.setLabel(text="")
                _apply_pg_axis_font(bottom)
            except Exception:
                pass

    def set_xlim(self, lo, hi):
        """Apply a new xlim to the primary axis. Compatibility-only:
        external callers should prefer ``self._primary_xaxis_ax.set_xlim``.
        """
        primary = self._primary_xaxis_ax
        if primary is None:
            return
        primary.set_xlim(float(lo), float(hi))

    def reset_view_to_data_extents(self):
        """Toolbar Home helper: restore global X (raw union) AND global Y
        (per-channel raw full min/max) in one click.

        Bug 4: the hot-path ``PlotDataItem`` holds ONLY the viewport-clipped
        envelope (``_refresh_visible_data`` ships the xlim-clipped envelope),
        so an ``autoRange()``-based Home computed Y from the clipped window
        and left Y stuck at the previous zoom. We instead read Y from the
        RAW ``channel_data`` arrays.

        Ordering honors pyqt-ui/2026-04-25-flush-after-axis-mutation-not-
        before: set the X union FIRST, flush the debounced refresh so the
        envelope repopulates for the global window, THEN set Y from raw.
        A try/finally tail flush covers every return path so no stale
        debounce frame lands after Home.
        """
        self.disable_interactive_quality()
        try:
            # (1) Set X to the raw union on every handle (seeds the X-master
            # too in overlay mode).
            self._set_xrange_to_data_union()
            # (2) Drain the debounced refresh scheduled by the X mutation so
            # the visible curve holds the global-window envelope.
            try:
                self._flush_pending_refresh()
            except Exception:
                pass
            # (3) Set Y per handle from the RAW channel data (full, finite),
            # not from the clipped PlotDataItem. Each handle hosts exactly
            # one channel (subplot/single: one per row; overlay: one per aux
            # ViewBox), so map handle -> channel via _channel_lines.
            for name, (handle, _line) in self._channel_lines.items():
                row = self.channel_data.get(name)
                if row is None:
                    continue
                try:
                    sig = np.asarray(row[1], dtype=float)
                    finite = sig[np.isfinite(sig)]
                except Exception:
                    continue
                if finite.size == 0:
                    continue
                lo = float(finite.min())
                hi = float(finite.max())
                if not (np.isfinite(lo) and np.isfinite(hi)):
                    continue
                if hi <= lo:
                    # Flat signal: give it a small symmetric pad so the line
                    # is visible rather than a zero-height range.
                    pad = abs(lo) * 0.05 or 1.0
                    lo, hi = lo - pad, hi + pad
                try:
                    handle.set_ylim(lo, hi)
                except Exception:
                    pass
            self._refresh = True
            self.draw_idle()
        finally:
            try:
                self._flush_pending_refresh()
            except Exception:
                pass
            self.schedule_idle_quality()

    def _data_x_union(self):
        bounds = []
        for t, _sig, _color, _unit in self.channel_data.values():
            try:
                arr = np.asarray(t, dtype=float)
                finite = arr[np.isfinite(arr)]
            except Exception:
                finite = np.asarray([])
            if finite.size:
                bounds.append((float(finite.min()), float(finite.max())))
        if not bounds:
            return None
        return (min(lo for lo, _hi in bounds), max(hi for _lo, hi in bounds))

    def _set_xrange_to_data_union(self):
        x_union = self._data_x_union()
        if x_union is None:
            return
        lo, hi = x_union
        # In overlay mode the X-master ViewBox owns the shared X range but
        # is not in axes_list (no curve lives on it); seed its X too so
        # cursor mapping and _current_pixel_width read a real range.
        handles = list(self.axes_list)
        if (
            self._overlay_mode
            and self._x_master_handle is not None
            and self._x_master_handle not in handles
        ):
            handles.append(self._x_master_handle)
        for handle in handles:
            vb = handle.view_box
            did_set = False
            try:
                if vb is not None:
                    vb.blockSignals(True)
                handle.set_xlim(lo, hi)
                did_set = True
            except Exception:
                pass
            finally:
                try:
                    if vb is not None:
                        vb.blockSignals(False)
                except Exception:
                    pass
            if did_set:
                self._sync_x_axis_item_range(handle, lo, hi)
        self._apply_target_x_ticks_to_all_axes()

    def _build_overlay_y_grid(self):
        """Lock X-master ViewBox to Y=[0,1] and populate uniform horizontal
        InfiniteLines that serve as the shared graticule for overlay mode.

        The X-master ViewBox carries no channel data; its Y range is fixed so
        lines placed at k/self._overlay_divisions stay at even screen fractions
        regardless of channel data changes.  The InfiniteLines are added to
        the X-master ViewBox via vb.addItem(), so they are removed automatically
        when _glw.clear() tears down the PlotItem.
        """
        if self._x_master_handle is None:
            return
        vb = getattr(self._x_master_handle, "view_box", None)
        if vb is None:
            return

        # Lock Y to [0, 1]: disable autorange, then set the fixed range.
        try:
            vb.enableAutoRange(axis="y", enable=False)
            vb.setYRange(0.0, 1.0, padding=0)
            vb.setMouseEnabled(x=True, y=False)
        except Exception:
            pass

        for line in list(self._overlay_grid_lines):
            try:
                vb.removeItem(line)
            except Exception:
                pass
        self._overlay_grid_lines = []

        n = max(3, min(20, int(getattr(self, "_overlay_divisions", 8))))
        alpha_int = max(1, min(255, int(round(_OVERLAY_GRID_ALPHA * 255))))
        pen = pg.mkPen(color=(180, 180, 180, alpha_int), width=1)
        lines = []
        for i in range(1, n):
            y_pos = i / n
            line = pg.InfiniteLine(
                pos=y_pos,
                angle=0,          # horizontal
                movable=False,
                pen=pen,
            )
            try:
                vb.addItem(line)
                lines.append(line)
            except Exception:
                pass
        self._overlay_grid_lines = lines

    def _repin_overlay_channel_ticks(self):
        """Frame overlay channels and pin their ticks to the shared graticule."""
        if not getattr(self, "_overlay_mode", False):
            return
        n = max(3, min(20, int(getattr(self, "_overlay_divisions", 8))))
        for handle in list(self.axes_list):
            try:
                lo, hi = handle.get_ylim()
            except Exception:
                continue
            bottom, top, ticks = _frame_to_nice(lo, hi, n)
            try:
                handle.set_ylim(bottom, top)
            except Exception:
                continue
            axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            if axis is None:
                continue
            try:
                axis.setStyle(maxTickLevel=0)
            except Exception:
                pass
            try:
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
            except Exception:
                pass

    def _snap_overlay_channel_to_grid(self, ax):
        """Snap a dragged overlay channel to its current graticule span."""
        if ax is None:
            return
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            return
        span = hi - lo
        if not (math.isfinite(span) and span > 0):
            return
        n = max(3, min(20, int(getattr(self, "_overlay_divisions", 8))))
        per_div = span / n
        if not (math.isfinite(per_div) and per_div > 0):
            return
        bottom = round(lo / per_div) * per_div
        if abs(bottom) < per_div * 1e-10:
            bottom = 0.0
        top = bottom + span
        ticks = [bottom + k * per_div for k in range(n + 1)]
        try:
            ax.set_ylim(bottom, top)
            axis = ax.y_axis_item() if hasattr(ax, "y_axis_item") else None
            if axis is not None:
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
        except Exception:
            pass

    def _stop_snap_anim(self):
        """Stop any in-flight drag-release snap animation."""
        anim = getattr(self, "_snap_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
            self._snap_anim = None

    def _animate_overlay_snap(self, ax):
        """Glide ``ax`` from its dragged position to the nice graticule.

        Keeps the dragged span and snaps ``bottom`` to the nearest grid
        multiple (same target as ``_snap_overlay_channel_to_grid``), but
        eases there over ``_snap_anim_ms`` so the release is not a jump.
        ``_snap_anim_ms <= 0`` (or an already-aligned channel) snaps
        synchronously.
        """
        if ax is None:
            return
        self._stop_snap_anim()
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            return
        span = hi - lo
        if not (math.isfinite(span) and span > 0):
            return
        n = max(3, min(20, int(getattr(self, "_overlay_divisions", 8))))
        per_div = span / n
        if not (math.isfinite(per_div) and per_div > 0):
            return
        bottom = round(lo / per_div) * per_div
        if abs(bottom) < per_div * 1e-10:
            bottom = 0.0
        top = bottom + span
        duration = int(getattr(self, "_snap_anim_ms", 150))
        # No visible move, or animation disabled → snap synchronously.
        if duration <= 0 or abs(bottom - lo) < per_div * 1e-6:
            self._snap_overlay_channel_to_grid(ax)
            return

        # Pin the FINAL graticule ticks once, up front. The labels are the
        # correct snapped integers from the very first frame and never
        # recompute during the glide — only the curve's ylim animates into
        # place, so the numbers do not flicker (2026-06-06 no-tick-flicker).
        ticks = [bottom + k * per_div for k in range(n + 1)]
        try:
            axis = ax.y_axis_item() if hasattr(ax, "y_axis_item") else None
            if axis is not None:
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
        except Exception:
            pass

        start_lo, start_hi = lo, hi
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _on_value(frac):
            try:
                f = float(frac)
            except Exception:
                return
            cur_lo = start_lo + (bottom - start_lo) * f
            cur_hi = start_hi + (top - start_hi) * f
            try:
                ax.set_ylim(cur_lo, cur_hi)  # glide only; ticks already pinned
            except Exception:
                return
            self._refresh = True
            self.draw_idle()

        def _on_finished():
            self._snap_overlay_channel_to_grid(ax)
            self._snap_anim = None
            self._refresh = True
            self.draw_idle()

        anim.valueChanged.connect(_on_value)
        anim.finished.connect(_on_finished)
        self._snap_anim = anim
        anim.start()

    def _apply_overlay_box_zoom_y(self):
        """Re-lock the X-master Y to [0, 1] after a RectMode box-zoom and
        redirect the box's Y span onto the selected channel.

        pyqtgraph's RectMode ``setRange`` ignores ``mouseEnabled`` and pulls
        the X-master Y to the box sub-range, collapsing the fixed k/N
        graticule. The shared X stays as the base class zoomed it; here we
        read the box's Y fraction (in [0, 1] graticule space), restore the
        grid, and frame the selected channel into that fraction.
        """
        if not getattr(self, "_overlay_mode", False):
            return
        master = self._x_master_handle
        if master is None:
            return
        vb = getattr(master, "view_box", None)
        if vb is None:
            return
        try:
            y0, y1 = vb.viewRange()[1]
        except Exception:
            return
        already_locked = abs(y0 - 0.0) < 1e-9 and abs(y1 - 1.0) < 1e-9
        if not already_locked:
            try:
                vb.enableAutoRange(axis="y", enable=False)
                vb.setYRange(0.0, 1.0, padding=0)
            except Exception:
                pass
        sel = self._selected_overlay_axes()
        if sel is None or already_locked:
            # No channel to receive the Y zoom (or the box had no Y span):
            # X-only zoom, graticule already restored above.
            self._refresh = True
            self.draw_idle()
            return
        f0 = max(0.0, min(1.0, min(y0, y1)))
        f1 = max(0.0, min(1.0, max(y0, y1)))
        if f1 - f0 < 1e-6:
            self._refresh = True
            self.draw_idle()
            return
        try:
            clo, chi = sel.get_ylim()
        except Exception:
            return
        cspan = chi - clo
        if not (math.isfinite(cspan) and cspan > 0):
            return
        new_lo = clo + f0 * cspan
        new_hi = clo + f1 * cspan
        n = max(3, min(20, int(getattr(self, "_overlay_divisions", 8))))
        bottom, top, ticks = _frame_to_nice(new_lo, new_hi, n)
        try:
            sel.set_ylim(bottom, top)
            axis = sel.y_axis_item() if hasattr(sel, "y_axis_item") else None
            if axis is not None:
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
        except Exception:
            pass
        self._refresh = True
        self.draw_idle()

    def _teardown_overlay_aux_viewboxes(self):
        """Remove every overlay aux ViewBox, its child curves, and the
        ch3+ appended right ``AxisItem``s from the scene.

        pyqtgraph's ``GraphicsLayout.clear()`` only removes items that were
        registered via ``addItem`` (the PlotItems). Overlay aux ViewBoxes
        are attached top-level via ``primary_plot.scene().addItem(aux_vb)``
        (``_add_overlay_axis_handle``) and every right axis (ch2+) via
        ``primary_plot.layout.addItem(axis_item, ...)``, so both leak as
        ghost curves/axes on every rebuild unless removed explicitly here.
        Mirrors ``_teardown_inside_labels`` (the same scene-leak class).

        ch1 reuses the PlotItem's built-in LEFT axis (removed with the
        PlotItem by ``_glw.clear()``); every right channel (ch2+) is a fresh
        appended ``AxisItem`` and needs explicit removal. Iterating all of
        ``_overlay_aux_axes`` and guarding each ``removeItem`` is safe and
        idempotent (the built-in left axis ignores both removals harmlessly).
        """
        for aux_vb in list(self._overlay_aux_viewboxes):
            try:
                scene = aux_vb.scene()
                if scene is not None:
                    scene.removeItem(aux_vb)
            except Exception:
                pass
        for ax_item in list(self._overlay_aux_axes):
            # Drop the appended right axes from the PlotItem layout first,
            # then from the scene. Built-in left/right axes (ch1/ch2) are
            # owned by the PlotItem and ignore both removals harmlessly.
            primary = self._primary_xaxis_ax
            try:
                if primary is not None and primary.plot_item is not None:
                    primary.plot_item.layout.removeItem(ax_item)
            except Exception:
                pass
            try:
                scene = ax_item.scene()
                if scene is not None:
                    scene.removeItem(ax_item)
            except Exception:
                pass

    def clear(self):
        """Tear down the chart. Mirrors TimeDomainCanvas.clear."""
        # Drop xrange listener before we wipe the axes it points at.
        self._disconnect_xrange_listener()
        self._disconnect_overlay_view_sync()
        # Remove overlay aux ViewBoxes + ch3+ appended axes from the scene
        # BEFORE _glw.clear() (which only drops layout PlotItems) and BEFORE
        # we zero _overlay_aux_viewboxes/_overlay_aux_axes below — otherwise
        # the ghost curves leak (Bug 2). Uses _primary_xaxis_ax for the
        # PlotItem layout, so it must run before that is nulled.
        self._teardown_overlay_aux_viewboxes()
        self._teardown_inside_labels()
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        try:
            self._idle_aa_timer.stop()
        except Exception:
            pass
        try:
            self._resize_settle_timer.stop()
        except Exception:
            pass
        self._refresh_pending = False
        self._idle_aa_on = False
        self._idle_aa_density_allowed = False
        # Rebuild changes the curve set / point counts → re-seed the
        # cold-start dead-band fix so the next decision uses the OFF
        # threshold rather than inheriting a stale allowance (Fix C).
        self._idle_aa_density_seeded = False

        # Strip everything from the GraphicsLayoutWidget.
        try:
            self._glw.clear()
        except Exception:
            pass

        self.axes_list = []
        self._channel_lines = {}
        self._channel_view_state_lines = {}
        self.channel_data = {}
        self._channel_data_id = {}
        self._channel_is_monotonic = {}
        self._primary_xaxis_ax = None
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._overlay_mode = False
        self._refresh = True
        # T6 — drop overlay selection + subplot label scaffolding so the
        # next plot_channels build starts from a clean slate. Inside-label
        # scene items were already removed by _teardown_inside_labels()
        # above (pg.GLW.clear() does NOT remove scene().addItem() items).
        self._selected_overlay_channel = None
        self._overlay_y_drag_start = None
        self._overlay_dragging = False
        self._x_master_handle = None
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        # InfiniteLines were added via vb.addItem() on the X-master ViewBox,
        # which is part of the PlotItem already destroyed by _glw.clear() above.
        self._overlay_grid_lines = []
        self._subplot_label_specs = []
        self._cursor_line_items = []
        self._cursor_a_items = []
        self._cursor_b_items = []
        self._dual_cursor_extreme_markers = []
        # Cursor placement is NOT cleared here — full_reset / reset_cursor_state
        # do that. Mirror TimeDomainCanvas.clear's behavior.

    def full_reset(self):
        """Clear chart AND cursor state. Use on file close."""
        self.clear()
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._cursor_visible = False
        self._dual = False
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._last_t = 0
        self.draw_idle()

    def set_cursor_visible(self, v):
        """Toggle single-cursor visibility."""
        self._cursor_visible = bool(v)
        if not self._cursor_visible:
            self._hide_cursor_items(self._cursor_line_items)
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self._hide_dual_cursor_extreme_markers()
            self.draw_idle()

    def set_dual_cursor_mode(self, en):
        """Toggle dual-cursor mode."""
        self._dual = bool(en)
        if not en:
            self._ax = None
            self._bx = None
            self._placing = "A"
            self._refresh = True
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self._hide_dual_cursor_extreme_markers()
            self.dual_cursor_info.emit("")
            self.draw_idle()

    def reset_cursor_state(self):
        """Drop dual-cursor placement and request a redraw.

        Compatibility seam called by ``MainWindow._reset_cursors``. The
        ordering (mutate fields, then redraw) follows
        ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``.
        """
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._refresh = True
        self._hide_cursor_items(self._cursor_line_items)
        self._hide_cursor_items(self._cursor_a_items)
        self._hide_cursor_items(self._cursor_b_items)
        self._hide_dual_cursor_extreme_markers()
        self.dual_cursor_info.emit("")
        self.draw_idle()

    def draw_idle(self):
        """No-op equivalent of matplotlib FigureCanvas.draw_idle.

        Pyqtgraph re-renders automatically on data/range changes; we
        only need to nudge the scene so post-Apply paint passes flush.
        """
        # Avoid an explicit repaint here — pyqtgraph's scene already
        # invalidates lazily. The cursor/span overlays will need an
        # update() pass once T6 wires them.
        try:
            self._glw.update()
        except Exception:
            pass

    def draw(self):
        """Synchronous redraw alias (matplotlib FigureCanvas parity).

        MainWindow.plot_time() calls ``self.canvas_time.draw()`` on the
        no-files / no-checked-channels / no-plottable-data early-return
        paths. Pyqtgraph's scene already invalidates lazily, so this is
        a thin alias over ``draw_idle()`` — no flush bookkeeping needed
        per ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``
        (draw_idle handles scheduling; this is a parity seam, not a
        mutator).
        """
        self.draw_idle()

    # ------------------------------------------------------------------
    # Cursor item helpers.
    # ------------------------------------------------------------------

    def _hide_cursor_items(self, items):
        for item in items or []:
            try:
                item.setVisible(False)
            except Exception:
                pass

    def _ensure_cursor_items(self, attr_name, *, color, width=1.0, style=Qt.SolidLine):
        items = getattr(self, attr_name, [])
        if len(items) == len(self.axes_list):
            return items
        self._remove_cursor_items(items)
        pen = pg.mkPen(color=color, width=width, style=style)
        new_items = []
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            line = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=pen)
            line.setZValue(1000)
            line.setVisible(False)
            try:
                vb.addItem(line, ignoreBounds=True)
                new_items.append(line)
            except Exception:
                pass
        setattr(self, attr_name, new_items)
        return new_items

    def _remove_cursor_items(self, items):
        for item in items or []:
            try:
                parent = item.parentItem()
                if parent is not None and hasattr(parent, "removeItem"):
                    parent.removeItem(item)
            except Exception:
                pass

    def _set_cursor_items_pos(self, items, x):
        for item in items or []:
            try:
                item.setValue(float(x))
                item.setVisible(True)
            except Exception:
                pass

    def _ensure_dual_cursor_extreme_markers(self):
        markers = getattr(self, "_dual_cursor_extreme_markers", [])
        if len(markers) == len(self.axes_list):
            return markers
        for marker in markers or []:
            try:
                marker.setVisible(False)
            except Exception:
                pass
        new_markers = []
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            marker = pg.ScatterPlotItem(size=10)
            marker.setZValue(1100)
            marker.setVisible(False)
            try:
                vb.addItem(marker, ignoreBounds=True)
                new_markers.append(marker)
            except Exception:
                pass
        self._dual_cursor_extreme_markers = new_markers
        return new_markers

    def _hide_dual_cursor_extreme_markers(self):
        for marker in getattr(self, "_dual_cursor_extreme_markers", []) or []:
            try:
                marker.setData([], [])
                marker.setVisible(False)
            except Exception:
                pass

    def _update_dual_cursor_extreme_markers(self, points_by_channel):
        markers = self._ensure_dual_cursor_extreme_markers()
        point_map = {
            name: (min_x, min_y, max_x, max_y)
            for name, min_x, min_y, max_x, max_y in points_by_channel
        }
        for marker, handle in zip(markers, self.axes_list):
            name = self._channel_name_for_handle(handle)
            points = point_map.get(name)
            try:
                if points is None:
                    marker.setData([], [])
                    marker.setVisible(False)
                    continue
                min_x, min_y, max_x, max_y = points
                marker.setData(
                    [min_x, max_x],
                    [min_y, max_y],
                    symbol="o",
                    size=10,
                    pen=[
                        pg.mkPen("#ffffff", width=1.2),
                        pg.mkPen("#ffffff", width=1.2),
                    ],
                    brush=[
                        pg.mkBrush("#16a34a"),
                        pg.mkBrush("#dc2626"),
                    ],
                )
                marker.setVisible(True)
            except Exception:
                pass

    def _cursor_data_x_from_viewport_pos(self, viewport_pos):
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        handle = self._axis_handle_at_scene_pos(scene_pos)
        if handle is None or handle.view_box is None:
            return None
        try:
            data_pos = handle.view_box.mapSceneToView(scene_pos)
            x = float(data_pos.x())
        except Exception:
            return None
        if not np.isfinite(x):
            return None
        return x

    def _handle_cursor_mouse_move(self, event_or_pos):
        if not self._cursor_visible:
            return False
        try:
            if event_or_pos.buttons() & Qt.LeftButton:
                return False
            viewport_pos = event_or_pos.pos()
        except Exception:
            viewport_pos = event_or_pos
        x = self._cursor_data_x_from_viewport_pos(viewport_pos)
        if x is None:
            return False
        now = _time.monotonic() * 1000
        if now - self._last_t < 33:
            return True
        self._last_t = now
        if self._dual:
            hover_items = self._ensure_cursor_items(
                "_cursor_line_items", color="#64748b", width=1.0, style=Qt.DotLine
            )
            self._set_cursor_items_pos(hover_items, x)
            # Dual cursor stats depend only on the fixed A/B positions; A/B
            # placement already emits them, so hover only moves the guide line.
        else:
            items = self._ensure_cursor_items(
                "_cursor_line_items", color="#111827", width=1.0
            )
            self._set_cursor_items_pos(items, x)
            self._emit_single_cursor_html(x)
        self.draw_idle()
        return True

    def _handle_cursor_mouse_press(self, event):
        if not (self._cursor_visible and self._dual):
            return False
        try:
            if event.button() != Qt.LeftButton:
                return False
        except Exception:
            return False
        x = self._cursor_data_x_from_viewport_pos(event.pos())
        if x is None:
            return False
        if self._placing == "A":
            self._ax = x
            self._placing = "B"
            a_items = self._ensure_cursor_items(
                "_cursor_a_items", color="#2563eb", width=1.1
            )
            self._set_cursor_items_pos(a_items, x)
        else:
            self._bx = x
            self._placing = "A"
            b_items = self._ensure_cursor_items(
                "_cursor_b_items", color="#dc2626", width=1.1
            )
            self._set_cursor_items_pos(b_items, x)
        self._emit_dual_cursor_html()
        self.draw_idle()
        return True

    # ------------------------------------------------------------------
    # Overlay selection + Y-drag mouse wiring (Problem 2). Ports
    # canvases.py:_select_overlay_channel_from_event (850-895) and
    # _update_overlay_y_drag (916) onto the pyqtgraph eventFilter, driven
    # by real Qt events rather than the matplotlib callback dispatcher.
    # ------------------------------------------------------------------

    def _scene_y_from_viewport_pos(self, viewport_pos):
        """Map a viewport-pixel ``QPoint`` to a scene Y coordinate.

        The Y-drag helpers work in a single monotonic pixel axis; scene Y
        (top-origin, increasing downward) is used consistently for both
        the begin-capture and apply steps so the delta is well-defined.
        Returns ``None`` on failure.
        """
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None:
            return None
        try:
            return float(scene_pos.y())
        except Exception:
            return None

    def _select_overlay_channel_from_scene_pos(self, scene_pos):
        """Resolve which overlay channel a press at ``scene_pos`` selects.

        Returns the nearest curve's channel name when a sample is within
        ``_overlay_pick_radius_px`` of the press, else ``None`` so a blank
        in-plot click deselects.

        Bug 5: the old ViewBox-rect axis-hit fallback is removed. In overlay
        mode every aux ViewBox's ``sceneBoundingRect`` spans the FULL plot
        rect (``_sync_overlay_aux_viewboxes`` sets them all to the X-master's
        geometry), so ``_axis_handle_at_scene_pos`` returned channel 1 for
        ANY in-plot point — making a genuine blank click impossible to
        deselect. The real axis gutter sits OUTSIDE the plot rect anyway, so
        the rect test never identified a true gutter hit.
        """
        if scene_pos is None:
            return None

        best_name = None
        best_dist = float("inf")
        try:
            px = float(scene_pos.x())
            py = float(scene_pos.y())
        except Exception:
            return None
        for name, (handle, line) in self._channel_lines.items():
            vb = handle.view_box
            if vb is None:
                continue
            pdi = line.plot_data_item
            try:
                xdata, ydata = pdi.getData()
            except Exception:
                xdata = ydata = None
            if xdata is None or ydata is None:
                continue
            xdata = np.asarray(xdata, dtype=float)
            ydata = np.asarray(ydata, dtype=float)
            n = min(xdata.size, ydata.size)
            if n == 0:
                continue
            xdata = xdata[:n]
            ydata = ydata[:n]
            # Drop NaN-gap samples so the pixel mapping below stays finite
            # (arraytoqpath-not-byte-identical lesson: NaN gaps + single
            # points need explicit handling).
            finite = np.isfinite(xdata) & np.isfinite(ydata)
            if not finite.any():
                continue
            xdata = xdata[finite]
            ydata = ydata[finite]
            if n > 3000:
                step = max(1, xdata.size // 3000)
                xdata = xdata[::step]
                ydata = ydata[::step]
            # Map each data point to scene pixels via this channel's VB.
            try:
                scene_pts = self._map_view_points_to_scene(vb, xdata, ydata)
            except Exception:
                continue
            if scene_pts is None or scene_pts.size == 0:
                continue
            dist = float(
                np.min(
                    np.hypot(scene_pts[:, 0] - px, scene_pts[:, 1] - py)
                )
            )
            if dist < best_dist:
                best_dist = dist
                best_name = name
        if best_name is not None and best_dist <= self._overlay_pick_radius_px:
            return best_name
        # No curve within the pick radius → blank in-plot click → deselect.
        return None

    def _map_view_points_to_scene(self, view_box, xdata, ydata):
        """Map arrays of (x, y) view coordinates to scene pixel coords.

        Returns an ``(n, 2)`` float array of scene (x, y) or ``None``. Uses
        the ViewBox's view→scene transform via ``mapViewToScene`` per
        point. A single point is handled correctly (n>=1).
        """
        try:
            from PyQt5.QtCore import QPointF
        except Exception:
            return None
        pts = np.empty((xdata.size, 2), dtype=float)
        ok = 0
        for i in range(xdata.size):
            try:
                sp = view_box.mapViewToScene(QPointF(float(xdata[i]), float(ydata[i])))
                pts[ok, 0] = float(sp.x())
                pts[ok, 1] = float(sp.y())
                ok += 1
            except Exception:
                continue
        if ok == 0:
            return None
        return pts[:ok]

    def _channel_name_for_handle(self, handle):
        for name, (axis_handle, _line) in self._channel_lines.items():
            if axis_handle is handle:
                return name
        return None

    def _overlay_axis_handle_at_scene_pos(self, scene_pos):
        """Return the overlay channel whose Y-axis gutter contains scene_pos."""
        if scene_pos is None:
            return None
        handles = list(self.axes_list)
        selected = self._selected_overlay_axes()
        if selected is not None:
            handles = [selected] + [h for h in handles if h is not selected]
        for handle in handles:
            axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            if axis is None:
                continue
            try:
                rect = axis.sceneBoundingRect()
                if rect.contains(scene_pos):
                    return handle
            except Exception:
                continue
        return None

    def _set_x_master_mouse_enabled(self, enabled):
        """Toggle the X-master ViewBox's mouse interaction.

        X is enabled in normal overlay interaction so users can pan time.
        Y stays disabled permanently because the X-master owns the fixed
        [0, 1] graticule, not channel data.
        """
        master = self._x_master_handle
        if master is None:
            return
        vb = master.view_box
        if vb is None:
            return
        try:
            vb.setMouseEnabled(x=bool(enabled), y=False)
        except Exception:
            pass

    def _press_view_box_in_rect_mode(self, scene_pos):
        """Return True when the ViewBox under ``scene_pos`` (or, on a miss,
        the primary/X-master ViewBox) is in box-zoom (RectMode).

        Fix A (2026-05-31 overlay-aa-interaction-fixes): the overlay press
        handler must yield to pyqtgraph's rubber band in box-zoom mode so a
        press tight on a curve still draws a zoom rectangle instead of
        being swallowed as a curve-select + Y-drag. We read
        ``vb.state['mouseMode']`` directly — no mouse-mode controller
        dependency — and compare against ``pg.ViewBox.RectMode`` (==1).
        """
        vb = None
        handle = self._axis_handle_at_scene_pos(scene_pos)
        if handle is not None:
            vb = handle.view_box
        if vb is None and self._primary_xaxis_ax is not None:
            vb = self._primary_xaxis_ax.view_box
        if vb is None:
            return False
        try:
            return vb.state.get("mouseMode") == pg.ViewBox.RectMode
        except Exception:
            return False

    def _handle_overlay_mouse_press(self, event):
        """Overlay-mode left-press: select nearest channel + begin Y-drag,
        or deselect on a blank-area click. No-op outside overlay mode or
        in cursor mode (cursor takes precedence, matching canvases.py:853).
        Returns ``True`` when the gesture was consumed.

        In box-zoom (RectMode) the handler returns ``False`` so the press
        falls through to pyqtgraph and the rubber band starts (Fix A); the
        nearest-curve select + Y-drag is kept ONLY in pan (PanMode).
        """
        if not self._overlay_mode or self._cursor_visible:
            return False
        try:
            if event.button() != Qt.LeftButton:
                return False
            viewport_pos = event.pos()
        except Exception:
            return False
        # A new interaction interrupts any in-flight drag-release glide.
        self._stop_snap_anim()
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        # Fix A: in box-zoom mode let the rubber band own the left press.
        if self._press_view_box_in_rect_mode(scene_pos):
            return False
        axis_handle = self._overlay_axis_handle_at_scene_pos(scene_pos)
        if axis_handle is not None:
            name = self._channel_name_for_handle(axis_handle)
            if name is None:
                return False
            self.select_overlay_channel(name)
            start_y = self._scene_y_from_viewport_pos(viewport_pos)
            if start_y is not None:
                self._begin_overlay_y_drag_at(start_y_px=start_y)
                self._overlay_dragging = True
                self.disable_interactive_quality()
                self._set_x_master_mouse_enabled(False)
            return True
        name = self._select_overlay_channel_from_scene_pos(scene_pos)
        if name is None:
            # Blank-area click → deselect (emits overlay_channel_selected(None)
            # only when something was selected, via select_overlay_channel).
            if self._selected_overlay_channel is not None:
                self.select_overlay_channel(None)
                return True
            return False
        self.select_overlay_channel(name)
        # Begin the Y-drag from this scene Y; disable the X-master pan so
        # the drag is Y-only.
        start_y = self._scene_y_from_viewport_pos(viewport_pos)
        if start_y is not None:
            self._begin_overlay_y_drag_at(start_y_px=start_y)
            self._overlay_dragging = True
            self.disable_interactive_quality()
            self._set_x_master_mouse_enabled(False)
        return True

    def _handle_overlay_mouse_move(self, event):
        """Apply a Y-drag while the left button is held during an overlay
        drag. Returns ``True`` when the drag consumed the move."""
        if not self._overlay_dragging:
            return False
        try:
            if not (event.buttons() & Qt.LeftButton):
                return False
            viewport_pos = event.pos()
        except Exception:
            return False
        cur_y = self._scene_y_from_viewport_pos(viewport_pos)
        if cur_y is None:
            return False
        self._apply_overlay_y_drag_at(current_y_px=cur_y)
        return True

    def _handle_overlay_mouse_release(self, event):
        """End a live overlay Y-drag and re-enable the X-master pan."""
        if not self._overlay_dragging:
            return False
        self._overlay_dragging = False
        self._overlay_y_drag_start = None
        self._set_x_master_mouse_enabled(True)
        # Glide the selected channel to the nearest grid division (animated
        # so the release is not a jump; falls back to a synchronous snap
        # when _snap_anim_ms <= 0 or the channel is already aligned).
        selected_ax = self._selected_overlay_axes()
        self._animate_overlay_snap(selected_ax)
        self.schedule_idle_quality()
        return True

    def get_statistics(self, time_range=None):
        """Read RAW arrays from ``channel_data`` (design §4.2 invariant).

        Identical to ``TimeDomainCanvas.get_statistics`` so the W0
        contract holds.
        """
        stats = {}
        for ch, (t, sig, _color, unit) in self.channel_data.items():
            if time_range is not None:
                lo, hi = time_range
                m = (t >= lo) & (t <= hi)
                s = sig[m]
            else:
                s = sig
            if len(s):
                stats[ch] = {
                    "min": float(np.min(s)),
                    "max": float(np.max(s)),
                    "mean": float(np.mean(s)),
                    "rms": float(np.sqrt(np.mean(s ** 2))),
                    "std": float(np.std(s)),
                    "p2p": float(np.ptp(s)),
                    "unit": unit,
                }
        return stats

    def enable_span_selector(self, cb):
        """Store the callback; do NOT auto-enable the drag-to-select.

        Design §4.2 invariant + main_window.py:993-996: the always-on
        SpanSelector was retired. We keep the method as a compatibility
        seam so callers don't AttributeError, but no drag handler is
        wired here — Task 6 will add an opt-in gesture if and only if
        the design requires one.
        """
        self._span_callback = cb
        # Intentionally no widget installed. self.span_selector stays None.

    def set_tick_density(self, x, y):
        """Apply inspector-controlled tick density to PG axes.

        Use pyqtgraph's adaptive density knob instead of explicit
        ``setTickSpacing``. Fixed major/minor spacing is range-stale after
        auto-range and makes the minor level labelable, which can produce dense
        tick-label piles and very slow repaint on channel rebuilds.
        """
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except Exception:
            x_n, y_n = self._tick_density
        self._tick_density = (x_n, y_n)
        if self._overlay_mode:
            self._overlay_divisions = max(3, min(20, int(y_n)))
            self._build_overlay_y_grid()
            self._repin_overlay_channel_ticks()
            self._apply_target_x_ticks_to_all_axes()
            self._refresh = True
            self.draw_idle()
            return
        self._apply_tick_density_to_all_axes()
        # Tick density changes tick-label text → left-axis auto-width, which
        # re-skews subplot left edges; re-unify after applying density.
        self._unify_subplot_left_axis_widths()
        self._unify_subplot_bottom_axis_heights()
        self._refresh = True
        self.draw_idle()

    def _apply_tick_density_to_all_axes(self):
        _x_n, y_n = self._tick_density
        y_density = max(0.35, min(3.0, float(y_n) / 6.0))
        self._apply_target_x_ticks_to_all_axes()
        for handle in self.axes_list:
            y_axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            self._apply_axis_tick_density(y_axis, y_density)

    def _apply_target_x_ticks_to_all_axes(self):
        seen = set()
        for handle in self._x_tick_axis_handles():
            axis = handle.x_axis_item() if hasattr(handle, "x_axis_item") else None
            if axis is None:
                continue
            key = id(axis)
            if key in seen:
                continue
            seen.add(key)
            self._apply_target_x_ticks(axis, handle)

    def _x_tick_axis_handles(self):
        handles = list(self.axes_list)
        if self._overlay_mode and self._x_master_handle is not None:
            handles.insert(0, self._x_master_handle)
        return handles

    def _apply_target_x_ticks(self, axis, handle):
        try:
            lo, hi = handle.get_xlim()
            axis_width = float(axis.size().width())
        except Exception:
            self._reset_x_ticks_to_adaptive(axis)
            return
        ticks = self._compute_target_x_ticks(axis, float(lo), float(hi), axis_width)
        if not ticks:
            self._reset_x_ticks_to_adaptive(axis)
            return
        try:
            axis.setStyle(maxTickLevel=0)
            axis.setTicks([ticks, []])
        except Exception:
            self._reset_x_ticks_to_adaptive(axis)

    def _reset_x_ticks_to_adaptive(self, axis):
        try:
            axis.setTicks(None)
        except Exception:
            pass
        self._apply_axis_tick_density(
            axis,
            max(0.35, min(3.0, float(self._tick_density[0]) / 10.0)),
        )

    def _compute_target_x_ticks(self, axis, lo, hi, axis_width):
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            return []
        if axis_width <= 1.0:
            return []

        target = max(_TARGET_X_TICK_MIN_COUNT, int(self._tick_density[0]))
        raw_step = (hi - lo) / max(1, target - 1)
        candidates = []
        for step in self._nice_x_tick_steps(raw_step):
            values = self._x_tick_values_for_step(lo, hi, step)
            if len(values) < _TARGET_X_TICK_MIN_COUNT:
                continue
            labels = self._format_x_tick_labels(axis, values, step)
            fit = self._fit_x_tick_labels(values, labels, lo, hi, axis_width)
            if not fit:
                continue
            fit_values, fit_labels = fit
            candidates.append((
                abs(len(fit_values) - target),
                -len(fit_values),
                abs(math.log(step / raw_step)) if raw_step > 0 else 0.0,
                step,
                fit_values,
                fit_labels,
            ))

        if not candidates:
            return []
        _distance, _neg_count, _nice_distance, _step, values, labels = min(candidates)
        return [(float(value), str(label)) for value, label in zip(values, labels)]

    def _nice_x_tick_steps(self, raw_step):
        if not np.isfinite(raw_step) or raw_step <= 0:
            return []
        exponent = math.floor(math.log10(raw_step))
        bases = []
        for exp in range(exponent - 2, exponent + 4):
            scale = 10.0 ** exp
            for factor in _TARGET_X_TICK_NICE_FACTORS:
                step = factor * scale
                if step > 0:
                    bases.append(step)
        return sorted(set(bases), key=lambda step: abs(math.log(step / raw_step)))

    def _x_tick_values_for_step(self, lo, hi, step):
        start = math.ceil(lo / step) * step
        values = []
        value = start
        guard = 0
        while value <= hi + step * 1e-9 and guard < 500:
            if value >= lo - step * 1e-9:
                values.append(0.0 if abs(value) < step * 1e-10 else float(value))
            value += step
            guard += 1
        return values

    def _format_x_tick_labels(self, axis, values, spacing):
        try:
            return axis.tickStrings(values, getattr(axis, "scale", 1.0), spacing)
        except Exception:
            return [f"{value:g}" for value in values]

    def _fit_x_tick_labels(self, values, labels, lo, hi, axis_width):
        metrics = QFontMetrics(_pg_chart_font(9))
        span = hi - lo
        fit_values = []
        fit_labels = []
        previous_right = None
        for value, label in zip(values, labels):
            x = (float(value) - lo) / span * axis_width
            text = str(label)
            try:
                width = float(metrics.horizontalAdvance(text))
            except AttributeError:  # pragma: no cover - older Qt fallback
                width = float(metrics.width(text))
            left = x - width / 2.0
            right = x + width / 2.0
            if left < _TARGET_X_TICK_EDGE_PAD_PX:
                continue
            if right > axis_width - _TARGET_X_TICK_EDGE_PAD_PX:
                continue
            if previous_right is not None and left - previous_right < _TARGET_X_TICK_MIN_GAP_PX:
                return None
            fit_values.append(float(value))
            fit_labels.append(text)
            previous_right = right
        if len(fit_values) < _TARGET_X_TICK_MIN_COUNT:
            return None
        return fit_values, fit_labels

    def _apply_axis_tick_density(self, axis, density):
        if axis is None:
            return
        set_style = getattr(axis, "setStyle", None)
        if callable(set_style):
            try:
                set_style(maxTickLevel=0)
            except Exception:
                pass
        reset_spacing = getattr(axis, "setTickSpacing", None)
        if callable(reset_spacing):
            try:
                reset_spacing()
            except Exception:
                pass
        set_density = getattr(axis, "setTickDensity", None)
        if callable(set_density):
            try:
                set_density(float(density))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Chart-options dialog (Fix 1: parity with the matplotlib path's
    # canvases.py:_open_chart_options_for_axes + dblclick handler).
    # ------------------------------------------------------------------

    def open_chart_options_dialog(self, parent=None):
        """Open the chart-options dialog for the active/primary axis.

        Wired to ``_ChartCard.open_chart_options()`` via the toolbar
        图表选项 button — the matplotlib canvas exposes the identically
        named method (canvases.py:593), and ``_ChartCard`` does
        ``getattr(self.canvas, 'open_chart_options_dialog', None)``; once
        this exists the button stops returning ``False`` on the PG canvas.

        Resolves the axis to drive (preferring the last double-clicked
        axis, then the primary), wraps it in its ``PgAxisHandle`` (already
        the live form in ``axes_list``), and hands it to
        ``_axis_interaction.edit_chart_options_dialog`` which T3 made
        handle-aware. Returns the dialog's truthy result.
        """
        handle = self._resolve_active_axis_handle()
        if handle is None:
            return False
        return self._open_chart_options_for_handle(handle, parent=parent)

    def _resolve_active_axis_handle(self):
        """Return the ``PgAxisHandle`` the toolbar button should target.

        Prefer the remembered (last double-clicked) handle when it is
        still live, else the primary axis, else the first in
        ``axes_list`` (mirrors canvases.py:_first_live_axes preference
        order).
        """
        remembered = self._chart_options_ax
        if remembered is not None and remembered in self.axes_list:
            return remembered
        if self._primary_xaxis_ax is not None and self._primary_xaxis_ax in self.axes_list:
            return self._primary_xaxis_ax
        return self.axes_list[0] if self.axes_list else None

    def _open_chart_options_for_handle(self, handle, parent=None):
        """Open the chart-options dialog for ``handle`` (a ``PgAxisHandle``).

        Guards against a double-open from a fast double-click via
        ``_chart_options_opening`` (pyqt-ui/2026-04-26-popover-accept-
        deactivate-race). Records the handle as the remembered axis so a
        following toolbar-button open targets the same subplot, then
        delegates to the handle-aware dialog entry point.
        """
        if self._chart_options_opening:
            return False
        if handle is None or handle not in self.axes_list:
            return False
        from . import _axis_interaction

        self._chart_options_ax = handle
        # Releasing any latched pan/zoom drag state so the modal does not
        # leave the ViewBox mid-drag (parity with matplotlib's
        # _clear_canvas_pointer_state). The PG canvas has no
        # _mouse_button_pressed flag, but it does carry overlay-drag
        # bookkeeping — drop it so the dialog cannot resume a stale drag.
        self._overlay_y_drag_start = None
        self._chart_options_opening = True
        try:
            target_parent = parent if parent is not None else self.window()
            return bool(_axis_interaction.edit_chart_options_dialog(target_parent, handle))
        finally:
            self._chart_options_opening = False

    def eventFilter(self, obj, event):
        """Intercept a left double-click on the GraphicsLayoutWidget's
        viewport and open the chart-options dialog for the subplot under
        the cursor.

        The matplotlib path keys on ``event.button == 1 and
        event.dblclick`` (canvases.py:1370); the QWidget analogue is a
        ``QEvent.MouseButtonDblClick`` with ``button() == LeftButton``. We
        map the viewport pixel position into the scene so the subplot
        hit-test (``_axis_handle_at_scene_pos``) stays accurate. A miss
        (double-click in the axis-label gutter) falls back to the
        active/primary axis so the gesture is never a dead click.
        """
        try:
            if event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._handle_viewport_double_click(event.pos())
                    # Return False so the GraphicsView still processes the
                    # event for its own bookkeeping; we do not consume it.
            elif event.type() == QEvent.MouseButtonPress:
                # Overlay selection / Y-drag begin takes precedence over
                # cursor placement, but only outside cursor mode (cursor
                # mode wins, matching canvases.py:853). _handle_overlay_
                # mouse_press is a no-op outside overlay mode.
                if self._handle_overlay_mouse_press(event):
                    return True
                if self._handle_cursor_mouse_press(event):
                    return True
            elif event.type() == QEvent.MouseMove:
                if self._handle_overlay_mouse_move(event):
                    return True
                if self._handle_cursor_mouse_move(event):
                    return True
            elif event.type() == QEvent.MouseButtonRelease:
                if self._handle_overlay_mouse_release(event):
                    return True
                self.schedule_idle_quality()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _handle_viewport_double_click(self, viewport_pos):
        """Resolve the subplot under ``viewport_pos`` (a widget-pixel
        ``QPoint``) and open the chart-options dialog for it."""
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        handle = self._axis_handle_at_scene_pos(scene_pos)
        if handle is None:
            handle = self._resolve_active_axis_handle()
        if handle is None:
            return
        self._open_chart_options_for_handle(handle)

    def _viewport_pos_to_scene(self, viewport_pos):
        """Map a viewport-pixel ``QPoint`` to a scene ``QPointF`` via the
        GraphicsView's ``mapToScene``. Returns ``None`` on failure."""
        try:
            return self._glw.mapToScene(viewport_pos)
        except Exception:
            return None

    def _axis_handle_at_scene_pos(self, scene_pos):
        """Return the ``PgAxisHandle`` whose ViewBox contains ``scene_pos``.

        Iterates ``axes_list`` and tests each ViewBox's
        ``sceneBoundingRect`` (verified present on pyqtgraph 0.14.0
        ViewBox). Returns ``None`` when the click is outside every plot
        area (e.g. in the axis-label gutter) so the caller can fall back
        to the active axis.
        """
        if scene_pos is None:
            return None
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            try:
                rect = vb.sceneBoundingRect()
            except Exception:
                continue
            try:
                if rect.contains(scene_pos):
                    return handle
            except Exception:
                continue
        return None

    def _axis_handle_for_view_box(self, view_box):
        if view_box is None:
            return None
        for handle in self.axes_list:
            if handle.view_box is view_box:
                return handle
        return None

    def _sync_overlay_aux_viewboxes(self):
        if not self._overlay_aux_viewboxes or self._primary_xaxis_ax is None:
            return
        primary_vb = self._primary_xaxis_ax.view_box
        if primary_vb is None:
            return
        try:
            rect = primary_vb.sceneBoundingRect()
        except Exception:
            return
        for aux_vb in list(self._overlay_aux_viewboxes):
            try:
                aux_vb.setGeometry(rect)
            except Exception:
                continue
            try:
                xlo, xhi = self._primary_xaxis_ax.get_xlim()
                aux_vb.setXRange(float(xlo), float(xhi), padding=0)
            except Exception:
                pass

    def _connect_overlay_view_sync(self):
        self._disconnect_overlay_view_sync()
        if self._primary_xaxis_ax is None or not self._overlay_aux_viewboxes:
            return
        primary_vb = self._primary_xaxis_ax.view_box
        if primary_vb is None or not hasattr(primary_vb, "sigResized"):
            return

        def _handler(*_args):
            self._sync_overlay_aux_viewboxes()

        try:
            primary_vb.sigResized.connect(_handler)
            self._overlay_view_sync_conns.append((primary_vb, _handler))
        except Exception:
            pass

    def _disconnect_overlay_view_sync(self):
        for vb, handler in self._overlay_view_sync_conns:
            try:
                vb.sigResized.disconnect(handler)
            except Exception:
                pass
        self._overlay_view_sync_conns = []

    def invalidate_envelope_cache(self, reason: str, *, data_id=None, channel=None):
        """Drop curve-layer cache entries.

        Same filter contract as ``TimeDomainCanvas.invalidate_envelope_cache``
        so the call sites in MainWindow keep working unchanged. Filter
        scope: ``data_id`` is stored alongside the cache key (as part of
        the channel key prefix); without a channel filter we drop every
        entry whose channel name participates in this canvas's data_id
        mapping for that file.
        """
        if data_id is None and channel is None:
            self._curve_path_cache.clear()
            self._last_range_key.clear()
            return
        keys_to_drop = []
        for k in self._curve_path_cache:
            k_channel = k[0]
            if channel is not None and k_channel != channel:
                continue
            if data_id is not None:
                # Match data_id via the parallel dict.
                if self._channel_data_id.get(k_channel) != data_id:
                    continue
            keys_to_drop.append(k)
        for k in keys_to_drop:
            self._curve_path_cache.pop(k, None)
        # Also drop the per-channel last-range marker so the next flush
        # rebuilds the cache entry.
        if channel is not None:
            self._last_range_key.pop(channel, None)
        elif data_id is not None:
            for ch_name, ch_data_id in list(self._channel_data_id.items()):
                if ch_data_id == data_id:
                    self._last_range_key.pop(ch_name, None)

    def invalidate_monotonicity_cache(self, custom_xaxis_fid=None, custom_xaxis_ch=None):
        """Drop per-channel monotonicity flags. Mirrors the matplotlib
        canvas surface so MainWindow's invalidation call sites remain
        renderer-agnostic. Full-clear (no filters) matches the
        TimeDomainCanvas behavior — the next plot_channels rebuilds the
        dict."""
        self._channel_is_monotonic.clear()

    # ------------------------------------------------------------------
    # Viewport refresh wiring (design §5.2 hot path).
    # ------------------------------------------------------------------

    def _connect_xrange_listener(self, axis_handle):
        """Attach sigXRangeChanged on the axis's ViewBox.

        Connects ADDITIVELY: every subplot axis gets its own connection
        so an origin-aware propagation handler can identify which axis
        sourced the change. The prior implementation overwrote a single
        ``_xrange_conn`` slot per call, which left only the most-recent
        axis wired and silently dropped earlier subscriptions on every
        ``plot_channels`` rebuild.
        """
        vb = axis_handle.view_box if axis_handle is not None else None
        if vb is None or not hasattr(vb, "sigXRangeChanged"):
            return
        # Closure binds the SOURCE handle so origin-skip works correctly
        # without relying on pyqtgraph emitting the ViewBox as sender.
        source_handle = axis_handle

        def _handler(*_args, _src=source_handle):
            self._on_xrange_changed(_src)

        try:
            vb.sigXRangeChanged.connect(_handler)
            self._xrange_conns.append((vb, _handler))
        except Exception:
            pass

    def _disconnect_xrange_listener(self):
        """Drop every sigXRangeChanged hook before its axis is destroyed.

        Pyqtgraph analogue of
        ``pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle``:
        callbacks survive widget teardown unless explicitly disconnected.
        """
        for vb, handler in self._xrange_conns:
            try:
                vb.sigXRangeChanged.disconnect(handler)
            except Exception:
                pass
        self._xrange_conns = []

    def _on_xrange_changed(self, source_handle, *_args):
        """Coalesce rapid xlim updates into a single refresh AND
        propagate the exact range to sibling axes (subplot mode).

        We do NOT use pyqtgraph's ``setXLink`` because its
        ``linkedViewChanged`` uses screen-geometry interpolation that
        introduces a small per-axis shift when the subplots' screen
        widths differ. For this app the range must be byte-identical
        across subplots, so we push it ourselves.

        ``source_handle`` is the axis whose ViewBox emitted the range
        change. Propagation skips ``source_handle`` so it does not
        receive its own range back as a redundant write.
        """
        self.disable_interactive_quality()
        # Propagate first so the sibling axes are in sync BEFORE the
        # debounced refresh runs.
        self._propagate_xlim_to_siblings(source=source_handle)
        self._apply_target_x_ticks_to_all_axes()
        self._emit_xrange_changed(source_handle)
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()

    def _emit_xrange_changed(self, source_handle=None):
        if source_handle is None:
            source_handle = self._primary_xaxis_ax
        if source_handle is None:
            return
        try:
            lo, hi = source_handle.get_xlim()
        except Exception:
            return
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return
        self.xrange_changed.emit(float(lo), float(hi))
        self.visible_range_changed.emit()

    def _propagate_xlim_to_siblings(self, source=None):
        """Mirror ``source``'s xlim onto every other axis facade.

        Cheap and idempotent: pyqtgraph's setXRange short-circuits when
        the range is already equal modulo padding (event-conditional per
        ``pyqt-ui/2026-04-25-cache-invalidation-event-conditional`` — we
        skip siblings whose current range already matches the source).
        We guard against re-entrant sigXRangeChanged by blocking
        signals on siblings while we set the range.

        ``source=None`` falls back to the primary axis (legacy call site
        + the ``_restore_primary_xlim`` path).
        """
        if source is None:
            source = self._primary_xaxis_ax
        targets = list(self.axes_list)
        if self._overlay_mode and self._x_master_handle is not None:
            targets = [self._x_master_handle] + targets
        if source is None or len(targets) <= 1:
            return
        try:
            lo, hi = source.get_xlim()
        except Exception:
            return
        for handle in targets:
            if handle is source:
                continue
            vb = handle.view_box
            if vb is None:
                continue
            # Event-conditional skip: only push when the sibling's
            # current range actually differs. pyqtgraph's setXRange is
            # already a no-op for equal ranges, but checking here also
            # avoids the blockSignals dance for the no-op case.
            try:
                cur_lo, cur_hi = handle.get_xlim()
            except Exception:
                cur_lo, cur_hi = (None, None)
            if cur_lo == float(lo) and cur_hi == float(hi):
                self._sync_x_axis_item_range(handle, lo, hi)
                continue
            did_set = False
            try:
                # blockSignals avoids ping-pong with sibling listeners.
                vb.blockSignals(True)
                vb.setXRange(float(lo), float(hi), padding=0)
                did_set = True
            except Exception:
                pass
            finally:
                try:
                    vb.blockSignals(False)
                except Exception:
                    pass
            if did_set:
                self._sync_x_axis_item_range(handle, lo, hi)

    def _flush_pending_refresh(self):
        """Drain any pending refresh immediately (end-of-pan/zoom).

        Per pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before:
        callers MUST invoke this AFTER mutating xlim, never before. The
        canvas has no awareness of who scheduled the pending refresh —
        all it does is run the visible-data update synchronously.
        """
        # Even with no scheduled timer we still want to allow a
        # synchronous repopulation when the caller has just mutated
        # xlim without a sigXRangeChanged round-trip (programmatic
        # plot_channels rebuilds). Hit the timer's flag too.
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        # If nothing is scheduled and there is no data, exit cheaply.
        if not self._channel_lines or self._primary_xaxis_ax is None:
            self._refresh_pending = False
            return
        # Run the update synchronously so the last frame of a pan ends
        # on the high-detail envelope.
        try:
            self._refresh_visible_data()
        finally:
            self._refresh_pending = False

    def _current_pixel_width(self) -> int:
        """Pixel width of the primary chart area (used as the envelope
        bucket count)."""
        primary = self._primary_xaxis_ax
        if primary is None:
            return self.MAX_PTS
        vb = primary.view_box
        if vb is None:
            return self.MAX_PTS
        try:
            rect = vb.sceneBoundingRect()
            w = int(max(1, rect.width()))
            return w
        except Exception:
            return self.MAX_PTS

    def _refresh_visible_data(self):
        """Recompute and display the viewport envelope for every channel."""
        self._refresh_pending = False
        if not self._channel_lines or self._primary_xaxis_ax is None:
            return
        try:
            xlim = self._primary_xaxis_ax.get_xlim()
        except Exception:
            return
        pixel_width = self._current_pixel_width()

        for name, (axis_facade, line_facade) in list(self._channel_lines.items()):
            entry = self.channel_data.get(name)
            if entry is None:
                continue
            t, sig, color, _unit = entry

            # Range-key gate: if the key didn't change since the last flush,
            # skip the envelope+setData work entirely. This keeps repeated
            # _flush_pending_refresh() calls with the same xlim a no-op.
            range_key = _quantize_range_key(name, xlim, pixel_width)
            if self._last_range_key.get(name) == range_key:
                continue

            is_monotonic = self._channel_is_monotonic.get(name)
            try:
                env_t, env_s = positions_envelope(
                    t, sig,
                    xlim=xlim,
                    pixel_width=pixel_width,
                    is_monotonic=is_monotonic,
                )
            except Exception as exc:
                _log.warning(
                    "positions_envelope failed for %r at xlim=%r: %s",
                    name, xlim, exc,
                )
                continue

            self._last_range_key[name] = range_key

            try:
                line_facade.plot_data_item.setData(env_t, env_s)
            except Exception as exc:
                _log.warning("PlotDataItem.setData failed for %r: %s", name, exc)

        self._refresh = True
        self.schedule_idle_quality()

    def _build_painter_path(self, t, s) -> QPainterPath:
        """Build a ``QPainterPath`` from envelope output. We work in data
        space here; the eventual blit translates to pixel space via the
        ViewBox's transform. Building the path once per cache key means
        repeated paint events (e.g. cursor overlay) do NOT re-walk the
        envelope arrays.

        Perf (T9): the all-finite case — which is the production hot path,
        since :func:`positions_envelope` bails to the numpy reference on any
        NaN in the visible window — is vectorized through
        ``pyqtgraph.functions.arrayToQPath(x, y, connect='all')``. That
        builds the ``QPainterPath`` from the numpy ``x``/``y`` arrays in C
        (the same QPolygonF→addPolygon fast path ``PlotCurveItem`` uses
        internally), replacing the pure-Python per-point
        ``moveTo``/``lineTo`` loop that dominated the ~10.7 ms pan frame
        (see signal-processing/2026-05-28-component-speedup-does-not-imply-
        end-to-end-target). For all-finite input the resulting path is
        byte-identical to the old loop (1 MoveTo + N-1 LineTo, same
        coordinates, same order).

        The NaN-gap path still goes through :meth:`_build_painter_path_loop`
        unchanged, because ``arrayToQPath``'s ``connect='all'`` would bridge
        the gap with a spurious line and its ``connect='finite'`` backfills
        non-finite samples with their neighbour (extra duplicate elements)
        and drops single-point chunks — neither reproduces the old loop's
        break-the-subpath discontinuity geometry.
        """
        n = min(len(t), len(s))
        if n == 0:
            return QPainterPath()
        t = np.asarray(t)
        s = np.asarray(s)
        # Fast path: >= 2 samples, all finite → vectorized C build.
        # asammdf's min/max envelope over a finite window is finite, so
        # this is the branch the production pan loop takes every frame.
        # We require n >= 2 because arrayToQPath drops a lone point
        # (elementCount 0), whereas the old loop emitted a bare moveTo
        # (elementCount 1) — routing n < 2 through the loop keeps that
        # degenerate single-point geometry byte-identical.
        if n >= 2 and np.isfinite(t[:n]).all() and np.isfinite(s[:n]).all():
            # arrayToQPath needs same-length contiguous float arrays; the
            # envelope output is float64 but slice to n and enforce
            # contiguity defensively (a view of a larger buffer would not
            # be C-contiguous). finiteCheck=False because we just proved
            # finiteness — this skips arrayToQPath's internal isfinite scan.
            x = np.ascontiguousarray(t[:n], dtype=np.float64)
            y = np.ascontiguousarray(s[:n], dtype=np.float64)
            return pg.functions.arrayToQPath(x, y, connect="all",
                                             finiteCheck=False)
        # Slow path: NaN segments present — break the sub-path on each
        # discontinuity, matches asammdf's handling. Byte-identical to the
        # historical loop (T9 preserved this verbatim for gap parity).
        return self._build_painter_path_loop(t, s, n)

    def _build_painter_path_loop(self, t, s, n) -> QPainterPath:
        """Pure-Python per-point builder used only when NaN gaps are
        present. Kept byte-identical to the pre-T9 ``_build_painter_path``
        loop so the discontinuity geometry (bare ``moveTo`` after a gap, no
        element for NaN samples) is preserved exactly.
        """
        path = QPainterPath()
        # Skip NaN segments by breaking the sub-path; matches asammdf's
        # discontinuity handling.
        started = False
        for i in range(n):
            ti = float(t[i])
            si = float(s[i])
            if not (np.isfinite(ti) and np.isfinite(si)):
                started = False
                continue
            if not started:
                path.moveTo(ti, si)
                started = True
            else:
                path.lineTo(ti, si)
        return path

    def _render_path_to_pixmap(self, path: QPainterPath, color: str, pixel_width: int) -> QPixmap:
        """Render the QPainterPath into a QPixmap once per cache entry.

        Antialiasing is OFF (matches asammdf strategy from design §5.2
        evidence). The pixmap is sized to ``pixel_width × 200`` as a
        proxy chart-area; T6 will plumb the actual ViewBox geometry once
        the overlay/cursor layer lands.
        """
        height = 200
        pix = QPixmap(max(1, pixel_width), height)
        pix.fill(Qt.transparent)
        # Painter on a 1×1 pixmap is a no-op; guard the degenerate case.
        if pix.isNull() or pix.width() < 2 or pix.height() < 2:
            return pix
        try:
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing, False)
            pen = QPen()
            try:
                pen.setColor(pg.mkColor(color))
            except Exception:
                from PyQt5.QtGui import QColor
                pen.setColor(QColor(color))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)
            painter.end()
        except Exception:
            # Degenerate-rect fallback (pyqt-ui/2026-04-25-tightbbox-
            # survives-offscreen-qt): a 1×1 transparent pixmap is still
            # a valid QPixmap; callers test pix.isNull(), not contents.
            pass
        return pix

    # ------------------------------------------------------------------
    # T6 — Overlay selection / emphasis (mirrors
    # canvases.py:_apply_overlay_selection_style).
    # ------------------------------------------------------------------

    def select_overlay_channel(self, name):
        """Select an overlay channel as the per-series Y-drag target.

        ``name=None`` clears the selection. Emits
        ``overlay_channel_selected(name)`` once and ONLY when the
        selection actually changes (matches matplotlib path's idempotent
        gate at canvases.py:813-814 so the test asserting exactly two
        emissions — select then deselect — holds).
        """
        if name is not None and name not in self._channel_lines:
            return
        if self._selected_overlay_channel == name:
            return
        self._selected_overlay_channel = name
        self._apply_overlay_emphasis()
        self.overlay_channel_selected.emit(name)
        self.draw_idle()

    def _overlay_emphasis_for_channel(self, name):
        """Return ``(line_width, alpha)`` currently displayed for ``name``.

        Used by tests to make a two-frame state-change assertion on the
        per-channel emphasis without coupling to pyqtgraph internals.
        """
        pair = self._channel_lines.get(name)
        if pair is None:
            return (None, None)
        _axis_facade, line_facade = pair
        pdi = line_facade.plot_data_item
        # Pull pen width + alpha from the PlotDataItem.
        opts = getattr(pdi, "opts", {}) or {}
        pen = opts.get("pen")
        width = 1.0
        alpha = 1.0
        try:
            from PyQt5.QtGui import QPen
            if isinstance(pen, QPen):
                width = float(pen.widthF() or 1.0)
        except Exception:
            pass
        try:
            opacity = pdi.opacity()
            if opacity is not None:
                alpha = float(opacity)
        except Exception:
            pass
        return (width, alpha)

    def _apply_overlay_emphasis(self):
        """Walk every channel and set line width + alpha to match the
        current selection state. Matches
        canvases.py:_apply_overlay_selection_style.
        """
        selected = self._selected_overlay_channel
        for name, (_axis_facade, line_facade) in self._channel_lines.items():
            pdi = line_facade.plot_data_item
            if not self._overlay_mode or selected is None:
                self._apply_pdi_emphasis(
                    pdi, width=self._overlay_default_lw,
                    alpha=self._overlay_default_alpha,
                )
                continue
            is_selected = (name == selected)
            if is_selected:
                self._apply_pdi_emphasis(
                    pdi, width=self._overlay_selected_lw,
                    alpha=self._overlay_selected_alpha,
                )
            else:
                self._apply_pdi_emphasis(
                    pdi, width=self._overlay_de_emphasised_lw,
                    alpha=self._overlay_de_emphasised_alpha,
                )

    def _apply_pdi_emphasis(self, pdi, *, width, alpha):
        """Set line width (via pen) + alpha on a single PlotDataItem.

        Antialiasing stays OFF so the asammdf-style cached pixmap
        strategy (design §5.2) is preserved.
        """
        try:
            opts = getattr(pdi, "opts", {}) or {}
            pen = opts.get("pen")
            color = None
            try:
                from PyQt5.QtGui import QPen
                if isinstance(pen, QPen):
                    color = pen.color()
            except Exception:
                color = None
            if color is None:
                # Fall back to mkColor on the stored color name.
                try:
                    color = pg.mkColor(pen)
                except Exception:
                    color = None
            if color is None:
                pdi.setPen(pg.mkPen(width=float(width)))
            else:
                pdi.setPen(pg.mkPen(color=color, width=float(width)))
        except Exception:
            pass
        try:
            pdi.setOpacity(float(alpha))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # T6 — Selected-channel Y drag.
    # ------------------------------------------------------------------

    def _begin_overlay_y_drag_at(self, *, start_y_px):
        """Capture the (pixel, ylim) pair so the next drag-apply can
        compute the shift. Mirrors canvases.py:_begin_overlay_y_drag.
        """
        ax = self._selected_overlay_axes()
        if ax is None:
            self._overlay_y_drag_start = None
            return
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            self._overlay_y_drag_start = None
            return
        self._overlay_y_drag_start = (float(start_y_px), (float(lo), float(hi)))

    def _apply_overlay_y_drag_at(self, *, current_y_px):
        """Apply the pan implied by a Y drag from start to ``current_y_px``.

        Returns ``True`` when a ylim shift was applied, ``False``
        otherwise. Mirrors canvases.py:_update_overlay_y_drag, except we
        derive the pixel height from the ViewBox's sceneBoundingRect
        rather than ``ax.bbox.height``.
        """
        if self._overlay_y_drag_start is None:
            return False
        ax = self._selected_overlay_axes()
        if ax is None:
            self._overlay_y_drag_start = None
            return False
        start_y, (lo, hi) = self._overlay_y_drag_start
        # Pixel height of the selected ViewBox.
        vb = ax.view_box
        height = 1.0
        if vb is not None:
            try:
                rect = vb.sceneBoundingRect()
                height = max(float(rect.height()), 1.0)
            except Exception:
                height = 1.0
        dy_px = float(current_y_px) - float(start_y)
        shift = -dy_px * (hi - lo) / height
        # Symmetric overlay layout (Problem 3): the selected channel now
        # lives on its OWN aux ViewBox, NOT on the X-master ViewBox, so a
        # ``set_ylim`` here cannot perturb the shared X range — the prior
        # X-pin capture/restore around this mutation is dead and removed.
        # (Verified byte-exact by the X-stability assertions in
        # tests/ui/test_chart_stack.py and tests/ui/test_pg_timedomain_canvas.py.)
        try:
            ax.set_ylim(lo + shift, hi + shift)
        except Exception:
            return False
        self.visible_range_changed.emit()
        self._refresh = True
        self.draw_idle()
        return True

    def _selected_overlay_axes(self):
        """Return the axis facade associated with the selected channel.

        Overlay mode now mirrors matplotlib twinx: every channel has its
        own Y-axis handle, so a selected-channel Y drag only moves that
        channel's ViewBox.
        """
        if self._selected_overlay_channel is None:
            return None
        pair = self._channel_lines.get(self._selected_overlay_channel)
        if pair is None:
            return None
        axis_handle, _line_handle = pair
        return axis_handle

    # ------------------------------------------------------------------
    # T6 — Modifier-aware wheel dispatch.
    # ------------------------------------------------------------------

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos, view_box=None):
        """Central wheel dispatch routed from ``_ModifierWheelViewBox``.

        Behavior matches canvases.py:_on_scroll (lines 1501-1515):

        - delta > 0 → factor 0.85 (zoom in / pan up)
        - delta < 0 → factor 1/0.85 (zoom out / pan down)
        - Ctrl + wheel  → zoom X about ``x_pos``
        - Shift + wheel → zoom Y about ``y_pos``
        - plain wheel   → pan Y by 10 % of span per step

        Returns ``True`` if consumed, ``False`` otherwise (caller falls
        back to default ViewBox behavior).
        """
        # Matplotlib uses step = +/-1; here Qt uses delta in units of 120.
        step = 1 if delta > 0 else -1 if delta < 0 else 0
        if step == 0:
            return False
        # Match matplotlib factor (canvases.py:1507).
        factor = 0.85 if step > 0 else 1.0 / 0.85

        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        self.disable_interactive_quality()

        if getattr(self, "_overlay_mode", False) and not ctrl:
            target = self._selected_overlay_axes()
            if target is None:
                self.overlay_y_needs_selection.emit()
                self.schedule_idle_quality()
                return True
            try:
                lo, hi = target.get_ylim()
            except Exception:
                return True
            n = max(3, min(20, int(getattr(self, "_overlay_divisions", 8))))
            span = hi - lo
            if not math.isfinite(span) or span <= 0:
                bottom, top, ticks = _frame_to_nice(lo, hi, n)
            elif shift:
                try:
                    anchor = float(y_pos)
                except Exception:
                    anchor = (lo + hi) / 2.0
                if not math.isfinite(anchor):
                    anchor = (lo + hi) / 2.0
                x_master_vb = (
                    getattr(self._x_master_handle, "view_box", None)
                    if self._x_master_handle is not None
                    else None
                )
                if (
                    0.0 <= anchor <= 1.0
                    and (view_box is None or view_box is x_master_vb)
                ):
                    anchor = lo + anchor * span
                current_per_div = span / n
                next_per_div = _adjacent_nice_step(
                    current_per_div,
                    -1 if step > 0 else 1,
                )
                if next_per_div is None:
                    next_per_div = current_per_div * factor
                ratio = max(0.0, min(1.0, (anchor - lo) / span))
                framed_span = max(next_per_div, (n - 1) * next_per_div)
                new_lo = anchor - ratio * framed_span
                new_hi = anchor + (1.0 - ratio) * framed_span
                bottom, top, ticks = _frame_to_nice(new_lo, new_hi, n)
            else:
                per_div = span / n
                bottom = lo + step * per_div
                top = hi + step * per_div
                ticks = [bottom + k * per_div for k in range(n + 1)]
            try:
                target.set_ylim(bottom, top)
                axis = target.y_axis_item() if hasattr(target, "y_axis_item") else None
                if axis is not None:
                    axis.setStyle(maxTickLevel=0)
                    axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
            except Exception:
                return True
            self.visible_range_changed.emit()
            self._refresh = True
            self.draw_idle()
            self.schedule_idle_quality()
            return True

        target = self._axis_handle_for_view_box(view_box) or self._primary_xaxis_ax
        if target is None:
            return False

        try:
            if ctrl:
                lo, hi = target.get_xlim()
                c = float(x_pos) if np.isfinite(x_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
                target.set_xlim(new_lo, new_hi)
            elif shift:
                lo, hi = target.get_ylim()
                c = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
                target.set_ylim(new_lo, new_hi)
            else:
                lo, hi = target.get_ylim()
                d = (hi - lo) * 0.1 * step
                target.set_ylim(lo + d, hi + d)
        except Exception:
            return False

        self.visible_range_changed.emit()
        self._refresh = True
        self.draw_idle()
        self.schedule_idle_quality()
        return True

    # ------------------------------------------------------------------
    # T6 — Cursor HTML emission (byte-for-byte parity with
    # canvases.py:_update_single / _update_dual).
    # ------------------------------------------------------------------

    def _emit_single_cursor_html(self, x):
        """Build and emit the single-cursor HTML payload exactly the
        same way canvases.py:_update_single does (lines 1434-1448).

        We do NOT call any pyqtgraph paint helpers here — this is the
        DATA-ONLY emit path the tests use to compare strings. The live
        UI's hover handler will call this plus an overlay-line update.
        """
        sep = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>')
        parts = [f'<span style="color:#111827;">t={x:.4f}s</span>']
        for ch, (tf, sf, color, u) in self.channel_data.items():
            if len(tf):
                idx = min(np.searchsorted(tf, x), len(sf) - 1)
                unit_s = f" {u}" if u else ""
                parts.append(_format_single_cursor_channel_html(ch, sf[idx], unit_s, color))
        self.cursor_info.emit(sep.join(parts))

    def _emit_dual_cursor_html(self):
        """Build and emit cursor_info + dual_cursor_info exactly the same
        way canvases.py:_update_dual does (lines 1450-1499).

        Reuses the module-level ``_format_dual_html`` helper imported
        from ``canvases.py`` so the bytes cannot drift —
        ``codex-plan-spec-literal-evidence`` is satisfied by import,
        not by reimplementation.
        """
        info, dual = [], []
        extreme_points = []
        if self._ax is not None:
            info.append(f"A={self._ax:.4f}s")
        if self._bx is not None:
            info.append(f"B={self._bx:.4f}s")
        if self._ax is not None and self._bx is not None:
            dx = self._bx - self._ax
            info.append(f"ΔT={dx:.4f}s")
            if abs(dx) > 1e-12:
                info.append(f"1/ΔT={1 / abs(dx):.2f}Hz")
            xlo, xhi = min(self._ax, self._bx), max(self._ax, self._bx)
            for ch, (tf, sf, color, u) in self.channel_data.items():
                if not len(tf):
                    continue
                m = (tf >= xlo) & (tf <= xhi)
                seg = sf[m]
                if not len(seg):
                    continue
                segment_indices = np.flatnonzero(m)
                finite = np.isfinite(seg)
                if np.any(finite):
                    finite_segment = seg[finite]
                    finite_indices = segment_indices[finite]
                    min_idx = int(finite_indices[int(np.argmin(finite_segment))])
                    max_idx = int(finite_indices[int(np.argmax(finite_segment))])
                    extreme_points.append((
                        ch,
                        float(tf[min_idx]),
                        float(sf[min_idx]),
                        float(tf[max_idx]),
                        float(sf[max_idx]),
                    ))
                u_suffix = f" {u}" if u else ""
                delta = _interp_cursor_value(tf, sf, self._bx) - _interp_cursor_value(
                    tf, sf, self._ax
                )
                dual.append((
                    ch,
                    float(np.min(seg)),
                    float(np.max(seg)),
                    float(np.mean(seg)),
                    float(delta),
                    u_suffix,
                    color,
                ))
        if info:
            primary_html = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
                            .join(f'<span style="color:#111827;">{p}</span>' for p in info))
        else:
            primary_html = "Click A"
        self.cursor_info.emit(primary_html)
        self.dual_cursor_info.emit(_format_dual_html(dual) if dual else "")
        if self._ax is not None and self._bx is not None:
            self._update_dual_cursor_extreme_markers(extreme_points)
        else:
            self._hide_dual_cursor_extreme_markers()

    def _cursor_x_to_pixmap_x(self, data_x, pixmap_width):
        """Map a data-space cursor X to pixel-x in the grabbed pixmap.

        Used by the screenshot geometry test to assert the cursor pill
        position is contained in the pixmap bbox. The mapping uses the
        primary axis's current xlim → simple linear interpolation across
        the full pixmap width. (The actual chart area is narrower than
        the pixmap because of left/right axis gutters, but that is
        irrelevant to the bbox-contains gate.)
        """
        primary = self._primary_xaxis_ax
        if primary is None:
            return 0.0
        try:
            lo, hi = primary.get_xlim()
        except Exception:
            return 0.0
        if hi <= lo:
            return 0.0
        frac = (float(data_x) - lo) / (hi - lo)
        frac = max(0.0, min(1.0, frac))
        return frac * float(pixmap_width)

    # ------------------------------------------------------------------
    # T6 — Subplot inside-label placement
    # (mirrors canvases.py:_subplot_ylabels_need_inside_labels).
    # ------------------------------------------------------------------

    def _subplot_ylabels_need_inside_labels(self):
        """Return True when the outer Y axis labels would overlap each
        other or the chart's left edge → callers should flip the labels
        inside the axes.

        Mirrors the rule in canvases.py:_subplot_ylabels_need_inside_labels
        (lines 937-965): the decision is bbox-overlap-driven, NOT a
        fixed pixel/percent offset. Design §0 explicitly corrects the
        earlier draft that proposed a 5-10% offset.

        Pyqtgraph implementation: normal-width stacks with long or
        file-prefixed channel names use inside labels because rotated
        AxisItem labels are taller than the subplot row. Narrow stacks also
        flip inside on the historical 320 px threshold.
        """
        if len(self.axes_list) <= 1:
            return False
        if len(self.axes_list) >= 4:
            return True
        for _handle, name, _color in self._subplot_label_specs:
            text = str(name)
            if len(text) > 32 or (text.startswith("[") and "]" in text):
                return True
        try:
            scene_widget = self._glw.viewport()
            widget_w = max(int(scene_widget.width()), 1)
        except Exception:
            widget_w = 0
        if widget_w == 0:
            return False
        return widget_w < 320

    def _teardown_inside_labels(self):
        """Remove every inside-label scene item and drop its listeners.

        Single owner of inside-label teardown. pyqtgraph's
        GraphicsLayout.clear() only removes items registered via
        addItem() (the PlotItems); our TextItem badges are attached with
        scene().addItem(), so they MUST be removed explicitly here or
        they leak into the scene on every rebuild (ghost badges).
        """
        self._disconnect_inside_label_listeners()
        for item in self._inside_label_items:
            try:
                scene = item.scene()
                if scene is not None:
                    scene.removeItem(item)
            except Exception:
                pass
        self._inside_label_items = []
        self._inside_label_handles = []

    def _disconnect_inside_label_listeners(self):
        for signal, handler in self._inside_label_conns:
            try:
                signal.disconnect(handler)
            except Exception:
                pass
        self._inside_label_conns = []

    def _position_inside_label_item(self, handle, item):
        vb = handle.view_box
        if vb is None:
            return
        try:
            rect = vb.sceneBoundingRect()
            item.setPos(rect.left() + 4.0, rect.top() + 4.0)
        except Exception:
            pass

    def _position_inside_label_items(self):
        for handle, item in zip(self._inside_label_handles, self._inside_label_items):
            self._position_inside_label_item(handle, item)

    def _attach_axis_handle_callbacks(self, handle):
        add_callback = getattr(handle, "add_title_changed_callback", None)
        if callable(add_callback):
            add_callback(self._on_axis_title_changed)

    def _on_axis_title_changed(self, handle, title):
        self._update_inside_label_visibility_for_handle(handle, title)

    def _update_inside_label_visibility_for_handle(self, handle, title=None):
        if title is None:
            try:
                title = handle.get_title()
            except Exception:
                title = ""
        title_visible = bool(str(title).strip())
        for label_handle, item in zip(self._inside_label_handles, self._inside_label_items):
            if label_handle is not handle:
                continue
            try:
                item.setVisible(not title_visible)
                if not title_visible:
                    self._position_inside_label_item(label_handle, item)
            except Exception:
                pass

    def _recheck_subplot_label_placement(self):
        """Place subplot Y labels either OUTSIDE (default AxisItem
        label) or INSIDE (a TextItem at the top-left of each ViewBox).

        Apply once per ``plot_channels`` build; resize-triggered
        re-checks are deferred to T7 because they're not on the parity
        gate for this task.
        """
        # Drop any previously-installed inside-label items.
        self._teardown_inside_labels()

        need_inside = self._subplot_ylabels_need_inside_labels()
        for handle, name, color in self._subplot_label_specs:
            ax_item = handle._ax("left") if hasattr(handle, "_ax") else None
            if need_inside:
                # Hide the outer label by clearing it; install a TextItem
                # at the top-left of the ViewBox.
                if ax_item is not None:
                    try:
                        ax_item.setLabel(text="")
                    except Exception:
                        pass
                prefix, rest = _split_prefixed_label(str(name))
                label_text = f"{prefix}\n{rest}" if prefix is not None else str(name)
                text_item = pg.TextItem(
                    text=f"● {label_text}",
                    color=pg.mkColor(color),
                    anchor=(0, 0),
                    fill=pg.mkBrush(255, 255, 255, 220),
                    border=pg.mkPen(color=color, width=0.8),
                )
                _apply_pg_text_item_font(text_item)
                vb = handle.view_box
                if vb is not None:
                    try:
                        scene = vb.scene()
                        if scene is not None:
                            scene.addItem(text_item)
                        else:
                            vb.addItem(text_item, ignoreBounds=True)
                        text_item.setZValue(1000)
                        title_text = ""
                        try:
                            title_text = handle.get_title()
                        except Exception:
                            title_text = ""
                        text_item.setVisible(not bool(title_text))
                        self._position_inside_label_item(handle, text_item)
                        self._inside_label_items.append(text_item)
                        self._inside_label_handles.append(handle)
                        if hasattr(vb, "sigResized"):
                            def _resize_handler(*_args, _handle=handle, _item=text_item):
                                self._position_inside_label_item(_handle, _item)

                            vb.sigResized.connect(_resize_handler)
                            self._inside_label_conns.append((vb.sigResized, _resize_handler))
                    except Exception:
                        pass
            else:
                # Outside: ensure the standard axis label is set.
                if ax_item is not None:
                    try:
                        ax_item.setLabel(text=str(name))
                        _apply_pg_axis_font(ax_item)
                    except Exception:
                        pass

    def _unify_subplot_left_axis_widths(self):
        """Align every subplot's plot-area left edge to a common x.

        pyqtgraph sizes each PlotItem's left ``AxisItem`` to its own
        tick-label text width. In subplot mode that makes rows with wider
        numeric labels start further right, skewing the shared time grid.
        We measure each left axis's current width and pin all of them to
        the max so the left edges align. Cheap and idempotent: re-running
        with the same widths leaves the max unchanged.

        Only meaningful in subplot mode (``_subplot_label_specs`` is the
        subplot marker); short-circuits otherwise so overlay/single paths
        are untouched.
        """
        if not self._subplot_label_specs:
            return
        left_axes = []
        for handle in self.axes_list:
            ax_item = handle._ax("left") if hasattr(handle, "_ax") else None
            if ax_item is not None:
                left_axes.append(ax_item)
        if len(left_axes) < 2:
            return
        # Release any prior pin so width() reflects the CURRENT tick-label
        # text width before we re-measure. Without this, a previous pin
        # (e.g. from an earlier density level) would make every axis report
        # the same stale width and the unification would never re-tighten.
        for ax_item in left_axes:
            try:
                ax_item.setWidth(None)
            except Exception:
                pass
        max_w = 0.0
        for ax_item in left_axes:
            try:
                w = float(ax_item.width())
            except Exception:
                continue
            if w > max_w:
                max_w = w
        if max_w <= 0.0:
            return
        for ax_item in left_axes:
            try:
                ax_item.setWidth(max_w)
            except Exception:
                pass
        try:
            layout = self._glw.ci.layout
            layout.invalidate()
            layout.activate()
        except Exception:
            pass

    def _unify_subplot_bottom_axis_heights(self):
        """Collapse hidden upper subplot bottom-axis reserves and balance rows.

        Only the bottom subplot shows X tick values and the X label, yet every
        subplot's bottom AxisItem still consumes layout height. Letting the
        hidden upper rows reserve a full tick/label height opens a large blank
        band between rows — most visible in two-row mode. Reserve the X
        tick/label height only on the final row and collapse the hidden upper
        rows to ~1 px, so subplots sit flush regardless of row count.

        After collapsing, give every grid row equal preferred height + stretch
        so QGraphicsGridLayout keeps the ViewBoxes the same size instead of
        handing the collapsed rows extra cell height (which leaves the bottom
        plot cramped). The bottom ViewBox stays ~one-axis-height shorter than
        the rows above it — the intended stacked-shared-X look, favouring flush
        adjacency over pixel-equal heights. The preferred height is a constant:
        equal values distribute proportionally, so rows stay balanced at any
        canvas size without reading live geometry. See
        docs/superpowers/specs/2026-06-02-subplot-vertical-spacing-design.md.
        """
        if not self._subplot_label_specs:
            return
        bottom_axes = []
        for handle in self.axes_list:
            pi = getattr(handle, "plot_item", None)
            if pi is None:
                continue
            try:
                axis = pi.getAxis("bottom")
            except Exception:
                axis = None
            if axis is not None:
                bottom_axes.append(axis)
        if len(bottom_axes) < 2:
            return
        for axis in bottom_axes[:-1]:
            try:
                axis.setHeight(1.0)
            except Exception:
                pass
        try:
            bottom_axes[-1].setHeight(None)
        except Exception:
            pass
        try:
            layout = self._glw.ci.layout
            for row in range(layout.rowCount()):
                layout.setRowStretchFactor(row, 1)
                layout.setRowPreferredHeight(row, 100.0)
            layout.invalidate()
            layout.activate()
        except Exception:
            pass

    def resizeEvent(self, event):
        """Re-check subplot inside-label placement on resize.

        Mirrors canvases.py's resize-driven inside/outside flip without
        adding a new debounced QTimer (the existing `_refresh_timer` is
        for envelope refresh only). The recheck is cheap: we just call
        ``_recheck_subplot_label_placement`` which short-circuits when
        ``_subplot_label_specs`` is empty.
        """
        try:
            super().resizeEvent(event)
        finally:
            try:
                if self._subplot_label_specs:
                    self._recheck_subplot_label_placement()
                    # Resize changes label widths; re-pin so left edges
                    # stay aligned across rows.
                    self._unify_subplot_left_axis_widths()
            except Exception:
                pass
            # Fix C (2026-05-31): the plot-area width just changed, so the
            # idle-AA density budget and envelope point count are stale.
            # Debounce a single settle pass (40 ms, _refresh_timer style)
            # so dragging the window border does not recompute on every
            # intermediate size, then recompute the envelope at the new
            # width and re-arm idle AA so crisp curves recover.
            try:
                self._idle_aa_density_seeded = False
                self._resize_settle_timer.start()
            except Exception:
                pass

    def _on_resize_settled(self):
        """Resize-debounce slot (Fix C): recompute the viewport envelope at
        the new width and re-arm the idle-AA timer so AA recovers.

        Reuses the existing debounced envelope-refresh path (set
        ``_refresh_pending`` + start ``_refresh_timer``) rather than adding
        a new rendering primitive; the resize → data-settle → idle-AA
        sequencing is the two-stage settle the design accepts (R4).
        """
        try:
            self.disable_interactive_quality()
        except Exception:
            pass
        try:
            self._refresh_overlay_axis_labels()
        except Exception:
            pass
        try:
            self._apply_target_x_ticks_to_all_axes()
            self._unify_subplot_left_axis_widths()
            self._unify_subplot_bottom_axis_heights()
        except Exception:
            pass
        # Recompute the envelope for the new plot-area width, matching the
        # _on_xrange_changed scheduling pattern (no new rendering path).
        try:
            if not self._refresh_pending:
                self._refresh_pending = True
                self._refresh_timer.start()
        except Exception:
            pass
        self.schedule_idle_quality()

    # ------------------------------------------------------------------
    # Screenshot grab (compat with chart_stack._copy_card_image).
    # ------------------------------------------------------------------

    def _collect_curve_items(self):
        """Every ``PlotCurveItem`` on the scene — the painted line of each
        PlotDataItem. Returns ``[]`` if the scene cannot be reached."""
        try:
            scene = self._glw.scene()
        except Exception:
            scene = None
        if scene is None:
            return []
        return [it for it in scene.items() if isinstance(it, pg.PlotCurveItem)]

    def _set_curves_antialias(self, on: bool) -> int:
        """Persistently set curve AA without repainting or changing data."""
        n = 0
        for it in self._collect_curve_items():
            try:
                it.opts["antialias"] = bool(on)
                n += 1
            except Exception:
                pass
        return n

    def _set_curves_cache_mode(self, mode) -> None:
        """Set the QGraphicsItem cache mode on every curve item.

        Fix D (2026-05-31): ``DeviceCoordinateCache`` lets hover /
        ``draw_idle`` blit the cached device-coordinate bitmap of the
        overlaid AA curves instead of re-rasterizing them every frame.
        The cache MUST be cleared (``NoCache``) on any range / geometry /
        resize / replot change, all of which converge on
        ``disable_interactive_quality`` (verified callers: _on_xrange_changed,
        reset_view_to_data_extents, the overlay Y-drag, the box-zoom hook,
        wheel zoom, and rebuild's AA reset).
        """
        for it in self._collect_curve_items():
            try:
                it.setCacheMode(mode)
            except Exception:
                pass

    def _install_viewport_event_filter(self) -> None:
        """Install this canvas' event filter on the current GLW viewport.

        ``GraphicsView.useOpenGL`` replaces the viewport widget. The filter is
        where double-click chart options, overlay selection/Y-drag, and cursor
        press/move/release enter the canvas, so every viewport swap must rebind
        it.
        """
        previous = getattr(self, "_gpu_viewport_filter_target", None)
        if previous is not None:
            try:
                previous.removeEventFilter(self)
            except Exception:
                pass
        viewport = None
        try:
            viewport = self._glw.viewport()
        except Exception:
            viewport = None
        if viewport is not None:
            try:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
            except Exception:
                viewport = None
        self._gpu_viewport_filter_target = viewport

    def set_gpu_render(self, on: bool) -> None:
        """Switch the time-domain canvas between CPU raster and GL viewport."""
        self._gpu_render_requested = bool(on)
        self._apply_gpu_viewport()

    def _apply_gpu_viewport(self) -> None:
        """Apply the requested GPU state to the actual GraphicsView viewport."""
        desired = bool(getattr(self, "_gpu_render_requested", False))
        if desired == bool(getattr(self, "_gpu_render_on", False)):
            self._install_viewport_event_filter()
            return
        glw = getattr(self, "_glw", None)
        if glw is None:
            self._gpu_render_on = False
            return
        try:
            glw.useOpenGL(desired)
        except Exception as exc:  # noqa: BLE001 - driver/context failures must not crash
            _log.warning("useOpenGL(%s) failed; will retry after next plot: %s", desired, exc)
            return
        self._gpu_render_on = desired
        self._install_viewport_event_filter()
        try:
            self._flush_pending_refresh()
        except Exception:
            pass
        try:
            glw.update()
        except Exception:
            pass

    def disable_interactive_quality(self):
        """Force the interactive path back to AA-off and cancel idle upgrade."""
        try:
            self._idle_aa_timer.stop()
        except Exception:
            pass
        if not getattr(self, "_idle_aa_on", False):
            return
        self._set_curves_antialias(False)
        # Fix D: a stale device-coordinate cache would smear during the
        # pan/zoom that this call precedes — drop it in lockstep with AA.
        # ALWAYS NoCache, in BOTH modes: even though only subplot ever sets
        # DeviceCoordinateCache, clearing unconditionally guarantees no stale
        # cache survives a subplot→overlay mode switch (cheap no-op when none
        # was set).
        self._set_curves_cache_mode(QGraphicsItem.NoCache)
        self._idle_aa_on = False
        try:
            self._glw.update()
        except Exception:
            pass

    def schedule_idle_quality(self):
        """Re-arm the single-shot idle-AA timer after a settled interaction."""
        try:
            self._idle_aa_timer.start()
        except Exception:
            pass

    def try_enable_idle_quality(self):
        """Idle timer slot: enable curve AA once every hands-off gate passes."""
        if self._idle_aa_on:
            return
        if not self._idle_quality_allowed():
            return
        if self._set_curves_antialias(True) > 0:
            # Fix D (RECALIBRATED, subplot-only): DeviceCoordinateCache blits
            # the cached device-coordinate bitmap on subsequent hover /
            # draw_idle repaints instead of re-rasterizing. Measured 15–30×
            # win for SUBPLOT (disjoint rows: 5×6000 AA-on 25.3 ms → 0.86 ms)
            # but ZERO win for OVERLAY (its aux ViewBoxes fully overlap at one
            # full-plot rect, so N full-size cache layers must alpha-composite
            # every frame — the compositing cancels the rasterization saving,
            # measured slightly WORSE). So cache subplot only; overlay relies
            # entirely on the tight density budget above. NoCache is still set
            # unconditionally on disable so no stale cache survives a mode swap.
            if not getattr(self, "_overlay_mode", False):
                self._set_curves_cache_mode(QGraphicsItem.DeviceCoordinateCache)
            self._idle_aa_on = True
            try:
                self._glw.update()
            except Exception:
                pass

    def _idle_quality_allowed(self) -> bool:
        """Return True only while the user is hands-off and density is safe."""
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                return False
        except Exception:
            return False
        if self._overlay_dragging:
            return False
        return self._idle_aa_density_ok()

    def _idle_aa_density_ok(self) -> bool:
        """Hysteresis density gate, branched on overlay vs subplot economics.

        Fix C (2026-05-31, RECALIBRATED): the per-frame rasterization cost
        differs structurally between the two modes, so the metric AND the
        budget differ:

        * OVERLAY (``self._overlay_mode``): metric = SUM of drawn points
          across ALL curves. Every overlay curve lives on its own aux
          ViewBox, but those aux ViewBoxes fully OVERLAP at the X-master's
          full plot rect, so a single ``draw_idle`` / ``_glw.update``
          re-rasterizes every overlaid curve as one region — the real cost
          is their sum, not the single densest. (Per-VB MAX undercounted
          overlay precisely because the distinct-but-overlapping aux
          ViewBoxes made the MAX see only one curve.) This is the UNCACHED
          path (Fix D's DeviceCoordinateCache gives no win on overlapping
          full-rect layers), so the tight overlay budget is what gates the
          measured-slow dense overlay (sum ≥ 9000 ≈ > 30 ms AA-on) to off.

        * SUBPLOT / SINGLE: metric = MAX over rows of that row's drawn-point
          sum. The rows are disjoint device rectangles and each subplot
          curve carries a DeviceCoordinateCache (Fix D, subplot-only), so an
          AA-on cached frame is ~0.3–0.9 ms at ANY width. The generous
          subplot budget therefore lets a single maximized / 4K curve
          (~7700-pt envelope) always get AA — fixing issue 1.

        Any unreadable ``getData()`` fails closed (AA stays off). The
        cold-start dead band is fixed by seeding the FIRST decision (and
        the first after a resize / rebuild reset) via the OFF threshold
        instead of inheriting the pessimistic initial ``False``; only
        thereafter does the ON/OFF hysteresis hold a value parked inside
        the band.
        """
        overlay = bool(getattr(self, "_overlay_mode", False))
        if overlay:
            on_budget = self._AA_OVERLAY_SEGMENT_ON
            off_budget = self._AA_OVERLAY_SEGMENT_OFF
        else:
            on_budget = self._AA_SUBPLOT_SEGMENT_ON
            off_budget = self._AA_SUBPLOT_SEGMENT_OFF

        sums: dict = {}
        total = 0
        for it in self._collect_curve_items():
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                self._idle_aa_density_allowed = False
                return False
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n

        if overlay:
            # Overlapping aux ViewBoxes → one repaint region → SUM.
            metric = total
        else:
            # Disjoint rows → independent dirty rects → MAX over rows.
            metric = max(sums.values()) if sums else 0

        if not self._idle_aa_density_seeded:
            # Cold start: a value at or below OFF is allowed; only a true
            # over-budget metric seeds False. This breaks the old dead-band
            # trap where a first metric in (ON, OFF] stuck at the initial
            # pessimistic False forever.
            self._idle_aa_density_allowed = metric <= off_budget
            self._idle_aa_density_seeded = True
        elif metric <= on_budget:
            self._idle_aa_density_allowed = True
        elif metric > off_budget:
            self._idle_aa_density_allowed = False
        # else: metric in the (ON, OFF] band → hold the previous value.
        return bool(self._idle_aa_density_allowed)

    def _export_aa_affordable(self) -> bool:
        """Return whether copy/export can afford forced curve antialiasing.

        This mirrors the idle-AA metric (overlay = sum of all curve points;
        subplot/single = max row point sum) but does not touch the idle-AA
        hysteresis state. Dense multi-channel exports fail closed to the cheap
        screen-state grab path.
        """
        overlay = bool(getattr(self, "_overlay_mode", False))
        off_budget = (
            self._AA_OVERLAY_SEGMENT_OFF if overlay else self._AA_SUBPLOT_SEGMENT_OFF
        )
        sums: dict = {}
        total = 0
        for it in self._collect_curve_items():
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                return False
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n
        metric = total if overlay else (max(sums.values()) if sums else 0)
        return metric <= off_budget

    @contextmanager
    def _curves_antialiased(self):
        """Temporarily enable antialiasing on every curve so an export grab
        renders crisp edges, then restore the prior (interactive, AA-off)
        state on exit.

        Interactive panning keeps curve AA OFF for speed (commit 4734d7f4);
        the soft/jagged export users compared unfavourably to matplotlib is a
        direct consequence. This flips ``PlotCurveItem.opts['antialias']``
        directly (NOT ``setData``), so the viewport-clipped envelope data is
        left untouched, and reverts it the moment the grab is done — no
        permanent perf regression on the pan hot path.
        """
        # Toggle the painter-hint opt ONLY — no setData / update / repaint.
        # The grab forces a fresh paint that reads opts['antialias'] at paint
        # time, so AA takes effect without invalidating geometry. Crucially we
        # must NOT trigger a repaint here: that would run the viewport-aware
        # envelope refresh, whose setData re-pushes data and clobbers the flag.
        saved = []
        for it in self._collect_curve_items():
            try:
                saved.append((it, it.opts.get("antialias", False)))
                it.opts["antialias"] = True
            except Exception:
                pass
        try:
            yield
        finally:
            for it, prev in saved:
                try:
                    it.opts["antialias"] = bool(prev)
                except Exception:
                    pass

    def grab_pixmap(self, scale: float = 1.0) -> QPixmap:
        """Return a ``QPixmap`` snapshot of the canvas.

        ``scale`` (spec §E) renders the scene at a HIGHER resolution for
        crisp, DPI-independent copy/save output. The effective factor is
        capped by ``_capped_hidpi_scale`` (floor 1×, width ceiling
        ``_HIDPI_MAX_WIDTH``) so export stays fast.

        Order of attempts:
        1. ``QWidget.grab()`` on the outer widget (covers GraphicsLayoutWidget
           + any sibling overlays MainWindow may add later). For ``scale`` > 1
           the grabbed bitmap is smoothly magnified to the capped target size.
           This keeps interactive copy to one widget paint instead of a
           screen-size grab plus a second high-DPI render in the click handler.
        2. Direct ``self._glw.grab()`` if the outer grab returned null.
        3. A 1×1 transparent fallback pixmap if both fail.

        Step 3 is the degenerate-rect fallback the
        ``2026-04-25-tightbbox-survives-offscreen-qt`` lesson prescribes:
        callers MUST check ``pix.isNull()`` rather than assuming a
        well-formed image. The degenerate fallback (and the isNull guard
        on every primary attempt) is preserved at ``scale`` > 1 too — we
        never default to a full-canvas-sized guess on a failed grab.
        """
        # Resolve the effective (capped) factor from the OUTER widget's
        # current width — the same surface step 1 grabs. Dense exports keep
        # the current screen rendering state and skip 2× magnification.
        base_w = max(1, int(self.width()))
        affordable = self._export_aa_affordable()
        eff_scale = _capped_hidpi_scale(base_w, scale) if affordable else 1.0

        def _grab_first_good():
            for target in (self, getattr(self, "_glw", None)):
                if target is None:
                    continue
                try:
                    pix = self._grab_widget_scaled(target, eff_scale)
                except Exception:
                    pix = None
                if pix is not None and not pix.isNull() and pix.width() > 0 and pix.height() > 0:
                    return pix
            return None

        # Few-channel exports keep the crisp forced-AA path. Dense exports are
        # what-you-see-is-what-you-get and avoid re-enabling AA for all curves.
        if affordable:
            with self._curves_antialiased():
                pix = _grab_first_good()
        else:
            pix = _grab_first_good()
        if pix is not None:
            return pix
        # Final fallback: a 1×1 transparent pixmap. Tests gate on
        # geometry, not pixels, so this is acceptable when offscreen Qt
        # cannot realize the widget at all. We do NOT scale this up — a
        # 1×1 degenerate marker stays 1×1 so callers' isNull/size guards
        # behave identically regardless of the requested scale.
        fallback = QPixmap(1, 1)
        fallback.fill(Qt.transparent)
        return fallback

    @staticmethod
    def _grab_widget_scaled(widget, eff_scale: float) -> QPixmap:
        """Grab ``widget`` at ``eff_scale``×.

        At 1× this is exactly ``widget.grab()`` (unchanged legacy path).
        Above 1× the same grabbed bitmap is smoothly scaled to
        ``round(w*scale) × round(h*scale)`` so the copy path avoids a second
        synchronous widget render. Returns a null pixmap when the widget has
        no realizable geometry (caller guards on ``isNull()``).
        """
        # Always grab once first. This is the legacy capture primitive and
        # the realizability probe: if the widget cannot be grabbed (null /
        # zero-size — e.g. offscreen Qt could not realize it), we return
        # that null result so grab_pixmap cascades to its 1×1 degenerate
        # fallback instead of synthesizing a blank full-canvas QImage.
        base = widget.grab()
        if eff_scale <= 1.0:
            return base
        if base is None or base.isNull() or base.width() <= 0 or base.height() <= 0:
            return base
        w = int(widget.width())
        h = int(widget.height())
        if w <= 0 or h <= 0:
            # No geometry to magnify — return the plain grab so the
            # caller's null/size guard runs against the real result.
            return base
        tw = max(1, int(round(w * eff_scale)))
        th = max(1, int(round(h * eff_scale)))
        return base.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


__all__ = [
    "TimeDomainCanvasPG",
    "_quantize_range_key",
    "_capped_hidpi_scale",
    "_HIDPI_MAX_WIDTH",
    "_HIDPI_COPY_SCALE",
]

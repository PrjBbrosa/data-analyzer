"""Fixed left UltraView tool rail and pointer tile.

Page owns which requested panel opens. Empty-board CTA state is a local
visual flag (``set_empty_board``). The rail never reads
``UltraViewBoardState``; Page decides when the canvas has no placed cards.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from PyQt5.QtCore import QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui.ultraview_state import ULTRAVIEW_REF_MIME, parse_ref_payload

from .author_chrome import (
    ConnectorPopover,
    DrawPopover,
    PointerPopover,
    ShapePopover,
    StickyPopover,
)
from .author_tools import (
    DEFAULT_DRAW_SUBTOOL,
    POINTER_MODE_LASER,
    POINTER_MODE_MOUSE,
    normalize_draw_subtool,
    normalize_pointer_mode,
)
from .chrome_common import (
    UV_BRAND,
    UV_FROST,
    UV_LINE_STRONG,
    UV_MUTED,
    UV_PRESENTATION_ICON,
    UV_SELECTED,
    _icon_button,
    _repolish,
    _set_flag,
    _ultraview_icon_color,
)
from .floating_layout import RAIL_CONTENT_HEIGHT, RAIL_WIDTH, RAIL_WIDTH_COMPACT


PANEL_LIBRARY = "library"
PANEL_LAYOUT = "layout"
PANEL_FILTER = "filter"
PANEL_UNPLACED = "unplaced"
PANEL_BOARDS = "boards"
AUTHOR_TOOL_SELECT = "select"
AUTHOR_TOOL_STICKY = "sticky"
AUTHOR_TOOL_TEXT = "text"
AUTHOR_TOOL_SHAPES = "shapes"
AUTHOR_TOOL_CONNECTOR = "connector"
AUTHOR_TOOL_DRAW = "draw"
AUTHOR_TOOLS = (
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_CONNECTOR,
    AUTHOR_TOOL_DRAW,
)
# Connector is chosen from the Shapes flyout. Draw is a first-class rail tool.
# Pointer (internal owner: select) is a visible FreeGrid mode, not an author object.
RELEASE_AUTHOR_TOOLS: tuple[str, ...] = (
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_DRAW,
)
OVERLAY_AUTHOR_POINTER = "author_pointer"
RAIL_BUTTON_SIZE = 40
RAIL_BUTTON_SIZE_COMPACT = 36
# Keep the 40/36px hit targets stable while giving the icon-only rail enough
# readable ink: desktop consumes the native 24px raster; compact consumes 20px.
RAIL_ICON_SIZE = 24
RAIL_ICON_SIZE_COMPACT = 20
RAIL_GROUP_GAP = 6
# Compact group/divider spacing is the only squeeze allowed so the full
# release rail (Pointer included) fits the 800×560 available band (432px)
# without clipping or shrinking the 36px hit targets.
RAIL_GROUP_GAP_COMPACT = 2
RAIL_DIVIDER_CLEAR = 10
RAIL_DIVIDER_CLEAR_COMPACT = 2
RAIL_DIVIDER_INSET = 8
RAIL_MARGINS = (10, 8, 10, 8)
RAIL_MARGINS_COMPACT = (6, 4, 6, 4)
RAIL_RADIUS = 14
RAIL_BADGE_MAX_HEIGHT = 18
RAIL_BADGE_INSET = 2
# Compatibility aliases: author buttons share the same rail box as panels.
RAIL_BUTTON_SIZE_AUTHOR = RAIL_BUTTON_SIZE
RAIL_BUTTON_SIZE_AUTHOR_COMPACT = RAIL_BUTTON_SIZE_COMPACT
RAIL_ICON_SIZE_AUTHOR = RAIL_ICON_SIZE
RAIL_ICON_SIZE_AUTHOR_COMPACT = RAIL_ICON_SIZE_COMPACT
OVERLAY_AUTHOR_STICKY = "author_sticky"
OVERLAY_AUTHOR_SHAPES = "author_shapes"
OVERLAY_AUTHOR_DRAW = "author_draw"
OVERLAY_AUTHOR_CONNECTOR = "author_connector"
OVERLAY_AUTHOR_FORMAT = "author_format"

def _author_tool_icon(
    tool: str,
    *,
    active: bool,
    draw_subtool: str = "pen",
    pointer_mode: str = POINTER_MODE_MOUSE,
) -> QIcon:
    """Return one compact outline icon. Draw stays a canonical pen on the rail."""
    del draw_subtool
    color = UV_SELECTED if active else UV_MUTED
    if str(tool) == AUTHOR_TOOL_SELECT and (
        active and normalize_pointer_mode(pointer_mode) == POINTER_MODE_LASER
    ):
        return Icons.ultraview_author_laser(color)
    factories = {
        AUTHOR_TOOL_SELECT: Icons.ultraview_author_select,
        AUTHOR_TOOL_STICKY: Icons.ultraview_author_sticky,
        AUTHOR_TOOL_TEXT: Icons.ultraview_author_text,
        AUTHOR_TOOL_SHAPES: Icons.ultraview_author_shapes,
        AUTHOR_TOOL_CONNECTOR: Icons.ultraview_author_connector,
        AUTHOR_TOOL_DRAW: Icons.ultraview_author_draw,
    }
    factory = factories.get(str(tool), Icons.ultraview_author_select)
    return factory(color)


class _AuthorToolButton(QToolButton):
    """A rail button that distinguishes a click from the pin gesture."""

    pin_requested = pyqtSignal(str)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.pin_requested.emit(str(self.property("authorTool") or ""))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _PointerToolButton(_AuthorToolButton):
    """One 40/36px tile whose complete hit area opens the pointer popover."""

    menu_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Mouse, QAbstractButton.click(), and macOS AXPress all emit clicked.
        # Keyboard Space/Enter are handled below so they share this slot
        # without QAbstractButton also synthesizing a second click().
        self.clicked.connect(self._on_standard_activate)

    def _on_standard_activate(self, _checked: bool = False) -> None:
        self.menu_requested.emit()

    def nextCheckState(self) -> None:  # noqa: N802
        """Keep checked/active state owned by ToolRail, not by this click."""
        return

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self.isEnabled():
            self._on_standard_activate()
            event.accept()
            return
        super().keyPressEvent(event)

def _rail_button(
    parent: QWidget,
    *,
    object_name: str,
    icon: QIcon,
    tooltip: str,
    accessible_name: str,
) -> QToolButton:
    return _icon_button(
        parent,
        object_name=object_name,
        icon=icon,
        tooltip=tooltip,
        accessible_name=accessible_name,
        size=RAIL_BUTTON_SIZE,
        icon_size=RAIL_ICON_SIZE,
    )


def _prepare_rail_pass_through(
    widget: QWidget, *, object_name: str | None = None
) -> None:
    """Keep a rail child from painting an opaque backing through the frost."""
    if object_name is not None:
        widget.setObjectName(object_name)
    widget.setAutoFillBackground(False)
    widget.setAttribute(Qt.WA_StyledBackground, False)
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    widget.setAttribute(Qt.WA_NoSystemBackground, True)
    widget.setProperty("railLayer", "passThrough")
    palette = widget.palette()
    palette.setColor(QPalette.Window, QColor(0, 0, 0, 0))
    palette.setColor(QPalette.Base, QColor(0, 0, 0, 0))
    widget.setPalette(palette)
    widget.setStyleSheet(
        'QWidget[railLayer="passThrough"] { background-color: transparent; }'
    )

class ToolRail(QFrame):
    """The fixed left rail; Page owns which requested panel opens.

    Empty-board CTA state is a local visual flag (``set_empty_board``).  The
    rail never reads ``UltraViewBoardState``; Page decides when the canvas
    has no placed cards.
    """

    panel_requested = pyqtSignal(str)
    tool_requested = pyqtSignal(str)
    tool_pinned_changed = pyqtSignal(str, bool)
    pointer_mode_requested = pyqtSignal(str)
    pointer_menu_requested = pyqtSignal()
    free_grid_toggled = pyqtSignal(bool)
    ref_dropped = pyqtSignal(str, str)
    sync_all_requested = pyqtSignal()

    _PANEL_SPECS: tuple[tuple[str, str, str, Callable[..., QIcon]], ...] = (
        (PANEL_LIBRARY, "Library", "打开 View 库", Icons.ultraview_library),
        (PANEL_LAYOUT, "Layout", "选择 Board 布局", Icons.ultraview_layout),
        (PANEL_FILTER, "Filter", "筛选可对比的 View", Icons.ultraview_filter),
        (PANEL_UNPLACED, "Unplaced", "查看未放置的 View", Icons.ultraview_unplaced),
    )
    _CREATION_SPECS: tuple[tuple[str, str, str], ...] = (
        (AUTHOR_TOOL_SELECT, "Pointer", "选择鼠标或激光笔 (V)"),
        (AUTHOR_TOOL_STICKY, "Sticky", "添加便签贴纸 (N)"),
        (AUTHOR_TOOL_TEXT, "Text", "添加文字 (T)"),
        (AUTHOR_TOOL_SHAPES, "Shapes", "形状与连接线 (S)"),
        (AUTHOR_TOOL_CONNECTOR, "Connector", "添加连接线 (L)"),
        (AUTHOR_TOOL_DRAW, "Draw", "钢笔、荧光笔、橡皮擦或套索 (P)"),
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        visible_author_tools: Sequence[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewToolRail")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # WA_TranslucentBackground disables this frame's QSS fill; paintEvent
        # owns the rounded frost so corner pixels stay transparent.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.Base, QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.setAcceptDrops(True)
        self.setProperty("surface", "island")
        self.setProperty("compact", "false")
        self.setFixedWidth(RAIL_WIDTH)
        self._compact = False
        self._buttons: dict[str, QToolButton] = {}
        self._tool_buttons: dict[str, _AuthorToolButton] = {}
        self._icon_factories: dict[str, Callable[..., QIcon]] = {}
        self._badges: dict[str, QLabel] = {}
        self._active_panel: str | None = None
        self._filter_active = False
        self._free_grid_enabled = False
        self._empty_board = False
        self._stale_count = 0
        self._creation_enabled = False
        self._creation_disabled_reason = "创作工具将在自由网格中可用"
        self._active_tool = AUTHOR_TOOL_SELECT
        self._pointer_mode = POINTER_MODE_MOUSE
        self._pointer_menu_open = False
        self._pinned_tool: str | None = None
        self._draw_subtool = DEFAULT_DRAW_SUBTOOL
        self._group_layouts: list[QVBoxLayout] = []
        self._divider_spacers: list[QWidget] = []
        self._syncing_rail = False
        # Release rail uses RELEASE_AUTHOR_TOOLS, which now includes Pointer.
        if visible_author_tools is None:
            allowed = set(RELEASE_AUTHOR_TOOLS)
        else:
            allowed = {str(tool) for tool in visible_author_tools}
        self._visible_author_tools = tuple(
            tool for tool, _short, _tip in self._CREATION_SPECS if tool in allowed
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(*RAIL_MARGINS)
        root.setSpacing(0)
        nav_group, nav_layout = self._make_rail_group()
        for index, (panel_id, short_name, tooltip, icon_factory) in enumerate(self._PANEL_SPECS):
            if index == 1:
                self._free_grid = _rail_button(
                    self,
                    object_name="ultraViewRailFreeGridButton",
                    icon=Icons.ultraview_free_grid(UV_MUTED),
                    tooltip="切换自由网格（12 列基准网格）",
                    accessible_name="切换自由网格（12 列基准网格）",
                )
                self._free_grid.setCheckable(True)
                self._free_grid.clicked.connect(self._on_free_grid_clicked)
                nav_layout.addWidget(self._free_grid, 0, Qt.AlignHCenter)
            if index == 3:
                root.addWidget(nav_group, 0, Qt.AlignHCenter)
                if self._visible_author_tools:
                    self._add_rail_divider(root, "ultraViewToolRailCreationDivider")
                    create_group, create_layout = self._make_rail_group()
                    self._add_creation_section(create_layout)
                    root.addWidget(create_group, 0, Qt.AlignHCenter)
                    self._add_rail_divider(root, "ultraViewToolRailPostCreationDivider")
                status_group, status_layout = self._make_rail_group()
            parent_layout = nav_layout if index < 3 else status_layout
            button = _rail_button(
                self,
                object_name=f"ultraViewRail{short_name}Button",
                icon=icon_factory(UV_MUTED),
                tooltip=tooltip,
                accessible_name=tooltip,
            )
            button.setProperty("panel", panel_id)
            button.setCheckable(True)
            button.clicked.connect(self._on_panel_clicked)
            self._buttons[panel_id] = button
            self._icon_factories[panel_id] = icon_factory
            parent_layout.addWidget(button, 0, Qt.AlignHCenter)
            badge = QLabel(self)
            badge.setObjectName(f"ultraViewRail{short_name}Badge")
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            badge.setAlignment(Qt.AlignCenter)
            badge.setMinimumSize(14, 14)
            badge.setMaximumHeight(RAIL_BADGE_MAX_HEIGHT)
            badge.setProperty("role", "badge")
            badge.hide()
            self._badges[panel_id] = badge
        self._filter_warning = False
        self._filter_dot = QLabel(self)
        self._filter_dot.setObjectName("ultraViewRailFilterWarningDot")
        self._filter_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._filter_dot.setFixedSize(8, 8)
        self._filter_dot.setToolTip("轴量纲或范围不一致")
        self._filter_dot.setAccessibleName("轴一致性警告")
        self._filter_dot.hide()
        self._sync_all = _rail_button(
            self,
            object_name="ultraViewRailSyncAllButton",
            icon=Icons.ultraview_sync(UV_MUTED),
            tooltip="一键更新源",
            accessible_name="一键更新全部已变化的预览",
        )
        self._sync_all.clicked.connect(self._on_sync_all_clicked)
        status_layout.addWidget(self._sync_all, 0, Qt.AlignHCenter)
        root.addWidget(status_group, 0, Qt.AlignHCenter)
        self._sync_all_badge = QLabel(self)
        self._sync_all_badge.setObjectName("ultraViewRailSyncAllBadge")
        self._sync_all_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._sync_all_badge.setAlignment(Qt.AlignCenter)
        self._sync_all_badge.setMinimumSize(14, 14)
        self._sync_all_badge.setMaximumHeight(RAIL_BADGE_MAX_HEIGHT)
        self._sync_all_badge.setProperty("role", "badge")
        self._sync_all_badge.hide()
        self.set_stale_count(0)
        self.set_active_panel(None)
        self._sync_creation_states()

    def panel_button(self, panel_id: str) -> QToolButton | None:
        return self._buttons.get(str(panel_id))

    def free_grid_button(self) -> QToolButton:
        return self._free_grid

    def tool_button(self, tool: str) -> QToolButton | None:
        """Return a creation-tool button without exposing its panel siblings."""
        return self._tool_buttons.get(str(tool))

    def visible_author_tools(self) -> tuple[str, ...]:
        """Tools actually constructed on this rail. Release includes Pointer."""
        return self._visible_author_tools

    def visible_enabled_author_tools(self) -> tuple[str, ...]:
        return tuple(
            tool
            for tool, button in self._tool_buttons.items()
            if button.isVisible() and button.isEnabled()
        )

    def creation_section_visible(self) -> bool:
        return bool(self._visible_author_tools) and any(
            button.isVisible() for button in self._tool_buttons.values()
        )

    def active_tool(self) -> str:
        return self._active_tool

    def pinned_tool(self) -> str | None:
        return self._pinned_tool

    def set_creation_enabled(self, enabled: bool, reason: str = "") -> None:
        """Gate the visible creation section for template/presentation states.

        Page supplies the reason so disabled chrome remains explanatory rather
        than looking like an unavailable implementation stub.
        """
        self._creation_enabled = bool(enabled)
        self._creation_disabled_reason = str(reason or "创作工具仅在自由网格中可用")
        if not self._creation_enabled:
            self._active_tool = AUTHOR_TOOL_SELECT
            self._pinned_tool = None
        self._sync_creation_states()

    set_authoring_enabled = set_creation_enabled

    def set_active_tool(self, tool: str, *, pinned: bool = False) -> None:
        checked = str(tool)
        if checked not in self._tool_buttons:
            if checked == AUTHOR_TOOL_SELECT:
                self._active_tool = AUTHOR_TOOL_SELECT
                self._pinned_tool = None
                self._sync_creation_states()
                return
            raise ValueError(f"unknown authoring tool: {checked}")
        self._active_tool = checked
        self._pinned_tool = checked if pinned and checked != AUTHOR_TOOL_SELECT else None
        self._sync_creation_states()

    def pointer_mode(self) -> str:
        return self._pointer_mode

    def set_pointer_mode(self, mode: str) -> None:
        """Project the interaction owner's pointer mode onto the Pointer tile."""
        checked = normalize_pointer_mode(mode)
        if self._pointer_mode == checked:
            return
        self._pointer_mode = checked
        self._sync_creation_states()

    def set_pointer_menu_open(self, opened: bool) -> None:
        """Mirror CanvasHost pointer-popup visibility onto the Pointer tile."""
        wanted = bool(opened)
        if self._pointer_menu_open == wanted:
            return
        self._pointer_menu_open = wanted
        self._sync_creation_states()

    def set_draw_subtool(self, tool: str) -> None:
        checked = normalize_draw_subtool(tool)
        if self._draw_subtool == checked:
            return
        self._draw_subtool = checked
        self._sync_creation_states()

    def draw_subtool(self) -> str:
        return self._draw_subtool

    def make_pointer_popover(self, parent: QWidget | None = None) -> PointerPopover:
        return PointerPopover(parent or self)

    def make_sticky_popover(self, parent: QWidget | None = None) -> StickyPopover:
        return StickyPopover(parent or self)

    def make_shape_popover(self, parent: QWidget | None = None) -> ShapePopover:
        return ShapePopover(parent or self)

    def make_connector_popover(self, parent: QWidget | None = None) -> ConnectorPopover:
        return ConnectorPopover(parent or self)

    def make_draw_popover(self, parent: QWidget | None = None) -> DrawPopover:
        return DrawPopover(parent or self)

    def sync_all_button(self) -> QToolButton:
        return self._sync_all

    def set_stale_count(self, count: int) -> None:
        """Show how many Board previews are stale; zero disables the action."""
        try:
            value = max(0, int(count or 0))
        except (TypeError, ValueError):
            value = 0
        self._stale_count = value
        self._sync_all.setEnabled(value > 0)
        _set_flag(self._sync_all, "attention", value > 0)
        badge = self._sync_all_badge
        badge.setText(str(value) if value else "")
        badge.setToolTip(f"{value} 个预览源已变化" if value else "")
        badge.setAccessibleName(f"已变化预览：{value}" if value else "")
        if value > 0:
            badge.adjustSize()
            hint = badge.sizeHint()
            badge.resize(
                max(14, min(hint.width(), 22)),
                min(RAIL_BADGE_MAX_HEIGHT, max(14, hint.height())),
            )
            badge.show()
        else:
            badge.hide()
        self._sync_all.setToolTip(
            "一键更新源" if value else "没有需要更新的预览"
        )
        self._sync_all.setAccessibleName(
            "一键更新全部已变化的预览" if value else "一键更新源（当前没有已变化预览）"
        )
        self._sync_all.setIcon(
            Icons.ultraview_sync(_ultraview_icon_color(active=value > 0))
        )
        self._position_badges()

    def stale_count(self) -> int:
        return self._stale_count

    def active_panel(self) -> str | None:
        return self._active_panel

    def set_active_panel(self, panel_id: str | None) -> None:
        key = str(panel_id) if panel_id is not None else None
        if key not in self._buttons:
            key = None
        self._active_panel = key
        self._sync_button_states()

    def set_filter_active(self, active: bool) -> None:
        """Keep a non-``all`` compare filter discoverable after closing it."""
        self._filter_active = bool(active)
        self._sync_button_states()

    def set_filter_warning(self, warning: bool) -> None:
        """Show the funnel warning dot while axis facts are inconsistent."""
        self._filter_warning = bool(warning)
        self._filter_dot.setVisible(self._filter_warning)
        if self._filter_warning:
            self._position_badges()

    def filter_warning(self) -> bool:
        return self._filter_warning

    def set_free_grid_enabled(self, enabled: bool) -> None:
        """Project the current free-grid mode without emitting the toggle."""
        self._free_grid_enabled = bool(enabled)
        self._sync_button_states()

    def set_empty_board(self, empty: bool) -> None:
        """Paint View 库 as the empty-canvas primary CTA; retracts once cards exist."""
        wanted = bool(empty)
        if self._empty_board == wanted:
            return
        self._empty_board = wanted
        self._sync_button_states()

    def _rail_icon_buttons(self) -> tuple[QToolButton, ...]:
        buttons = [
            *self._buttons.values(),
            *self._tool_buttons.values(),
            getattr(self, "_free_grid", None),
            getattr(self, "_sync_all", None),
        ]
        return tuple(button for button in buttons if button is not None)

    def _primary_fill_button(self) -> QToolButton | None:
        """One rail tile may own the selected-blue wash.

        Priority: author active (including Pointer) > open panel > empty-board
        CTA > persistent mode. Filter persistence, warning dots, and count
        badges are never primary.
        """
        if self._creation_enabled and self._active_tool in self._tool_buttons:
            return self._tool_buttons.get(self._active_tool)
        if self._active_panel in self._buttons:
            return self._buttons[self._active_panel]
        if self._empty_board:
            return self._buttons.get(PANEL_LIBRARY)
        if self._free_grid_enabled:
            return self._free_grid
        return self._buttons.get(PANEL_LAYOUT)

    def _sync_primary_fill(self) -> None:
        owner = self._primary_fill_button()
        for button in self._rail_icon_buttons():
            _set_flag(button, "primaryFill", button is owner)

    def _sync_button_states(self) -> None:
        self._syncing_rail = True
        try:
            self._sync_button_states_inner()
        finally:
            self._syncing_rail = False

    def _sync_button_states_inner(self) -> None:
        for candidate, button in self._buttons.items():
            mode_active = (
                candidate == PANEL_FILTER and self._filter_active
            ) or (
                candidate == PANEL_LAYOUT and not self._free_grid_enabled
            )
            panel_open = candidate == self._active_panel
            empty_cta = candidate == PANEL_LIBRARY and self._empty_board
            _set_flag(button, "modeActive", mode_active)
            _set_flag(button, "panelOpen", panel_open)
            _set_flag(button, "emptyCta", empty_cta)
            _set_flag(button, "active", False)
            button.setChecked(panel_open)
            factory = self._icon_factories.get(candidate)
            if factory is not None:
                filled = button is self._primary_fill_button()
                if filled:
                    button.setIcon(factory(UV_PRESENTATION_ICON))
                else:
                    button.setIcon(
                        factory(_ultraview_icon_color(active=mode_active or panel_open))
                    )
        blocked = self._free_grid.blockSignals(True)
        self._free_grid.setChecked(self._free_grid_enabled)
        self._free_grid.blockSignals(blocked)
        _set_flag(self._free_grid, "modeActive", self._free_grid_enabled)
        _set_flag(self._free_grid, "panelOpen", False)
        _set_flag(self._free_grid, "active", False)
        filled_free = self._free_grid is self._primary_fill_button()
        self._free_grid.setIcon(
            Icons.ultraview_free_grid(
                UV_PRESENTATION_ICON if filled_free else (
                    UV_BRAND if self._free_grid_enabled else UV_MUTED
                )
            )
        )
        sync_all = getattr(self, "_sync_all", None)
        if sync_all is not None:
            sync_all.setIcon(
                Icons.ultraview_sync(
                    _ultraview_icon_color(active=self._stale_count > 0)
                )
            )
        self._sync_primary_fill()

    def _sync_creation_states(self) -> None:
        for tool, button in self._tool_buttons.items():
            is_active = self._creation_enabled and tool == self._active_tool
            is_pinned = self._creation_enabled and tool == self._pinned_tool
            button.setEnabled(self._creation_enabled)
            button.setChecked(is_active)
            button.setToolTip(
                button.accessibleName() if self._creation_enabled else self._creation_disabled_reason
            )
            _set_flag(button, "active", is_active)
            _set_flag(button, "pinned", is_pinned)
            _set_flag(button, "modeActive", False)
            pointer_open = tool == AUTHOR_TOOL_SELECT and self._pointer_menu_open
            _set_flag(button, "panelOpen", pointer_open)
            _set_flag(button, "open", pointer_open)
            button.setIcon(
                _author_tool_icon(
                    tool,
                    active=is_active,
                    draw_subtool=self._draw_subtool,
                    pointer_mode=self._pointer_mode,
                )
            )
        if not self._syncing_rail:
            self._sync_button_states()

    def _group_gap(self) -> int:
        return RAIL_GROUP_GAP_COMPACT if self._compact else RAIL_GROUP_GAP

    def _divider_clear(self) -> int:
        return RAIL_DIVIDER_CLEAR_COMPACT if self._compact else RAIL_DIVIDER_CLEAR

    def _make_rail_group(self) -> tuple[QWidget, QVBoxLayout]:
        host = QWidget(self)
        _prepare_rail_pass_through(host, object_name="ultraViewToolRailGroup")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self._group_gap())
        self._group_layouts.append(layout)
        return host, layout

    def _add_rail_divider(self, layout: QVBoxLayout, object_name: str) -> None:
        wrap = QWidget(self)
        _prepare_rail_pass_through(wrap, object_name=f"{object_name}Wrap")
        wrap.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        inner = QVBoxLayout(wrap)
        clear = self._divider_clear()
        inner.setContentsMargins(RAIL_DIVIDER_INSET, clear, RAIL_DIVIDER_INSET, clear)
        inner.setSpacing(0)
        divider = QFrame(wrap)
        divider.setObjectName(object_name)
        divider.setFrameShape(QFrame.NoFrame)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(50, 86, 97, 59); border: 0;")
        inner.addWidget(divider)
        layout.addWidget(wrap, 0)
        self._divider_spacers.append(wrap)

    def _add_creation_section(self, layout: QVBoxLayout) -> None:
        specs = {
            tool: (short_name, tooltip)
            for tool, short_name, tooltip in self._CREATION_SPECS
        }
        for tool in self._visible_author_tools:
            short_name, tooltip = specs[tool]
            if tool == AUTHOR_TOOL_SELECT:
                button = _PointerToolButton(self)
                button.menu_requested.connect(self._on_pointer_menu_requested)
            else:
                button = _AuthorToolButton(self)
            button.setObjectName(f"ultraViewRail{short_name}Button")
            button.setIcon(
                _author_tool_icon(
                    tool,
                    active=False,
                    draw_subtool=self._draw_subtool,
                    pointer_mode=self._pointer_mode,
                )
            )
            button.setIconSize(QSize(RAIL_ICON_SIZE, RAIL_ICON_SIZE))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setAutoRaise(True)
            button.setAutoFillBackground(False)
            button.setAttribute(Qt.WA_StyledBackground, True)
            button.setFixedSize(RAIL_BUTTON_SIZE, RAIL_BUTTON_SIZE)
            button.setFocusPolicy(Qt.TabFocus)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setProperty("role", "icon")
            button.setProperty("chrome", "ultraview")
            button.setProperty("authorTool", tool)
            button.setProperty("active", "false")
            button.setProperty("pinned", "false")
            button.setProperty("modeActive", "false")
            button.setProperty("panelOpen", "false")
            button.setProperty("primaryFill", "false")
            button.setCheckable(True)
            if tool == AUTHOR_TOOL_SELECT:
                button.setProperty("open", "false")
                # Pointer deliberately does not apply its last mode on click:
                # Mouse and Laser are explicit choices in the CanvasHost flyout.
                # Do not connect clicked here — _PointerToolButton already
                # routes clicked → menu_requested, and a second connection
                # would double-fire.
                pass
            else:
                button.clicked.connect(self._on_tool_clicked)
                button.pin_requested.connect(self._on_tool_pin_requested)
            self._tool_buttons[tool] = button
            layout.addWidget(button, 0, Qt.AlignHCenter)

    def set_badge(self, panel_id: str, count: int | None) -> None:
        """Set an exact count badge; zero/None intentionally shows no badge."""
        key = str(panel_id)
        badge = self._badges.get(key)
        if badge is None:
            raise KeyError(key)
        try:
            value = max(0, int(count or 0))
        except (TypeError, ValueError):
            value = 0
        badge.setText(str(value))
        badge.setToolTip(f"{value} 个未放置 View" if value else "")
        badge.setAccessibleName(f"未放置 View：{value}" if value else "")
        if value > 0:
            badge.adjustSize()
            hint = badge.sizeHint()
            badge.resize(max(14, min(hint.width(), 22)), min(RAIL_BADGE_MAX_HEIGHT, max(14, hint.height())))
            badge.show()
        else:
            badge.hide()
        self._position_badges()

    def badge_text(self, panel_id: str) -> str:
        badge = self._badges.get(str(panel_id))
        return badge.text() if badge is not None else ""

    def set_panel_attention(self, panel_id: str, attention: bool) -> None:
        button = self._buttons.get(str(panel_id))
        if button is None:
            raise KeyError(str(panel_id))
        _set_flag(button, "attention", bool(attention))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_badges()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect().adjusted(0, 0, -1, -1)),
            float(RAIL_RADIUS),
            float(RAIL_RADIUS),
        )
        painter.fillPath(path, UV_FROST)
        painter.setPen(QPen(UV_LINE_STRONG, 1.0))
        painter.drawPath(path)

    def set_compact(self, compact: bool) -> None:
        """Switch every rail icon between desktop 40px and compact 36px."""
        self._compact = bool(compact)
        width = RAIL_WIDTH_COMPACT if self._compact else RAIL_WIDTH
        self.setFixedWidth(width)
        size = RAIL_BUTTON_SIZE_COMPACT if self._compact else RAIL_BUTTON_SIZE
        icon = RAIL_ICON_SIZE_COMPACT if self._compact else RAIL_ICON_SIZE
        margins = RAIL_MARGINS_COMPACT if self._compact else RAIL_MARGINS
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(*margins)
        gap = self._group_gap()
        for group in self._group_layouts:
            group.setSpacing(gap)
        clear = self._divider_clear()
        for wrap in self._divider_spacers:
            inner = wrap.layout()
            if inner is not None:
                inner.setContentsMargins(RAIL_DIVIDER_INSET, clear, RAIL_DIVIDER_INSET, clear)
        _set_flag(self, "compact", self._compact)
        for button in self._rail_icon_buttons():
            button.setFixedSize(size, size)
            button.setIconSize(QSize(icon, icon))
            _repolish(button)

    def is_compact(self) -> bool:
        return self._compact

    def sizeHint(self) -> QSize:  # noqa: N802
        width = RAIL_WIDTH_COMPACT if self._compact else RAIL_WIDTH
        return QSize(width, max(RAIL_CONTENT_HEIGHT, super().sizeHint().height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _button_origin(self, button: QWidget) -> QPoint:
        return button.mapTo(self, QPoint(0, 0))

    def _position_badge_on_button(self, badge: QLabel, button: QToolButton) -> None:
        origin = self._button_origin(button)
        width = min(max(14, badge.width()), 22)
        height = min(RAIL_BADGE_MAX_HEIGHT, max(14, badge.height()))
        badge.resize(width, height)
        x = origin.x() + button.width() - width - RAIL_BADGE_INSET
        y = origin.y() + RAIL_BADGE_INSET
        x = min(max(0, x), max(0, self.width() - width))
        y = min(max(0, y), max(0, origin.y() + button.height() - height - RAIL_BADGE_INSET))
        badge.move(x, y)
        badge.raise_()

    def _position_badges(self) -> None:
        for panel_id, badge in self._badges.items():
            button = self._buttons[panel_id]
            if badge.isHidden():
                continue
            self._position_badge_on_button(badge, button)
        button = self._buttons.get(PANEL_FILTER)
        if button is not None and not self._filter_dot.isHidden():
            origin = self._button_origin(button)
            x = min(max(0, origin.x() + button.width() - 8 - RAIL_BADGE_INSET), max(0, self.width() - 8))
            y = origin.y() + RAIL_BADGE_INSET
            self._filter_dot.move(x, y)
            self._filter_dot.raise_()
        badge = getattr(self, "_sync_all_badge", None)
        button = getattr(self, "_sync_all", None)
        if badge is not None and button is not None and not badge.isHidden():
            self._position_badge_on_button(badge, button)

    def _on_panel_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        panel_id = str(button.property("panel") or "")
        if panel_id in self._buttons:
            self.panel_requested.emit(panel_id)

    def _on_tool_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton) or not self._creation_enabled:
            return
        tool = str(button.property("authorTool") or "")
        if tool not in self._tool_buttons:
            return
        if tool != self._active_tool:
            self.set_active_tool(tool, pinned=False)
        self.tool_requested.emit(tool)

    def _on_pointer_menu_requested(self) -> None:
        if not self._creation_enabled:
            return
        self.pointer_menu_requested.emit()

    def _on_tool_pin_requested(self, tool: str) -> None:
        checked = str(tool)
        if not self._creation_enabled or checked not in self._tool_buttons:
            return
        now_pinned = checked != self._pinned_tool
        self.set_active_tool(checked, pinned=now_pinned)
        self.tool_pinned_changed.emit(checked, now_pinned)

    def _on_free_grid_clicked(self) -> None:
        self.free_grid_toggled.emit(self._free_grid.isChecked())

    def _on_sync_all_clicked(self) -> None:
        self.sync_all_requested.emit()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(ULTRAVIEW_REF_MIME):
            self.set_panel_attention(PANEL_UNPLACED, True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_panel_attention(PANEL_UNPLACED, False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_panel_attention(PANEL_UNPLACED, False)
        try:
            raw = bytes(event.mimeData().data(ULTRAVIEW_REF_MIME)).decode("utf-8")
            ref = parse_ref_payload(json.loads(raw))
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            ref = None
        if ref is None:
            event.ignore()
            return
        self.ref_dropped.emit(ref.section, ref.view_id)
        event.acceptProposedAction()

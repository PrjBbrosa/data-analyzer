"""Excel-style time-domain View tab bar.

The widget renders the ViewManager state and emits user intent only. It does
not mutate the manager directly, leaving capture/apply and manager operations to
the integration layer.
"""
from __future__ import annotations

from PyQt5.QtCore import (
    QDateTime,
    QEvent,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionTab,
    QTabBar,
    QToolTip,
    QWidget,
)

from . import hints
from ..ui_kit.icons import Icons, icon_device_pixel_ratio
from ..ui_kit.menus import apply_rounded_menu_chrome
from .view_state import MAX_VIEWS
from .widgets.view_overflow_popup import ViewOverflowPopup, ViewOverflowRow

_KEEP_ONE_VIEW_TIP = "至少保留一个 View"
_CLOSE_INK = QColor("#bf3447")
_CLOSE_SOFT = QColor("#fff0f2")
_CLOSE_BORDER = QColor("#e5a8b0")
_CLOSE_PRESSED = QColor("#ffe3e7")
_CLOSE_VISUAL_SIZE = 18
_CLOSE_HIT_SIZE = 20

# Shared bottom-rail band (TimeDomain dock + analysis compare row). The
# 26px tab strip is vertically centered inside this; the left navigator's
# 28px config controls plus a 2px host inset match the same 30px band.
RAIL_HEIGHT = 30

# Quiet section identity for the shared ViewTabBar. Keys match ChartStack /
# AnalysisSectionPage mode ids; display lives here so callers never assemble
# labels or invent colors. View tab_color stays a View identity cue only.
_SECTION_ANCHORS = {
    "time": ("时域", Icons.mode_time),
    "fft": ("频谱", Icons.mode_fft),
    "fft_time": ("时频", Icons.mode_fft_time),
    "frf": ("频响", Icons.mode_frf),
    "order": ("阶次", Icons.mode_order),
}


def tab_icon_slot_rect(tabbar: QTabBar, index: int) -> QRect:
    """Return the stable icon-cell anchor for ``index``.

    PyQt5 does not wrap ``SE_TabBarTabIcon``. The slot is the ``iconSize``
    band reserved immediately left of ``SE_TabBarTabText`` (falling back to
    ``PM_TabBarTabHSpace``). It is an anchor only: the close visual and its hit
    target are both derived from :func:`tab_close_hit_rect` so platform icon
    painting can never drift away from pointer routing.
    """
    if index < 0 or index >= tabbar.count():
        return QRect()
    opt = QStyleOptionTab()
    tabbar.initStyleOption(opt, index)
    tab_rect = tabbar.tabRect(index)
    if not tab_rect.isValid():
        return QRect()
    icon_size = QSize(opt.iconSize) if opt.iconSize.isValid() else QSize(tabbar.iconSize())
    if icon_size.width() <= 0 or icon_size.height() <= 0:
        icon_size = QSize(
            tabbar.style().pixelMetric(QStyle.PM_TabBarIconSize, opt, tabbar),
            tabbar.style().pixelMetric(QStyle.PM_TabBarIconSize, opt, tabbar),
        )
    style = tabbar.style()
    text_rect = style.subElementRect(QStyle.SE_TabBarTabText, opt, tabbar)
    if text_rect.isValid() and text_rect.left() >= tab_rect.left() + icon_size.width():
        x = text_rect.left() - icon_size.width()
    else:
        hspace = style.pixelMetric(QStyle.PM_TabBarTabHSpace, opt, tabbar)
        x = tab_rect.left() + max(0, hspace // 2)
    y = tab_rect.center().y() - icon_size.height() // 2
    return QRect(x, y, icon_size.width(), icon_size.height()).intersected(tab_rect)


def _centered_square(center, side: int) -> QRect:
    rect = QRect(0, 0, int(side), int(side))
    rect.moveCenter(center)
    return rect


def _centered_rect(center, width: int, height: int) -> QRect:
    rect = QRect(0, 0, int(width), int(height))
    rect.moveCenter(center)
    return rect


def tab_close_hit_rect(tabbar: QTabBar, index: int) -> QRect:
    """Return the single 20×20 pointer target used by every close event."""
    anchor = tab_icon_slot_rect(tabbar, index)
    if not anchor.isValid():
        return QRect()
    return _centered_square(anchor.center(), _CLOSE_HIT_SIZE).intersected(
        tabbar.tabRect(index)
    )


def tab_close_visual_rect(tabbar: QTabBar, index: int) -> QRect:
    """Return the 18×18 rounded-square paint rect centered in the hit target."""
    hit = tab_close_hit_rect(tabbar, index)
    if not hit.isValid():
        return QRect()
    return _centered_square(hit.center(), _CLOSE_VISUAL_SIZE)


def tab_swatch_visual_rect(tabbar: QTabBar, index: int) -> QRect:
    """Return the normal 10×6 swatch rect using the close target's center."""
    hit = tab_close_hit_rect(tabbar, index)
    if not hit.isValid():
        return QRect()
    return _centered_rect(hit.center(), 10, 6)


class _ViewTabs(QTabBar):
    """Owns icon-slot hover/armed state and consumes close-slot mouse events."""

    close_slot_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self._hover_index = -1
        self._armed_view_id = None
        self._last_close_view_id = None
        self._last_close_msecs = 0

    def clear_interaction_state(self) -> None:
        old_hover = self._hover_index
        self._hover_index = -1
        self._armed_view_id = None
        if old_hover >= 0:
            self._update_close_region(old_hover)

    def hover_index(self) -> int:
        return self._hover_index

    def armed_view_id(self):
        return self._armed_view_id

    def event(self, event):
        etype = event.type()
        if etype in (QEvent.HoverMove, QEvent.HoverEnter):
            self._update_hover(event.pos())
        elif etype == QEvent.HoverLeave:
            self._update_hover(None)
        elif etype == QEvent.ToolTip:
            if self._handle_close_tooltip(event):
                return True
        elif etype == QEvent.MouseButtonDblClick:
            if self._consume_close_double_click(event):
                return True
        return super().event(event)

    def leaveEvent(self, event):
        self._update_hover(None)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.clear_interaction_state()
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        bar = self._bar()
        if bar is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        for idx in range(min(self.count(), len(bar._manager.views))):
            if not self.isTabVisible(idx):
                continue
            tab_rect = self.tabRect(idx)
            if not tab_rect.isValid() or not event.rect().intersects(tab_rect):
                continue
            if idx == self._hover_index and bar._views_closable():
                rect = tab_close_visual_rect(self, idx)
                pressed = self._armed_view_id == bar._view_id_at(idx)
                _paint_tab_close_button(painter, QRectF(rect), pressed=pressed)
                continue
            _paint_tab_swatch(
                painter,
                QRectF(tab_swatch_visual_rect(self, idx)),
                self.tabData(idx),
                bar._partner_color_for(idx),
            )
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx, in_slot = self._hit_close_slot(event.pos())
            if in_slot:
                bar = self._bar()
                if bar is not None and bar._views_closable():
                    view_id = bar._view_id_at(idx)
                    if view_id and not self._is_double_close_repeat(view_id):
                        self._armed_view_id = view_id
                        self._hover_index = idx
                        self._update_close_region(idx)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._update_hover(event.pos())
        if self._armed_view_id is not None:
            idx, in_slot = self._hit_close_slot(event.pos())
            bar = self._bar()
            if not in_slot or (
                bar is not None and bar._view_id_at(idx) != self._armed_view_id
            ):
                armed_idx = self._index_for_view_id(self._armed_view_id)
                self._armed_view_id = None
                self._update_close_region(armed_idx)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._armed_view_id is not None:
            idx, in_slot = self._hit_close_slot(event.pos())
            view_id = self._armed_view_id
            self._armed_view_id = None
            bar = self._bar()
            self._update_close_region(idx)
            if (
                in_slot
                and bar is not None
                and bar._view_id_at(idx) == view_id
                and bar._views_closable()
            ):
                self._last_close_view_id = view_id
                self._last_close_msecs = QDateTime.currentMSecsSinceEpoch()
                self.close_slot_clicked.emit(idx)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _consume_close_double_click(self, event) -> bool:
        idx, in_slot = self._hit_close_slot(event.pos())
        recent_close = bool(
            self._last_close_view_id
            and self._is_double_close_repeat(self._last_close_view_id)
        )
        if not (in_slot or recent_close):
            return False
        bar = self._bar()
        if (
            bar is not None
            and bar._views_closable()
            and event.button() == Qt.LeftButton
            and in_slot
        ):
            view_id = bar._view_id_at(idx)
            if view_id and not self._is_double_close_repeat(view_id):
                self._last_close_view_id = view_id
                self._last_close_msecs = QDateTime.currentMSecsSinceEpoch()
                self.close_slot_clicked.emit(idx)
        return True

    def _bar(self):
        parent = self.parentWidget()
        return parent if isinstance(parent, ViewTabBar) else None

    def _hit_close_slot(self, pos) -> tuple[int, bool]:
        idx = self.tabAt(pos)
        if idx < 0:
            return -1, False
        slot = tab_close_hit_rect(self, idx)
        return idx, slot.contains(pos)

    def _index_for_view_id(self, view_id) -> int:
        if not view_id:
            return -1
        bar = self._bar()
        if bar is None:
            return -1
        for idx in range(self.count()):
            if bar._view_id_at(idx) == view_id:
                return idx
        return -1

    def _update_close_region(self, idx: int) -> None:
        if idx < 0 or idx >= self.count():
            return
        self.update(tab_close_hit_rect(self, idx).adjusted(-1, -1, 1, 1))

    def _update_hover(self, pos) -> None:
        bar = self._bar()
        new_index = -1
        if pos is not None and bar is not None and bar._views_closable():
            idx, in_slot = self._hit_close_slot(pos)
            if in_slot:
                new_index = idx
        if new_index == self._hover_index:
            return
        old = self._hover_index
        self._hover_index = new_index
        if old >= 0:
            self._update_close_region(old)
        if new_index >= 0:
            self._update_close_region(new_index)

    def _handle_close_tooltip(self, event) -> bool:
        idx, in_slot = self._hit_close_slot(event.pos())
        if not in_slot:
            return False
        bar = self._bar()
        if bar is None:
            return False
        name = bar._view_name(idx)
        text = (
            f"关闭 View「{name}」"
            if bar._views_closable()
            else _KEEP_ONE_VIEW_TIP
        )
        QToolTip.showText(event.globalPos(), text, self, tab_close_hit_rect(self, idx))
        return True

    def _is_double_close_repeat(self, view_id: str) -> bool:
        if self._last_close_view_id != view_id:
            return False
        interval = QApplication.doubleClickInterval()
        return (
            QDateTime.currentMSecsSinceEpoch() - self._last_close_msecs
        ) <= interval


class ViewTabBar(QWidget):
    switch_requested = pyqtSignal(int)
    new_requested = pyqtSignal()
    delete_requested = pyqtSignal(int)
    overflow_delete_requested = pyqtSignal(int)
    close_others_requested = pyqtSignal(str)
    close_all_requested = pyqtSignal()
    rename_requested = pyqtSignal(int, str)
    duplicate_requested = pyqtSignal(int)
    color_requested = pyqtSignal(int)
    reorder_requested = pyqtSignal(int, int)
    split_requested = pyqtSignal(int)
    clear_split_requested = pyqtSignal(int)
    add_to_ultraview_requested = pyqtSignal(str, str)

    def __init__(
        self,
        manager,
        parent=None,
        *,
        section=None,
        split_action_labels=None,
        split_action_mode='view_pair',
        active_split_provider=None,
    ):
        super().__init__(parent)
        self.setObjectName("viewTabBar")
        self.setFocusPolicy(Qt.StrongFocus)
        self._manager = manager
        self._section_key = None
        self._section_anchor = None
        self._split_action_labels = {
            'split': "与此 View 并排",
            'replace': "与此 View 并排（替换当前合并）",
            'clear': "取消合并",
        }
        if split_action_labels:
            self._split_action_labels.update(split_action_labels)
        self._split_action_mode = str(split_action_mode)
        self._active_split_provider = active_split_provider
        self._suppress = False
        self._rename_editor = None
        self._rename_index = -1
        self._secondary_focused = False
        self._suppress_switch_after_reorder = False
        # True only while a drag-reorder's tabMoved is being handled, so the
        # views_changed → refresh() it triggers skips the destructive rebuild
        # (which crashes mid-drag). See _on_tab_moved / refresh.
        self._reordering = False
        # Fit state, recomputed by _sync_tabbar_width from MEASURED widths.
        # _density_compact: labels are the ordinal only, full name in tooltip.
        # _overflow_indices: View indices retired into the » menu (tabs still
        # exist, they are only setTabVisible(False) — see _retire_tail_tabs).
        self._density_compact = False
        self._overflow_indices: list[int] = []
        # Set by _on_tab_moved, consumed on the drag's mouse release: a drag
        # scrambles the compact ordinals and refresh() is banned mid-drag.
        self._pending_reorder_resync = False
        # One QSettings write per session for the view.compact_tabs footer hint
        # — see _mark_compact_tabs_discovered.
        self._compact_tabs_discovered = False
        self._overflow_popup = None
        self._overflow_popup_closed_msecs = 0
        self._tab_spacer_icon = _tab_spacer_icon()
        self.setFixedHeight(RAIL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        right_margin = 4 if self._split_action_mode == 'active_pane' else 8
        # 2px top/bottom centers the 26px tab strip in the 30px rail.
        layout.setContentsMargins(8, 2, right_margin, 2)
        layout.setSpacing(2)

        if section is not None:
            self._section_anchor = self._make_section_anchor(section)
            layout.addWidget(self._section_anchor, 0, Qt.AlignVCenter)

        self._tabs = _ViewTabs(self)
        self._tabs.setObjectName("viewTabs")
        self._tabs.setMovable(True)
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setDrawBase(False)
        self._tabs.setShape(QTabBar.RoundedSouth)
        self._tabs.setFixedHeight(26)
        self._tabs.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        # Seeded so the QSS density rule has an explicit state from the start
        # (_set_density flips it); the roomy box lives in the unqualified
        # ::tab rule, so "roomy" simply matches nothing extra.
        self._tabs.setProperty("density", "roomy")
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.tabBarDoubleClicked.connect(self._on_double_clicked)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        self._tabs.customContextMenuRequested.connect(self._on_context_menu)
        self._tabs.close_slot_clicked.connect(self.delete_requested.emit)
        # Watched for the mouse release that ends a drag-reorder; see eventFilter.
        self._tabs.installEventFilter(self)
        layout.addWidget(self._tabs, 0, Qt.AlignVCenter)

        if self._section_anchor is not None:
            # Same typeface metrics as View tabs so "时域"/"频谱" share the
            # Latin "View N" optical line (QLabel defaults can differ).
            label = self._section_anchor.findChild(QLabel, "viewSectionAnchorLabel")
            if label is not None:
                label.setFont(self._tabs.font())

        # Part of the fixed right-hand group: like _plus it never compresses,
        # it is only shown when tabs had to be retired. Hidden widgets are
        # skipped by QHBoxLayout, so it costs nothing while everything fits.
        self._overflow = QPushButton("»", self)
        self._overflow.setObjectName("viewTabOverflow")
        self._overflow.setCursor(Qt.PointingHandCursor)
        self._overflow.setVisible(False)
        self._overflow.clicked.connect(self._on_overflow_clicked)
        layout.addWidget(self._overflow, 0, Qt.AlignVCenter)

        self._plus = QPushButton("+", self)
        self._plus.setObjectName("viewTabPlus")
        self._plus.setToolTip("新建 View")
        self._plus.setFixedSize(24, 22)
        self._plus.clicked.connect(self._on_plus_clicked)
        layout.addWidget(self._plus, 0, Qt.AlignVCenter)
        layout.addStretch(1)

        self._split_chip = QLabel(self)
        self._split_chip.setObjectName("viewSplitChip")
        self._split_clear = QPushButton("✕ 取消合并", self)
        self._split_clear.setObjectName("viewSplitClear")
        self._split_clear.setProperty("variant", "softDanger")
        self._split_clear.setToolTip("解除当前合并，两个 View 各自独立")
        self._split_clear.setCursor(Qt.PointingHandCursor)
        self._split_clear.clicked.connect(self._on_split_clear_clicked)
        layout.addWidget(self._split_chip, 0)
        layout.addWidget(self._split_clear, 0)

        manager.views_changed.connect(self.refresh)
        manager.active_changed.connect(self._sync_active)
        manager.split_changed.connect(self._on_manager_split_changed)
        self.refresh()

    def _make_section_anchor(self, section: str) -> QWidget:
        key = str(section)
        try:
            label_text, icon_factory = _SECTION_ANCHORS[key]
        except KeyError as exc:
            known = ", ".join(sorted(_SECTION_ANCHORS))
            raise ValueError(
                f"unknown ViewTabBar section {section!r}; expected one of: {known}"
            ) from exc
        self._section_key = key

        # Height matches QTabBar (26). Content margins carve the same ~20px
        # band the View tabs use (QSS ::tab height 20 + top-biased margin), so
        # the icon/label midline lands on the View text midline — not the
        # geometric center of the full 30px outer rail.
        anchor = QWidget(self)
        anchor.setObjectName("viewSectionAnchor")
        anchor.setFocusPolicy(Qt.NoFocus)
        anchor.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        anchor.setAttribute(Qt.WA_StyledBackground, True)
        anchor.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        anchor.setFixedHeight(26)
        anchor.setAccessibleName(f"当前区域：{label_text}")

        row = QHBoxLayout(anchor)
        # Top 4 / bottom 2: content mid ≈ bar y+14, matching polished tabRect.
        # Right 10 is the gap before the first View tab.
        row.setContentsMargins(2, 4, 10, 2)
        row.setSpacing(6)

        icon_host = QLabel(anchor)
        icon_host.setObjectName("viewSectionAnchorIcon")
        icon_host.setFocusPolicy(Qt.NoFocus)
        icon_host.setFixedSize(18, 18)
        icon_host.setAlignment(Qt.AlignCenter)
        icon_host.setPixmap(icon_factory().pixmap(12, 12))
        row.addWidget(icon_host, 0, Qt.AlignVCenter)

        label = QLabel(label_text, anchor)
        label.setObjectName("viewSectionAnchorLabel")
        label.setFocusPolicy(Qt.NoFocus)
        # Same box as the icon badge so CJK cap-height shares its midline;
        # QSS padding-top nudges the glyph down (descent space is empty).
        label.setFixedHeight(18)
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(label, 0, Qt.AlignVCenter)

        # Dedicated 1px rule — more reliable than border-right on a transparent
        # host (TimeDomain previously ate borders via WA_TranslucentBackground).
        rule = QFrame(anchor)
        rule.setObjectName("viewSectionAnchorRule")
        rule.setFocusPolicy(Qt.NoFocus)
        rule.setFixedSize(1, 14)
        rule.setAttribute(Qt.WA_StyledBackground, True)
        rule.setAutoFillBackground(True)
        row.addWidget(rule, 0, Qt.AlignVCenter)
        return anchor

    def _on_manager_split_changed(self, _idx) -> None:
        # Merge created/cancelled: update the status chip AND re-tint tab dots
        # (host gains a half partner-color swatch; cancel restores solid).
        self._update_split_chip()
        self._refresh_tab_swatches()
        # The cancel-merge button just appeared/vanished, which moves the tab
        # strip's measured budget by its whole width.
        self._sync_tabbar_width()

    def _partner_color_for(self, idx: int):
        """Return the partner View's tab color when ``idx`` is a merge host,
        else None. Only hosts get a split dot; source Views stay solid."""
        partner_for = getattr(self._manager, "partner_for", None)
        if not callable(partner_for):
            return None
        partner = partner_for(idx)
        if partner is None:
            return None
        try:
            return self._manager.get(partner).tab_color
        except Exception:
            return None

    def _refresh_tab_swatches(self) -> None:
        if self._reordering:
            return
        count = min(self._tabs.count(), len(self._manager.views))
        for idx in range(count):
            self._refresh_tab_icon(idx)

    def _refresh_tab_icon(self, idx: int) -> None:
        if idx < 0 or idx >= self._tabs.count() or idx >= len(self._manager.views):
            return
        self._tabs.setTabIcon(idx, self._icon_for_tab(idx))
        self._tabs.update(self._tabs.tabRect(idx))

    def _icon_for_tab(self, idx: int) -> QIcon:
        del idx
        return self._tab_spacer_icon

    def _views_closable(self) -> bool:
        return len(self._manager.views) > 1

    def _view_id_at(self, idx: int) -> str:
        if 0 <= idx < len(self._manager.views):
            return str(self._manager.views[idx].view_id)
        return ""

    def _index_for_view_id(self, view_id: str) -> int:
        target = str(view_id or "")
        if not target:
            return -1
        for idx, view in enumerate(self._manager.views):
            if str(view.view_id) == target:
                return idx
        return -1

    def count(self) -> int:
        return self._tabs.count()

    def tabBar(self) -> QTabBar:
        return self._tabs

    def split_action_labels(self) -> dict:
        return dict(self._split_action_labels)

    def split_action_mode(self) -> str:
        return self._split_action_mode

    def refresh_split_controls(self) -> None:
        self._update_split_chip()
        self._sync_tabbar_width()

    def refresh_fit(self) -> None:
        """Public entry for hosts that changed sibling width (UltraView Dock)."""
        self._sync_tabbar_width()

    def refresh(self) -> None:
        if self._reordering:
            # A live drag-reorder is on the stack. Qt has ALREADY moved the
            # dragged tab — with its icon/text/tabData — to its new slot, and
            # ViewManager.reorder updated the views list to match, so the bar
            # is already correct. Rebuilding it here (removeTab/addTab +
            # setFixedWidth) from inside the QTabBar's own tabMoved emission is
            # a use-after-free on the tab still held by the live drag → hard
            # crash (闪退). Skip the rebuild; nothing visible needs it.
            return
        self._tabs.clear_interaction_state()
        self._suppress = True
        try:
            while self._tabs.count():
                self._tabs.removeTab(0)
            for view_idx, view in enumerate(self._manager.views):
                icon = self._icon_for_tab(view_idx)
                idx = self._tabs.addTab(icon, view.name)
                self._tabs.setTabData(idx, view.tab_color)
            self._set_current_index(self._manager.active)
        finally:
            self._suppress = False
        self._update_plus_state()
        # Before the fit, not after: _update_split_chip decides whether the
        # cancel-merge button is on the row, and _sync_tabbar_width reserves its
        # measured width out of the tab budget.
        self._update_split_chip()
        self._sync_tabbar_width()
        self._sync_overflow_popup()

    def _sync_tabbar_width(self) -> None:
        """Fit the tab strip to the row, degrading only when MEASURED too wide.

        Three passes, each decided by comparing a real ``sizeHint()`` against a
        real budget — there is deliberately no px threshold in this file. A
        literal budget is how a degrade branch becomes a false green (see
        docs/lessons-learned/pyqt-ui/
        2026-07-10-facts-degrade-budget-from-measured-not-literal-px.md); the
        spec's own 58px/49px models are both wrong on this machine, where a
        roomy tab really measures 91px.

          1. roomy   — every tab visible, full names.
          2. compact — dot + ordinal, full name moves to the tooltip.
          3. overflow — tail tabs retired into the » menu.
        """
        if self._reordering:
            # Same use-after-free as refresh(): re-styling / re-laying out the
            # strip from inside a live tabMoved drag touches the tab the drag
            # still holds. Nothing visible needs it mid-drag.
            return
        if self._tabs.count() <= 0:
            self._set_overflow(())
            self._clamp_tabs_width(0)
            return
        self._tabs.ensurePolished()

        budget = self._tabs_budget(include_overflow=False)

        # Pass 1 — roomy.
        self._show_all_tabs()
        self._set_density(compact=False)
        natural = self._natural_tabs_width()
        if budget is None or natural <= budget:
            self._set_overflow(())
            self._clamp_tabs_width(natural)
            return

        # Pass 2 — compact.
        self._set_density(compact=True)
        natural = self._natural_tabs_width()
        if natural <= budget:
            self._set_overflow(())
            self._clamp_tabs_width(natural)
            return

        # Pass 3 — compact still overflows: retire the tail into the » menu.
        # Reserving the button costs width, so the budget shrinks again here.
        budget = self._tabs_budget(include_overflow=True)
        hidden = self._retire_tail_tabs(budget)
        self._set_overflow(hidden)
        self._clamp_tabs_width(min(self._natural_tabs_width(), max(1, budget)))

    def _natural_tabs_width(self) -> int:
        # sizeHint() sums the per-tab style hints of the VISIBLE tabs (incl. the
        # QSS min-width/padding) and is independent of the current width clamp.
        # tabRect() must NOT be used here: once the bar is width-clamped,
        # tabRect reports the *compressed* layout, so re-measuring would lock
        # the squeeze in. (The bug: an early, pre-style measurement pinned 263px
        # while the styled tabs need 294px → "View 1" clipped to "1" with
        # scroll arrows.)
        return max(1, self._tabs.sizeHint().width())

    def _clamp_tabs_width(self, width: int) -> None:
        # setMaximumWidth, NOT setFixedWidth. A fixed width tells Qt the strip
        # can never overflow, which is exactly what kept the setUsesScrollButtons
        # (see __init__) permanently inert. The strip's Maximum size policy makes
        # the layout hand it min(sizeHint, maximumWidth), so pinning the natural
        # width as the *maximum* still hugs _plus against the last tab, while a
        # narrow row now genuinely compresses the strip and nothing else.
        # setMinimumWidth(0) undoes any earlier fixed width.
        self._tabs.setMinimumWidth(0)
        self._tabs.setMaximumWidth(max(0, int(width)))

    def _tabs_budget(self, *, include_overflow: bool) -> int | None:
        """Width the tab strip may occupy, measured off the live row.

        Everything right of the strip (», +, and the split action) is fixed and
        must never compress, so the budget is this bar's own width minus those
        siblings' real hints plus the layout's margins/spacing. Returns None
        while the bar has no realised geometry — measuring an unshown widget
        yields a phantom width and would compact a strip that has plenty of room.
        """
        if not self.isVisible():
            return None
        layout = self.layout()
        if layout is None:
            return None
        margins = layout.contentsMargins()
        avail = self.width() - margins.left() - margins.right()
        if avail <= 0:
            return None
        spacing = max(0, layout.spacing())
        siblings = [self._plus]
        # Quiet section anchor is a fixed left sibling: same reserve formula as
        # + / » / split actions. It never compresses; tabs yield first.
        if self._section_anchor is not None and not self._section_anchor.isHidden():
            siblings.append(self._section_anchor)
        if include_overflow:
            # Measure at the widest label this bar could ever show ("»" + every
            # View retired) so the reserve cannot jitter as the count changes.
            self._overflow.setText(f"»{self._tabs.count()}")
            siblings.append(self._overflow)
        if not self._split_chip.isHidden():
            siblings.append(self._split_chip)
        if not self._split_clear.isHidden():
            siblings.append(self._split_clear)
        reserved = 0
        for widget in siblings:
            hint = max(
                widget.sizeHint().width(), widget.minimumSizeHint().width()
            )
            reserved += hint + spacing
        return avail - reserved

    def _show_all_tabs(self) -> None:
        for idx in range(self._tabs.count()):
            if not self._tabs.isTabVisible(idx):
                self._tabs.setTabVisible(idx, True)

    def _set_density(self, *, compact: bool) -> None:
        changed = bool(compact) != self._density_compact
        self._density_compact = bool(compact)
        if changed:
            self._tabs.setProperty("density", "compact" if compact else "roomy")
            style = self._tabs.style()
            style.unpolish(self._tabs)
            style.polish(self._tabs)
            # unpolish/polish updates tabSizeHint() but leaves QTabBar's CACHED
            # layout — and therefore sizeHint() — stale. Measured on Qt 5.15.2:
            # tabSizeHint went 91→77 while sizeHint stayed at the roomy 1110, so
            # the fit decision above would read the OLD width and never degrade.
            # StyleChange is what runs QTabBarPrivate::refresh(). It is safe
            # here: changeEvent only re-derives usesScrollButtons/elideMode when
            # they were not set by the user, and __init__ sets the former.
            QApplication.sendEvent(self._tabs, QEvent(QEvent.StyleChange))
        self._apply_tab_labels()

    def _apply_tab_labels(self) -> None:
        count = min(self._tabs.count(), len(self._manager.views))
        for idx in range(count):
            # The full name MUST come from the manager, never read back off the
            # widget: in compact mode the tab only ever holds the ordinal, so
            # tabText() would put "7" in the tooltip instead of the View name
            # (same trap as QLabel.text() returning the elided string — see
            # 2026-06-15-eliding-label-stable-anchor-and-text-returns-elided).
            name = self._manager.views[idx].name
            if self._density_compact:
                self._tabs.setTabText(idx, str(idx + 1))
                self._tabs.setTabToolTip(idx, name)
            else:
                self._tabs.setTabText(idx, name)
                self._tabs.setTabToolTip(idx, "")

    def _retire_tail_tabs(self, budget: int) -> list[int]:
        """Hide tail tabs until the strip fits ``budget``; return their indices.

        setTabVisible, NEVER removeTab: six places in this class treat "QTabBar
        tab i" and "manager.views[i]" as one index (_on_current_changed,
        _on_tab_moved, _refresh_tab_swatches, _set_current_index,
        _begin_inline_rename, _on_context_menu). removeTab would renumber all of
        them silently — wrong View switched, wrong View renamed. setTabVisible
        keeps count(), tabData and every index intact.
        """
        current = self._tabs.currentIndex()
        hidden: list[int] = []
        for idx in range(self._tabs.count() - 1, -1, -1):
            if self._natural_tabs_width() <= budget:
                break
            if idx == current:
                # Hiding the CURRENT tab makes Qt move the selection to a
                # neighbour and emit currentChanged (measured on Qt 5.15.2),
                # which here means resizing the window would silently switch the
                # user's active View. The active tab always stays on the strip.
                continue
            self._tabs.setTabVisible(idx, False)
            hidden.append(idx)
        hidden.sort()
        return hidden

    def _set_overflow(self, hidden) -> None:
        self._overflow_indices = list(hidden)
        count = len(self._overflow_indices)
        if count <= 0:
            self._close_overflow_popup()
            self._overflow.setText("»")
            self._overflow.setToolTip("")
            self._overflow.setVisible(False)
            return
        self._overflow.setText(f"»{count}")
        self._overflow.setToolTip(f"另有 {count} 个 View 放不下，点击选择")
        self._overflow.setVisible(True)

    def overflow_indices(self) -> list[int]:
        """View indices currently retired into the » menu (test/diagnostic)."""
        return list(self._overflow_indices)

    def is_compact(self) -> bool:
        """True when tabs are rendered as dot + ordinal (test/diagnostic)."""
        return self._density_compact

    def _mark_compact_tabs_discovered(self) -> None:
        """Retire the ``view.compact_tabs`` footer hint ("窄窗口 View 标签只剩
        编号，悬停可看全名"): the user has just been shown a full View name by
        the very affordance the hint points at.

        ``mark_discovered`` takes the HINT ID, not the ``retire_on`` descriptor
        (which is documentation only — ``hints.discovery_hint`` retires on
        ``hint.id not in state.discovered``). It also syncs QSettings to disk on
        every call while the tooltip path fires on every hover, so the session
        flag keeps that to one write. Default QSettings: the same discovered set
        the chart-card footer reads (same pattern as ``widgets/__init__.py``'s
        ``coaxis.merge``).
        """
        if self._compact_tabs_discovered:
            return
        self._compact_tabs_discovered = True
        hints.mark_discovered(QSettings(), "view.compact_tabs")

    def _on_overflow_clicked(self) -> None:
        if self._overflow_popup is not None and self._overflow_popup.isVisible():
            self._close_overflow_popup()
            return
        if (
            QDateTime.currentMSecsSinceEpoch() - self._overflow_popup_closed_msecs
            < 250
        ):
            return
        if not self._overflow_indices:
            return
        self._mark_compact_tabs_discovered()
        popup = ViewOverflowPopup(self)
        popup.switch_requested.connect(self._on_overflow_switch)
        popup.close_requested.connect(self._on_overflow_row_close)
        popup.close_others_requested.connect(self._on_overflow_close_others)
        popup.close_all_requested.connect(self._on_overflow_close_all)
        popup.closed.connect(self._on_overflow_popup_closed)
        self._overflow_popup = popup
        self._set_overflow_expanded(True)
        popup.populate(self._overflow_rows())
        popup.show_at(self._overflow)

    def _overflow_rows(self) -> list[ViewOverflowRow]:
        current_id = self._view_id_at(self._tabs.currentIndex())
        closable = self._views_closable()
        rows = []
        for idx, view in enumerate(self._manager.views):
            partner = self._partner_color_for(idx)
            rows.append(
                ViewOverflowRow(
                    view_id=str(view.view_id),
                    name=view.name,
                    ordinal=idx + 1,
                    color=view.tab_color,
                    partner_color=partner,
                    current=str(view.view_id) == current_id,
                    closable=closable,
                )
            )
        return rows

    def _set_overflow_expanded(self, expanded: bool) -> None:
        self._overflow.setProperty("expanded", "true" if expanded else "false")
        style = self._overflow.style()
        style.unpolish(self._overflow)
        style.polish(self._overflow)
        self._overflow.update()

    def _close_overflow_popup(self) -> None:
        popup = self._overflow_popup
        if popup is None:
            self._set_overflow_expanded(False)
            return
        self._overflow_popup = None
        popup.hide()
        popup.deleteLater()
        self._set_overflow_expanded(False)

    def _on_overflow_popup_closed(self) -> None:
        self._overflow_popup = None
        self._overflow_popup_closed_msecs = QDateTime.currentMSecsSinceEpoch()
        self._set_overflow_expanded(False)
        self._overflow.setFocus(Qt.PopupFocusReason)

    def _on_overflow_switch(self, view_id: str) -> None:
        self._close_overflow_popup()
        idx = self._index_for_view_id(view_id)
        if idx < 0 or idx == self._tabs.currentIndex():
            return
        self.switch_requested.emit(idx)

    def _on_overflow_row_close(self, view_id: str) -> None:
        idx = self._index_for_view_id(view_id)
        if idx < 0 or not self._views_closable():
            return
        self.overflow_delete_requested.emit(idx)

    def _sync_overflow_popup(self) -> None:
        popup = self._overflow_popup
        if popup is None or not popup.isVisible():
            return
        if not self._overflow_indices:
            self._close_overflow_popup()
            return
        popup.populate(self._overflow_rows())

    def _on_overflow_close_others(self, keep_view_id: str) -> None:
        self._close_overflow_popup()
        if not self._views_closable() or self._index_for_view_id(keep_view_id) < 0:
            return
        self.close_others_requested.emit(keep_view_id)

    def _on_overflow_close_all(self) -> None:
        self._close_overflow_popup()
        if not self._views_closable():
            return
        self.close_all_requested.emit()

    def showEvent(self, event):
        super().showEvent(event)
        # Re-measure once shown/polished so the initial pre-style width (taken
        # during __init__'s refresh, where the row has no geometry yet) is
        # corrected against the real styled widths.
        self._sync_tabbar_width()

    def hideEvent(self, event):
        self._close_overflow_popup()
        self._tabs.clear_interaction_state()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.WindowDeactivate, QEvent.ActivationChange):
            window = self.window()
            if window is not None and not window.isActiveWindow():
                self._tabs.clear_interaction_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The budget is a function of the row width, so every resize re-runs the
        # fit: narrowing compacts the tabs and then retires them, while the +
        # button and the split action keep their measured reserve throughout.
        self._sync_tabbar_width()

    def _sync_active(self, idx: int) -> None:
        self._secondary_focused = False
        self._suppress = True
        try:
            self._set_current_index(idx)
        finally:
            self._suppress = False
        self._update_split_chip()
        # The View just made active may be retired into the » menu (e.g. it was
        # picked FROM that menu). Re-fitting pulls it back onto the strip, since
        # _retire_tail_tabs never hides the current tab, and pushes some other
        # tail tab into the menu in its place.
        self._sync_tabbar_width()

    def set_split_focus(self, secondary_focused: bool) -> None:
        self._secondary_focused = bool(secondary_focused)
        self._update_split_chip()
        self._sync_tabbar_width()

    def _set_current_index(self, idx: int) -> None:
        if 0 <= idx < self._tabs.count():
            self._tabs.setCurrentIndex(idx)

    def _update_plus_state(self) -> None:
        # The cap is per manager (time domain runs at 12, the analysis sections
        # keep the default), so read it off the instance; getattr keeps any
        # manager predating the instance attribute on the module default.
        cap = getattr(self._manager, "max_views", MAX_VIEWS)
        can_add = len(self._manager.views) < cap
        self._plus.setEnabled(can_add)
        self._plus.setToolTip("新建 View" if can_add else "View 数量已达上限")

    def _on_split_clear_clicked(self) -> None:
        self.clear_split_requested.emit(self._manager.active)

    def _active_pane_split_visible(self) -> bool:
        if self._split_action_mode != 'active_pane':
            return False
        provider = self._active_split_provider
        if provider is None:
            return False
        try:
            return int(provider()) > 1
        except Exception:
            return False

    def _update_split_chip(self) -> None:
        if self._split_action_mode == 'active_pane':
            visible = self._active_pane_split_visible()
            self._split_chip.setVisible(False)
            self._split_chip.setText("")
            self._split_clear.setVisible(visible)
            self._split_clear.setText("✕ " + self._split_action_labels['clear'])
            self._split_clear.setToolTip("关闭当前 View 的对比窗格")
            self._split_clear.setAccessibleName(
                "关闭当前 View 的对比窗格" if visible else "")
            return
        partner_for = getattr(self._manager, "partner_for", None)
        partner = partner_for(self._manager.active) if callable(partner_for) else None
        visible = partner is not None
        self._split_chip.setVisible(False)
        self._split_chip.setText("")
        self._split_clear.setVisible(visible)
        if not visible:
            self._split_clear.setToolTip("解除当前合并，两个 View 各自独立")
            self._split_clear.setAccessibleName("")
            return
        active_name = self._manager.get(self._manager.active).name
        partner_name = self._manager.get(partner).name
        editing = partner_name if self._secondary_focused else active_name
        tip = f"取消 {active_name} + {partner_name} 合并；当前操作 {editing}"
        self._split_clear.setToolTip(tip)
        self._split_clear.setAccessibleName(tip)

    def _on_current_changed(self, idx: int) -> None:
        if self._suppress or idx < 0:
            return
        if self._suppress_switch_after_reorder:
            self._suppress_switch_after_reorder = False
            return
        self.switch_requested.emit(idx)

    def _on_plus_clicked(self) -> None:
        if not self._plus.isEnabled():
            return
        self.new_requested.emit()

    def _on_double_clicked(self, idx: int) -> None:
        if not self._is_valid_tab(idx):
            return
        self._begin_inline_rename(idx)

    def keyPressEvent(self, event):  # noqa: N802
        if self._handle_view_keyboard(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_view_keyboard(self, event) -> bool:
        if self._rename_editor is not None:
            return False
        key = event.key()
        mods = int(event.modifiers())
        ctrl = bool(mods & int(Qt.ControlModifier)) or bool(mods & int(Qt.MetaModifier))
        shift = bool(mods & int(Qt.ShiftModifier))
        alt = bool(mods & int(Qt.AltModifier))
        if ctrl and key in (Qt.Key_Tab, Qt.Key_Backtab) and not alt:
            delta = -1 if key == Qt.Key_Backtab or shift else 1
            self._cycle_section_views(delta)
            return True
        if key == Qt.Key_F2:
            self._rename_current_view()
            return True
        if alt and key in (Qt.Key_Up, Qt.Key_Down) and not ctrl:
            self._reorder_current_view(-1 if key == Qt.Key_Up else 1)
            return True
        return False

    def _cycle_section_views(self, delta: int) -> None:
        count = self._tabs.count()
        if count <= 1:
            return
        current = self._tabs.currentIndex()
        if current < 0:
            current = 0
        target = (current + delta) % count
        if target == current:
            return
        self._tabs.setCurrentIndex(target)

    def _rename_current_view(self) -> None:
        idx = self._tabs.currentIndex()
        if not self._is_valid_tab(idx):
            return
        self._begin_inline_rename(idx)

    def _reorder_current_view(self, delta: int) -> None:
        from_idx = self._tabs.currentIndex()
        to_idx = from_idx + delta
        if not self._is_valid_tab(from_idx) or not self._is_valid_tab(to_idx):
            return
        self._emit_reorder(from_idx, to_idx)

    def _begin_inline_rename(self, idx: int) -> None:
        self._finish_inline_rename(accepted=False)
        self._rename_index = idx
        editor = QLineEdit(self._tabs)
        editor.setObjectName("viewTabRenameEditor")
        # Seed from the manager, never from tabText(): in compact density the
        # tab only holds the ordinal, so tabText() would prefill the editor with
        # "7" and renaming would silently overwrite the View's real name.
        editor.setText(self._view_name(idx))
        editor.selectAll()
        # Overlay the editor on (almost) the whole tab so its QSS chrome
        # (tinted fill + soft blue border, see ui_kit/style.qss
        # QLineEdit#viewTabRenameEditor) reads as editing the tab in place,
        # not a separate white popover. A 1px inset keeps the editor's rounded
        # border just inside the tab's own border; the QSS padding (0 9px)
        # aligns the text with where the tab label sat.
        editor.setGeometry(self._tabs.tabRect(idx).adjusted(1, 1, -1, -1))
        editor.returnPressed.connect(
            lambda: self._finish_inline_rename(accepted=True)
        )
        editor.installEventFilter(self)
        self._rename_editor = editor
        editor.show()
        editor.setFocus(Qt.MouseFocusReason)

    def _finish_inline_rename(self, *, accepted: bool) -> None:
        editor = self._rename_editor
        if editor is None:
            return
        idx = self._rename_index
        text = editor.text()
        self._rename_editor = None
        self._rename_index = -1
        editor.removeEventFilter(self)
        editor.hide()
        editor.deleteLater()
        if accepted and self._is_valid_tab(idx):
            self.rename_requested.emit(idx, text)

    def eventFilter(self, watched, event):
        if watched is self._rename_editor:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._finish_inline_rename(accepted=False)
                return True
            if event.type() == QEvent.FocusOut:
                self._finish_inline_rename(accepted=True)
                return False
        if (
            watched is self._tabs
            and event.type() == QEvent.KeyPress
            and self._handle_view_keyboard(event)
        ):
            return True
        if (
            watched is self._tabs
            and event.type() == QEvent.MouseButtonDblClick
            and self._tabs._consume_close_double_click(event)
        ):
            return True
        if (
            watched is self._tabs
            and event.type() == QEvent.MouseButtonRelease
            and self._pending_reorder_resync
        ):
            # This release ENDS the drag-reorder whose refresh() we had to skip
            # (see refresh / _on_tab_moved). A filter runs before the widget's
            # own handler, so the drag is not finished yet — defer one tick so
            # QTabBar::mouseReleaseEvent completes first and the rebuild lands
            # on tabs nobody is holding.
            self._pending_reorder_resync = False
            QTimer.singleShot(0, self._resync_after_reorder)
        if (
            watched is self._tabs
            and event.type() == QEvent.ToolTip
            and self._density_compact
            and self._tabs.tabAt(event.pos()) >= 0
        ):
            # Compact density is the ONLY state where a tab carries a tooltip
            # (_apply_tab_labels clears it when roomy), and that tooltip IS the
            # answer the view.compact_tabs hint promises. This is also the only
            # retire path for a row that compacts WITHOUT overflowing — there is
            # no » button to click there. Deliberately not consumed: fall
            # through so QTabBar still shows the tip.
            self._mark_compact_tabs_discovered()
        return super().eventFilter(watched, event)

    def _resync_after_reorder(self) -> None:
        if self._reordering:
            return
        self.refresh()

    def _split_context_partner(self, idx: int) -> int | None:
        partner_for = getattr(self._manager, "partner_for", None)
        if not callable(partner_for):
            return None
        partner = partner_for(idx)
        if partner is not None:
            return partner
        for host in range(len(self._manager.views)):
            if host != idx and partner_for(host) == idx:
                return host
        return None

    def _on_context_menu(self, pos) -> None:
        idx = self._tabs.tabAt(pos)
        if not self._is_valid_tab(idx):
            return

        menu = apply_rounded_menu_chrome(QMenu(self))
        rename_action = menu.addAction("重命名")
        duplicate_action = menu.addAction("复制此 View")
        color_action = menu.addAction("改标签颜色...")
        menu.addSeparator()
        partner_for = getattr(self._manager, "partner_for", None)
        partner = self._split_context_partner(idx)
        active_partner = (
            partner_for(self._manager.active) if callable(partner_for) else None
        )
        will_replace = (
            partner is None
            and idx != self._manager.active
            and active_partner is not None
            and active_partner != idx
        )
        if self._split_action_mode == 'active_pane':
            if self._active_pane_split_visible() and idx == self._manager.active:
                split_action = menu.addAction(self._split_action_labels['clear'])
            else:
                split_action = menu.addAction(self._split_action_labels['split'])
            split_action.setEnabled(idx == self._manager.active)
        else:
            if partner is not None:
                split_action = menu.addAction(self._split_action_labels['clear'])
            elif will_replace:
                split_action = menu.addAction(self._split_action_labels['replace'])
            else:
                split_action = menu.addAction(self._split_action_labels['split'])
                split_action.setEnabled(idx != self._manager.active)
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.setEnabled(len(self._manager.views) > 1)
        add_ultraview_action = None
        if self._section_key:
            menu.addSeparator()
            add_ultraview_action = menu.addAction("加入总览")

        chosen = menu.exec_(self._tabs.mapToGlobal(pos))
        if chosen is None or not chosen.isEnabled():
            return
        if chosen is rename_action:
            self._begin_inline_rename(idx)
        elif chosen is duplicate_action:
            self.duplicate_requested.emit(idx)
        elif chosen is color_action:
            self.color_requested.emit(idx)
        elif chosen is split_action:
            if self._split_action_mode == 'active_pane':
                if self._active_pane_split_visible():
                    self.clear_split_requested.emit(idx)
                else:
                    self.split_requested.emit(idx)
                return
            if partner is not None:
                self.clear_split_requested.emit(idx)
            else:
                if will_replace:
                    ans = QMessageBox.question(
                        self,
                        "替换合并",
                        f"“{self._manager.get(self._manager.active).name}” 当前已与 "
                        f"“{self._manager.get(active_partner).name}” 合并；改为与 "
                        f"“{self._manager.get(idx).name}” 合并会解除原合并。继续？",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if ans != QMessageBox.Yes:
                        return
                self.split_requested.emit(idx)
        elif chosen is delete_action:
            self.delete_requested.emit(idx)
        elif add_ultraview_action is not None and chosen is add_ultraview_action:
            state = self._manager.get(idx)
            view_id = str(getattr(state, "view_id", "") or "")
            if view_id:
                self.add_to_ultraview_requested.emit(self._section_key, view_id)

    def _on_tab_moved(self, from_idx: int, to_idx: int) -> None:
        if not self._suppress:
            self._suppress_switch_after_reorder = True
            QTimer.singleShot(0, self._clear_reorder_switch_suppression)
            # Mark the reorder so the manager's views_changed → refresh() does
            # NOT rebuild the tab bar while this drag's tabMoved is live (that
            # rebuild crashes — see refresh()). The QTabBar already moved the
            # tab; the manager just needs its list synced.
            self._reordering = True
            try:
                self._emit_reorder(from_idx, to_idx)
            finally:
                self._reordering = False
            # Qt moved the tab WITH its text, so under compact density the
            # ordinals now travel with the drag and stop matching their
            # positions (measured: dragging tab 0 to slot 4 left the strip
            # reading 2,3,4,5,1). refresh() would fix it but is a hard crash
            # from inside this live tabMoved — re-label on the release instead.
            self._pending_reorder_resync = True

    def _emit_reorder(self, from_idx: int, to_idx: int) -> None:
        if from_idx == to_idx:
            return
        self.reorder_requested.emit(from_idx, to_idx)

    def _clear_reorder_switch_suppression(self) -> None:
        self._suppress_switch_after_reorder = False

    def _is_valid_tab(self, idx: int) -> bool:
        return 0 <= idx < self._tabs.count()

    def _view_name(self, idx: int) -> str:
        """The View's real name. The single read-back-safe source: the tab label
        is the ordinal under compact density."""
        if 0 <= idx < len(self._manager.views):
            return self._manager.views[idx].name
        return self._tabs.tabText(idx)


def _tab_color_pixmap(hex_color: str, ratio=None, partner_color=None) -> QPixmap:
    """Render the View-tab color dot at ``ratio x`` physical resolution and tag
    it with that devicePixelRatio so Retina screens paint it crisp instead of
    upscaling a 1x bitmap (the source of the jagged tab dots).

    When ``partner_color`` is given the dot is split left (own color) / right
    (partner color) with a thin white gap, marking a merge HOST that contains
    the partner View. The partner (source) View keeps a solid dot."""
    color = QColor(hex_color)
    if not color.isValid():
        color = QColor("#2d7ff9")

    if ratio is None:
        ratio = icon_device_pixel_ratio()
    side = round(12 * ratio)
    pixmap = QPixmap(side, side)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    _paint_tab_swatch(painter, QRectF(1, 3, 10, 6), color, partner_color)
    painter.end()
    return pixmap


def _tab_spacer_icon() -> QIcon:
    """Reserve QTabBar's existing icon cell without delegating its painting."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    return QIcon(pixmap)


def _paint_tab_swatch(
    painter: QPainter,
    rect: QRectF,
    color_value,
    partner_value=None,
) -> None:
    color = color_value if isinstance(color_value, QColor) else QColor(color_value)
    if not color.isValid():
        color = QColor("#2d7ff9")
    partner = QColor(partner_value) if partner_value else None
    if partner is not None and partner.isValid():
        clip = QPainterPath()
        clip.addRoundedRect(rect, 2, 2)
        painter.save()
        painter.setClipPath(clip)
        mid = rect.center().x()
        painter.fillRect(
            QRectF(rect.left(), rect.top(), mid - rect.left(), rect.height()), color
        )
        painter.fillRect(
            QRectF(mid, rect.top(), rect.right() - mid, rect.height()), partner
        )
        painter.fillRect(
            QRectF(mid - 0.5, rect.top(), 1.0, rect.height()), QColor("#ffffff")
        )
        painter.restore()
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 2, 2)
        return
    painter.setPen(QPen(color.darker(115), 1))
    painter.setBrush(color)
    painter.drawRoundedRect(rect, 2, 2)


def _paint_tab_close_button(painter: QPainter, rect: QRectF, *, pressed=False) -> None:
    """Paint the product close affordance; callers own the target geometry."""
    fill = _CLOSE_PRESSED if pressed else _CLOSE_SOFT
    border_rect = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
    painter.setPen(QPen(_CLOSE_BORDER, 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(border_rect, 4, 4)
    center = rect.center()
    arm = 4.0
    painter.setPen(QPen(_CLOSE_INK, 1.5, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(
        QPointF(center.x() - arm, center.y() - arm),
        QPointF(center.x() + arm, center.y() + arm),
    )
    painter.drawLine(
        QPointF(center.x() + arm, center.y() - arm),
        QPointF(center.x() - arm, center.y() + arm),
    )


def _tab_close_pixmap(ratio=None, *, pressed=False) -> QPixmap:
    """Render the 18×18 HiDPI square used by close-button paint tests."""
    if ratio is None:
        ratio = icon_device_pixel_ratio()
    side = max(1, round(_CLOSE_VISUAL_SIZE * ratio))
    pixmap = QPixmap(side, side)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    _paint_tab_close_button(
        painter,
        QRectF(0, 0, _CLOSE_VISUAL_SIZE, _CLOSE_VISUAL_SIZE),
        pressed=pressed,
    )
    painter.end()
    return pixmap

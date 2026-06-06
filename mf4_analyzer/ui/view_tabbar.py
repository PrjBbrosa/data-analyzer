"""Excel-style time-domain View tab bar.

The widget renders the ViewManager state and emits user intent only. It does
not mutate the manager directly, leaving capture/apply and manager operations to
the integration layer.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QWidget,
)

from ..ui_kit.icons import icon_device_pixel_ratio
from ..ui_kit.menus import apply_rounded_menu_chrome
from .view_state import MAX_VIEWS


class ViewTabBar(QWidget):
    switch_requested = pyqtSignal(int)
    new_requested = pyqtSignal()
    delete_requested = pyqtSignal(int)
    rename_requested = pyqtSignal(int, str)
    duplicate_requested = pyqtSignal(int)
    color_requested = pyqtSignal(int)
    reorder_requested = pyqtSignal(int, int)
    split_requested = pyqtSignal(int)
    clear_split_requested = pyqtSignal(int)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setObjectName("viewTabBar")
        self._manager = manager
        self._suppress = False
        self._rename_editor = None
        self._rename_index = -1
        self._secondary_focused = False
        self._suppress_switch_after_reorder = False
        # True only while a drag-reorder's tabMoved is being handled, so the
        # views_changed → refresh() it triggers skips the destructive rebuild
        # (which crashes mid-drag). See _on_tab_moved / refresh.
        self._reordering = False
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(2)

        self._tabs = QTabBar(self)
        self._tabs.setObjectName("viewTabs")
        self._tabs.setMovable(True)
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setDrawBase(False)
        self._tabs.setShape(QTabBar.RoundedSouth)
        self._tabs.setFixedHeight(26)
        self._tabs.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.tabBarDoubleClicked.connect(self._on_double_clicked)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        self._tabs.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tabs, 0)

        self._plus = QPushButton("+", self)
        self._plus.setObjectName("viewTabPlus")
        self._plus.setToolTip("新建 View")
        self._plus.setFixedSize(24, 22)
        self._plus.clicked.connect(self._on_plus_clicked)
        layout.addWidget(self._plus, 0)
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

    def _on_manager_split_changed(self, _idx) -> None:
        # Merge created/cancelled: update the status chip AND re-tint tab dots
        # (host gains a half partner-color swatch; cancel restores solid).
        self._update_split_chip()
        self._refresh_tab_swatches()

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
            view = self._manager.views[idx]
            self._tabs.setTabIcon(
                idx, _tab_color_icon(view.tab_color, self._partner_color_for(idx))
            )

    def count(self) -> int:
        return self._tabs.count()

    def tabBar(self) -> QTabBar:
        return self._tabs

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
        self._suppress = True
        try:
            while self._tabs.count():
                self._tabs.removeTab(0)
            for view_idx, view in enumerate(self._manager.views):
                icon = _tab_color_icon(
                    view.tab_color, self._partner_color_for(view_idx)
                )
                idx = self._tabs.addTab(icon, view.name)
                self._tabs.setTabData(idx, view.tab_color)
                self._tabs.setTabToolTip(idx, view.name)
            self._set_current_index(self._manager.active)
        finally:
            self._suppress = False
        self._sync_tabbar_width()
        self._update_plus_state()
        self._update_split_chip()

    def _sync_tabbar_width(self) -> None:
        if self._tabs.count() <= 0:
            self._tabs.setFixedWidth(0)
            return
        # Pin to the NATURAL total tab width so the + button hugs the tabs
        # without clipping any label. sizeHint() sums the per-tab style hints
        # (incl. the QSS min-width/padding) and is independent of the current
        # width clamp. tabRect() must NOT be used here: once the bar is
        # fixed-width, tabRect reports the *compressed* layout, so re-measuring
        # would lock the squeeze in. (The bug: an early, pre-style measurement
        # pinned 263px while the styled tabs need 294px → "View 1" clipped to
        # "1" with scroll arrows.)
        self._tabs.ensurePolished()
        self._tabs.setFixedWidth(max(1, self._tabs.sizeHint().width()))

    def showEvent(self, event):
        super().showEvent(event)
        # Re-measure once shown/polished so the initial pre-style width (taken
        # during __init__'s refresh) is corrected to the natural styled width.
        self._sync_tabbar_width()

    def _sync_active(self, idx: int) -> None:
        self._secondary_focused = False
        self._suppress = True
        try:
            self._set_current_index(idx)
        finally:
            self._suppress = False
        self._update_split_chip()

    def set_split_focus(self, secondary_focused: bool) -> None:
        self._secondary_focused = bool(secondary_focused)
        self._update_split_chip()

    def _set_current_index(self, idx: int) -> None:
        if 0 <= idx < self._tabs.count():
            self._tabs.setCurrentIndex(idx)

    def _update_plus_state(self) -> None:
        can_add = len(self._manager.views) < MAX_VIEWS
        self._plus.setEnabled(can_add)
        self._plus.setToolTip("新建 View" if can_add else "View 数量已达上限")

    def _on_split_clear_clicked(self) -> None:
        self.clear_split_requested.emit(self._manager.active)

    def _update_split_chip(self) -> None:
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

    def _begin_inline_rename(self, idx: int) -> None:
        self._finish_inline_rename(accepted=False)
        self._rename_index = idx
        editor = QLineEdit(self._tabs)
        editor.setObjectName("viewTabRenameEditor")
        editor.setText(self._tabs.tabText(idx))
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
        return super().eventFilter(watched, event)

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
        if partner is not None:
            split_action = menu.addAction("取消合并")
        elif will_replace:
            split_action = menu.addAction("与此 View 并排（替换当前合并）")
        else:
            split_action = menu.addAction("与此 View 并排")
            split_action.setEnabled(idx != self._manager.active)
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.setEnabled(len(self._manager.views) > 1)

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

    def _emit_reorder(self, from_idx: int, to_idx: int) -> None:
        if from_idx == to_idx:
            return
        self.reorder_requested.emit(from_idx, to_idx)

    def _clear_reorder_switch_suppression(self) -> None:
        self._suppress_switch_after_reorder = False

    def _is_valid_tab(self, idx: int) -> bool:
        return 0 <= idx < self._tabs.count()


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

    # Logical coordinates; the painter is scaled by devicePixelRatio.
    partner = QColor(partner_color) if partner_color else None
    if partner is not None and partner.isValid():
        rect = QRectF(1, 3, 10, 6)
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
        # Thin white gap so the two halves read as distinct (not fully joined).
        painter.fillRect(
            QRectF(mid - 0.5, rect.top(), 1.0, rect.height()), QColor("#ffffff")
        )
        painter.restore()
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 2, 2)
    else:
        painter.setPen(QPen(color.darker(115), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(1, 3, 10, 6, 2, 2)
    painter.end()
    return pixmap


def _tab_color_icon(hex_color: str, partner_color=None) -> QIcon:
    return QIcon(_tab_color_pixmap(hex_color, partner_color=partner_color))

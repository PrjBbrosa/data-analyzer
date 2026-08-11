"""Excel-style time-domain View tab bar.

The widget renders the ViewManager state and emits user intent only. It does
not mutate the manager directly, leaving capture/apply and manager operations to
the integration layer.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QRectF, QSettings, Qt, QTimer, pyqtSignal
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
    QTabBar,
    QWidget,
)

from . import hints
from ..ui_kit.icons import Icons, icon_device_pixel_ratio
from ..ui_kit.menus import apply_rounded_menu_chrome
from .view_state import MAX_VIEWS

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
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        right_margin = 4 if self._split_action_mode == 'active_pane' else 8
        layout.setContentsMargins(8, 0, right_margin, 0)
        layout.setSpacing(2)

        if section is not None:
            self._section_anchor = self._make_section_anchor(section)
            layout.addWidget(self._section_anchor, 0, Qt.AlignVCenter)

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
        # Seeded so the QSS density rule has an explicit state from the start
        # (_set_density flips it); the roomy box lives in the unqualified
        # ::tab rule, so "roomy" simply matches nothing extra.
        self._tabs.setProperty("density", "roomy")
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.tabBarDoubleClicked.connect(self._on_double_clicked)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        self._tabs.customContextMenuRequested.connect(self._on_context_menu)
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
        layout.addWidget(self._overflow, 0)

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
        # geometric center of the full 28px outer bar.
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
            view = self._manager.views[idx]
            self._tabs.setTabIcon(
                idx, _tab_color_icon(view.tab_color, self._partner_color_for(idx))
            )

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
            self._set_current_index(self._manager.active)
        finally:
            self._suppress = False
        self._update_plus_state()
        # Before the fit, not after: _update_split_chip decides whether the
        # cancel-merge button is on the row, and _sync_tabbar_width reserves its
        # measured width out of the tab budget.
        self._update_split_chip()
        self._sync_tabbar_width()

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
        if not self._overflow_indices:
            return
        # The » menu below lists every View by its FULL name, so opening it is
        # one of the two ways the user learns where the names went.
        self._mark_compact_tabs_discovered()
        # Checkable rows need the wider QSS right gutter (gutter="check").
        menu = apply_rounded_menu_chrome(QMenu(self), gutter="check")
        current = self._tabs.currentIndex()
        # Every View, not just the retired ones: the button only exists while
        # something overflowed, and the current View is never among the hidden
        # (see _retire_tail_tabs), so a hidden-only menu could never render the
        # selected state the design calls for. Listing all of them keeps the
        # checkmark live and gives one complete View list.
        targets = {}
        for idx, view in enumerate(self._manager.views):
            action = menu.addAction(
                _tab_color_icon(view.tab_color, self._partner_color_for(idx)),
                view.name,
            )
            action.setCheckable(True)
            action.setChecked(idx == current)
            targets[action] = idx
        chosen = menu.exec_(
            self._overflow.mapToGlobal(self._overflow.rect().bottomLeft())
        )
        if chosen is None:
            return
        idx = targets.get(chosen)
        if idx is None or idx == current:
            return
        # Intent only, like every other signal here. The host switches the
        # manager, whose active_changed lands in _sync_active → _sync_tabbar_width,
        # which pulls the newly active tab back onto the strip.
        self.switch_requested.emit(idx)

    def showEvent(self, event):
        super().showEvent(event)
        # Re-measure once shown/polished so the initial pre-style width (taken
        # during __init__'s refresh, where the row has no geometry yet) is
        # corrected against the real styled widths.
        self._sync_tabbar_width()

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

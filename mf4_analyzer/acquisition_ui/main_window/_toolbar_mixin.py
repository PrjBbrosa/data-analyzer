"""ToolbarMixin: toolbar construction + overflow for CockpitMainWindow."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome
# Module-level constants mirrored from window module for convenience.
from ._defs import MODE_SEGMENTS


class ToolbarMixin:
    """Domain mixin: toolbar construction and overflow recompute.

    All methods become CockpitMainWindow instance methods.
    They may only reference ``self.*`` attributes set in
    ``CockpitMainWindow.__init__`` or ``_build_ui``.
    """

    def _build_toolbar(self) -> QWidget:
        toolbar = QFrame(self)
        toolbar.setObjectName("cockpitToolbarBand")
        toolbar.setFrameShape(QFrame.NoFrame)
        toolbar.setFixedHeight(50)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self._a2l_btn = self._make_selector_button(
            "cockpitSelectorA2l", "A2L", "未加载"
        )
        self._a2l_btn.clicked.connect(self._on_pick_a2l)
        layout.addWidget(self._a2l_btn)

        self._output_btn = self._make_selector_button(
            "cockpitSelectorOutput", "输出", self._output_dir_label
        )
        self._output_btn.clicked.connect(self._on_pick_output_dir)
        layout.addWidget(self._output_btn)

        self._transport_chip = QLabel("传输未配置", self)
        self._transport_chip.setObjectName("cockpitTransportStatusChip")
        self._transport_chip.setProperty("transportState", "unconfigured")
        self._transport_chip.setFixedHeight(30)
        self._transport_chip.setMinimumWidth(96)
        self._transport_chip.setMaximumWidth(260)
        self._transport_chip.setAlignment(Qt.AlignCenter)
        self._transport_chip.setToolTip("打开传输设置")
        self._transport_chip.setCursor(Qt.PointingHandCursor)
        self._transport_chip.mousePressEvent = (
            lambda _event: self._open_settings_dialog(initial_tab="transport")
        )
        layout.addWidget(self._transport_chip)

        self._settings_action = QAction("设置", self)
        self._settings_action.setObjectName("cockpitSettingsAction")
        self._settings_action.triggered.connect(self._open_settings_dialog)
        self._settings_btn = QToolButton(self)
        self._settings_btn.setObjectName("cockpitSettingsButton")
        self._settings_btn.setDefaultAction(self._settings_action)
        self._settings_btn.setText("⚙")
        self._settings_btn.setToolTip("设置")
        self._settings_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._settings_btn.setFixedSize(30, 30)
        layout.addWidget(self._settings_btn)

        layout.addWidget(self._toolbar_separator(toolbar))

        self._segment_action = QAction("+ 段", self)
        self._segment_action.setObjectName("segmentMarkerAction")
        self._segment_action.setToolTip("标记一段 (M)")
        self._segment_action.setShortcut("M")
        self._segment_action.triggered.connect(self._on_mark_segment)
        self._segment_action.setVisible(False)
        self._segment_btn = QToolButton(self)
        self._segment_btn.setObjectName("segmentMarkerButton")
        self._segment_btn.setDefaultAction(self._segment_action)
        self._segment_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._segment_btn.setVisible(False)
        layout.addWidget(self._segment_btn)

        self._mode_segment_widget = self._build_mode_segment(toolbar)
        layout.addWidget(self._mode_segment_widget)

        # Stretch.
        spacer = QWidget(self)
        spacer.setObjectName("cockpitToolbarSpacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(spacer)

        # REC indicator (toolbar global).
        self._rec_indicator = QLabel("● REC OFF", self)
        self._rec_indicator.setObjectName("cockpitRecIndicator")
        self._rec_indicator.setFixedHeight(32)
        self._rec_indicator.setMinimumWidth(92)
        self._rec_indicator.setAlignment(Qt.AlignCenter)
        self._set_visual_property(self._rec_indicator, "recState", "off")
        layout.addWidget(self._rec_indicator)

        layout.addWidget(self._toolbar_separator(toolbar))

        # Main stateful button.
        self._main_btn = QPushButton("连接 ECU", self)
        self._main_btn.setProperty("role", "primary")
        self._main_btn.setFixedHeight(32)
        self._main_btn.setMinimumWidth(106)
        self._main_btn.clicked.connect(self._on_main_button)
        layout.addWidget(self._main_btn)

        # Spec §S4.2 — overflow chevron and its menu. Hidden by default;
        # ``_recompute_toolbar_overflow`` shows it when at least one
        # eligible toolbar child needs to be demoted at the current
        # window width.
        self._overflow_btn = QToolButton(toolbar)
        self._overflow_btn.setObjectName("cockpitToolbarOverflow")
        self._overflow_btn.setText("≡")
        self._overflow_btn.setToolTip("更多")
        self._overflow_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._overflow_btn.setFixedSize(30, 30)
        self._overflow_btn.setPopupMode(QToolButton.InstantPopup)
        self._overflow_menu = apply_rounded_menu_chrome(QMenu(self._overflow_btn))
        self._overflow_menu.setObjectName("cockpitToolbarOverflowMenu")
        self._overflow_btn.setMenu(self._overflow_menu)
        self._overflow_btn.setVisible(False)
        layout.addWidget(self._overflow_btn)

        # Build the QAction wrappers that the overflow menu mirrors. The
        # `_settings_action` and `_segment_action` instances already
        # exist; create QAction wrappers for the selectors and mode
        # segment so they can be added to a QMenu (only QAction works in
        # QMenu — naked QPushButton clicks cannot). Each wrapper re-uses
        # the existing slot verbatim.
        self._a2l_action = QAction("A2L", self)
        self._a2l_action.setObjectName("cockpitSelectorA2lAction")
        self._a2l_action.triggered.connect(self._on_pick_a2l)
        self._output_action = QAction("输出", self)
        self._output_action.setObjectName("cockpitSelectorOutputAction")
        self._output_action.triggered.connect(self._on_pick_output_dir)
        self._transport_action = QAction("传输", self)
        self._transport_action.setObjectName("cockpitTransportAction")
        self._transport_action.triggered.connect(
            lambda _checked=False: self._open_settings_dialog(initial_tab="transport")
        )
        # The mode segment is a composite of three buttons — when the
        # whole segment overflows, expose a single "模式" submenu-ish
        # action that opens the segment as a popup; for now we route to
        # the current capture/replay/history switch via menu items added
        # at recompute time. To keep the contract simple here, we create
        # one wrapper QAction labelled with the segment's first button
        # text ("采集" by default) — the test only checks `text()` parity
        # with the affordance, and the segment widget has no single
        # text() of its own. Tests can disambiguate via objectName when
        # they need it.
        self._mode_segment_action = QAction("模式", self)
        self._mode_segment_action.setObjectName("cockpitModeSegmentAction")
        # When the mode segment is demoted into the overflow menu, the
        # user must be able to pick a specific tab. A bare cycling
        # `_on_mode_segment_clicked((idx+1) % 3)` lambda forces
        # round-robin advancement with no visible current state.
        # Attach a submenu with one QAction per ``MODE_SEGMENTS``
        # entry so the overflow path renders as ``模式 ▶ 采集 / 回放
        # / 历史`` and each sub-action sets the tab to its specific
        # index.
        self._mode_overflow_submenu = apply_rounded_menu_chrome(QMenu("模式", self))
        self._mode_overflow_submenu.setObjectName("cockpitModeOverflowSubmenu")
        self._mode_overflow_actions: list[QAction] = []
        for _mode, label, idx in MODE_SEGMENTS:
            sub_action = QAction(label, self)
            sub_action.triggered.connect(
                lambda _checked=False, target_idx=idx: self._on_mode_segment_clicked(
                    target_idx
                )
            )
            self._mode_overflow_submenu.addAction(sub_action)
            self._mode_overflow_actions.append(sub_action)
        self._mode_segment_action.setMenu(self._mode_overflow_submenu)
        # Map each eligible toolbar child widget to its menu QAction.
        # Order matters: this is left-to-right toolbar order, so
        # recompute hides right-to-left (reversed iteration).
        self._toolbar_overflow_items: list[tuple[QWidget, QAction]] = [
            (self._a2l_btn, self._a2l_action),
            (self._output_btn, self._output_action),
            (self._transport_chip, self._transport_action),
            (self._settings_btn, self._settings_action),
            (self._segment_btn, self._segment_action),
            (self._mode_segment_widget, self._mode_segment_action),
        ]
        # Initial seed — see
        # `pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`:
        # the recompute must seed once at the end of __init__ so the
        # overflow chevron's initial visibility is honest before
        # show(). Defer one event-loop tick via ``QTimer.singleShot``
        # so the toolbar's child widgets have settled width() values
        # — calling synchronously here observes width()=0 and would
        # otherwise have to fall back to a hard-coded default that
        # mis-seeds the state on narrower screens.
        QTimer.singleShot(0, self._recompute_toolbar_overflow)

        return toolbar

    def _make_selector_button(
        self, object_name: str, key: str, value: str
    ) -> QPushButton:
        button = QPushButton("", self)
        button.setObjectName(object_name)
        button.setProperty("cockpitSelector", True)
        button.setFixedHeight(28)
        # Spec §S4.2 — loosen the selector widths from a fixed value to
        # a min+max band so the toolbar can compress at narrow window
        # widths without clipping primary actions. The default-render
        # width sits inside each band so the visible diff at 1280px is
        # zero.
        width_bands = {
            "cockpitSelectorA2l": (90, 160),
            "cockpitSelectorOutput": (110, 220),
        }
        min_w, max_w = width_bands.get(object_name, (90, 160))
        button.setMinimumWidth(min_w)
        button.setMaximumWidth(max_w)
        button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(button)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        key_label = QLabel(key, button)
        key_label.setObjectName("cockpitSelectorKey")
        value_label = QLabel(value, button)
        value_label.setObjectName("cockpitSelectorValue")
        key_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        value_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(key_label, 0, Qt.AlignVCenter)
        layout.addWidget(value_label, 1, Qt.AlignVCenter)
        caret = QLabel("▾", button)
        caret.setObjectName("cockpitSelectorCaret")
        caret.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(caret, 0, Qt.AlignVCenter)

        button.setToolTip(value)
        return button

    def _set_selector_value(
        self, button: QPushButton, key: str, value: str
    ) -> None:
        key_label = button.findChild(QLabel, "cockpitSelectorKey")
        value_label = button.findChild(QLabel, "cockpitSelectorValue")
        if key_label is not None:
            key_label.setText(key)
        if value_label is not None:
            value_label.setText(value)
        button.setToolTip(value)

    def _toolbar_separator(self, parent: QWidget) -> QFrame:
        separator = QFrame(parent)
        separator.setObjectName("cockpitToolbarSeparator")
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setFixedHeight(22)
        return separator

    def _build_mode_segment(self, parent: QWidget) -> QWidget:
        segment = QWidget(parent)
        segment.setObjectName("cockpitModeSegment")
        segment.setFixedHeight(32)
        layout = QHBoxLayout(segment)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._mode_button_group = QButtonGroup(self)
        self._mode_button_group.setExclusive(True)
        self._mode_buttons: dict[int, QPushButton] = {}
        for mode, label, index in MODE_SEGMENTS:
            button = QPushButton(label, segment)
            button.setCheckable(True)
            button.setProperty("cockpitMode", mode)
            button.setFixedHeight(26)
            button.setMinimumWidth(56)
            button.clicked.connect(
                lambda _checked=False, tab_index=index: (
                    self._on_mode_segment_clicked(tab_index)
                )
            )
            self._mode_button_group.addButton(button, index)
            self._mode_buttons[index] = button
            layout.addWidget(button)
        self._sync_mode_segment(0)
        return segment

    def _neutralize_mode_tab_bar(self) -> None:
        tab_bar = self._mode_tabs.tabBar()
        tab_bar.hide()
        tab_bar.setEnabled(False)
        tab_bar.setMinimumHeight(0)
        tab_bar.setMaximumHeight(0)
        self._mode_tabs.setDocumentMode(True)

    # ------------------------------------------------------------------
    # Toolbar overflow recompute — spec §S4.2.
    # ------------------------------------------------------------------

    def _recompute_toolbar_overflow(self) -> None:
        """Hide overflow-eligible toolbar widgets right-to-left when the
        toolbar's accumulated child width exceeds its outer width, and
        mirror the hidden affordances into ``_overflow_menu``.

        Eligible widgets are taken from ``_toolbar_overflow_items``;
        ``_rec_indicator`` and ``_main_btn`` are NEVER eligible. Each
        demoted widget is marked with the dynamic property
        ``cockpitOverflowHidden = True`` so callers (and tests) can
        distinguish overflow-hidden widgets from state-hidden widgets
        (e.g. the segment marker during DISCONNECTED). Widgets that
        were previously overflow-hidden may be restored when the
        toolbar widens, unless they were also state-hidden in the
        meantime.
        """
        if not hasattr(self, "_toolbar") or not hasattr(
            self, "_toolbar_overflow_items"
        ):
            return
        toolbar = self._toolbar
        outer_w = toolbar.width()
        if outer_w <= 0:
            # Layout not yet computed (pre-show). Use the parent
            # window's width as a best-effort proxy.
            outer_w = self.width()
        if outer_w <= 0:
            # Still not laid out — give up rather than seed against a
            # hard-coded fallback (which would mis-seed on screens
            # narrower than the default). The first ``resizeEvent``
            # after show() will recompute against real widths.
            return

        # Determine each eligible widget's "design visibility" — True
        # if the state machine wants it visible. We treat
        # overflow-hidden widgets (cockpitOverflowHidden=True) as
        # design-visible because they were hidden by us, not by state.
        # Widgets that are not visible AND not overflow-hidden are
        # design-hidden (e.g. segment marker outside RECORDING) and
        # are excluded from the eligibility set for this recompute.
        eligible: list[tuple[QWidget, QAction, bool]] = []
        for widget, action in self._toolbar_overflow_items:
            overflow_hidden = bool(widget.property("cockpitOverflowHidden"))
            design_visible = widget.isVisible() or overflow_hidden
            eligible.append((widget, action, design_visible))

        # Compute always-on cost: REC indicator + main button +
        # overflow chevron's own width + separators + layout margins.
        layout = toolbar.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        spacing = max(0, layout.spacing())
        always_on_w = margins.left() + margins.right()
        for w in (self._rec_indicator, self._main_btn, self._overflow_btn):
            if w is not None:
                always_on_w += max(w.sizeHint().width(), w.minimumWidth())
        # Count separators (find by objectName) and the stretch spacer
        # contribution (treat spacer as 0 width — it absorbs slack).
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                continue
            if w.objectName() == "cockpitToolbarSeparator":
                always_on_w += max(w.sizeHint().width(), w.minimumWidth())
        # Spacing between every adjacent pair of widgets — a coarse
        # estimate from the design-visible eligible count plus the
        # three always-on widgets.
        approx_widget_count = (
            len([w for w, _, dv in eligible if dv])
            + 3  # rec, main, overflow
        )
        always_on_w += max(0, approx_widget_count - 1) * spacing

        # Cache each eligible widget's natural width.
        widget_natural_w: dict[QWidget, int] = {}
        for widget, _action, _dv in eligible:
            natural = max(widget.sizeHint().width(), widget.minimumWidth())
            widget_natural_w[widget] = natural

        # Start with every design-visible eligible widget shown; demote
        # by explicit priority until the running total fits. Menu order
        # stays left-to-right when rebuilt below.
        shown: list[QWidget] = [w for w, _, dv in eligible if dv]
        demote_rank = {
            self._transport_chip: 0,
            self._output_btn: 1,
            self._settings_btn: 2,
            self._segment_btn: 3,
            self._a2l_btn: 4,
            self._mode_segment_widget: 5,
        }
        shown.sort(key=lambda w: demote_rank.get(w, -1), reverse=True)
        running = always_on_w + sum(widget_natural_w[w] for w in shown)
        demoted: list[QWidget] = []
        while running > outer_w and shown:
            victim = shown.pop()
            demoted.append(victim)
            running -= widget_natural_w[victim]

        # Apply visibility + dynamic-property updates.
        demoted_set = set(demoted)
        for widget, _action, design_visible in eligible:
            if not design_visible:
                # State-hidden — never touched here.
                continue
            if widget in demoted_set:
                widget.setProperty("cockpitOverflowHidden", True)
                widget.setVisible(False)
            else:
                if bool(widget.property("cockpitOverflowHidden")):
                    widget.setProperty("cockpitOverflowHidden", False)
                widget.setVisible(True)

        # Rebuild the overflow menu in left-to-right toolbar order so
        # the menu reads naturally.
        self._overflow_menu.clear()
        ordered_demoted: list[QAction] = []
        for widget, action, _ in eligible:
            if widget in demoted_set:
                if widget is self._transport_chip:
                    action.setText(self._transport_chip.text())
                ordered_demoted.append(action)
        for action in ordered_demoted:
            self._overflow_menu.addAction(action)
        self._overflow_btn.setVisible(len(ordered_demoted) > 0)

    def resizeEvent(self, event):  # noqa: N802 — Qt override
        """Recompute toolbar overflow on every window resize.

        Pure UI hook — does not touch the four-state machine.
        """
        super().resizeEvent(event)
        if hasattr(self, "_overflow_btn"):
            self._recompute_toolbar_overflow()

    def _on_mode_segment_clicked(self, index: int) -> None:
        if hasattr(self, "_mode_tabs"):
            self._mode_tabs.setCurrentIndex(index)
        else:
            self._sync_mode_segment(index)

    def _sync_mode_segment(self, index: int) -> None:
        if not hasattr(self, "_mode_buttons"):
            return
        for button_index, button in self._mode_buttons.items():
            old = button.blockSignals(True)
            button.setChecked(button_index == index)
            button.blockSignals(old)

    @staticmethod
    def _set_visual_property(widget: QWidget, name: str, value: str) -> None:
        if widget.property(name) == value:
            return
        widget.setProperty(name, value)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _build_acquisition_page(self) -> QWidget:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QHBoxLayout, QSplitter, QWidget

        from mf4_analyzer.acquisition_ui.widgets.left_pane import LeftPane
        from mf4_analyzer.acquisition_ui.widgets.live_cards import LiveCardGrid

        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal, page)
        splitter.setObjectName("cockpitSplitter")
        self._splitter = splitter

        self._left_pane = LeftPane(splitter)
        self._left_pane.selection_changed.connect(self._on_selection_changed)

        self._center = LiveCardGrid(splitter)
        # Cockpit keeps the live card flow in place while focusing one card;
        # Replay intentionally retains LiveCardGrid's isolated default.
        self._center.set_focus_presentation("inplace")

        # Pin 接线（spec 2026-07-08 §G6b）。ReplayTab 的 grid 不启用。
        self._left_pane.set_pin_state_provider(
            lambda name: name in self._effective_pinned_names()
        )
        self._left_pane.pin_toggle_requested.connect(self._on_pin_toggle)
        self._center.set_pinning_enabled(True)
        self._center.unpin_requested.connect(self.unpin_channel)
        self._center.pins_reset_requested.connect(lambda: self.reset_pins())

        # Spec B3/B4: health moved to the top strip (chips + preflight pill)
        # and the bottom facts / escalation bar, so the capture body is a
        # two-column left + center splitter — the right health pane is gone.
        splitter.addWidget(self._left_pane)
        splitter.addWidget(self._center)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.setHandleWidth(3)
        splitter.setSizes([420, 860])
        layout.addWidget(splitter)
        return page

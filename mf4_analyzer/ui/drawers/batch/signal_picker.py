"""Summary-row multi-select picker for the batch dialog.

``SignalPickerPopup`` collapses to a **read-only summary row**: the trigger
does one job only — report what is currently selected.  Searching, checking
and the bulk actions all live inside the popup, whose search field takes focus
the moment the popup opens.  Splitting the two jobs is what keeps the trigger
geometry pinned while the user types (chips used to vanish mid-query and drag
the caret hundreds of pixels sideways) and lets the popup be wider than the
narrow BatchSheet column it hangs from, so 46-character signal names stay
readable.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from PyQt5.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QLayout, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.popup_shell import apply_popup_shell


# Signal names are code identifiers; a monospace face lines up the ``_xds16`` /
# ``_gdf32`` suffixes that distinguish otherwise identical channels.  Matches
# pipeline_strip.py and the three existing style.qss uses.
_MONO = '"SF Mono","Menlo",monospace'
# Qt's QSS parser converts ``font-size:<n>px`` through QVariant::Int, so the
# prototype's fractional 11.5px is silently dropped.  12px is the portable
# integer neighbour and matches the repo's existing px-based rules.
_MONO_PX = "12px"

_ARROW_REST = QColor("#7b8798")
_ARROW_HOVER = QColor("#354254")


class _TriggerFrame(QFrame):
    """Button-semantics surface for the collapsed picker.

    Click, ``Space`` or ``Enter`` all expand.  It never accepts text — the
    caret belongs to the popup's search field.
    """

    clicked = pyqtSignal()
    resized = pyqtSignal()
    enabledChanged = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 (Qt API)
        if event.key() in (
            Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down,
        ):
            event.accept()
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self.resized.emit()

    def changeEvent(self, event):  # noqa: N802 (Qt API)
        super().changeEvent(event)
        # setEnabled(False) on an ancestor (BatchSheet.lock_editing disables
        # the whole input panel) cascades effective-enabled state down to
        # this frame without necessarily calling setEnabled() on it
        # directly; Qt still delivers EnabledChange here, so re-skin from it
        # rather than relying solely on a bare QSS ``:disabled`` selector.
        if event.type() == QEvent.EnabledChange:
            self.enabledChanged.emit()


class _ArrowButton(QPushButton):
    """Chevron toggle that swaps a drawn icon for direction and hover."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_cache: dict[tuple[bool, bool], object] = {}
        self._expanded = False
        self._hovered = False
        self.setFlat(True)
        self.setFixedSize(26, 28)
        self.setIconSize(QSize(14, 14))
        self.setFocusPolicy(Qt.NoFocus)
        self._refresh_icon()

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._refresh_icon()

    def enterEvent(self, event):  # noqa: N802 (Qt API)
        self._hovered = True
        self._refresh_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt API)
        self._hovered = False
        self._refresh_icon()
        super().leaveEvent(event)

    def _refresh_icon(self) -> None:
        key = (self._expanded, self._hovered)
        icon = self._icon_cache.get(key)
        if icon is None:
            color = _ARROW_HOVER if self._hovered else _ARROW_REST
            factory = Icons.chevron_up if self._expanded else Icons.chevron_down
            icon = factory(color)
            self._icon_cache[key] = icon
        self.setIcon(icon)


class SignalPickerPopup(QWidget):
    """Read-only summary trigger plus a searchable checkbox popup."""

    selectionChanged = pyqtSignal(tuple)
    # Emitted when the user asks for the partial-availability restriction to be
    # lifted.  The picker does not own the target policy, so it only reports
    # the request; whoever owns that state decides (see InputPanel).
    relaxPolicyRequested = pyqtSignal()

    _DISPLAY_HEIGHT = 38
    _POPUP_MIN_WIDTH = 420
    _LIST_MIN_HEIGHT = 96
    # Rows shown before the list starts scrolling.  Without a cap the popup
    # grows to whatever the screen allows — 25 channels ate most of the
    # display — and, worse, its height then tracked the filter, so the
    # flip-above decision changed as the user typed.  A fixed row budget
    # keeps the popup one predictable size.
    _LIST_MAX_ROWS = 9
    # Popup width minus its chrome (layout margins, surface border, the
    # vertical scrollbar a capped list always shows, and the checkbox
    # indicator + padding) — what is left is the text budget per row.
    _ROW_TEXT_INSET = 74
    _SUMMARY_MIN_BUDGET = 60
    _SCREEN_MARGIN = 8
    _POPUP_GAP = 4

    # Resting / active trigger skins.  QSS has no ``box-shadow``, so the
    # prototype's focus glow becomes a 1px -> 2px border; the layout margins
    # give the extra pixel back so nothing shifts between the two states.
    #
    # Rest now mirrors the global QLineEdit/QComboBox skin (style.qss:65-92:
    # white fill, #dfe5ee border, #b7c4d3 on hover) instead of a bespoke
    # sunken grey — that grey (#eef2f7) sat darker than even the *disabled*
    # global input fill, so users read the resting trigger as read-only.
    _TRIGGER_REST_QSS = (
        "#SignalPickerTrigger {border:1px solid #dfe5ee; border-radius:7px;"
        " background:#ffffff;}"
        "#SignalPickerTrigger:hover {background:#f8fafc;"
        " border-color:#b7c4d3;}"
    )
    _TRIGGER_ACTIVE_QSS = (
        "#SignalPickerTrigger {border:2px solid #1769e0; border-radius:7px;"
        " background:#fff;}"
    )
    # Disabled skin — same recipe as QLineEdit:disabled in style.qss. Applied
    # explicitly from _apply_trigger_style() rather than left to a bare
    # ``:disabled`` selector: the active skin has no disabled-aware rule of
    # its own, and a QFrame disabled mid-expand must not keep showing the
    # blue focus ring.
    _TRIGGER_DISABLED_QSS = (
        "#SignalPickerTrigger {border:1px solid #eef2f7; border-radius:7px;"
        " background:#f5f7fb;}"
    )
    _TRIGGER_REST_MARGINS = (8, 0, 4, 0)
    _TRIGGER_ACTIVE_MARGINS = (7, 0, 3, 0)

    # All three skins carry the same metrics so switching between placeholder,
    # signal name and disabled text never re-measures the elision budget
    # against a different font.  Only the colour differs.
    _SUMMARY_QSS = (
        "#SignalPickerSummary {background:transparent; border:none;"
        " color:#172033; font-family:" + _MONO + ";"
        " font-size:" + _MONO_PX + ";}"
        "#SignalPickerSummary:disabled {color:#94a3b8;}"
    )
    _SUMMARY_PLACEHOLDER_QSS = (
        "#SignalPickerSummary {background:transparent; border:none;"
        " color:#64748b; font-family:" + _MONO + ";"
        " font-size:" + _MONO_PX + ";}"
        "#SignalPickerSummary:disabled {color:#94a3b8;}"
    )

    def __init__(
        self,
        available_signals: Iterable[str] = (),
        partially_available: Mapping[str, str] | None = None,
        initial_selection: tuple[str, ...] = (),
        parent: QWidget | None = None,
        *,
        single_select: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._DISPLAY_HEIGHT)
        self._single_select = bool(single_select)
        self._available: list[str] = list(available_signals)
        self._partial: dict[str, str] = dict(partially_available or {})
        self._partial_selectable = False
        selection = tuple(initial_selection)
        if self._single_select and len(selection) > 1:
            selection = selection[:1]
        self._selected: tuple[str, ...] = selection
        self._suppress_signal = False
        self._expanded = False
        self._match_count = 0
        self._locked_list_height: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SetNoConstraint)

        # ---------------- collapsed trigger ----------------
        self._trigger = _TriggerFrame(self)
        self._trigger.setObjectName("SignalPickerTrigger")
        self._trigger.setFrameShape(QFrame.NoFrame)
        self._trigger.setAttribute(Qt.WA_StyledBackground, True)
        self._trigger.setFocusPolicy(Qt.StrongFocus)
        self._trigger.setCursor(Qt.PointingHandCursor)
        self._trigger.setFixedHeight(self._DISPLAY_HEIGHT)
        self._trigger.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Signals/filters are wired at the end of __init__: the trigger emits
        # resize events while the popup's widgets are still being built.
        # Historic name kept as an alias: probes, proofs and tests reach the
        # collapsed surface through it.
        self._display_frame = self._trigger

        self._trigger_layout = QHBoxLayout(self._trigger)
        self._trigger_layout.setContentsMargins(*self._TRIGGER_REST_MARGINS)
        self._trigger_layout.setSpacing(6)

        self._summary_label = QLabel(self._trigger)
        self._summary_label.setObjectName("SignalPickerSummary")
        self._summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._summary_is_placeholder: bool | None = None
        self._set_summary_placeholder(True)
        self._trigger_layout.addWidget(self._summary_label, 1)

        self._overflow_label = QLabel(self._trigger)
        self._overflow_label.setObjectName("SignalPickerOverflow")
        self._overflow_label.setAlignment(Qt.AlignCenter)
        self._overflow_label.setStyleSheet(
            "#SignalPickerOverflow {color:#234d78; background:#eef4ff;"
            " border:1px solid #d4e3f8; border-radius:6px; padding:3px 7px;"
            " font-family:" + _MONO + "; font-size:11px; font-weight:600;}"
        )
        self._overflow_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._overflow_label.hide()
        self._trigger_layout.addWidget(self._overflow_label)

        self._arrow_button = _ArrowButton(self._trigger)
        self._arrow_button.setObjectName("SignalPickerArrow")
        self._arrow_button.setToolTip("展开信号列表")
        self._arrow_button.setStyleSheet(
            "#SignalPickerArrow {border:none; border-radius:6px;"
            " background:transparent; padding:0;}"
            "#SignalPickerArrow:hover {background:#eef2f7;}"
        )
        self._arrow_button.clicked.connect(self._toggle_popup)
        self._trigger_layout.addWidget(self._arrow_button)
        outer.addWidget(self._trigger, 1)

        # ---------------- popup ----------------
        # The rounded shell (apply_popup_shell + WA_TranslucentBackground +
        # WA_StyledBackground + NoFrame) is load bearing: dropping any of it
        # leaves a square frame around the radius on macOS.  Children paint
        # their own backgrounds, which is fine — only the translucent shell
        # itself loses plain QSS.
        self._popup = QFrame(self, Qt.Popup)
        self._popup.setObjectName("SignalPickerPopup")
        apply_popup_shell(self._popup)
        self._popup.setFrameShape(QFrame.NoFrame)
        self._popup.setAttribute(Qt.WA_StyledBackground, True)
        # WA_TranslucentBackground (installed by apply_popup_shell) makes the
        # shell's OWN qss background a no-op, so filling #fff here leaves the
        # list area see-through on a real screen — offscreen grabs composite
        # onto black and hide it.  An inner surface carries the fill and the
        # radius instead, mirroring RenderStylePopover's ``_surface``.
        self._popup.setStyleSheet(
            "#SignalPickerPopup {background:transparent; border:none;}"
        )
        self._popup.setMinimumWidth(self._POPUP_MIN_WIDTH)
        self._popup.setFocusPolicy(Qt.StrongFocus)
        shell_lay = QVBoxLayout(self._popup)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)

        self._surface = QFrame(self._popup)
        self._surface.setObjectName("SignalPickerSurface")
        self._surface.setAttribute(Qt.WA_StyledBackground, True)
        self._surface.setStyleSheet(
            "#SignalPickerSurface {background:#fff; border:1px solid #cbd5e1;"
            " border-radius:9px;}"
        )
        shell_lay.addWidget(self._surface)

        pop_lay = QVBoxLayout(self._surface)
        pop_lay.setContentsMargins(6, 6, 6, 6)
        pop_lay.setSpacing(6)
        self._popup_layout = pop_lay

        self._search = QLineEdit(self._surface)
        self._search.setObjectName("SignalPickerSearch")
        self._search.setPlaceholderText("搜索信号…")
        self._search.setFrame(False)
        self._search.setFixedHeight(32)
        self._search.setStyleSheet(
            "#SignalPickerSearch {border:1px solid #d3dbe5; border-radius:7px;"
            " background:#f7f9fc; color:#172033; padding:0 9px;}"
            "#SignalPickerSearch:focus {border:1px solid #1769e0;"
            " background:#fff;}"
        )
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.installEventFilter(self)
        pop_lay.addWidget(self._search)
        # Focus proxy: any code (or Qt itself) that focuses the popup lands on
        # the search field, and clearing the popup's focus still reaches the
        # widget that actually holds it.
        self._popup.setFocusProxy(self._search)

        self._list = QListWidget(self._surface)
        self._list.setObjectName("SignalPickerList")
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.setFrameShape(QFrame.NoFrame)
        # No horizontal scrolling: dragging a dropdown sideways to read the
        # end of a name is poor interaction, and the scrollbar also ate
        # viewport height, leaving the last row clipped under the footer.
        # Names are middle-elided to the popup width instead (same treatment
        # as the collapsed summary), with the full name on the tooltip.
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            "#SignalPickerList {border:none; background:transparent;"
            " outline:none;}"
            "#SignalPickerList::item {border-radius:5px;}"
            "#SignalPickerList::item:hover {background:#f2f6fb;}"
            "#SignalPickerList QCheckBox {background:transparent;"
            " color:#26313f; spacing:8px; padding:2px 7px;"
            " font-family:" + _MONO + "; font-size:" + _MONO_PX + ";}"
            "#SignalPickerList QCheckBox:disabled {color:#98a3b1;}"
        )
        pop_lay.addWidget(self._list, 1)

        self._empty_label = QLabel("无匹配信号", self._surface)
        self._empty_label.setObjectName("SignalPickerEmpty")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(
            "#SignalPickerEmpty {color:#8b95a3; background:transparent;"
            " padding:14px 8px;}"
        )
        self._empty_label.hide()
        pop_lay.addWidget(self._empty_label)

        # Cause-and-exit row.  When every row is greyed out the list alone says
        # nothing: the user reads "匹配 18" and cannot tick one of them.  This
        # names the reason and offers the one action that lifts it.  Kept as a
        # sibling of the stats footer so the popup keeps a single bottom block.
        self._notice = QWidget(self._surface)
        self._notice.setObjectName("SignalPickerNotice")
        self._notice.setAttribute(Qt.WA_StyledBackground, True)
        self._notice.setStyleSheet(
            "#SignalPickerNotice {background:#fff8ec;"
            " border-top:1px solid #f2e3c9;}"
            "#SignalPickerNoticeText {color:#8a5a12; background:transparent;}"
            "#SignalPickerNotice QPushButton {border:1px solid #d9c6a2;"
            " background:#fffdf8; color:#8a5a12; padding:3px 8px;"
            " border-radius:5px;}"
            "#SignalPickerNotice QPushButton:hover {background:#fdf1dc;}"
        )
        notice_lay = QHBoxLayout(self._notice)
        notice_lay.setContentsMargins(10, 7, 10, 7)
        notice_lay.setSpacing(8)
        self._notice_label = QLabel(self._notice)
        self._notice_label.setObjectName("SignalPickerNoticeText")
        self._notice_label.setWordWrap(True)
        notice_lay.addWidget(self._notice_label, 1)
        self._relax_button = QPushButton("改用「按来源可用」", self._notice)
        self._relax_button.setObjectName("SignalPickerRelax")
        self._relax_button.setCursor(Qt.PointingHandCursor)
        self._relax_button.setFocusPolicy(Qt.TabFocus)
        self._relax_button.setToolTip(
            "切换目标策略，让只存在于部分来源的通道变为可选"
        )
        self._relax_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._relax_button.clicked.connect(self.relaxPolicyRequested)
        notice_lay.addWidget(self._relax_button)
        self._notice.hide()
        pop_lay.addWidget(self._notice)

        self._foot = QWidget(self._surface)
        self._foot.setObjectName("SignalPickerFoot")
        self._foot.setAttribute(Qt.WA_StyledBackground, True)
        self._foot.setStyleSheet(
            "#SignalPickerFoot {background:#fafbfd;"
            " border-top:1px solid #edf1f6;}"
            "#SignalPickerFootStats {color:#5c6875; background:transparent;}"
            "#SignalPickerFoot QPushButton {border:none; background:transparent;"
            " color:#1769e0; padding:2px 4px; border-radius:4px;}"
            "#SignalPickerFoot QPushButton:hover {background:#eef4ff;}"
            "#SignalPickerFoot QPushButton:disabled {color:#a8b2bf;"
            " background:transparent;}"
        )
        foot_lay = QHBoxLayout(self._foot)
        foot_lay.setContentsMargins(10, 7, 10, 7)
        foot_lay.setSpacing(10)

        self._foot_stats = QLabel(self._foot)
        self._foot_stats.setObjectName("SignalPickerFootStats")
        foot_lay.addWidget(self._foot_stats)
        foot_lay.addStretch(1)

        self._select_all_button = QPushButton("全选", self._foot)
        self._select_all_button.setObjectName("SignalPickerSelectAll")
        self._select_all_button.setFlat(True)
        self._select_all_button.setCursor(Qt.PointingHandCursor)
        self._select_all_button.setFocusPolicy(Qt.TabFocus)
        self._select_all_button.setToolTip("把当前筛选结果并入已选")
        self._select_all_button.clicked.connect(self._on_select_all)
        foot_lay.addWidget(self._select_all_button)
        # "Select all" is meaningless when only one signal may be held.
        self._select_all_button.setVisible(not self._single_select)

        self._clear_button = QPushButton("清空", self._foot)
        self._clear_button.setObjectName("SignalPickerClear")
        self._clear_button.setFlat(True)
        self._clear_button.setCursor(Qt.PointingHandCursor)
        self._clear_button.setFocusPolicy(Qt.TabFocus)
        self._clear_button.setToolTip("清空全部已选信号")
        self._clear_button.clicked.connect(self._on_clear)
        foot_lay.addWidget(self._clear_button)

        pop_lay.addWidget(self._foot)

        self._popup.installEventFilter(self)
        self._trigger.installEventFilter(self)
        self._trigger.clicked.connect(self._open_from_display)
        self._trigger.resized.connect(self._refresh_display)
        self._trigger.enabledChanged.connect(self._apply_trigger_style)
        self._apply_trigger_style()
        self._rebuild_list()
        self._refresh_display()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_selected(self, signals: Iterable[str]) -> None:
        new = tuple(signals)
        if self._single_select and len(new) > 1:
            new = new[:1]
        if new == self._selected:
            return
        self._apply_selection(new)

    def set_available(self, available_signals: Iterable[str]) -> None:
        self._available = list(available_signals)
        self._rebuild_list()
        self._refresh_display()

    def set_partially_available(
        self,
        partially_available: Mapping[str, str] | None,
        *,
        selectable: bool = False,
    ) -> None:
        self._partial = dict(partially_available or {})
        self._partial_selectable = bool(selectable)
        keep = tuple(
            signal for signal in self._selected
            if signal in self._available or signal in self._partial
        )
        if keep != self._selected:
            self._selected = keep
            self.selectionChanged.emit(self._selected)
        self._rebuild_list()
        self._refresh_display()

    def selected(self) -> tuple[str, ...]:
        return self._selected

    def show_popup(self) -> None:
        if self._popup.isVisible():
            return
        # Re-measure once per opening; the size then stays put while typing.
        self._locked_list_height = None
        self._sync_popup_geometry()
        self._popup.show()
        self._popup.raise_()
        self._set_expanded(True)
        # Opening *is* the invitation to type: without this the extra search
        # box would cost a second click, which is what option A trades on.
        self._search.setFocus(Qt.PopupFocusReason)
        self._search.selectAll()

    def hide_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()  # QEvent.Hide resets the arrow and the query
        else:
            self._set_expanded(False)
            self._reset_search()

    def is_popup_visible(self) -> bool:
        return self._popup.isVisible()

    def visible_items(self) -> list[str]:
        return [
            self._list.item(index).data(Qt.UserRole)
            for index in range(self._list.count())
            if not self._list.item(index).isHidden()
        ]

    def is_disabled(self, signal: str) -> bool:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) == signal:
                return not bool(item.flags() & Qt.ItemIsEnabled)
        return False

    def label_for(self, signal: str) -> str:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) != signal:
                continue
            # Not ``checkbox.text()``: that one is elided for display.
            return self._full_label(signal)
        return ""

    def set_search_text(self, text: str) -> None:
        """Write *text* into the popup's search field."""

        self._search.setText(text)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        """Return a selection-count-independent preferred size."""

        return QSize(220, self._DISPLAY_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(0, self._DISPLAY_HEIGHT)

    # ------------------------------------------------------------------
    # Internal — expansion state
    # ------------------------------------------------------------------
    def _open_from_display(self) -> None:
        self.show_popup()

    def _toggle_popup(self) -> None:
        if self.is_popup_visible():
            self.hide_popup()
        else:
            self.show_popup()

    def _set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self._expanded = expanded
        self._arrow_button.set_expanded(expanded)
        self._arrow_button.setToolTip(
            "收起信号列表" if expanded else "展开信号列表"
        )
        self._apply_trigger_style()

    def _apply_trigger_style(self) -> None:
        if not self._trigger.isEnabled():
            # Disabled always wins, even mid-expand/focus: a locked panel
            # (BatchSheet.lock_editing) must not keep showing the blue
            # active ring underneath the greyed-out contents.
            self._trigger.setStyleSheet(self._TRIGGER_DISABLED_QSS)
            self._trigger_layout.setContentsMargins(*self._TRIGGER_REST_MARGINS)
            return
        active = self._expanded or self._trigger.hasFocus()
        if active:
            self._trigger.setStyleSheet(self._TRIGGER_ACTIVE_QSS)
            self._trigger_layout.setContentsMargins(*self._TRIGGER_ACTIVE_MARGINS)
        else:
            self._trigger.setStyleSheet(self._TRIGGER_REST_QSS)
            self._trigger_layout.setContentsMargins(*self._TRIGGER_REST_MARGINS)

    def _reset_search(self) -> None:
        if self._search.text():
            self._search.clear()

    # ------------------------------------------------------------------
    # Internal — popup geometry
    # ------------------------------------------------------------------
    def _available_screen_rect(self):
        screen = QApplication.screenAt(self._trigger.mapToGlobal(QPoint(0, 0)))
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _full_label(self, name: str) -> str:
        """Untruncated row text: the name plus any partial-availability tag."""

        if name in self._partial:
            return f"{name} {self._partial[name]}".strip()
        return name

    def _elide_list_labels(self, popup_width: int) -> None:
        """Middle-elide every row to the popup width.

        Derived from *popup_width* rather than ``viewport().width()``: this
        runs right after ``setFixedWidth`` and the viewport has not been
        re-laid-out yet.  Middle elision keeps both the module prefix and the
        ``_xds16`` / ``_gdf32`` suffix, which is what tells two otherwise
        identical EPS channels apart.
        """

        budget = popup_width - self._ROW_TEXT_INSET
        if budget <= 0:
            return
        for index in range(self._list.count()):
            item = self._list.item(index)
            checkbox = self._list.itemWidget(item)
            if not isinstance(checkbox, QCheckBox):
                continue
            full = self._full_label(str(item.data(Qt.UserRole) or ""))
            checkbox.setText(
                QFontMetrics(checkbox.font()).elidedText(
                    full, Qt.ElideMiddle, budget,
                )
            )
            item.setSizeHint(checkbox.sizeHint())

    def _row_budget(self) -> int:
        """Height of ``_LIST_MAX_ROWS`` rows — anything longer scrolls."""

        row = 0
        for index in range(self._list.count()):
            row = self._list.sizeHintForRow(index)
            if row > 0:
                break
        if row <= 0:
            row = 26
        # Exactly N rows, no slack: a few spare pixels let row N+1 peek out
        # from under the footer and read as a clipped entry rather than as
        # "scroll for more".
        return row * self._LIST_MAX_ROWS + 2 * self._list.frameWidth()

    def _list_content_height(self) -> int:
        total = 0
        for index in range(self._list.count()):
            if self._list.item(index).isHidden():
                continue
            total += self._list.sizeHintForRow(index)
        return total + 2 * self._list.frameWidth()

    def _sync_popup_geometry(self) -> None:
        """Size and place the popup against whatever screen room is left."""

        trigger = self._trigger
        anchor = trigger.mapToGlobal(trigger.rect().bottomLeft())
        top = trigger.mapToGlobal(trigger.rect().topLeft())
        margin = self._SCREEN_MARGIN
        rect = self._available_screen_rect()

        width = max(self._POPUP_MIN_WIDTH, trigger.width())
        if rect is not None:
            width = min(width, max(self._POPUP_MIN_WIDTH, rect.width() - 2 * margin))
        self._popup.setFixedWidth(width)
        self._elide_list_labels(width)

        room = (rect.bottom() - anchor.y() - margin) if rect is not None else 480
        chrome = (
            self._popup_layout.contentsMargins().top()
            + self._popup_layout.contentsMargins().bottom()
            + self._search.height()
            + self._foot.sizeHint().height()
            + 2 * self._popup_layout.spacing()
            + self._POPUP_GAP
        )
        if self.is_relax_notice_visible():
            # The notice is a third fixed block; leaving it out of the chrome
            # budget makes the list overshoot and pushes the footer off-screen.
            # Asked via ``isVisibleTo``: this runs from ``show_popup`` before
            # the popup itself is shown, when ``isVisible()`` is still False.
            chrome += (
                self._notice.sizeHint().height() + self._popup_layout.spacing()
            )
        cap = max(self._LIST_MIN_HEIGHT, room - chrome)
        if self._locked_list_height is None:
            # Measured once per opening, against the unfiltered list, then
            # held: a popup that resizes while you type also re-decides
            # whether to open upwards, which reads as the panel jumping.
            self._locked_list_height = max(
                32, min(self._list_content_height(), self._row_budget(), cap),
            )
        height = min(self._locked_list_height, cap)
        self._list.setFixedHeight(height)
        # The empty state stands in for the list, so "no matches" does not
        # collapse the popup to a different size (and a different position).
        self._empty_label.setFixedHeight(height)
        # ``adjustSize`` reads the layout, and a ``setVisible`` from this same
        # turn has not reached it yet: on the empty->matches transition both
        # the list and the empty label still counted, doubling the popup.
        # Activating first makes the measurement see current visibility.
        self._popup_layout.activate()
        self._popup.layout().activate()
        self._popup.adjustSize()

        x = anchor.x()
        y = anchor.y() + self._POPUP_GAP
        if rect is not None:
            if x + width > rect.right() - margin:
                x = rect.right() - margin - width
            x = max(rect.left() + margin, x)
            if y + self._popup.height() > rect.bottom() - margin:
                above = top.y() - self._POPUP_GAP - self._popup.height()
                y = (
                    above if above >= rect.top() + margin
                    else max(
                        rect.top() + margin,
                        rect.bottom() - margin - self._popup.height(),
                    )
                )
        self._popup.move(x, y)

    # ------------------------------------------------------------------
    # Internal — list and selection
    # ------------------------------------------------------------------
    def _rebuild_list(self) -> None:
        self._list.clear()
        names = list(self._available)
        names.extend(name for name in self._partial if name not in names)
        for name in names:
            item = QListWidgetItem(self._list)
            item.setData(Qt.UserRole, name)
            label = name
            if name in self._partial:
                label = f"{name} {self._partial[name]}".strip()
            checkbox = QCheckBox(label, self._list)
            checkbox.setToolTip(name)
            checkbox.setChecked(name in self._selected)
            if name in self._partial and not self._partial_selectable:
                checkbox.setEnabled(False)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            else:
                checkbox.toggled.connect(
                    lambda checked, signal=name: self._on_checkbox_toggled(
                        signal, checked,
                    )
                )
            item.setSizeHint(checkbox.sizeHint())
            self._list.setItemWidget(item, checkbox)
        # Before the filter pass: ``_on_search_text_changed`` re-syncs the popup
        # geometry, and that measurement has to see the notice's final state.
        self._refresh_notice()
        self._on_search_text_changed(self._search.text())

    def _refresh_notice(self) -> None:
        """Show the cause-and-exit row only when nothing at all can be ticked.

        The trigger is a list that is entirely partial-availability rows under
        a policy that forbids them — the case where a file split into several
        logical sources (HDF groups by sample rate) and the selected channels
        exist in only some of them.
        """

        blocked = bool(self._partial) and not (
            self._partial_selectable or self._available
        )
        if blocked:
            self._notice_label.setText(
                f"{len(self._partial)} 个通道只存在于部分来源，"
                "「所有来源共有」策略下不可选"
            )
        self._notice.setVisible(blocked)

    def is_relax_notice_visible(self) -> bool:
        """True when the partial-availability explanation row is showing.

        Measured against the surface, not the screen: the popup spends most of
        its life hidden, and ``isVisible()`` would report False for a row that
        is correctly armed for the next opening.
        """

        return self._notice.isVisibleTo(self._surface)

    def _apply_selection(self, new: tuple[str, ...]) -> None:
        self._selected = new
        self._suppress_signal = True
        try:
            for index in range(self._list.count()):
                item = self._list.item(index)
                checkbox = self._list.itemWidget(item)
                if isinstance(checkbox, QCheckBox):
                    want = item.data(Qt.UserRole) in self._selected
                    if checkbox.isChecked() != want:
                        checkbox.setChecked(want)
        finally:
            self._suppress_signal = False
        self._refresh_display()
        self._refresh_foot()
        self.selectionChanged.emit(self._selected)

    def _on_checkbox_toggled(self, signal: str, checked: bool) -> None:
        if self._suppress_signal:
            return
        if self._single_select:
            if checked:
                self._suppress_signal = True
                try:
                    for index in range(self._list.count()):
                        item = self._list.item(index)
                        checkbox = self._list.itemWidget(item)
                        if (
                            isinstance(checkbox, QCheckBox)
                            and item.data(Qt.UserRole) != signal
                            and checkbox.isChecked()
                        ):
                            checkbox.setChecked(False)
                finally:
                    self._suppress_signal = False
                self._selected = (signal,)
            else:
                self._selected = ()
        else:
            selected = list(self._selected)
            if checked and signal not in selected:
                selected.append(signal)
            elif not checked and signal in selected:
                selected.remove(signal)
            self._selected = tuple(selected)
        self._refresh_display()
        self._refresh_foot()
        if self._popup.isVisible():
            # Ticking a box must not cost the caret: the popup stays open and
            # the query keeps its focus so several signals can be picked in a
            # row (spec 3.1).
            self._search.setFocus()
        self.selectionChanged.emit(self._selected)

    def _on_select_all(self) -> None:
        if self._single_select:
            return
        additions: list[str] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.isHidden() or not bool(item.flags() & Qt.ItemIsEnabled):
                continue
            name = item.data(Qt.UserRole)
            if name not in self._selected and name not in additions:
                additions.append(name)
        if additions:
            self._apply_selection(self._selected + tuple(additions))
        self._search.setFocus()

    def _on_clear(self) -> None:
        if self._selected:
            self._apply_selection(())
        self._search.setFocus()

    def _on_search_text_changed(self, text: str) -> None:
        """Filter the popup list only — the trigger must not move."""

        needle = text.strip().lower()
        matches = 0
        for index in range(self._list.count()):
            item = self._list.item(index)
            name = str(item.data(Qt.UserRole) or "").lower()
            hidden = bool(needle) and needle not in name
            item.setHidden(hidden)
            matches += int(not hidden)
        self._match_count = matches
        self._list.setVisible(matches > 0)
        self._empty_label.setVisible(matches == 0)
        self._refresh_foot()
        if self._popup.isVisible():
            self._sync_popup_geometry()

    def _refresh_foot(self) -> None:
        matches = self._match_count
        chosen = len(self._selected)
        self._foot_stats.setText(f"已选 {chosen} · 匹配 {matches}")
        self._select_all_button.setText(f"全选 {matches} 条")
        self._select_all_button.setEnabled(matches > 0)
        self._clear_button.setEnabled(chosen > 0)

    # ------------------------------------------------------------------
    # Internal — collapsed summary
    # ------------------------------------------------------------------
    def _set_summary_placeholder(self, placeholder: bool) -> None:
        """Swap the summary skin, but only when the state really changed.

        ``setStyleSheet`` repolishes the widget, which momentarily resets its
        font — measuring the elision budget against that transient font is how
        summaries end up cut in the wrong place.
        """
        if placeholder == self._summary_is_placeholder:
            return
        self._summary_is_placeholder = placeholder
        self._summary_label.setStyleSheet(
            self._SUMMARY_PLACEHOLDER_QSS if placeholder else self._SUMMARY_QSS
        )

    def _summary_budget(self, overflow_width: int) -> int:
        margins = self._trigger_layout.contentsMargins()
        spacing = self._trigger_layout.spacing()
        width = self._trigger.width()
        if width <= 0:
            width = max(self.width(), self.sizeHint().width())
        budget = (
            width
            - margins.left()
            - margins.right()
            - self._arrow_button.width()
            - spacing
        )
        if overflow_width:
            budget -= overflow_width + spacing
        return max(self._SUMMARY_MIN_BUDGET, budget)

    def _refresh_display(self) -> None:
        """Re-render the collapsed summary.  Never called from search."""

        count = len(self._selected)
        if not count:
            self._overflow_label.hide()
            self._overflow_label.clear()
            self._overflow_label.setToolTip("")
            self._trigger.setToolTip("")
            self._set_summary_placeholder(True)
            self._summary_label.setText("选择信号…")
            self.updateGeometry()
            return

        overflow_width = 0
        if count >= 2:
            self._overflow_label.setText(f"+{count - 1}")
            self._overflow_label.setToolTip("\n".join(self._selected[1:]))
            overflow_width = max(30, self._overflow_label.sizeHint().width())
            self._overflow_label.setFixedWidth(overflow_width)
            self._overflow_label.show()
        else:
            self._overflow_label.hide()
            self._overflow_label.clear()
            self._overflow_label.setToolTip("")

        self._trigger.setToolTip("\n".join(self._selected))
        self._set_summary_placeholder(False)
        name = self._selected[0]
        metrics = QFontMetrics(self._summary_label.font())
        self._summary_label.setText(
            metrics.elidedText(
                name, Qt.ElideMiddle, self._summary_budget(overflow_width),
            )
        )
        self.updateGeometry()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if hasattr(self, "_summary_label"):
            self._refresh_display()

    def _hide_if_focus_left_popup(self) -> None:
        if not self._popup.isVisible():
            return
        new_focus = QApplication.focusWidget()
        if new_focus is not None and (
            new_focus is self._popup or self._popup.isAncestorOf(new_focus)
        ):
            return
        self.hide_popup()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        event_type = event.type()
        if obj is self._search:
            if event_type == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hide_popup()
                self._trigger.setFocus(Qt.PopupFocusReason)
                return True
            if event_type == QEvent.FocusOut:
                self._hide_if_focus_left_popup()
        elif obj is self._popup:
            if event_type == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hide_popup()
                self._trigger.setFocus(Qt.PopupFocusReason)
                return True
            if event_type == QEvent.FocusOut:
                self._hide_if_focus_left_popup()
            elif event_type == QEvent.Hide:
                # Covers Qt.Popup's own click-away close as well as hide_popup.
                self._set_expanded(False)
                self._reset_search()
        elif obj is self._trigger:
            if event_type in (QEvent.FocusIn, QEvent.FocusOut):
                self._apply_trigger_style()
        return super().eventFilter(obj, event)

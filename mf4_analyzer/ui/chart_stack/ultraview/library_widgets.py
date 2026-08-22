"""UltraView view-library overlay and unplaced-tray widgets.

Rows, section headers, the library panel, and the unplaced tray. They emit
typed intents and do not import the page host, FreeGridBoard, or MainWindow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PyQt5.QtCore import QPoint, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QMouseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    SECTION_LABELS_ZH,
    SOURCE_SECTIONS,
    STATUS_ORPHANED,
    UltraViewRef,
    parse_ref_payload,
    section_search_haystack,
)
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.widgets import SearchField

from .chrome import ULTRAVIEW_MUTED
from .widgets_common import (
    STATUS_LABELS_ZH,
    _ColorDot,
    _ElideLabel,
    _accept_ultraview_drag,
    _full_tooltip,
    _repolish,
    _run_ultraview_drag,
    _set_flag,
    extract_ref_strings,
    make_ref_mime,
)

# The library stays a narrow on-canvas overlay.  ``UltraViewPage`` imports the
# default instead of carrying a second geometry literal, so this is the one
# source of truth for the rail overlay's normal width.
LIBRARY_DEFAULT_WIDTH = 360
LIBRARY_MAX_WIDTH = 400
LIBRARY_MODE_GROUPS = "groups"
_LIBRARY_PIN_REST = QColor("#6B7D8E")
_LIBRARY_PIN_ACTIVE = QColor("#3E709C")

# View-library geometry. Every value below is an **outer-frame** height, QSS
# stroke included. Qt's `min-height` is content-box, so the matching rule in
# `style.qss` writes `value - border - padding`: 44 for the 46px row (1px
# stroke each side), but 32 for the 32px section head, whose rule turns every
# border off. Mixing the two conventions is what let the hand-written height
# formula drift 51px away from the layout and clip the "time" group.
LIBRARY_OVERLAY_HEIGHT = 560
LIBRARY_OVERLAY_MIN_HEIGHT = 360
LIBRARY_HEAD_HEIGHT = 52
LIBRARY_SEARCH_HEIGHT = 34
LIBRARY_SECTION_GAP = 8
LIBRARY_SECTION_HEAD_HEIGHT = 32
# Two lines (name + checked-channel summary). A deliberate departure from the
# HTML prototype's single 38px row: the second line is the only thing that
# tells default "View 1..N" names apart, so evenness comes from pinning the
# height, not from dropping the information.
LIBRARY_ROW_HEIGHT = 46
# A selected row owns a small shadow.  Rows therefore need an actual air gap
# instead of a sibling border that can show through the selected card's lower
# corner (the recurrent View 1/View 2 line regression).
LIBRARY_SELECTED_ROW_GUTTER = 8
LIBRARY_SECTION_ROW_GAP = LIBRARY_SELECTED_ROW_GUTTER
LIBRARY_ROW_ACTION_SIZE = 23
LIBRARY_ROW_DOT_INSET = 14
TRAY_BODY_MAX_HEIGHT = 220
TRAY_ITEM_MIN_HEIGHT = 40
UNPLACED_OVERLAY_VISIBLE_ROWS = 3
UNPLACED_OVERLAY_WIDTH = 400
UNPLACED_OVERLAY_MIN_HEIGHT = 160

def _hairline(parent: QWidget, object_name: str) -> QFrame:
    """1px separator whose color comes from QSS, not from the native frame.

    ``QFrame.HLine`` alone paints a two-tone sunken groove that reads as a
    bevel next to this panel's flat material, so the shape only carries the
    semantics and the styled background carries the ink.
    """
    rule = QFrame(parent)
    rule.setObjectName(object_name)
    rule.setFrameShape(QFrame.HLine)
    rule.setFrameShadow(QFrame.Plain)
    rule.setAttribute(Qt.WA_StyledBackground, True)
    rule.setFixedHeight(1)
    rule.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return rule


@dataclass(frozen=True)
class LibraryRow:
    section: str
    view_id: str
    name: str = ""
    tab_color: str = ""
    status: str = ""
    on_board: bool = False
    source_summary: str = ""

def coerce_library_row(row: LibraryRow | Mapping[str, Any]) -> LibraryRow:
    if isinstance(row, LibraryRow):
        return row
    return LibraryRow(
        section=str(row.get("section", "")),
        view_id=str(row.get("view_id", "")),
        name=str(row.get("name", "")),
        tab_color=str(row.get("tab_color", "")),
        status=str(row.get("status", "")),
        on_board=bool(row.get("on_board", False)),
        source_summary=str(row.get("source_summary", "")),
    )

class LibraryRowWidget(QFrame):
    add_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, row: LibraryRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibraryRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(LIBRARY_ROW_HEIGHT)
        self._row = row
        self._press_pos: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(LIBRARY_ROW_DOT_INSET, 5, 8, 5)
        layout.setSpacing(8)
        self._dot = _ColorDot(self)
        self._dot.set_color(row.tab_color)
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(0)
        self._name = _ElideLabel(row.name, self)
        self._name.set_full_text(row.name)
        self._meta = _ElideLabel(row.source_summary, self)
        self._meta.set_full_text(row.source_summary)
        self._meta.setObjectName("ultraViewLibraryMeta")
        # Channel names read as a list, not as prose: fixed pitch keeps the
        # second line from wobbling row to row. Same recipe as the navigation
        # island's zoom readout, which already ships on Windows.
        meta_font = QFont(self._meta.font())
        meta_font.setStyleHint(QFont.Monospace)
        meta_font.setFixedPitch(True)
        self._meta.setFont(meta_font)
        copy.addWidget(self._name)
        copy.addWidget(self._meta)
        layout.addLayout(copy, 1)
        self._add = QToolButton(self)
        self._add.setObjectName("ultraViewLibraryAdd")
        self._add.setAutoRaise(False)
        self._add.setFixedSize(LIBRARY_ROW_ACTION_SIZE, LIBRARY_ROW_ACTION_SIZE)
        self._add.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._add.clicked.connect(self._on_add)
        layout.addWidget(self._add, 0, Qt.AlignVCenter)
        self.set_row(row)

    def row(self) -> LibraryRow:
        return self._row

    def set_row(self, row: LibraryRow) -> None:
        self._row = row
        self._dot.set_color(row.tab_color)
        self._name.set_full_text(row.name or row.view_id)
        self._meta.set_full_text(row.source_summary)
        self._add.setText("−" if row.on_board else "+")
        self._add.setToolTip("从 Board 移除" if row.on_board else "添加到 Board")
        self._add.setProperty("action", "remove" if row.on_board else "add")
        _repolish(self._add)
        _set_flag(self, "onBoard", row.on_board)
        self.setToolTip(
            _full_tooltip(row.name or row.view_id, row.section, row.source_summary, row.status)
        )
        self.setAccessibleName(
            f"{SECTION_LABELS_ZH.get(row.section, row.section)} {row.name or row.view_id}"
        )

    def set_selected(self, on: bool) -> None:
        selected = bool(on)
        if (self.property("selected") == "true") != selected:
            _set_flag(self, "selected", selected)
        effect = self.graphicsEffect()
        if selected:
            if effect is None:
                shadow = QGraphicsDropShadowEffect(self)
                shadow.setBlurRadius(10)
                shadow.setOffset(0, 2)
                shadow.setColor(QColor(62, 112, 145, 52))
                self.setGraphicsEffect(shadow)
            return
        if effect is not None:
            # QWidget owns its graphics effect.  Clearing it before a rebuild
            # keeps the outgoing row from retaining a shadow wrapper while its
            # section host is queued for deletion.
            self.setGraphicsEffect(None)

    def _on_add(self) -> None:
        row = self._row
        if row.on_board:
            self.remove_requested.emit(row.section, row.view_id)
            return
        self.add_requested.emit(row.section, row.view_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = QPoint(event.pos())
            self.selected.emit(self._row.section, self._row.view_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._row.section, self._row.view_id)
        self.drag_started.emit("library")
        _run_ultraview_drag(
            self, mime, Qt.CopyAction, self.drag_finished.emit
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)


class _LibrarySectionHeader(QFrame):
    """Paper-card header for one SOURCE_SECTIONS group; no domain color bar."""

    toggled_section = pyqtSignal(str, bool)

    def __init__(
        self,
        section: str,
        count: int,
        expanded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibrarySectionHead")
        self.setProperty("section", section)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(LIBRARY_SECTION_HEAD_HEIGHT)
        self._section = section
        self._count_value = max(0, int(count))
        self._expanded = bool(expanded)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(4)
        self._title = QLabel(SECTION_LABELS_ZH.get(section, section), self)
        self._title.setObjectName("ultraViewLibrarySectionTitle")
        layout.addWidget(self._title, 1)
        self.setToolTip(f"{self._count_value} 个 View")
        self._toggle = QToolButton(self)
        self._toggle.setObjectName("ultraViewLibrarySectionToggle")
        self._toggle.setCheckable(True)
        self._toggle.setAutoRaise(True)
        self._toggle.setFocusPolicy(Qt.TabFocus)
        self._toggle.setFixedSize(22, 22)
        self._toggle.setIconSize(QSize(14, 14))
        # The native triangle is heavier than everything else on this panel;
        # the chevron pair matches the BoardIsland glyph. NoArrow keeps Qt from
        # painting its triangle underneath the icon.
        self._toggle.setArrowType(Qt.NoArrow)
        blocked = self._toggle.blockSignals(True)
        self._toggle.setChecked(expanded)
        self._toggle.blockSignals(blocked)
        self._sync_arrow(expanded)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle, 0, Qt.AlignVCenter)

    def section(self) -> str:
        return self._section

    def click(self) -> None:
        self._toggle.click()

    def text(self) -> str:
        return f"{SECTION_LABELS_ZH.get(self._section, self._section)}  {self._count_value}"

    def arrowType(self):  # noqa: N802
        """Collapse direction, still projected as a ``Qt.ArrowType``.

        The visual is a chevron icon now, so ``QToolButton.arrowType()`` is
        pinned to ``NoArrow``. This header keeps owning the direction and
        answers with the same vocabulary callers (and the header contract in
        ``tests/ui/test_ultraview_page.py``) already read.
        """
        return Qt.DownArrow if self._expanded else Qt.RightArrow

    def _on_toggled(self, checked: bool) -> None:
        self._sync_arrow(checked)
        self.toggled_section.emit(self._section, checked)

    def _sync_arrow(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._toggle.setIcon(
            Icons.chevron_down(ULTRAVIEW_MUTED)
            if self._expanded
            else Icons.chevron_right(ULTRAVIEW_MUTED)
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.childAt(event.pos()) is not self._toggle:
            self._toggle.click()
        super().mouseReleaseEvent(event)


class ViewLibraryPanel(QFrame):
    add_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()
    pin_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibrary")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self.setMaximumWidth(LIBRARY_MAX_WIDTH)
        self._rows: list[LibraryRow] = []
        self._selected: tuple[str, str] | None = None
        self._row_widgets: list[LibraryRowWidget] = []
        self._section_frames: dict[str, QFrame] = {}
        self._section_headers: dict[str, _LibrarySectionHeader] = {}
        self._section_rules: dict[str, QFrame] = {}
        self._expanded: dict[str, bool] = {section: True for section in SOURCE_SECTIONS}

        root = QVBoxLayout(self)
        # Root carries no inset: the head band needs to run edge to edge so its
        # rule reads as a real separator. Qt does not clip children to
        # `border-radius`, so each band owns its own padding instead — and the
        # only child that reaches the corner arcs is the head band, which paints
        # nothing.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head_host = QWidget(self)
        head_host.setObjectName("ultraViewLibraryHead")
        head_host.setFixedHeight(LIBRARY_HEAD_HEIGHT)
        head = QHBoxLayout(head_host)
        head.setContentsMargins(14, 12, 10, 10)
        head.setSpacing(6)
        title = QLabel("View 库", self)
        title.setObjectName("ultraViewLibraryTitle")
        self._count = QLabel("0 个", self)
        self._count.setObjectName("ultraViewLibraryCount")
        # Naming note: this `_pin` is the library overlay's own "keep open"
        # toggle (pinned = don't auto-close on canvas click), unrelated to
        # `PreviewStore.set_pinned_refs` (the residency API for the set of
        # UltraViewRef a Board keeps resident). Same word, different
        # domain — no functional overlap.
        self._pin = QToolButton(self)
        self._pin.setObjectName("ultraViewLibraryPin")
        self._pin.setCheckable(True)
        self._pin.setAutoRaise(True)
        self._pin.setFixedSize(24, 24)
        self._pin.setIconSize(QSize(14, 14))
        self._pin.setFocusPolicy(Qt.TabFocus)
        self._pin.setProperty("role", "icon")
        self._pin.setProperty("chrome", "ultraview")
        self._pin.setProperty("active", "false")
        self._pin.toggled.connect(self._on_pin_toggled)
        head.addWidget(title, 1)
        head.addWidget(self._count, 0, Qt.AlignVCenter)
        head.addWidget(self._pin, 0, Qt.AlignVCenter)
        self._sync_pin(False)
        root.addWidget(head_host)

        # Full width, and that is already 1px short of each edge: Qt's
        # stylesheet insets a styled widget's contents past its own border, so
        # the panel's stroke stays uncovered without an extra margin (measured:
        # contentsRect() is inset by the panel's 1px border on every edge).
        self._head_rule = _hairline(self, "ultraViewLibraryHeadRule")
        root.addWidget(self._head_rule)

        controls = QVBoxLayout()
        controls.setContentsMargins(12, 10, 12, 10)
        controls.setSpacing(8)
        self._search = SearchField("搜索 View、信号或分析类型…", self)
        self._search.setObjectName("ultraViewLibrarySearch")
        self._search.setFixedHeight(LIBRARY_SEARCH_HEIGHT)
        self._search.textChanged.connect(self._rebuild)
        search_wrap = QHBoxLayout()
        search_wrap.setContentsMargins(0, 0, 0, 0)
        search_wrap.addWidget(self._search)
        controls.addLayout(search_wrap)

        root.addLayout(controls)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("ultraViewLibraryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body = QWidget(self._scroll)
        self._body.setObjectName("ultraViewLibraryBody")
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._body_layout = QVBoxLayout(self._body)
        # The scroll area itself runs full width; the body carries the padding,
        # which puts the vertical scrollbar inside the 12px gutter instead of
        # on top of the group cards' right border.
        self._body_layout.setContentsMargins(12, 10, 12, 12)
        self._body_layout.setSpacing(LIBRARY_SECTION_GAP)
        self._scroll.setWidget(self._body)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(self._scroll, 1)
        # A rebuild creates fresh section frames.  Before Qt's next layout turn
        # their aggregate minimum can momentarily read as the outer margins
        # (22px), which would make QScrollArea squeeze every section instead of
        # turning its scrollbar on.  One owned, coalesced timer measures after
        # that layout turn; reopening the panel must not be the repair path.
        self._body_min_height_timer = QTimer(self)
        self._body_min_height_timer.setSingleShot(True)
        self._body_min_height_timer.timeout.connect(self._sync_body_min_height)
        self._rebuild()

    def search_field(self) -> QLineEdit:
        return self._search

    def selected_ref(self) -> tuple[str, str] | None:
        return self._selected

    def visible_rows(self) -> list[LibraryRow]:
        query = self._search.text().strip().lower()
        rows = []
        for row in self._rows:
            haystack = section_search_haystack(row.section, row.name, row.source_summary)
            if query and query not in haystack:
                continue
            rows.append(row)
        return rows

    def section_widgets(self) -> dict[str, QFrame]:
        return dict(self._section_frames)

    def section_headers(self) -> dict[str, QWidget]:
        return dict(self._section_headers)

    def browse_mode(self) -> str:
        """Return the only remaining browse path for legacy read-only callers."""
        return LIBRARY_MODE_GROUPS

    def is_section_expanded(self, section: str) -> bool:
        return bool(self._expanded.get(section, True))

    def row_widgets(self) -> list[LibraryRowWidget]:
        return list(self._row_widgets)

    def set_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        self._rows = [coerce_library_row(row) for row in rows]
        self._count.setText(f"{len(self._rows)} 个")
        self._rebuild()

    def set_on_board(self, membership: set[UltraViewRef]) -> None:
        updated: list[LibraryRow] = []
        for row in self._rows:
            parsed = parse_ref_payload({"section": row.section, "view_id": row.view_id})
            on_board = parsed in membership if parsed is not None else row.on_board
            if on_board != row.on_board:
                row = LibraryRow(
                    section=row.section,
                    view_id=row.view_id,
                    name=row.name,
                    tab_color=row.tab_color,
                    status=row.status,
                    on_board=on_board,
                    source_summary=row.source_summary,
                )
            updated.append(row)
        self._rows = updated
        self._rebuild()

    def set_selected(self, section: str, view_id: str) -> None:
        self._selected = (section, view_id)
        for widget in self._row_widgets:
            row = widget.row()
            widget.set_selected(row.section == section and row.view_id == view_id)

    def focus_search(self) -> None:
        self._search.setFocus(Qt.OtherFocusReason)

    def pin_button(self) -> QToolButton:
        return self._pin

    def is_pinned(self) -> bool:
        return bool(self._pin.isChecked())

    def set_pinned(self, pinned: bool) -> None:
        wanted = bool(pinned)
        if self.is_pinned() == wanted and self._pin.property("active") == (
            "true" if wanted else "false"
        ):
            return
        blocked = self._pin.blockSignals(True)
        self._pin.setChecked(wanted)
        self._pin.blockSignals(blocked)
        self._sync_pin(wanted)
        self.pin_toggled.emit(wanted)

    def _on_pin_toggled(self, checked: bool) -> None:
        self._sync_pin(bool(checked))
        self.pin_toggled.emit(bool(checked))

    def _sync_pin(self, pinned: bool) -> None:
        self._pin.setIcon(Icons.ultraview_pin(_LIBRARY_PIN_ACTIVE if pinned else _LIBRARY_PIN_REST))
        value = "true" if pinned else "false"
        if self._pin.property("active") != value:
            self._pin.setProperty("active", value)
            style = self._pin.style()
            if style is not None:
                style.unpolish(self._pin)
                style.polish(self._pin)
            self._pin.update()
        label = "取消钉住 View 库" if pinned else "钉住 View 库，点击画布不关闭"
        self._pin.setToolTip(label)
        self._pin.setAccessibleName(label)

    def _rebuild(self) -> None:
        # Effects are owned by their row widgets.  Clear them before detaching
        # a group host so selection remains an _selected projection, never a
        # lingering QObject/effect owned by a soon-to-die row.
        for row_widget in self._row_widgets:
            row_widget.set_selected(False)
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._row_widgets = []
        self._section_frames = {}
        self._section_headers = {}
        self._section_rules = {}
        visible = self.visible_rows()
        by_section: dict[str, list[LibraryRow]] = {section: [] for section in SOURCE_SECTIONS}
        for row in visible:
            if row.section in by_section:
                by_section[row.section].append(row)
        query = self._search.text().strip()
        if query:
            for section, rows in by_section.items():
                if rows:
                    self._expanded[section] = True
        self._groups_host = QWidget(self._body)
        self._groups_host.setObjectName("ultraViewLibraryGroupsHost")
        groups_layout = QVBoxLayout(self._groups_host)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(LIBRARY_SECTION_GAP)
        for section in SOURCE_SECTIONS:
            frame = QFrame(self._groups_host)
            frame.setObjectName("ultraViewLibrarySection")
            frame.setProperty("section", section)
            frame.setAttribute(Qt.WA_StyledBackground, True)
            section_layout = QVBoxLayout(frame)
            section_layout.setContentsMargins(1, 1, 1, 4)
            section_layout.setSpacing(LIBRARY_SECTION_ROW_GAP)
            expanded = self._expanded.get(section, True)
            header = _LibrarySectionHeader(section, len(by_section[section]), expanded, frame)
            header.toggled_section.connect(self._on_section_toggled)
            section_layout.addWidget(header)
            self._section_headers[section] = header
            rule = _hairline(frame, "ultraViewLibrarySectionRule")
            rule.setVisible(expanded and bool(by_section[section]))
            section_layout.addWidget(rule)
            self._section_rules[section] = rule
            for row in by_section[section]:
                row_widget = LibraryRowWidget(row, frame)
                row_widget.add_requested.connect(self.add_requested)
                row_widget.remove_requested.connect(self.remove_requested)
                row_widget.locate_requested.connect(self.locate_requested)
                row_widget.selected.connect(self._on_row_selected)
                row_widget.drag_started.connect(self.drag_started)
                row_widget.drag_finished.connect(self.drag_finished)
                if self._selected == (row.section, row.view_id):
                    row_widget.set_selected(True)
                row_widget.setVisible(expanded)
                section_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)
            self._section_frames[section] = frame
            groups_layout.addWidget(frame)
        self._body_layout.addWidget(self._groups_host)
        # The scroll body may be taller than its groups.  Keep spare height in
        # an explicit tail stretch rather than letting Qt distribute it into
        # section cards or rows after a rebuild.
        self._body_layout.addStretch(1)
        self._queue_body_min_height_sync()

    def sizeHint(self) -> QSize:  # noqa: N802
        """Fixed size, independent of the list inside.

        Deriving the hint from content made every in-panel action (collapse a
        group or type a character) resize the overlay, and
        ``floating_layout`` centers the panel on its trigger, so the height
        swing became a top-edge jump too. Content scrolls; the frame does not
        move. Capping a content-driven hint would only narrow the jump range.
        """
        return QSize(LIBRARY_DEFAULT_WIDTH, LIBRARY_OVERLAY_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, LIBRARY_OVERLAY_MIN_HEIGHT)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_body_min_height()
        self._queue_body_min_height_sync()

    def _measured_body_height(self) -> int:
        """Ask the layout instead of re-deriving what it already knows.

        The hand-written formula this replaces counted content-box constants
        against border-box widgets and forgot the group cards' own margins; it
        answered 528 where the layout needed 579, and QVBoxLayout paid the
        51px difference by squeezing the tallest group until its bottom border
        cut through the last row.
        """
        return self._body_layout.totalMinimumSize().height()

    def _sync_body_min_height(self) -> None:
        self._body.setMinimumHeight(self._measured_body_height())

    def _queue_body_min_height_sync(self) -> None:
        """Measure rebuilt section geometry after Qt has laid out their children."""
        self._body_min_height_timer.start(0)

    def _on_section_toggled(self, section: str, expanded: bool) -> None:
        self._expanded[section] = bool(expanded)
        rows = 0
        for widget in self._row_widgets:
            if widget.row().section == section:
                widget.setVisible(bool(expanded))
                rows += 1
        rule = self._section_rules.get(section)
        if rule is not None:
            rule.setVisible(bool(expanded) and rows > 0)
        self._queue_body_min_height_sync()

    def _on_row_selected(self, section: str, view_id: str) -> None:
        self.set_selected(section, view_id)

class TrayItem(QFrame):
    place_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(
        self,
        section: str,
        view_id: str,
        title: str,
        tab_color: str,
        status: str,
        parent: QWidget | None = None,
        *,
        replacement_armed: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewTrayItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(TRAY_ITEM_MIN_HEIGHT)
        self._section = section
        self._view_id = view_id
        self._press_pos: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(6)
        self._dot = _ColorDot(self)
        self._dot.set_color(tab_color)
        layout.addWidget(self._dot, 0)
        self._title = _ElideLabel(title, self)
        self._title.set_full_text(title)
        layout.addWidget(self._title, 1)
        self._status = QLabel(STATUS_LABELS_ZH.get(status, status), self)
        layout.addWidget(self._status, 0)
        place = QToolButton(self)
        place.setObjectName("ultraViewTrayPlace")
        place.setText("放置")
        place.clicked.connect(self._emit_place)
        self._rebind = QToolButton(self)
        self._rebind.setObjectName("ultraViewTrayRebind")
        self._rebind.setText("重新绑定")
        self._rebind.clicked.connect(self._emit_rebind)
        self._rebind.setVisible(status == STATUS_ORPHANED)
        remove = QToolButton(self)
        remove.setObjectName("ultraViewTrayRemove")
        remove.setText("移除")
        remove.clicked.connect(self._emit_remove)
        for button in (place, self._rebind, remove):
            button.setAutoRaise(False)
            button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(place, 0)
        layout.addWidget(self._rebind, 0)
        layout.addWidget(remove, 0)
        self.setAccessibleName(f"未放置 {title}")
        self.setProperty("status", status)
        _set_flag(self, "orphaned", status == STATUS_ORPHANED)
        _set_flag(self, "replacementArmed", replacement_armed)

    def ref(self) -> tuple[str, str]:
        return self._section, self._view_id

    def _emit_place(self) -> None:
        self.place_requested.emit(self._section, self._view_id)

    def _emit_rebind(self) -> None:
        self.rebind_arm_requested.emit(self._section, self._view_id)

    def _emit_remove(self) -> None:
        self.remove_requested.emit(self._section, self._view_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = QPoint(event.pos())
            self.locate_requested.emit(self._section, self._view_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._section, self._view_id)
        self.drag_started.emit("tray")
        _run_ultraview_drag(
            self, mime, Qt.MoveAction, self.drag_finished.emit
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)


class UnplacedTray(QFrame):
    place_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_dropped = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewUnplacedTray")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self._expanded = False
        self._overlay_mode = False
        self._items: list[TrayItem] = []
        self._content_signature: tuple | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._title = QPushButton("未放置", self)
        self._title.setObjectName("ultraViewTrayTitle")
        self._title.setCheckable(True)
        self._title.setChecked(False)
        self._title.clicked.connect(self._on_title)
        root.addWidget(self._title, 0)
        self._body = QScrollArea(self)
        self._body.setObjectName("ultraViewTrayBody")
        self._body.setWidgetResizable(True)
        self._body.setFrameShape(QFrame.NoFrame)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body.setMaximumHeight(TRAY_BODY_MAX_HEIGHT)
        self._inner = QWidget(self._body)
        self._inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(10, 8, 10, 10)
        self._inner_layout.setSpacing(6)
        self._body.setWidget(self._inner)
        self._empty = QLabel("缩小布局或移入的卡片会出现在这里", self._inner)
        self._empty.setObjectName("ultraViewTrayEmptyHint")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._inner_layout.addWidget(self._empty)
        self._empty.hide()
        self._body.setVisible(False)
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(self._body, 1)

    def title_bar(self) -> QPushButton:
        return self._title

    def body(self) -> QScrollArea:
        return self._body

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        blocked = self._title.blockSignals(True)
        self._title.setChecked(self._expanded)
        self._title.blockSignals(blocked)
        self._body.setVisible(self._expanded)

    def item_widgets(self) -> list[TrayItem]:
        return list(self._items)

    def set_refs(
        self,
        refs: Sequence[UltraViewRef],
        *,
        titles: Mapping[tuple[str, str], str] | None = None,
        colors: Mapping[tuple[str, str], str] | None = None,
        statuses: Mapping[tuple[str, str], str] | None = None,
        armed: UltraViewRef | None = None,
    ) -> None:
        titles = titles or {}
        colors = colors or {}
        statuses = statuses or {}
        signature = tuple(
            (
                (ref.section, ref.view_id),
                str(titles.get((ref.section, ref.view_id), ref.view_id)),
                str(colors.get((ref.section, ref.view_id), "")),
                str(statuses.get((ref.section, ref.view_id), "")),
                armed == ref,
            )
            for ref in refs
        )
        if signature == self._content_signature:
            return
        self._content_signature = signature
        empty = self._empty
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            widget = item.widget()
            if widget is None or widget is empty:
                continue
            widget.setParent(None)
            widget.deleteLater()
        self._items = []
        if self._inner_layout.indexOf(empty) < 0:
            self._inner_layout.addWidget(empty, 0)
        for ref in refs:
            key = (ref.section, ref.view_id)
            widget = TrayItem(
                ref.section,
                ref.view_id,
                titles.get(key, ref.view_id),
                colors.get(key, ""),
                statuses.get(key, ""),
                self._inner,
                replacement_armed=armed == ref,
            )
            widget.setFocusPolicy(Qt.TabFocus)
            widget.place_requested.connect(self.place_requested)
            widget.remove_requested.connect(self.remove_requested)
            widget.locate_requested.connect(self.locate_requested)
            widget.rebind_arm_requested.connect(self.rebind_arm_requested)
            widget.drag_started.connect(self.drag_started)
            widget.drag_finished.connect(self.drag_finished)
            self._inner_layout.addWidget(widget, 0)
            self._items.append(widget)
        count = len(refs)
        self._title.setText("未放置" if count == 0 else f"未放置 · {count}")
        empty.setVisible(count == 0)
        self._sync_inner_min_height()

    def sizeHint(self) -> QSize:  # noqa: N802
        title_h = max(28, self._title.sizeHint().height()) if self._title.isVisible() else 0
        rows = len(self._items) if self._items else 1
        visible = min(UNPLACED_OVERLAY_VISIBLE_ROWS, max(1, rows))
        margins = self._inner_layout.contentsMargins()
        body_h = (
            margins.top()
            + margins.bottom()
            + visible * TRAY_ITEM_MIN_HEIGHT
            + max(0, visible - 1) * self._inner_layout.spacing()
        )
        return QSize(UNPLACED_OVERLAY_WIDTH, max(UNPLACED_OVERLAY_MIN_HEIGHT, title_h + body_h))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, UNPLACED_OVERLAY_MIN_HEIGHT)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_inner_min_height()

    def _measured_inner_height(self) -> int:
        margins = self._inner_layout.contentsMargins()
        count = len(self._items)
        if count == 0:
            return margins.top() + margins.bottom() + 36
        return (
            margins.top()
            + margins.bottom()
            + count * TRAY_ITEM_MIN_HEIGHT
            + max(0, count - 1) * self._inner_layout.spacing()
        )

    def _sync_inner_min_height(self) -> None:
        self._inner.setMinimumHeight(self._measured_inner_height())

    def set_overlay_mode(self, overlay: bool) -> None:
        """Overlay host always shows the body; the old collapsible title is chrome."""
        self._overlay_mode = bool(overlay)
        self._title.setCheckable(not self._overlay_mode)
        self._title.setVisible(True)
        if self._overlay_mode:
            blocked = self._title.blockSignals(True)
            self._title.setChecked(True)
            self._title.blockSignals(blocked)
            self.set_expanded(True)
            self._body.setMaximumHeight(16777215)
        else:
            self._body.setMaximumHeight(TRAY_BODY_MAX_HEIGHT)

    def focus_first_item(self) -> bool:
        if not self._items:
            if self._empty.isVisible():
                self._empty.setFocus(Qt.OtherFocusReason)
                return True
            return False
        self._items[0].setFocus(Qt.OtherFocusReason)
        return True

    def _on_title(self, checked: bool) -> None:
        if self._overlay_mode:
            blocked = self._title.blockSignals(True)
            self._title.setChecked(True)
            self._title.blockSignals(blocked)
            return
        self.set_expanded(checked)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        if extracted is None:
            return
        section, view_id = extracted
        self.move_to_unplaced_dropped.emit(section, view_id)

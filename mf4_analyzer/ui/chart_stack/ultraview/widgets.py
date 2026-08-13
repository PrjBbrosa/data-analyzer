"""UltraView page widgets: library, board grid, cards, tray, focus layer.

Widgets emit typed intents. They do not import MainWindow, mutate BoardState,
or call analysis entry points. Preview records are duck-typed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from PyQt5.QtCore import QByteArray, QMimeData, QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QDrag,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    COMPARE_FILTERS,
    LAYOUT_SLOTS,
    SECTION_LABELS_ZH,
    SOURCE_SECTIONS,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_REF_MIME,
    UltraViewRef,
    parse_ref_payload,
    section_search_haystack,
)
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome

from .layouts import (
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    slot_rects,
)

LAYOUT_LABELS_ZH = {
    "split_horizontal": "左右双图",
    "split_vertical": "上下双图",
    "grid_2x2": "2 × 2",
    "hero_left_4": "左主图 + 3 辅图",
    "hero_top_4": "上主图 + 3 辅图",
    "grid_3x2": "3 × 2",
}

COMPARE_FILTER_LABELS_ZH = {
    COMPARE_FILTER_ALL: "全部",
    "time": "时间轴",
    "frequency": "频率轴",
    "time_freq": "时频轴",
    "order": "阶次轴",
}

STATUS_LABELS_ZH = {
    "fresh": "最新",
    STATUS_STALE: "源已变化",
    STATUS_MISSING: "尚无可用结果",
    STATUS_ORPHANED: "源已删除",
}

MISSING_CARD_COPY = "尚无可用结果，UltraView 不会后台计算"
STALE_CARD_COPY = "源已变化"
ORPHANED_CARD_COPY = "源 View 已删除"
DIMMED_OPACITY = 0.28
LIBRARY_DEFAULT_WIDTH = 224
TRAY_BODY_MAX_HEIGHT = 108


@dataclass(frozen=True)
class LibraryRow:
    section: str
    view_id: str
    name: str = ""
    tab_color: str = ""
    status: str = ""
    on_board: bool = False
    source_summary: str = ""


@dataclass
class CardViewModel:
    slot_id: str
    section: str
    view_id: str
    title: str = ""
    tab_color: str = ""
    status: str = STATUS_MISSING
    source_summary: str = ""
    axis_kind: str | None = None
    x_unit: str = ""
    x_range: tuple[float, float] | None = None
    image: Any = None
    selected: bool = False
    dimmed: bool = False
    replacement_armed: bool = False
    show_title: bool = True
    show_source: bool = True


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


def make_ref_mime(section: str, view_id: str) -> QMimeData:
    mime = QMimeData()
    payload = json.dumps(
        {"section": section, "view_id": view_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    mime.setData(ULTRAVIEW_REF_MIME, QByteArray(payload.encode("utf-8")))
    return mime


def extract_ref_strings(mime: QMimeData | None) -> tuple[str, str] | None:
    """Copy ``section`` / ``view_id`` out of ``QMimeData`` immediately.

    Callers must not keep ``mime`` for a queued callback. Invalid payloads
    return ``None``.
    """
    if mime is None or not mime.hasFormat(ULTRAVIEW_REF_MIME):
        return None
    try:
        raw = bytes(mime.data(ULTRAVIEW_REF_MIME)).decode("utf-8")
        payload = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    section = payload.get("section")
    view_id = payload.get("view_id")
    if not isinstance(section, str) or not isinstance(view_id, str):
        return None
    section_copy = str(section)
    view_id_copy = str(view_id)
    if parse_ref_payload({"section": section_copy, "view_id": view_id_copy}) is None:
        return None
    return section_copy, view_id_copy


def preview_image(record: Any) -> QImage | None:
    image = getattr(record, "image", None)
    if image is None:
        return None
    is_null = getattr(image, "isNull", None)
    if callable(is_null) and is_null():
        return None
    return image


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def _set_flag(widget: QWidget, name: str, on: bool) -> None:
    widget.setProperty(name, "true" if on else "false")
    _repolish(widget)


def _elide(label: QLabel, text: str) -> None:
    metrics = label.fontMetrics()
    label.setText(metrics.elidedText(text, Qt.ElideRight, max(0, label.width())))
    label.setToolTip(text if metrics.horizontalAdvance(text) > label.width() else "")


def _range_text(x_range: tuple[float, float] | None, x_unit: str) -> str:
    if x_range is None or len(x_range) != 2:
        return x_unit
    try:
        lo, hi = float(x_range[0]), float(x_range[1])
    except (TypeError, ValueError):
        return x_unit
    unit = f" {x_unit}" if x_unit else ""
    return f"{lo:g}–{hi:g}{unit}"


def _full_tooltip(name: str, section: str, source_summary: str, status: str) -> str:
    section_label = SECTION_LABELS_ZH.get(section, section)
    status_label = STATUS_LABELS_ZH.get(status, status)
    lines = [name or view_fallback(section, ""), f"{section_label} · {source_summary}".strip(" ·")]
    if status_label:
        lines.append(status_label)
    return "\n".join(line for line in lines if line)


def view_fallback(section: str, view_id: str) -> str:
    return view_id or SECTION_LABELS_ZH.get(section, section)


def _accept_ultraview_drag(event) -> bool:
    mime = event.mimeData()
    if mime is not None and mime.hasFormat(ULTRAVIEW_REF_MIME):
        event.acceptProposedAction()
        return True
    event.ignore()
    return False


class _ColorDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#94a3b8")
        self.setFixedSize(8, 8)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_color(self, color: str) -> None:
        self._color = QColor(color) if color else QColor("#94a3b8")
        if not self._color.isValid():
            self._color = QColor("#94a3b8")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())


class _ElideLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        super().setText(text)

    def set_full_text(self, text: str) -> None:
        self._full = text or ""
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        _elide(self, self._full)


class UltraViewHintBar(QFrame):
    """Status-bar hint host. ChartStack can later take this widget."""

    quickref_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartHintBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(22)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        self._quickref = QToolButton(self)
        self._quickref.setObjectName("chartHintQuickrefButton")
        self._quickref.setText("?")
        self._quickref.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._quickref.setAutoRaise(True)
        self._quickref.setCursor(Qt.PointingHandCursor)
        self._quickref.setToolTip("操作速查")
        self._quickref.clicked.connect(self.quickref_requested.emit)
        self._context = QLabel("拖到空槽添加 · 拖到卡片替换 · 双击临时放大", self)
        self._context.setObjectName("chartHintContext")
        self._context.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._discovery = QLabel("UltraView 不计算", self)
        self._discovery.setObjectName("chartHintDiscovery")
        self._discovery.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._quickref, 0, Qt.AlignVCenter)
        layout.addWidget(self._context, 1)
        layout.addWidget(self._discovery, 0)


class BoardToolbar(QFrame):
    layout_changed = pyqtSignal(str)
    ratio_nudge_requested = pyqtSignal(int)
    add_clicked = pyqtSignal()
    copy_board_requested = pyqtSignal()
    export_png_requested = pyqtSignal(int)
    show_titles_toggled = pyqtSignal(bool)
    show_sources_toggled = pyqtSignal(bool)
    presentation_toggled = pyqtSignal(bool)
    board_name_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardToolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._name = QLineEdit(self)
        self._name.setObjectName("ultraViewBoardName")
        self._name.setText("全局对比")
        self._name.setFrame(False)
        self._name.setPlaceholderText("Board 名称")
        self._name.setToolTip("编辑 Board 名称")
        self._name.editingFinished.connect(self._on_name_finished)
        layout.addWidget(self._name, 1)

        self._layout_combo = QComboBox(self)
        self._layout_combo.setObjectName("ultraViewLayoutCombo")
        for layout_id in LAYOUT_SLOTS:
            self._layout_combo.addItem(LAYOUT_LABELS_ZH[layout_id], layout_id)
        self._layout_combo.currentIndexChanged.connect(self._on_layout_index)
        layout.addWidget(self._layout_combo, 0)

        self._ratio_down = QToolButton(self)
        self._ratio_down.setObjectName("ultraViewRatioDown")
        self._ratio_down.setText("−")
        self._ratio_down.setToolTip("主图比例 −5%")
        self._ratio_down.clicked.connect(self._on_ratio_down)
        self._ratio_up = QToolButton(self)
        self._ratio_up.setObjectName("ultraViewRatioUp")
        self._ratio_up.setText("+")
        self._ratio_up.setToolTip("主图比例 +5%")
        self._ratio_up.clicked.connect(self._on_ratio_up)
        layout.addWidget(self._ratio_down, 0)
        layout.addWidget(self._ratio_up, 0)

        self._add = QPushButton("添加 View", self)
        self._add.setObjectName("ultraViewAddButton")
        self._add.clicked.connect(self.add_clicked)
        layout.addWidget(self._add, 0)

        self._copy = QPushButton("复制整板图", self)
        self._copy.setObjectName("ultraViewCopyBoardButton")
        self._copy.clicked.connect(self.copy_board_requested)
        layout.addWidget(self._copy, 0)

        self._export = QToolButton(self)
        self._export.setObjectName("ultraViewExportButton")
        self._export.setText("导出 PNG")
        self._export.setPopupMode(QToolButton.InstantPopup)
        self._export.setToolButtonStyle(Qt.ToolButtonTextOnly)
        export_menu = QMenu(self._export)
        apply_rounded_menu_chrome(export_menu)
        act_1x = export_menu.addAction("导出 PNG 1×")
        act_2x = export_menu.addAction("导出 PNG 2×")
        act_1x.triggered.connect(self._on_export_1x)
        act_2x.triggered.connect(self._on_export_2x)
        self._export.setMenu(export_menu)
        layout.addWidget(self._export, 0)

        self._display = QToolButton(self)
        self._display.setObjectName("ultraViewDisplayButton")
        self._display.setText("显示")
        self._display.setPopupMode(QToolButton.InstantPopup)
        self._display.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._display.setToolTip("显示标题和来源")
        display_menu = QMenu(self._display)
        apply_rounded_menu_chrome(display_menu)
        self._act_titles = display_menu.addAction("显示标题")
        self._act_titles.setCheckable(True)
        self._act_titles.setChecked(True)
        self._act_sources = display_menu.addAction("显示来源")
        self._act_sources.setCheckable(True)
        self._act_sources.setChecked(True)
        self._act_titles.toggled.connect(self.show_titles_toggled)
        self._act_sources.toggled.connect(self.show_sources_toggled)
        self._display.setMenu(display_menu)
        layout.addWidget(self._display, 0)

        self._presentation = QPushButton("演示", self)
        self._presentation.setObjectName("ultraViewPresentationButton")
        self._presentation.setCheckable(True)
        self._presentation.toggled.connect(self.presentation_toggled)
        layout.addWidget(self._presentation, 0)

    def set_board_name(self, name: str) -> None:
        text = name or ""
        if self._name.text() == text:
            return
        blocked = self._name.blockSignals(True)
        self._name.setText(text)
        self._name.blockSignals(blocked)

    def board_name_edit(self) -> QLineEdit:
        return self._name

    def _on_name_finished(self) -> None:
        self.board_name_changed.emit(self._name.text())

    def set_layout_id(self, layout_id: str) -> None:
        index = self._layout_combo.findData(layout_id)
        if index < 0:
            return
        blocked = self._layout_combo.blockSignals(True)
        self._layout_combo.setCurrentIndex(index)
        self._layout_combo.blockSignals(blocked)
        hero = layout_id in {"hero_left_4", "hero_top_4"}
        self._ratio_down.setVisible(hero)
        self._ratio_up.setVisible(hero)

    def set_presentation_checked(self, on: bool) -> None:
        blocked = self._presentation.blockSignals(True)
        self._presentation.setChecked(on)
        self._presentation.setText("退出演示" if on else "演示")
        self._presentation.blockSignals(blocked)

    def set_show_flags(self, titles: bool, sources: bool) -> None:
        blocked = self._act_titles.blockSignals(True)
        self._act_titles.setChecked(bool(titles))
        self._act_titles.blockSignals(blocked)
        blocked = self._act_sources.blockSignals(True)
        self._act_sources.setChecked(bool(sources))
        self._act_sources.blockSignals(blocked)

    def set_edit_visible(self, visible: bool) -> None:
        for widget in (
            self._layout_combo,
            self._ratio_down,
            self._ratio_up,
            self._add,
            self._copy,
            self._export,
            self._display,
        ):
            widget.setVisible(visible)

    def _on_layout_index(self, index: int) -> None:
        layout_id = self._layout_combo.itemData(index)
        if isinstance(layout_id, str) and layout_id:
            self.layout_changed.emit(layout_id)

    def _on_ratio_down(self) -> None:
        self.ratio_nudge_requested.emit(-1)

    def _on_ratio_up(self) -> None:
        self.ratio_nudge_requested.emit(1)

    def _on_export_1x(self, _checked: bool = False) -> None:
        self.export_png_requested.emit(1)

    def _on_export_2x(self, _checked: bool = False) -> None:
        self.export_png_requested.emit(2)


class CompareRail(QFrame):
    compare_filter_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCompareRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for filter_id in COMPARE_FILTERS:
            button = QPushButton(COMPARE_FILTER_LABELS_ZH[filter_id], self)
            button.setObjectName("ultraViewCompareButton")
            button.setCheckable(True)
            button.setProperty("filterId", filter_id)
            button.setFocusPolicy(Qt.TabFocus)
            self._group.addButton(button)
            self._buttons[filter_id] = button
            layout.addWidget(button, 0)
        self._buttons[COMPARE_FILTER_ALL].setChecked(True)
        self._group.buttonClicked.connect(self._on_button)
        self._warning = QLabel("", self)
        self._warning.setObjectName("ultraViewAxisWarning")
        self._warning.setWordWrap(False)
        layout.addWidget(self._warning, 1)
        layout.addStretch(1)
        self._filter_id = COMPARE_FILTER_ALL

    def filter_id(self) -> str:
        return self._filter_id

    def set_filter_id(self, filter_id: str) -> None:
        if filter_id not in self._buttons:
            filter_id = COMPARE_FILTER_ALL
        self._filter_id = filter_id
        button = self._buttons[filter_id]
        blocked = button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(blocked)

    def set_axis_warning(self, text: str) -> None:
        self._warning.setText(text)
        self._warning.setVisible(bool(text))

    def _on_button(self, button: QPushButton) -> None:
        filter_id = str(button.property("filterId") or COMPARE_FILTER_ALL)
        if filter_id == self._filter_id:
            return
        self._filter_id = filter_id
        self.compare_filter_changed.emit(filter_id)


class LibraryRowWidget(QFrame):
    add_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, row: LibraryRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibraryRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(False)
        self._row = row
        self._press_pos: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 4, 4)
        layout.setSpacing(6)
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
        copy.addWidget(self._name)
        copy.addWidget(self._meta)
        layout.addLayout(copy, 1)
        self._add = QToolButton(self)
        self._add.setObjectName("ultraViewLibraryAdd")
        self._add.clicked.connect(self._on_add)
        layout.addWidget(self._add, 0)
        self.set_row(row)

    def row(self) -> LibraryRow:
        return self._row

    def set_row(self, row: LibraryRow) -> None:
        self._row = row
        self._dot.set_color(row.tab_color)
        self._name.set_full_text(row.name or row.view_id)
        self._meta.set_full_text(row.source_summary)
        self._add.setText("✓" if row.on_board else "+")
        self._add.setToolTip("定位已在总览中的 View" if row.on_board else "添加到总览")
        _set_flag(self, "onBoard", row.on_board)
        self.setToolTip(
            _full_tooltip(row.name or row.view_id, row.section, row.source_summary, row.status)
        )
        self.setAccessibleName(
            f"{SECTION_LABELS_ZH.get(row.section, row.section)} {row.name or row.view_id}"
        )

    def set_selected(self, on: bool) -> None:
        _set_flag(self, "selected", on)

    def _on_add(self) -> None:
        row = self._row
        if row.on_board:
            self.locate_requested.emit(row.section, row.view_id)
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
        drag = QDrag(self)
        drag.setMimeData(mime)
        self.drag_started.emit("library")
        try:
            drag.exec_(Qt.CopyAction)
        finally:
            self.drag_finished.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)


class ViewLibraryPanel(QFrame):
    add_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibrary")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(160)
        self.setMaximumWidth(320)
        self._rows: list[LibraryRow] = []
        self._selected: tuple[str, str] | None = None
        self._row_widgets: list[LibraryRowWidget] = []
        self._section_frames: dict[str, QFrame] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(10, 8, 10, 6)
        title = QLabel("View 库", self)
        title.setObjectName("ultraViewLibraryTitle")
        self._count = QLabel("0", self)
        self._count.setObjectName("ultraViewLibraryCount")
        head.addWidget(title, 1)
        head.addWidget(self._count, 0)
        root.addLayout(head)

        self._search = QLineEdit(self)
        self._search.setObjectName("ultraViewLibrarySearch")
        self._search.setPlaceholderText("搜索 View…")
        self._search.textChanged.connect(self._rebuild)
        search_wrap = QHBoxLayout()
        search_wrap.setContentsMargins(8, 0, 8, 6)
        search_wrap.addWidget(self._search)
        root.addLayout(search_wrap)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._body = QWidget(self._scroll)
        self._body.setObjectName("ultraViewLibraryBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(6, 0, 6, 8)
        self._body_layout.setSpacing(8)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)
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

    def row_widgets(self) -> list[LibraryRowWidget]:
        return list(self._row_widgets)

    def set_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        self._rows = [coerce_library_row(row) for row in rows]
        self._count.setText(str(len(self._rows)))
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

    def _rebuild(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._row_widgets = []
        self._section_frames = {}
        visible = self.visible_rows()
        by_section: dict[str, list[LibraryRow]] = {section: [] for section in SOURCE_SECTIONS}
        for row in visible:
            if row.section in by_section:
                by_section[row.section].append(row)
        for section in SOURCE_SECTIONS:
            frame = QFrame(self._body)
            frame.setObjectName("ultraViewLibrarySection")
            frame.setProperty("section", section)
            section_layout = QVBoxLayout(frame)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(2)
            header = QLabel(
                f"{SECTION_LABELS_ZH[section]}  {len(by_section[section])}",
                frame,
            )
            header.setObjectName("ultraViewLibrarySectionHead")
            section_layout.addWidget(header)
            for row in by_section[section]:
                row_widget = LibraryRowWidget(row, frame)
                row_widget.add_requested.connect(self.add_requested)
                row_widget.locate_requested.connect(self.locate_requested)
                row_widget.selected.connect(self._on_row_selected)
                row_widget.drag_started.connect(self.drag_started)
                row_widget.drag_finished.connect(self.drag_finished)
                if self._selected == (row.section, row.view_id):
                    row_widget.set_selected(True)
                section_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)
            self._section_frames[section] = frame
            self._body_layout.addWidget(frame)
        self._body_layout.addStretch(1)

    def _on_row_selected(self, section: str, view_id: str) -> None:
        self.set_selected(section, view_id)


class EmptySlotWidget(QFrame):
    add_clicked = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str, str)
    drag_entered = pyqtSignal()

    def __init__(self, slot_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewEmptySlot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.TabFocus)
        self._slot_id = slot_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._label = QLabel("＋\n添加 View", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setObjectName("ultraViewEmptySlotLabel")
        layout.addWidget(self._label, 1)
        self.setAccessibleName(f"空槽 {slot_id} 添加 View")

    def slot_id(self) -> str:
        return self._slot_id

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.add_clicked.emit(self._slot_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.add_clicked.emit(self._slot_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            self.drag_entered.emit()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        if extracted is None:
            return
        section, view_id = extracted
        self.ref_dropped.emit(self._slot_id, section, view_id)


class UltraViewCard(QFrame):
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    ref_dropped = pyqtSignal(str, str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, model: CardViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_custom_menu)
        self._model = model
        self._press_pos: QPoint | None = None
        self._menu: QMenu | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("ultraViewCardHeader")
        self._header.setFixedHeight(CARD_HEADER_HEIGHT)
        header = QHBoxLayout(self._header)
        header.setContentsMargins(8, 4, 6, 4)
        header.setSpacing(6)
        self._dot = _ColorDot(self._header)
        header.addWidget(self._dot, 0)
        self._title = _ElideLabel("", self._header)
        header.addWidget(self._title, 1)
        self._status = QLabel("", self._header)
        self._status.setObjectName("ultraViewCardStatus")
        header.addWidget(self._status, 0)
        self._focus_btn = QToolButton(self._header)
        self._focus_btn.setObjectName("ultraViewCardFocusButton")
        self._focus_btn.setText("⛶")
        self._focus_btn.setToolTip("临时放大")
        self._focus_btn.clicked.connect(self._emit_focus)
        header.addWidget(self._focus_btn, 0)
        root.addWidget(self._header, 0)

        self._image = QLabel(self)
        self._image.setObjectName("ultraViewCardImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setWordWrap(True)
        self._image.setMinimumHeight(max(8, MIN_CARD_CHROME_HEIGHT // 4))
        self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._image, 1)

        self._orphan_bar = QWidget(self)
        self._orphan_bar.setObjectName("ultraViewCardOrphanBar")
        orphan = QHBoxLayout(self._orphan_bar)
        orphan.setContentsMargins(8, 2, 8, 2)
        orphan.setSpacing(6)
        self._rebind_btn = QPushButton("重新绑定", self._orphan_bar)
        self._rebind_btn.setObjectName("ultraViewCardRebindButton")
        self._rebind_btn.clicked.connect(self._emit_rebind)
        self._remove_btn = QPushButton("从总览移除", self._orphan_bar)
        self._remove_btn.setObjectName("ultraViewCardRemoveButton")
        self._remove_btn.clicked.connect(self._emit_remove)
        orphan.addWidget(self._rebind_btn)
        orphan.addWidget(self._remove_btn)
        orphan.addStretch(1)
        root.addWidget(self._orphan_bar, 0)

        self._footer = QWidget(self)
        self._footer.setObjectName("ultraViewCardFooter")
        self._footer.setFixedHeight(CARD_FOOTER_HEIGHT)
        footer = QHBoxLayout(self._footer)
        footer.setContentsMargins(8, 2, 8, 4)
        footer.setSpacing(6)
        self._foot_left = _ElideLabel("", self._footer)
        self._foot_source = _ElideLabel("", self._footer)
        self._foot_source.setObjectName("ultraViewCardSource")
        footer.addWidget(self._foot_left, 1)
        footer.addWidget(self._foot_source, 0)
        root.addWidget(self._footer, 0)

        self._raw_image: QImage | None = None
        self.apply_model(model)

    def model(self) -> CardViewModel:
        return self._model

    def slot_id(self) -> str:
        return self._model.slot_id

    def header_height(self) -> int:
        return self._header.height()

    def footer_height(self) -> int:
        return self._footer.height()

    def chrome_height(self) -> int:
        extra = self._orphan_bar.height() if self._orphan_bar.isVisible() else 0
        return self._header.height() + self._footer.height() + extra

    def apply_model(self, model: CardViewModel) -> None:
        self._model = model
        title = model.title or model.view_id
        self._dot.set_color(model.tab_color)
        self._title.setVisible(bool(model.show_title))
        self._title.set_full_text(title if model.show_title else "")
        if model.status == STATUS_MISSING:
            self._status.setText(STATUS_LABELS_ZH[STATUS_MISSING])
        elif model.status == STATUS_STALE:
            self._status.setText(STALE_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._status.setText(ORPHANED_CARD_COPY)
        else:
            self._status.setText("")
        self._status.setVisible(bool(self._status.text()))
        section_label = SECTION_LABELS_ZH.get(model.section, model.section)
        self._foot_left.set_full_text(
            f"{section_label} · {_range_text(model.x_range, model.x_unit)}"
        )
        self._foot_source.set_full_text(model.source_summary if model.show_source else "")
        self._footer.setVisible(bool(model.show_source))
        if model.show_source:
            self._footer.setFixedHeight(CARD_FOOTER_HEIGHT)
        else:
            self._footer.setFixedHeight(0)
        self._orphan_bar.setVisible(model.status == STATUS_ORPHANED)
        self._set_image(model)
        _set_flag(self, "selected", model.selected)
        _set_flag(self, "dimmed", model.dimmed)
        _set_flag(self, "orphaned", model.status == STATUS_ORPHANED)
        _set_flag(self, "replacementArmed", model.replacement_armed)
        self.setProperty("status", model.status)
        self._apply_dim(model.dimmed)
        _repolish(self)
        parts = [
            section_label,
            title,
            STATUS_LABELS_ZH.get(model.status, model.status),
        ]
        if model.selected:
            parts.append("已选中")
        if model.dimmed:
            parts.append("已弱化")
        if model.replacement_armed:
            parts.append("等待替换")
        if model.status == STATUS_ORPHANED:
            parts.append("源已删除")
        self.setAccessibleName(" ".join(part for part in parts if part))
        self.setToolTip(_full_tooltip(title, model.section, model.source_summary, model.status))

    def make_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("ultraViewCardMenu")
        apply_rounded_menu_chrome(menu)
        open_act = menu.addAction("打开原 View")
        focus_act = menu.addAction("临时放大")
        replace_act = menu.addAction("替换")
        unplaced_act = menu.addAction("移到未放置")
        remove_act = menu.addAction("从总览移除")
        copy_act = menu.addAction("复制本卡图像")
        open_act.triggered.connect(self._emit_open_source)
        focus_act.triggered.connect(self._emit_focus)
        replace_act.triggered.connect(self._emit_rebind)
        unplaced_act.triggered.connect(self._emit_unplaced)
        remove_act.triggered.connect(self._emit_remove)
        copy_act.triggered.connect(self._emit_copy)
        self._menu = menu
        return menu

    def _set_image(self, model: CardViewModel) -> None:
        image = model.image
        if image is not None and not (callable(getattr(image, "isNull", None)) and image.isNull()):
            self._raw_image = image if isinstance(image, QImage) else None
            self._image.setText("")
            self._fit_card_image()
            return
        self._raw_image = None
        self._image.setPixmap(QPixmap())
        if model.status == STATUS_MISSING:
            self._image.setText(MISSING_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._image.setText(ORPHANED_CARD_COPY)
        elif model.status == STATUS_STALE:
            self._image.setText(STALE_CARD_COPY)
        else:
            self._image.setText("")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_card_image()

    def _fit_card_image(self) -> None:
        if self._raw_image is None:
            return
        raw_w = self._raw_image.width()
        raw_h = self._raw_image.height()
        avail = self._image.size()
        if avail.width() < 2 or avail.height() < 2:
            return
        cap_w = max(1, min(avail.width(), raw_w))
        cap_h = max(1, min(avail.height(), raw_h))
        pixmap = QPixmap.fromImage(self._raw_image)
        self._image.setPixmap(
            pixmap.scaled(cap_w, cap_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _apply_dim(self, dimmed: bool) -> None:
        if dimmed:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(DIMMED_OPACITY)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def _emit_open_source(self, _checked: bool = False) -> None:
        if self._model.status == STATUS_ORPHANED:
            self.rebind_arm_requested.emit(self._model.section, self._model.view_id)
            return
        self.open_source_requested.emit(self._model.section, self._model.view_id)

    def _emit_focus(self, _checked: bool = False) -> None:
        self.focus_requested.emit(self._model.section, self._model.view_id)

    def _emit_rebind(self, _checked: bool = False) -> None:
        self.rebind_arm_requested.emit(self._model.section, self._model.view_id)

    def _emit_unplaced(self, _checked: bool = False) -> None:
        self.move_to_unplaced_requested.emit(self._model.section, self._model.view_id)

    def _emit_remove(self, _checked: bool = False) -> None:
        self.remove_ref_requested.emit(self._model.section, self._model.view_id)

    def _emit_copy(self, _checked: bool = False) -> None:
        self.copy_card_image_requested.emit(self._model.section, self._model.view_id)

    def _on_custom_menu(self, pos: QPoint) -> None:
        menu = self.make_context_menu()
        menu.popup(self.mapToGlobal(pos))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = QPoint(event.pos())
            self.selected.emit(self._model.section, self._model.view_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.focus_requested.emit(self._model.section, self._model.view_id)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._model.section, self._model.view_id)
        drag = QDrag(self)
        drag.setMimeData(mime)
        self.drag_started.emit("card")
        try:
            drag.exec_(Qt.MoveAction)
        finally:
            self.drag_finished.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._emit_focus()
            event.accept()
            return
        if key == Qt.Key_Delete:
            self._emit_remove()
            event.accept()
            return
        if key == Qt.Key_Backspace:
            self._emit_unplaced()
            event.accept()
            return
        if key == Qt.Key_O:
            self._emit_open_source()
            event.accept()
            return
        if key == Qt.Key_R:
            self._emit_rebind()
            event.accept()
            return
        if key == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self._emit_copy()
            event.accept()
            return
        super().keyPressEvent(event)

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
        self.ref_dropped.emit(self._model.slot_id, section, view_id)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = self.make_context_menu()
        menu.popup(event.globalPos())
        event.accept()


class BoardGrid(QWidget):
    add_clicked = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str, str)
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout_id = "hero_left_4"
        self._ratio = 0.67
        self._widgets: dict[str, QWidget] = {}

    def layout_id(self) -> str:
        return self._layout_id

    def slot_widget(self, slot_id: str) -> QWidget | None:
        return self._widgets.get(slot_id)

    def card_widgets(self) -> list[UltraViewCard]:
        return [widget for widget in self._widgets.values() if isinstance(widget, UltraViewCard)]

    def card_for(self, section: str, view_id: str) -> UltraViewCard | None:
        for card in self.card_widgets():
            model = card.model()
            if model.section == section and model.view_id == view_id:
                return card
        return None

    def set_grid(
        self,
        layout_id: str,
        primary_ratio: float,
        models: Mapping[str, CardViewModel | None],
    ) -> None:
        self._layout_id = layout_id
        self._ratio = primary_ratio
        wanted = set(LAYOUT_SLOTS[layout_id])
        for slot_id in list(self._widgets):
            if slot_id not in wanted:
                self._discard(slot_id)
        for slot_id in LAYOUT_SLOTS[layout_id]:
            model = models.get(slot_id)
            self._sync_slot(slot_id, model)
        self._relayout()

    def _discard(self, slot_id: str) -> None:
        widget = self._widgets.pop(slot_id, None)
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()

    def _sync_slot(self, slot_id: str, model: CardViewModel | None) -> None:
        current = self._widgets.get(slot_id)
        if model is None:
            if isinstance(current, EmptySlotWidget):
                return
            self._discard(slot_id)
            empty = EmptySlotWidget(slot_id, self)
            empty.add_clicked.connect(self.add_clicked)
            empty.ref_dropped.connect(self.ref_dropped)
            self._widgets[slot_id] = empty
            empty.show()
            return
        if isinstance(current, UltraViewCard):
            current.apply_model(model)
            return
        self._discard(slot_id)
        card = UltraViewCard(model, self)
        card.open_source_requested.connect(self.open_source_requested)
        card.focus_requested.connect(self.focus_requested)
        card.rebind_arm_requested.connect(self.rebind_arm_requested)
        card.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        card.remove_ref_requested.connect(self.remove_ref_requested)
        card.copy_card_image_requested.connect(self.copy_card_image_requested)
        card.selected.connect(self.selected)
        card.ref_dropped.connect(self.ref_dropped)
        card.drag_started.connect(self.drag_started)
        card.drag_finished.connect(self.drag_finished)
        self._widgets[slot_id] = card
        card.show()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, self.width() - 2 * BOARD_PADDING),
            max(0, self.height() - 2 * BOARD_PADDING),
        )
        try:
            rects = slot_rects(self._layout_id, content, self._ratio)
        except ValueError:
            return
        for slot_id, (x, y, width, height) in rects.items():
            widget = self._widgets.get(slot_id)
            if widget is not None:
                widget.setGeometry(x, y, max(0, width), max(0, height))

    def slot_id_at(self, pos: QPoint) -> str | None:
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, self.width() - 2 * BOARD_PADDING),
            max(0, self.height() - 2 * BOARD_PADDING),
        )
        rects = slot_rects(self._layout_id, content, self._ratio)
        px, py = pos.x(), pos.y()
        for slot_id, (x, y, width, height) in rects.items():
            if x <= px <= x + width and y <= py <= y + height:
                return slot_id
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        extracted = extract_ref_strings(event.mimeData())
        pos = QPoint(event.pos())
        event.acceptProposedAction()
        if extracted is None:
            return
        section, view_id = extracted
        slot_id = self.slot_id_at(pos)
        if slot_id is None:
            return
        self.ref_dropped.emit(slot_id, section, view_id)


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
        remove.setText("移除")
        remove.clicked.connect(self._emit_remove)
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
        drag = QDrag(self)
        drag.setMimeData(mime)
        self.drag_started.emit("tray")
        try:
            drag.exec_(Qt.MoveAction)
        finally:
            self.drag_finished.emit()

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
        self._body.setMaximumHeight(TRAY_BODY_MAX_HEIGHT)
        self._inner = QWidget(self._body)
        self._inner_layout = QHBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(8, 6, 8, 8)
        self._inner_layout.setSpacing(8)
        self._inner_layout.addStretch(1)
        self._body.setWidget(self._inner)
        self._body.setVisible(False)
        root.addWidget(self._body, 0)

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
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._items = []
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
            widget.place_requested.connect(self.place_requested)
            widget.remove_requested.connect(self.remove_requested)
            widget.locate_requested.connect(self.locate_requested)
            widget.rebind_arm_requested.connect(self.rebind_arm_requested)
            widget.drag_started.connect(self.drag_started)
            widget.drag_finished.connect(self.drag_finished)
            self._inner_layout.insertWidget(self._inner_layout.count() - 1, widget)
            self._items.append(widget)
        count = len(refs)
        self._title.setText("未放置" if count == 0 else f"未放置 · {count}")

    def _on_title(self, checked: bool) -> None:
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


class FocusLayer(QFrame):
    closed = pyqtSignal()
    open_source_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFocusLayer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        self._section = ""
        self._view_id = ""
        self._image: QImage | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        panel = QFrame(self)
        panel.setObjectName("ultraViewFocusPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 8, 8)
        self._title = QLabel("", panel)
        self._title.setObjectName("ultraViewFocusTitle")
        close_btn = QToolButton(panel)
        close_btn.setText("×")
        close_btn.setObjectName("ultraViewFocusClose")
        close_btn.clicked.connect(self.close_layer)
        head.addWidget(self._title, 1)
        head.addWidget(close_btn, 0)
        panel_layout.addLayout(head)
        self._image_host = QLabel(panel)
        self._image_host.setObjectName("ultraViewFocusImage")
        self._image_host.setAlignment(Qt.AlignCenter)
        self._image_host.setMinimumSize(QSize(120, 80))
        self._image_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(self._image_host, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 8, 12, 10)
        note = QLabel("临时查看 · 不改变源 View · 不超过原始像素 100%", panel)
        self._open = QPushButton("打开原 View", panel)
        self._open.setObjectName("ultraViewOpenSourceButton")
        self._open.clicked.connect(self._emit_open)
        foot.addWidget(note, 1)
        foot.addWidget(self._open, 0)
        panel_layout.addLayout(foot)
        root.addWidget(panel, 1)

    def open_source_button(self) -> QPushButton:
        return self._open

    def displayed_pixmap_size(self) -> QSize:
        pixmap = self._image_host.pixmap()
        if pixmap is None or pixmap.isNull():
            return QSize(0, 0)
        return pixmap.size()

    def raw_image_size(self) -> QSize:
        if self._image is None:
            return QSize(0, 0)
        return QSize(self._image.width(), self._image.height())

    def show_ref(
        self,
        section: str,
        view_id: str,
        title: str,
        image: QImage | None,
    ) -> None:
        self._section = section
        self._view_id = view_id
        self._image = image
        self._title.setText(title or view_id)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._refit()

    def close_layer(self) -> None:
        self.hide()
        self._image = None
        self._image_host.setPixmap(QPixmap())
        self.closed.emit()

    def _emit_open(self) -> None:
        if self._section and self._view_id:
            self.open_source_requested.emit(self._section, self._view_id)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close_layer()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        child = self.childAt(event.pos())
        if child is None or child is self:
            self.close_layer()
            event.accept()
            return
        super().mousePressEvent(event)

    def _refit(self) -> None:
        if self._image is None:
            self._image_host.setPixmap(QPixmap())
            return
        raw_w = self._image.width()
        raw_h = self._image.height()
        avail = self._image_host.size()
        cap_w = max(1, min(avail.width(), raw_w))
        cap_h = max(1, min(avail.height(), raw_h))
        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(cap_w, cap_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_host.setPixmap(scaled)

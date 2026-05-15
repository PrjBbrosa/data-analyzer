"""Manifest-backed History tab for Acquisition Cockpit."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PyQt5.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QObject,
    QRunnable,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import QBrush, QColor, QDesktopServices
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition.manifest import (
    Mf4DatasetEntry,
    load_manifest,
    resolve_entry_path,
)

logger = logging.getLogger(__name__)

ALL_FILTER_TEXT = "全部"
STATUS_RESOLVING = "解析中"
STATUS_LOCAL = "本地"
STATUS_LFS = "LFS"
STATUS_EXTERNAL = "外部 (NAS)"
STATUS_MISSING = "缺失"

COL_ID = 0
COL_VEHICLE = 1
COL_PLATFORM = 2
COL_SCENARIO = 3
COL_SETS = 4
COL_TAGS = 5
COL_PATH_KIND = 6
COL_SIZE = 7
COL_STATUS = 8

_HEADERS = (
    "录制时间",
    "vehicle",
    "platform",
    "scenario",
    "sets",
    "issue_tags",
    "path_kind",
    "文件大小",
    "状态",
)


@dataclass(frozen=True)
class HistoryPathInfo:
    """Resolved path status for one manifest entry."""

    path: Path
    exists: bool
    size_bytes: int | None
    status: str
    error: str | None = None


@dataclass(frozen=True)
class _HistoryRow:
    entry: Mf4DatasetEntry
    manifest_order: int
    path_info: HistoryPathInfo | None = None


class HistoryPathResolver:
    """Isolated path resolver used by the async worker and tests."""

    def resolve(
        self, entry: Mf4DatasetEntry, *, manifest_path: Path
    ) -> HistoryPathInfo:
        try:
            path = resolve_entry_path(entry, manifest_path=manifest_path)
            exists = path.exists()
            if not exists:
                return HistoryPathInfo(
                    path=path,
                    exists=False,
                    size_bytes=None,
                    status=STATUS_MISSING,
                )
            size_bytes = path.stat().st_size if entry.path_kind == "local" else None
            return HistoryPathInfo(
                path=path,
                exists=True,
                size_bytes=size_bytes,
                status=_status_for_path_kind(entry.path_kind),
            )
        except Exception as exc:  # noqa: BLE001 - UI must not crash on bad paths
            logger.warning("history path resolution failed for %s: %s", entry.id, exc)
            return HistoryPathInfo(
                path=Path(entry.path),
                exists=False,
                size_bytes=None,
                status=STATUS_MISSING,
                error=str(exc),
            )


class _ResolverSignals(QObject):
    resolved = pyqtSignal(int, int, object)


class _ResolveEntryRunnable(QRunnable):
    def __init__(
        self,
        *,
        generation: int,
        row: int,
        entry: Mf4DatasetEntry,
        manifest_path: Path,
        resolver: HistoryPathResolver,
    ) -> None:
        super().__init__()
        self.signals = _ResolverSignals()
        self._generation = generation
        self._row = row
        self._entry = entry
        self._manifest_path = manifest_path
        self._resolver = resolver

    @pyqtSlot()
    def run(self) -> None:
        info = self._resolver.resolve(self._entry, manifest_path=self._manifest_path)
        self.signals.resolved.emit(self._generation, self._row, info)


class _HistoryTableModel(QAbstractTableModel):
    EntryRole = Qt.UserRole + 1
    PathInfoRole = Qt.UserRole + 2
    ResolvedPathRole = Qt.UserRole + 3
    StatusRole = Qt.UserRole + 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_HistoryRow] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(_HEADERS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        try:
            return _HEADERS[section]
        except IndexError:
            return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        entry = row.entry
        info = row.path_info

        if role == self.EntryRole:
            return entry
        if role == self.PathInfoRole:
            return info
        if role == self.ResolvedPathRole:
            return str(info.path) if info is not None else ""
        if role == self.StatusRole:
            return info.status if info is not None else STATUS_RESOLVING
        if role == Qt.ToolTipRole:
            if info is not None:
                return str(info.path)
            return entry.path
        if role == Qt.ForegroundRole and index.column() == COL_STATUS:
            status = info.status if info is not None else STATUS_RESOLVING
            if status == STATUS_MISSING:
                return QBrush(QColor("#dc2626"))
            if status == STATUS_RESOLVING:
                return QBrush(QColor("#64748b"))
            return QBrush(QColor("#166534"))
        if role == Qt.TextAlignmentRole and index.column() in (COL_SIZE, COL_STATUS):
            return Qt.AlignCenter
        if role != Qt.DisplayRole:
            return None

        if index.column() == COL_ID:
            return entry.id
        if index.column() == COL_VEHICLE:
            return entry.vehicle or "—"
        if index.column() == COL_PLATFORM:
            return entry.platform or "—"
        if index.column() == COL_SCENARIO:
            return entry.scenario or "—"
        if index.column() == COL_SETS:
            return ", ".join(entry.sets) if entry.sets else "—"
        if index.column() == COL_TAGS:
            return ", ".join(entry.issue_tags) if entry.issue_tags else "—"
        if index.column() == COL_PATH_KIND:
            return entry.path_kind
        if index.column() == COL_SIZE:
            if info is None or info.size_bytes is None:
                return "n/a"
            return _format_bytes(info.size_bytes)
        if index.column() == COL_STATUS:
            return info.status if info is not None else STATUS_RESOLVING
        return None

    def set_rows(self, rows: list[_HistoryRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_path_info(self, row: int, info: HistoryPathInfo) -> None:
        if row < 0 or row >= len(self._rows):
            return
        old = self._rows[row]
        self._rows[row] = _HistoryRow(
            entry=old.entry,
            manifest_order=old.manifest_order,
            path_info=info,
        )
        top_left = self.index(row, COL_SIZE)
        bottom_right = self.index(row, COL_STATUS)
        self.dataChanged.emit(
            top_left,
            bottom_right,
            [
                Qt.DisplayRole,
                Qt.ForegroundRole,
                self.PathInfoRole,
                self.ResolvedPathRole,
                self.StatusRole,
            ],
        )

    def entry_at(self, row: int) -> Mf4DatasetEntry | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row].entry

    def path_info_at(self, row: int) -> HistoryPathInfo | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row].path_info


class _HistoryFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vehicle = ""
        self._scenario = ""
        self._path_kind = ""
        self._dataset = ""
        self._tags: set[str] = set()
        self._search = ""

    def set_vehicle(self, value: str) -> None:
        self._vehicle = _normalize_filter_value(value)
        self.invalidateFilter()

    def set_scenario(self, value: str) -> None:
        self._scenario = _normalize_filter_value(value)
        self.invalidateFilter()

    def set_path_kind(self, value: str) -> None:
        self._path_kind = _normalize_filter_value(value)
        self.invalidateFilter()

    def set_dataset(self, value: str) -> None:
        self._dataset = _normalize_filter_value(value)
        self.invalidateFilter()

    def set_tags(self, tags: Iterable[str]) -> None:
        self._tags = {tag for tag in tags if tag}
        self.invalidateFilter()

    def set_search(self, text: str) -> None:
        self._search = text.casefold().strip()
        self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        if not isinstance(model, _HistoryTableModel):
            return True
        entry = model.entry_at(source_row)
        if entry is None:
            return False
        if self._vehicle and entry.vehicle != self._vehicle:
            return False
        if self._scenario and entry.scenario != self._scenario:
            return False
        if self._path_kind and entry.path_kind != self._path_kind:
            return False
        if self._dataset and self._dataset not in entry.sets:
            return False
        if self._tags and not self._tags.issubset(set(entry.issue_tags)):
            return False
        if self._search and self._search not in _entry_search_text(entry):
            return False
        return True


class HistoryTab(QWidget):
    """Standalone manifest-backed history browser.

    ``analyzer_open_requested`` emits the resolved MF4 path for coordinator-
    owned integration with ``CockpitMainWindow`` / Analyzer.
    """

    analyzer_open_requested = pyqtSignal(str)

    def __init__(
        self,
        *,
        manifest_path: Path | str | None = None,
        resolver: HistoryPathResolver | None = None,
        resolve_async: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("historyTab")
        self._manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else default_manifest_path()
        )
        self._resolver = resolver or HistoryPathResolver()
        self._resolve_async = resolve_async
        self._thread_pool = QThreadPool(self)
        self._generation = 0
        self._pending: dict[int, _ResolveEntryRunnable] = {}
        self._tag_checks: dict[str, QCheckBox] = {}

        self._source_model = _HistoryTableModel(self)
        self._proxy_model = _HistoryFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._source_model)

        self._build_ui()
        self.reload()

    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    @property
    def table_view(self) -> QTableView:
        return self._table

    @property
    def empty_label(self) -> QLabel:
        return self._empty_label

    @property
    def vehicle_filter(self) -> QComboBox:
        return self._vehicle_filter

    @property
    def scenario_filter(self) -> QComboBox:
        return self._scenario_filter

    @property
    def path_kind_filter(self) -> QComboBox:
        return self._path_kind_filter

    @property
    def set_filter(self) -> QComboBox:
        return self._set_filter

    @property
    def search_box(self) -> QLineEdit:
        return self._search_box

    def set_manifest_path(self, path: Path | str | None) -> None:
        self._manifest_path = (
            Path(path) if path is not None else default_manifest_path()
        )
        self.reload()

    def reload(self) -> None:
        self._generation += 1
        self._pending.clear()
        path = self._manifest_path
        if not path.exists():
            self._source_model.set_rows([])
            self._refresh_filter_values([])
            self._show_empty_state("未找到 manifest")
            return
        try:
            entries = load_manifest(path)
        except Exception as exc:  # noqa: BLE001 - show error instead of crashing UI
            logger.exception("could not load acquisition manifest %s", path)
            self._source_model.set_rows([])
            self._refresh_filter_values([])
            self._show_empty_state(f"manifest 加载失败: {exc}")
            return

        rows = [
            _HistoryRow(entry=entry, manifest_order=idx)
            for idx, entry in reversed(list(enumerate(entries)))
        ]
        self._source_model.set_rows(rows)
        self._refresh_filter_values(entries)
        if rows:
            self._body_stack.setCurrentWidget(self._table)
        else:
            self._show_empty_state("manifest 为空")
        self._schedule_path_resolution(rows)

    def wait_for_resolutions(self, timeout_ms: int = 1000) -> bool:
        """Test helper: wait for async path workers without hanging forever."""

        deadline = time.monotonic() + timeout_ms / 1000
        while self._pending and time.monotonic() < deadline:
            self._thread_pool.waitForDone(10)
            QCoreApplication.processEvents()
        QCoreApplication.processEvents()
        return not self._pending

    def open_current_entry(self) -> bool:
        index = self._table.currentIndex()
        if not index.isValid():
            return False
        return self._open_index(index)

    def copy_current_path(self) -> bool:
        info = self._path_info_for_proxy_index(self._table.currentIndex())
        if info is None:
            return False
        QApplication.clipboard().setText(str(info.path))
        return True

    def open_current_directory(self) -> bool:
        info = self._path_info_for_proxy_index(self._table.currentIndex())
        if info is None:
            return False
        directory = info.path if info.path.is_dir() else info.path.parent
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._vehicle_filter = self._make_filter_combo("historyVehicleFilter")
        self._scenario_filter = self._make_filter_combo("historyScenarioFilter")
        self._path_kind_filter = self._make_filter_combo("historyPathKindFilter")
        self._set_filter = self._make_filter_combo("historySetFilter")
        self._search_box = QLineEdit(self)
        self._search_box.setObjectName("historySearchBox")
        self._search_box.setPlaceholderText("搜索 name / id")
        self._search_box.textChanged.connect(self._proxy_model.set_search)

        filter_row.addWidget(QLabel("vehicle", self))
        filter_row.addWidget(self._vehicle_filter)
        filter_row.addWidget(QLabel("scenario", self))
        filter_row.addWidget(self._scenario_filter)
        filter_row.addWidget(QLabel("path_kind", self))
        filter_row.addWidget(self._path_kind_filter)
        filter_row.addWidget(QLabel("set", self))
        filter_row.addWidget(self._set_filter)
        filter_row.addWidget(self._search_box, stretch=1)
        root.addLayout(filter_row)

        self._tag_row = QHBoxLayout()
        self._tag_row.setSpacing(6)
        self._tag_row.addWidget(QLabel("issue_tags", self))
        self._tag_row.addStretch(1)
        root.addLayout(self._tag_row)

        self._table = QTableView(self)
        self._table.setObjectName("historyTableView")
        self._table.setModel(self._proxy_model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.doubleClicked.connect(self._open_index)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        self._empty_page = QWidget(self)
        empty_layout = QVBoxLayout(self._empty_page)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(12)
        empty_layout.addStretch(1)
        self._empty_label = QLabel("", self._empty_page)
        self._empty_label.setObjectName("historyEmptyLabel")
        self._empty_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self._empty_label)
        choose_btn = QPushButton("选择 manifest", self._empty_page)
        choose_btn.setObjectName("historyChooseManifestButton")
        choose_btn.clicked.connect(self._choose_manifest)
        empty_layout.addWidget(choose_btn, alignment=Qt.AlignCenter)
        empty_layout.addStretch(1)

        self._body_stack = QStackedWidget(self)
        self._body_stack.addWidget(self._table)
        self._body_stack.addWidget(self._empty_page)
        root.addWidget(self._body_stack, stretch=1)

    def _make_filter_combo(self, object_name: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName(object_name)
        combo.currentTextChanged.connect(self._on_filter_changed)
        return combo

    def _on_filter_changed(self) -> None:
        self._proxy_model.set_vehicle(self._vehicle_filter.currentText())
        self._proxy_model.set_scenario(self._scenario_filter.currentText())
        self._proxy_model.set_path_kind(self._path_kind_filter.currentText())
        self._proxy_model.set_dataset(self._set_filter.currentText())

    def _refresh_filter_values(self, entries: list[Mf4DatasetEntry]) -> None:
        self._populate_combo(
            self._vehicle_filter,
            sorted({entry.vehicle for entry in entries if entry.vehicle}),
        )
        self._populate_combo(
            self._scenario_filter,
            sorted({entry.scenario for entry in entries if entry.scenario}),
        )
        self._populate_combo(
            self._path_kind_filter,
            sorted({entry.path_kind for entry in entries if entry.path_kind}),
        )
        self._populate_combo(
            self._set_filter,
            sorted({dataset for entry in entries for dataset in entry.sets}),
        )
        self._rebuild_tag_chips(
            sorted({tag for entry in entries for tag in entry.issue_tags})
        )
        self._on_filter_changed()

    def _populate_combo(self, combo: QComboBox, values: list[str]) -> None:
        current = _normalize_filter_value(combo.currentText())
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(ALL_FILTER_TEXT)
        combo.addItems(values)
        if current and current in values:
            combo.setCurrentText(current)
        else:
            combo.setCurrentText(ALL_FILTER_TEXT)
        combo.blockSignals(False)

    def _rebuild_tag_chips(self, tags: list[str]) -> None:
        while self._tag_row.count() > 2:
            item = self._tag_row.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._tag_checks.clear()

        for tag in tags:
            chip = QCheckBox(tag, self)
            chip.setObjectName(f"historyTagChip_{tag}")
            chip.toggled.connect(self._on_tag_filters_changed)
            self._tag_checks[tag] = chip
            self._tag_row.insertWidget(self._tag_row.count() - 1, chip)
        self._on_tag_filters_changed()

    def _on_tag_filters_changed(self) -> None:
        self._proxy_model.set_tags(
            tag for tag, checkbox in self._tag_checks.items() if checkbox.isChecked()
        )

    def _show_empty_state(self, text: str) -> None:
        self._empty_label.setText(text)
        self._body_stack.setCurrentWidget(self._empty_page)

    def _choose_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 manifest",
            str(self._manifest_path.parent),
            "JSON (*.json);;All (*)",
        )
        if path:
            self.set_manifest_path(path)

    def _schedule_path_resolution(self, rows: list[_HistoryRow]) -> None:
        generation = self._generation
        manifest_path = self._manifest_path
        if not self._resolve_async:
            for row, item in enumerate(rows):
                self._source_model.set_path_info(
                    row,
                    self._resolver.resolve(item.entry, manifest_path=manifest_path),
                )
            return

        for row, item in enumerate(rows):
            runnable = _ResolveEntryRunnable(
                generation=generation,
                row=row,
                entry=item.entry,
                manifest_path=manifest_path,
                resolver=self._resolver,
            )
            runnable.signals.resolved.connect(self._on_resolution_ready)
            self._pending[row] = runnable
            self._thread_pool.start(runnable)

    @pyqtSlot(int, int, object)
    def _on_resolution_ready(
        self, generation: int, row: int, info: HistoryPathInfo
    ) -> None:
        if generation != self._generation:
            return
        self._pending.pop(row, None)
        self._source_model.set_path_info(row, info)

    def _show_context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        self._table.setCurrentIndex(index)
        menu = QMenu(self)
        open_action = QAction("在 Analyzer 打开", menu)
        open_action.setEnabled(self._is_openable_index(index))
        open_action.triggered.connect(
            lambda _checked=False: self.open_current_entry()
        )
        menu.addAction(open_action)

        copy_action = QAction("复制路径", menu)
        copy_action.setEnabled(self._path_info_for_proxy_index(index) is not None)
        copy_action.triggered.connect(lambda _checked=False: self.copy_current_path())
        menu.addAction(copy_action)

        folder_action = QAction("打开所在目录", menu)
        folder_action.setEnabled(self._path_info_for_proxy_index(index) is not None)
        folder_action.triggered.connect(
            lambda _checked=False: self.open_current_directory()
        )
        menu.addAction(folder_action)
        menu.exec_(self._table.viewport().mapToGlobal(pos))

    def _open_index(self, index: QModelIndex) -> bool:
        info = self._path_info_for_proxy_index(index)
        if info is None or not info.exists:
            return False
        self.analyzer_open_requested.emit(str(info.path))
        return True

    def _is_openable_index(self, index: QModelIndex) -> bool:
        info = self._path_info_for_proxy_index(index)
        return info is not None and info.exists

    def _path_info_for_proxy_index(
        self, proxy_index: QModelIndex
    ) -> HistoryPathInfo | None:
        if not proxy_index.isValid():
            return None
        source_index = self._proxy_model.mapToSource(proxy_index)
        return self._source_model.path_info_at(source_index.row())


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "manifest.json"


def _status_for_path_kind(path_kind: str) -> str:
    if path_kind == "lfs":
        return STATUS_LFS
    if path_kind == "external":
        return STATUS_EXTERNAL
    return STATUS_LOCAL


def _normalize_filter_value(value: str) -> str:
    value = value.strip()
    if value == ALL_FILTER_TEXT:
        return ""
    return value


def _entry_search_text(entry: Mf4DatasetEntry) -> str:
    parts = [
        entry.id,
        entry.path,
        entry.vehicle,
        entry.platform,
        entry.scenario,
        entry.path_kind,
        *entry.sets,
        *entry.issue_tags,
    ]
    return " ".join(part for part in parts if part).casefold()


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"

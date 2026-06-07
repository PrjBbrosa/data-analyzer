"""A2L measurement left pane.

Spec §Left Pane Width target: 280 px; fixed search box, filters,
selected-signal list, raster dropdown, and footer with selected count
and estimated bandwidth.

Stage 4 consumes the existing search/filter helpers:

- ``mf4_analyzer.acquisition_capture.search.search_measurements`` returns
  ``SearchHit`` objects with pre-computed ``match_spans``. The pane
  renders the match highlights from those spans — **never** re-runs
  substring matching on the UI side.
- ``mf4_analyzer.acquisition_capture.a2l_events.build_event_intersection``
  drives the batch-raster dropdown.

A2L parsing and DAQ-event extraction live in the capture core; the
pane stays Qt-only and consumes pre-computed measurement summaries.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.a2l_events import build_event_intersection
from mf4_analyzer.acquisition_capture.config_store import (
    load_or_default,
    toggle_favorite,
)
from mf4_analyzer.acquisition_capture.preflight_estimates import (
    estimate_can_bus_load,
)
from mf4_analyzer.acquisition_capture.search import (
    SearchHit,
    search_measurements,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome


# Blue match-highlight color — used to inline-decorate spans in the list
# row. Project palette interaction blue.
_MATCH_BLUE = QColor("#1769E0")
_SELECTED_ROW_BG = QColor("#EAF2FF")


class _BatchBar(QFrame):
    """Small batch-action strip shown when selected rows share an event."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("leftBatchBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        self._label = QLabel(self)
        layout.addWidget(self._label)
        layout.addStretch(1)

    def setText(self, text: str) -> None:
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()


class LeftPane(QFrame):
    """A2L measurement search/filter/select pane.

    Public API:

    - :meth:`set_pool` — supply the full ``MeasurementSummary`` set.
    - :meth:`set_a2l_has_daq_events` — drive the ``有 DAQ`` chip
      fallback per spec §Left Pane.
    - :meth:`current_selection` — list of ``SelectedMeasurement`` for
      the toolbar/right-pane preview.
    - :meth:`set_frozen` — freeze A2L/raster controls during recording.
    - ``selection_changed`` Qt signal — fires after every selection
      mutation so the right pane can recompute preflight estimates.
    """

    selection_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("leftPane")
        self.setFixedWidth(280)
        self._pool: tuple[MeasurementSummary, ...] = ()
        self._selected_names: set[str] = set()
        self._favorite_names: set[str] = set()
        self._config_path: Path | None = None
        self._a2l_has_daq_events: bool = False
        self._frozen: bool = False
        self._visible_count: int = 0
        self._build_ui()

    # ------------------------------------------------------------------
    # UI scaffolding
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        self._header = QLabel("A2L Measurement", self)
        self._header.setObjectName("paneHeader")
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        self._summary = QLabel(self)
        self._summary.setObjectName("leftPaneSummary")
        header_row.addWidget(self._summary)
        outer.addLayout(header_row)

        self._search = QLineEdit(self)
        self._search.setObjectName("channelSearch")
        self._search.setPlaceholderText("搜索 name / 0x40A...")
        self._search.textChanged.connect(self._on_search_text_changed)
        outer.addWidget(self._search)

        filter_rows = QVBoxLayout()
        filter_rows.setContentsMargins(0, 0, 0, 0)
        filter_rows.setSpacing(4)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self._only_selected_chip = self._make_filter_chip("只看已选")
        self._only_selected_chip.toggled.connect(self._refresh_list)
        filter_row.addWidget(self._only_selected_chip)

        self._has_daq_chip = self._make_filter_chip("有 DAQ")
        self._has_daq_chip.setChecked(True)  # spec: default on.
        self._has_daq_chip.toggled.connect(self._refresh_list)
        filter_row.addWidget(self._has_daq_chip)
        recent_chip = self._make_filter_chip("最近")
        recent_chip.setEnabled(False)
        recent_chip.setToolTip("此筛选将在后续版本启用")
        filter_row.addWidget(recent_chip)
        filter_row.addStretch(1)
        filter_rows.addLayout(filter_row)

        filter_row_2 = QHBoxLayout()
        filter_row_2.setSpacing(4)
        for label in ("收藏", "组: All", "类型"):
            chip = self._make_filter_chip(label)
            chip.setEnabled(False)
            chip.setToolTip("此筛选将在后续版本启用")
            filter_row_2.addWidget(chip)
        filter_row_2.addStretch(1)
        filter_rows.addLayout(filter_row_2)
        outer.addLayout(filter_rows)

        self._batch_bar = _BatchBar(self)
        self._batch_bar.setVisible(False)
        outer.addWidget(self._batch_bar)

        self._list = QListWidget(self)
        self._list.setObjectName("measurementList")
        self._list.setSelectionMode(QAbstractItemView.NoSelection)
        self._list.setUniformItemSizes(True)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(
            self._on_context_menu_requested
        )
        self._list.itemChanged.connect(self._on_item_changed)
        outer.addWidget(self._list, stretch=1)

        self._footer = QLabel(self)
        self._footer.setObjectName("paneCount")
        self._footer.setWordWrap(True)
        outer.addWidget(self._footer)

        self._refresh_list()
        self._refresh_footer()

    @staticmethod
    def _make_filter_chip(text: str) -> QToolButton:
        chip = QToolButton()
        chip.setObjectName("filterChip")
        chip.setText(text)
        chip.setCheckable(True)
        chip.setToolButtonStyle(Qt.ToolButtonTextOnly)
        chip.setFocusPolicy(Qt.NoFocus)
        chip.setFixedHeight(22)
        chip.setMinimumWidth(52 if len(text) <= 3 else 68)
        return chip

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_pool(
        self,
        pool: Iterable[MeasurementSummary],
        *,
        a2l_has_daq_events: bool = False,
    ) -> None:
        """Replace the available measurement pool."""
        self._pool = tuple(pool)
        self.set_a2l_has_daq_events(a2l_has_daq_events)
        # Drop selections that fell outside the new pool.
        pool_names = {m.name for m in self._pool}
        self._selected_names = {n for n in self._selected_names if n in pool_names}
        self._refresh_list()
        self._refresh_footer()
        self.selection_changed.emit()

    def set_config_path(self, path: Path | str | None) -> None:
        """Set the ``acquisition_config.yaml`` path used by favorites."""
        self._config_path = Path(path) if path is not None else None
        self._favorite_names.clear()
        if self._config_path is not None and self._config_path.exists():
            store = load_or_default(
                project_root=self._config_path.parent,
                cli_config_path=self._config_path,
            )
            self._favorite_names = {
                str(item.get("name"))
                for item in store.favorites
                if item.get("name")
            }

    def set_a2l_has_daq_events(self, has_events: bool) -> None:
        """Spec §Left Pane fallback: ``有 DAQ`` chip flips off + disabled
        when the A2L has no DAQ events."""
        self._a2l_has_daq_events = bool(has_events)
        if not has_events:
            self._has_daq_chip.setChecked(False)
            self._has_daq_chip.setEnabled(False)
            self._has_daq_chip.setToolTip("该 A2L 不含 DAQ_EVENT 信息")
        else:
            self._has_daq_chip.setEnabled(not self._frozen)
            self._has_daq_chip.setToolTip("")

    def set_frozen(self, frozen: bool) -> None:
        """Recording state: A2L/raster controls become read-only."""
        self._frozen = bool(frozen)
        # Search stays interactive — the user can still browse names
        # — but the checkboxes themselves block selection changes via
        # ``_on_item_changed``.
        self._has_daq_chip.setEnabled(self._a2l_has_daq_events and not self._frozen)
        self._only_selected_chip.setEnabled(not self._frozen)

    def current_selection(self) -> list[SelectedMeasurement]:
        """Return the selected measurements as ``SelectedMeasurement``."""
        by_name = {m.name: m for m in self._pool}
        out: list[SelectedMeasurement] = []
        for name in sorted(self._selected_names):
            m = by_name.get(name)
            if m is None:
                continue
            event = m.available_events[0] if m.available_events else None
            out.append(
                SelectedMeasurement(
                    name=m.name,
                    unit=m.unit,
                    event=event,
                )
            )
        return out

    def common_events(self) -> set[str]:
        """Spec §Search And Filter Contract ``build_event_intersection``."""
        by_name = {m.name: m for m in self._pool}
        chosen = [by_name[n] for n in self._selected_names if n in by_name]
        return build_event_intersection(chosen)

    def _build_context_menu(
        self,
        measurements: Sequence[MeasurementSummary],
    ) -> QMenu:
        """Build the spec right-click menu for tests and the live widget."""
        menu = apply_rounded_menu_chrome(QMenu(self))
        if not measurements:
            return menu
        if len(measurements) == 1:
            m = measurements[0]
            fav_text = "取消收藏" if m.name in self._favorite_names else "⭐ 收藏"
            fav_action = menu.addAction(fav_text)
            fav_action.triggered.connect(
                lambda _checked=False, measurement=m: self._toggle_favorite(
                    measurement
                )
            )
            copy_name = menu.addAction("复制名字")
            copy_name.triggered.connect(
                lambda _checked=False, name=m.name: QApplication.clipboard().setText(
                    name
                )
            )
            copy_address = menu.addAction("复制地址")
            copy_address.triggered.connect(
                lambda _checked=False, address=m.address: QApplication.clipboard().setText(
                    f"0x{int(address):08X}"
                )
            )
            jump = menu.addAction("跳到 A2L 源行")
            jump.setEnabled(False)
            return menu

        raster_action = menu.addAction("批量设 raster ...")
        raster_action.setEnabled(bool(build_event_intersection(measurements)))
        copy_list = menu.addAction("复制为列表")
        copy_list.triggered.connect(
            lambda _checked=False, rows=tuple(measurements): self._copy_measurement_list(
                rows
            )
        )
        clear = menu.addAction("取消选择")
        clear.triggered.connect(self._clear_context_selection)
        return menu

    # ------------------------------------------------------------------
    # Refresh / filter pipeline
    # ------------------------------------------------------------------

    def _filtered_pool(self) -> list[MeasurementSummary]:
        out: list[MeasurementSummary] = []
        for m in self._pool:
            if self._has_daq_chip.isChecked() and not m.available_events:
                continue
            if self._only_selected_chip.isChecked() and m.name not in self._selected_names:
                continue
            out.append(m)
        return out

    def _measurement_by_name(self, name: str) -> MeasurementSummary | None:
        for measurement in self._pool:
            if measurement.name == name:
                return measurement
        return None

    def _measurements_by_names(
        self,
        names: Iterable[str],
    ) -> list[MeasurementSummary]:
        by_name = {m.name: m for m in self._pool}
        return [by_name[name] for name in names if name in by_name]

    def _hits_for_query(
        self, pool: Sequence[MeasurementSummary]
    ) -> tuple[list[SearchHit], bool]:
        """Return ``(hits, used_search)`` for the current query."""
        q = self._search.text().strip()
        if not q:
            return ([], False)
        hits = search_measurements(q, pool)
        return (hits, True)

    def _refresh_list(self) -> None:
        # Block ``itemChanged`` while we rebuild — checkbox creation
        # would otherwise fire selection_changed for every row.
        self._list.blockSignals(True)
        self._list.clear()
        pool = self._filtered_pool()
        hits, used_search = self._hits_for_query(pool)
        rows: list[tuple[MeasurementSummary, list[tuple[int, int]]]]
        if used_search:
            rows = [(hit.measurement, hit.match_spans) for hit in hits]
        else:
            rows = [(m, []) for m in pool]
        self._visible_count = len(rows)
        for measurement, match_spans in rows:
            item = self._build_row(measurement, match_spans)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._refresh_summary()
        self._refresh_footer()

    def _build_row(
        self,
        m: MeasurementSummary,
        match_spans: list[tuple[int, int]],
    ) -> QListWidgetItem:
        parts = [m.name]
        if m.unit:
            parts.append(m.unit)
        if m.available_events:
            parts.append(f"@ {_format_event_label(m.available_events[0])}")
        text = "  ·  ".join(parts)
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(
            Qt.Checked if m.name in self._selected_names else Qt.Unchecked
        )
        item.setData(Qt.UserRole, m.name)
        if m.name in self._selected_names:
            item.setBackground(QBrush(_SELECTED_ROW_BG))
        if match_spans:
            # Spec: highlight matched character ranges in blue. Qt
            # QListWidgetItem only exposes a single foreground brush,
            # so we use a tooltip that surfaces the spans textually
            # plus a brush color so the row visually pops. A future
            # QStyledItemDelegate could paint per-character runs.
            item.setForeground(QBrush(_MATCH_BLUE))
            spans_text = ", ".join(f"{s}:{e}" for s, e in match_spans)
            item.setToolTip(f"匹配: {spans_text}")
        return item

    def _refresh_summary(self) -> None:
        self._summary.setText(
            f"{len(self._pool)} · 显示 {self._visible_count} · 选 {len(self._selected_names)}"
        )

    def _refresh_footer(self) -> None:
        selected = self._selected_names
        self._refresh_batch_bar()
        if not selected:
            self._footer.setText("选 0 · CAN 估算 0.0%")
            return
        chosen = [m for m in self._pool if m.name in selected]
        load = estimate_can_bus_load(
            [
                SelectedMeasurement(
                    name=m.name,
                    unit=m.unit,
                    event=(m.available_events[0] if m.available_events else None),
                )
                for m in chosen
            ],
            thresholds.DEFAULT_CAN_BITRATE_BPS,
        )
        parts = [f"选 {len(selected)}", f"CAN 估算 {load:.1f}%"]
        event_counts = Counter(
            m.available_events[0] for m in chosen if m.available_events
        )
        if event_counts:
            distribution = " · ".join(
                f"{_format_event_label(event)} × {count}"
                for event, count in sorted(event_counts.items())
            )
            parts.append(f"事件 {distribution}")
        self._footer.setText(" · ".join(parts))

    def _refresh_batch_bar(self) -> None:
        if len(self._selected_names) < 2:
            self._batch_bar.setVisible(False)
            self._batch_bar.setText("")
            return
        common = sorted(self.common_events())
        if not common:
            self._batch_bar.setVisible(False)
            self._batch_bar.setText("")
            return
        first_event = common[0]
        self._batch_bar.setText(f"已选 {len(self._selected_names)} · 同 {first_event}")
        self._batch_bar.setVisible(True)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_search_text_changed(self, _text: str) -> None:
        self._refresh_list()

    def _on_context_menu_requested(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        clicked_name = item.data(Qt.UserRole)
        measurements: list[MeasurementSummary]
        if clicked_name in self._selected_names and len(self._selected_names) > 1:
            measurements = self._measurements_by_names(sorted(self._selected_names))
        else:
            measurement = self._measurement_by_name(clicked_name)
            measurements = [measurement] if measurement is not None else []
        if not measurements:
            return
        menu = self._build_context_menu(measurements)
        menu.exec_(self._list.mapToGlobal(pos))

    def _toggle_favorite(self, measurement: MeasurementSummary) -> None:
        address_hex = f"0x{int(measurement.address):08X}"
        if self._config_path is not None:
            store = toggle_favorite(
                measurement.name,
                config_path=self._config_path,
                address_hex=address_hex,
            )
        else:
            store = toggle_favorite(
                measurement.name,
                address_hex=address_hex,
            )
        self._favorite_names = {
            str(item.get("name"))
            for item in store.favorites
            if item.get("name")
        }

    @staticmethod
    def _copy_measurement_list(
        measurements: Sequence[MeasurementSummary],
    ) -> None:
        lines = [
            f"{m.name}\t{m.unit}\t0x{int(m.address):08X}"
            for m in measurements
        ]
        QApplication.clipboard().setText("\n".join(lines))

    def _clear_context_selection(self) -> None:
        if not self._selected_names:
            return
        self._selected_names.clear()
        self._refresh_list()
        self.selection_changed.emit()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._frozen:
            # Revert the checkbox; recording locks selection.
            name = item.data(Qt.UserRole)
            checked = name in self._selected_names
            self._list.blockSignals(True)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self._list.blockSignals(False)
            return
        name = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._selected_names.add(name)
        else:
            self._selected_names.discard(name)
        self._refresh_list()
        self.selection_changed.emit()


def _format_event_label(event_name: str) -> str:
    if event_name.startswith("event_"):
        return event_name[len("event_") :]
    return event_name

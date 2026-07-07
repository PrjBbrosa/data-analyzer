"""A2L measurement left pane.

Left-pane measurement picker with a wider A2L list, selected-signal
event controls, and footer estimates.

Stage 4 consumes the existing search/filter helpers:

- ``mf4_analyzer.acquisition_capture.search.search_measurements`` returns
  ``SearchHit`` objects with pre-computed ``match_spans``. The pane
  renders the match highlights from those spans — **never** re-runs
  substring matching on the UI side.
- ``mf4_analyzer.acquisition_capture.a2l_events.build_event_intersection``
  drives the batch sampling-event dropdown.

A2L parsing and DAQ-event extraction live in the capture core; the
pane stays Qt-only and consumes pre-computed measurement summaries.
"""

from __future__ import annotations

import html as _html
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
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
from mf4_analyzer.acquisition_capture.preflight_estimates import (
    estimate_can_bus_load,
)
from mf4_analyzer.acquisition_capture.search import (
    SearchHit,
    search_measurements,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome


_SELECTED_ROW_BG = QColor("#EAF2FF")
_EVENT_TIME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(us|ms|s)", re.IGNORECASE)
_MATCH_HIGHLIGHT_STYLE = "color:#1769E0;font-weight:600;"


def _highlight_name_html(name: str, spans: Sequence[tuple[int, int]]) -> str:
    if not spans:
        return name
    chunks: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        start = max(cursor, min(len(name), start))
        end = max(start, min(len(name), end))
        if start > cursor:
            chunks.append(_html.escape(name[cursor:start]))
        if end > start:
            chunks.append(
                f'<span style="{_MATCH_HIGHLIGHT_STYLE}">'
                f"{_html.escape(name[start:end])}</span>"
            )
        cursor = end
    if cursor < len(name):
        chunks.append(_html.escape(name[cursor:]))
    return "".join(chunks)


class _BatchBar(QFrame):
    """Batch event strip for selected measurements."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("leftBatchBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)
        self._label = QLabel(self)
        layout.addWidget(self._label)
        self.event_combo = QComboBox(self)
        self.event_combo.setObjectName("batchEventSelect")
        self.event_combo.setMinimumWidth(112)
        layout.addWidget(self.event_combo)

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
        self.setFixedWidth(420)
        self._pool: tuple[MeasurementSummary, ...] = ()
        self._selected_names: set[str] = set()
        self._selected_events: dict[str, str] = {}
        self._config_path: Path | None = None
        self._a2l_has_daq_events: bool = False
        self._frozen: bool = False
        self._visible_count: int = 0
        self._row_items: dict[str, QListWidgetItem] = {}
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
        filter_row.addStretch(1)
        filter_rows.addLayout(filter_row)
        outer.addLayout(filter_rows)

        self._batch_bar = _BatchBar(self)
        self._batch_bar.event_combo.currentIndexChanged.connect(
            self._on_batch_event_changed
        )
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
        self._selected_events = {
            name: event
            for name, event in self._selected_events.items()
            if name in self._selected_names
            and self._measurement_supports_event_name(name, event)
        }
        for name in self._selected_names:
            measurement = self._measurement_by_name(name)
            if measurement is not None and name not in self._selected_events:
                event = self._default_event_for(measurement)
                if event is not None:
                    self._selected_events[name] = event
        self._refresh_list()
        self._refresh_footer()
        self.selection_changed.emit()

    def set_config_path(self, path: Path | str | None) -> None:
        """Set the ``acquisition_config.yaml`` path.

        Favorites are currently hidden in the cockpit UI, but the path
        is retained so settings hydration remains stable.
        """
        self._config_path = Path(path) if path is not None else None

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
        for name in list(self._row_items):
            self._update_row_for(name)
        self._refresh_batch_bar()

    def current_selection(self) -> list[SelectedMeasurement]:
        """Return the selected measurements as ``SelectedMeasurement``."""
        by_name = {m.name: m for m in self._pool}
        out: list[SelectedMeasurement] = []
        for name in sorted(self._selected_names):
            m = by_name.get(name)
            if m is None:
                continue
            event = self._selected_event_for(m)
            out.append(
                SelectedMeasurement(
                    name=m.name,
                    unit=m.unit,
                    event=event,
                    event_rate_hz=_event_rate_hz(event),
                    address_hex=f"0x{int(m.address):08X}",
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
        scroll_bar = self._list.verticalScrollBar()
        scroll_value = scroll_bar.value()
        old_blocked = self._list.blockSignals(True)
        self._list.clear()
        self._row_items = {}
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
            self._row_items[measurement.name] = item
            self._list.setItemWidget(
                item,
                self._build_row_widget(measurement, match_spans),
            )
        self._list.blockSignals(old_blocked)
        scroll_bar.setValue(min(scroll_value, scroll_bar.maximum()))
        self._refresh_summary()
        self._refresh_footer()

    def _row_text_for(self, m: MeasurementSummary) -> str:
        parts = [m.name]
        if m.unit:
            parts.append(m.unit)
        event = self._selected_event_for(m)
        if event is not None:
            parts.append(f"@ {_format_event_label(event)}")
        return "  ·  ".join(parts)

    def _build_row(
        self,
        m: MeasurementSummary,
        match_spans: list[tuple[int, int]],
    ) -> QListWidgetItem:
        item = QListWidgetItem("")
        item.setData(Qt.UserRole, m.name)
        item.setData(Qt.UserRole + 1, self._row_text_for(m))
        item.setSizeHint(QSize(0, 46))
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if m.name in self._selected_names else Qt.Unchecked)
        if m.name in self._selected_names:
            item.setBackground(QBrush(_SELECTED_ROW_BG))
        return item

    def _update_row_for(self, name: str) -> None:
        item = self._row_items.get(name)
        measurement = self._measurement_by_name(name)
        if item is None or measurement is None:
            return
        selected = name in self._selected_names
        old_list_blocked = self._list.blockSignals(True)
        item.setData(Qt.UserRole + 1, self._row_text_for(measurement))
        item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
        item.setBackground(QBrush(_SELECTED_ROW_BG) if selected else QBrush())
        self._list.blockSignals(old_list_blocked)

        row = self._list.itemWidget(item)
        if row is None:
            return
        checkbox = row.findChild(QCheckBox, "measurementCheckBox")
        if checkbox is not None:
            old_checkbox_blocked = checkbox.blockSignals(True)
            checkbox.setChecked(selected)
            checkbox.setEnabled(not self._frozen)
            checkbox.blockSignals(old_checkbox_blocked)
        combo = row.findChild(QComboBox, "measurementEventSelect")
        if combo is not None:
            old_combo_blocked = combo.blockSignals(True)
            current_event = self._selected_event_for(measurement)
            idx = combo.findData(current_event) if current_event is not None else -1
            combo.setCurrentIndex(idx)
            combo.setEnabled(bool(measurement.available_events) and not self._frozen)
            combo.blockSignals(old_combo_blocked)

    def _build_row_widget(
        self,
        m: MeasurementSummary,
        match_spans: Sequence[tuple[int, int]] = (),
    ) -> QWidget:
        row = QFrame(self._list)
        row.setObjectName("measurementRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(8)

        checkbox = QCheckBox(row)
        checkbox.setObjectName("measurementCheckBox")
        checkbox.setChecked(m.name in self._selected_names)
        checkbox.setEnabled(not self._frozen)
        checkbox.stateChanged.connect(
            lambda state, name=m.name: self._set_measurement_selected(
                name,
                state == Qt.Checked,
            )
        )
        layout.addWidget(checkbox, 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(1)
        name_label = QLabel(_highlight_name_html(m.name, match_spans), row)
        name_label.setObjectName("measurementName")
        name_label.setTextFormat(Qt.RichText if match_spans else Qt.PlainText)
        name_label.setToolTip(m.name)
        name_label.setMinimumWidth(0)
        detail_parts: list[str] = []
        if m.unit:
            detail_parts.append(m.unit)
        datatype = getattr(m, "datatype", "")
        if datatype:
            detail_parts.append(str(datatype))
        address = getattr(m, "address", None)
        if address is not None:
            detail_parts.append(f"0x{int(address):08X}")
        detail_label = QLabel(" · ".join(detail_parts), row)
        detail_label.setObjectName("measurementDetail")
        detail_label.setToolTip(detail_label.text())
        detail_label.setMinimumWidth(0)
        text_box.addWidget(name_label)
        text_box.addWidget(detail_label)
        layout.addLayout(text_box, stretch=1)

        at_label = QLabel("@", row)
        at_label.setObjectName("measurementEventPrefix")
        layout.addWidget(at_label, 0, Qt.AlignVCenter)

        combo = QComboBox(row)
        combo.setObjectName("measurementEventSelect")
        combo.setProperty("measurementName", m.name)
        combo.setMinimumWidth(84)
        combo.setEnabled(bool(m.available_events) and not self._frozen)
        for event_name in m.available_events:
            combo.addItem(_format_event_label(event_name), event_name)
        current_event = self._selected_event_for(m)
        if current_event is not None:
            idx = combo.findData(current_event)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda _idx, name=m.name, widget=combo: self._on_row_event_changed(
                name,
                widget.currentData(),
            )
        )
        layout.addWidget(combo, 0, Qt.AlignVCenter)
        return row

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
                    event=self._selected_event_for(m),
                    event_rate_hz=_event_rate_hz(self._selected_event_for(m)),
                )
                for m in chosen
            ],
            thresholds.DEFAULT_CAN_BITRATE_BPS,
        )
        parts = [f"选 {len(selected)}", f"CAN 估算 {load:.1f}%"]
        event_counts = Counter(
            event
            for m in chosen
            for event in (self._selected_event_for(m),)
            if event is not None
        )
        if event_counts:
            distribution = " · ".join(
                f"{_format_event_label(event)} × {count}"
                for event, count in sorted(
                    event_counts.items(),
                    key=lambda item: _event_sort_key(item[0]),
                )
            )
            parts.append(f"事件 {distribution}")
        self._footer.setText(" · ".join(parts))

    def _refresh_batch_bar(self) -> None:
        if not self._selected_names:
            self._batch_bar.setVisible(False)
            self._batch_bar.setText("")
            return
        chosen = self._measurements_by_names(sorted(self._selected_names))
        common = _ordered_common_events(chosen)
        combo = self._batch_bar.event_combo
        old = combo.blockSignals(True)
        combo.clear()
        selected_events = {
            event
            for m in chosen
            for event in (self._selected_event_for(m),)
            if event is not None
        }
        mixed = len(selected_events) > 1
        if mixed:
            combo.addItem("混合", None)
        for event in common:
            combo.addItem(_format_event_label(event), event)
        if not common:
            combo.addItem("无共同事件", None)
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
            combo.setToolTip("选中信号没有共同的 DAQ event")
            combo.blockSignals(old)
            self._batch_bar.setText(f"选 {len(self._selected_names)}")
            self._batch_bar.setVisible(True)
            return
        if mixed:
            combo.setCurrentIndex(0)
        else:
            event = next(iter(selected_events), common[0])
            idx = combo.findData(event)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.setEnabled(not self._frozen)
        combo.setToolTip("")
        combo.blockSignals(old)
        self._batch_bar.setText(f"选 {len(self._selected_names)}")
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
        self._selected_events.clear()
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
            self._update_row_for(name)
            return
        name = item.data(Qt.UserRole)
        self._set_measurement_selected(name, item.checkState() == Qt.Checked)

    def _set_measurement_selected(self, name: str, selected: bool) -> None:
        if self._frozen:
            self._update_row_for(name)
            return
        before = set(self._selected_names)
        if selected:
            self._selected_names.add(name)
            measurement = self._measurement_by_name(name)
            if measurement is not None and name not in self._selected_events:
                event = self._default_event_for(measurement)
                if event is not None:
                    self._selected_events[name] = event
        else:
            self._selected_names.discard(name)
            self._selected_events.pop(name, None)
        if before == self._selected_names:
            return
        if self._only_selected_chip.isChecked():
            self._refresh_list()
        else:
            self._update_row_for(name)
            self._refresh_summary()
            self._refresh_footer()
        self.selection_changed.emit()

    def _on_row_event_changed(self, name: str, event: object) -> None:
        if not isinstance(event, str):
            return
        self._set_measurement_event(name, event, select=True)

    def _on_batch_event_changed(self, _index: int) -> None:
        event = self._batch_bar.event_combo.currentData()
        if not isinstance(event, str):
            return
        if self._frozen:
            for name in list(self._selected_names):
                self._update_row_for(name)
            self._refresh_footer()
            return
        changed = False
        for name in list(self._selected_names):
            if self._measurement_supports_event_name(name, event):
                if self._selected_events.get(name) != event:
                    self._selected_events[name] = event
                    changed = True
        if changed:
            for name in list(self._selected_names):
                self._update_row_for(name)
            self._refresh_footer()
            self.selection_changed.emit()

    def _set_measurement_event(
        self,
        name: str,
        event: str,
        *,
        select: bool,
    ) -> None:
        if self._frozen:
            self._update_row_for(name)
            return
        measurement = self._measurement_by_name(name)
        if measurement is None or event not in measurement.available_events:
            return
        selected_changed = False
        if select and name not in self._selected_names:
            self._selected_names.add(name)
            selected_changed = True
        event_changed = self._selected_events.get(name) != event
        if event_changed:
            self._selected_events[name] = event
        if selected_changed or event_changed:
            self._update_row_for(name)
            self._refresh_summary()
            self._refresh_footer()
            self.selection_changed.emit()

    def _default_event_for(self, measurement: MeasurementSummary) -> str | None:
        return measurement.available_events[0] if measurement.available_events else None

    def _selected_event_for(self, measurement: MeasurementSummary) -> str | None:
        event = self._selected_events.get(measurement.name)
        if event in measurement.available_events:
            return event
        return self._default_event_for(measurement)

    def _measurement_supports_event_name(self, name: str, event: str) -> bool:
        measurement = self._measurement_by_name(name)
        return measurement is not None and event in measurement.available_events


def _format_event_label(event_name: str) -> str:
    if event_name.startswith("event_"):
        event_name = event_name[len("event_") :]
    matches = list(_EVENT_TIME_RE.finditer(event_name))
    if matches:
        match = matches[-1]
        return f"{match.group(1)}{match.group(2).lower()}"
    return event_name


def _event_rate_hz(event_name: str | None) -> float:
    if event_name is None:
        return 100.0
    label = _format_event_label(event_name)
    match = _EVENT_TIME_RE.fullmatch(label)
    if match is None:
        return 100.0
    value = float(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        return 100.0
    if unit == "us":
        return 1_000_000.0 / value
    if unit == "ms":
        return 1_000.0 / value
    return 1.0 / value


def _event_sort_key(event_name: str) -> tuple[float, str]:
    return (-_event_rate_hz(event_name), _format_event_label(event_name))


def _ordered_common_events(
    measurements: Sequence[MeasurementSummary],
) -> list[str]:
    common = build_event_intersection(measurements)
    if not common:
        return []
    first = measurements[0] if measurements else None
    ordered = [
        event
        for event in (first.available_events if first is not None else ())
        if event in common
    ]
    remaining = sorted(common.difference(ordered), key=_event_sort_key)
    return ordered + remaining

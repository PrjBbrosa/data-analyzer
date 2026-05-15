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

from collections.abc import Iterable, Sequence

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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


# Blue match-highlight color — used to inline-decorate spans in the list
# row. Project palette interaction blue.
_MATCH_BLUE = QColor("#1769E0")


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
        self._a2l_has_daq_events: bool = False
        self._frozen: bool = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI scaffolding
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        header = QLabel("A2L 测量")
        header.setObjectName("paneHeader")
        outer.addWidget(header)

        self._search = QLineEdit(self)
        self._search.setObjectName("channelSearch")
        self._search.setPlaceholderText("搜索测量 / 单位 / 0x地址")
        self._search.textChanged.connect(self._on_search_text_changed)
        outer.addWidget(self._search)

        # Filter row: 有 DAQ + 只看已选. Other filters declared in spec
        # (`最近`, `收藏`, `组`, `类型`) are reserved for v2 — render
        # the two MVP-relevant ones explicitly.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._has_daq_chip = QCheckBox("有 DAQ", self)
        self._has_daq_chip.setChecked(True)  # spec: default on.
        self._has_daq_chip.toggled.connect(self._refresh_list)
        filter_row.addWidget(self._has_daq_chip)

        self._only_selected_chip = QCheckBox("只看已选", self)
        self._only_selected_chip.toggled.connect(self._refresh_list)
        filter_row.addWidget(self._only_selected_chip)
        filter_row.addStretch(1)
        outer.addLayout(filter_row)

        self._list = QListWidget(self)
        self._list.setObjectName("measurementList")
        self._list.setSelectionMode(QAbstractItemView.NoSelection)
        self._list.setUniformItemSizes(True)
        self._list.itemChanged.connect(self._on_item_changed)
        outer.addWidget(self._list, stretch=1)

        self._footer = QLabel(self)
        self._footer.setObjectName("paneCount")
        self._footer.setWordWrap(True)
        outer.addWidget(self._footer)

        self._refresh_list()
        self._refresh_footer()

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
        if used_search:
            for hit in hits:
                item = self._build_row(hit.measurement, hit.match_spans)
                self._list.addItem(item)
        else:
            for m in pool:
                item = self._build_row(m, [])
                self._list.addItem(item)
        self._list.blockSignals(False)
        self._refresh_footer()

    def _build_row(
        self,
        m: MeasurementSummary,
        match_spans: list[tuple[int, int]],
    ) -> QListWidgetItem:
        text = m.name
        if m.unit:
            text += f"  ·  {m.unit}"
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(
            Qt.Checked if m.name in self._selected_names else Qt.Unchecked
        )
        item.setData(Qt.UserRole, m.name)
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

    def _refresh_footer(self) -> None:
        selected = self._selected_names
        if not selected:
            self._footer.setText(f"共 {len(self._pool)} 个测量 · 0 已选")
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
        self._footer.setText(
            f"共 {len(self._pool)} 个测量 · {len(selected)} 已选 · "
            f"CAN 估算 {load:.1f}%"
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_search_text_changed(self, _text: str) -> None:
        self._refresh_list()

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
        self._refresh_footer()
        self.selection_changed.emit()

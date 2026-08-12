"""Input column for the batch dialog.

Two widgets:

* ``FileListWidget`` — manages the file list rows with a four-state machine
  (``loaded`` / ``path_pending`` / ``probing`` / ``probe_failed``) per
  spec §3.2. Disk-add delegates the registry probe via ``QThreadPool``;
  tests inject ``w._probe_signals_for = ...`` to make probing synchronous,
  so the production code calls ``self._probe_signals_for(path)`` (not a
  free function). No ``thread.wait()`` is used (per
  ``pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md``).

* ``InputPanel`` — composes the file list + signal picker + RPM channel and
  coefficient fields + time-range field. Re-emits a single ``changed`` signal whenever
  any sub-control mutates.
"""
from __future__ import annotations
from functools import partial
from ....ui_kit.qt_lifecycle import as_weak_callable

import math
import os
from typing import Iterable

from PyQt5.QtCore import (
    QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, pyqtSignal,
)
from PyQt5.QtWidgets import (
    QAbstractScrollArea, QAbstractSpinBox, QAction, QComboBox, QFileDialog,
    QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ....io.source_adapters import (
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
    SourceDescriptor,
    canonical_source_path,
    stable_source_id,
)
from ....list_text import split_list_text
from ....ui_kit.menus import apply_rounded_menu_chrome
from ....ui_kit.widgets.segmented_choice import SegmentedChoice
from ...widgets.compact_spinbox import CompactDoubleSpinBox
from .filter_panel import BatchFilterPanel
from .frf_pair_editor import FrfPairEditor
from .signal_picker import SignalPickerPopup


# Methods whose backend dispatch consumes RPM. Drives InputPanel.set_method
# row visibility — fft / fft_time skip the row entirely.
_RPM_USING_METHODS = frozenset({"order_time"})


# The first-level file manager is deliberately a fixed viewport.  File-count
# changes must not move the target/preprocess controls below it; long source
# lists scroll inside this surface and hand their wheel events to the parent
# pane once they reach either boundary.
BATCH_INLINE_FILE_MANAGER_HEIGHT = 250


# State machine values (spec §3.2). Run-time-only states (`loading`,
# `load_failed`) are NOT managed here — they belong to the runner thread
# in W6.
STATE_LOADED = "loaded"
STATE_PATH_PENDING = "path_pending"
STATE_PROBING = "probing"
STATE_PROBE_FAILED = "probe_failed"
STATE_UNAVAILABLE = "unavailable"


class _TargetStack(QStackedWidget):
    """Elastic target field whose current page may contain wide labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self._refresh_current_page_geometry)

    def _refresh_current_page_geometry(self, _index: int) -> None:
        """Let the owning form remeasure after switching signal/FRF pages."""

        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()

    def sizeHint(self):  # noqa: N802 (Qt API)
        hint = super().sizeHint()
        current = self.currentWidget()
        if current is None:
            return hint
        # QStackedWidget normally takes the tallest page's hint.  That leaves
        # the FRF pair editor's full height beneath the one-line target-signal
        # picker in every non-FRF method.
        return QSize(hint.width(), current.sizeHint().height())

    def minimumSizeHint(self):  # noqa: N802 (Qt API)
        current = self.currentWidget()
        height = current.minimumSizeHint().height() if current is not None else 0
        return QSize(0, height)


# ---------------------------------------------------------------------------
# Background probe worker
# ---------------------------------------------------------------------------
class _ProbeSignals(QObject):
    """Signal carrier for ``_ProbeRunnable``; lives on the UI thread."""

    finished = pyqtSignal(str, object)   # (path, descriptors_or_legacy_channels)
    failed = pyqtSignal(str, str)        # (path, error_msg)


class _ProbeRunnable(QRunnable):
    """Probe logical source descriptors on a thread-pool worker."""

    def __init__(self, path: str, probe_fn) -> None:
        super().__init__()
        self._path = path
        self._probe_fn = probe_fn
        self.signals = _ProbeSignals()

    def run(self) -> None:  # noqa: D401 (Qt naming)
        try:
            result = self._probe_fn(self._path)
        except Exception as exc:  # broad on purpose: convert to UI state
            msg = f"{type(exc).__name__}: {exc}"
            self.signals.failed.emit(self._path, msg)
            return
        self.signals.finished.emit(self._path, result)


def _default_probe_signals_for(
    path: str, *, source_registry=None, source_context: dict | None = None,
) -> frozenset:
    """Return the union of channels exposed by the shared source registry.

    This compatibility symbol is imported by an older MF4 regression test.
    It deliberately delegates format detection and probing to the registry so
    the batch UI has no second MDF-specific probe implementation.
    """
    registry = source_registry or DEFAULT_SOURCE_ADAPTER_REGISTRY
    descriptors = registry.probe_sources(path, context=source_context)
    return frozenset(
        str(name)
        for descriptor in descriptors
        for name in descriptor.channel_names
    )


# ---------------------------------------------------------------------------
# File list widget
# ---------------------------------------------------------------------------
class _FileRow:
    """Per-row state + cached channel set."""

    __slots__ = (
        "source_id", "path", "group_id", "display_name", "state", "fid",
        "channels", "units", "metadata", "availability", "probe_cost",
        "error", "label", "_item",
    )

    def __init__(
        self,
        path: str,
        state: str,
        fid: object | None,
        channels: frozenset,
        error: str = "",
        *,
        source_id: object | None = None,
        group_id: str = "root",
        display_name: str = "",
        units: dict | None = None,
        metadata: dict | None = None,
        availability: str = "ready",
        probe_cost: str = "",
    ) -> None:
        self.source_id = path if source_id is None else source_id
        self.path = path
        self.group_id = str(group_id or "root")
        self.display_name = str(display_name or "")
        self.state = state
        self.fid = fid
        self.channels = channels
        self.units = dict(units or {})
        self.metadata = dict(metadata or {})
        self.availability = str(availability or "ready")
        self.probe_cost = str(probe_cost or "")
        self.error = error
        self.label = ""
        self._item: QListWidgetItem | None = None


class _StructuredFileRow(QWidget):
    """Compact inline row that exposes source state without a text wall."""

    _STATE_TEXT = {
        STATE_LOADED: "已就绪",
        STATE_PATH_PENDING: "等待解析",
        STATE_PROBING: "解析中",
        STATE_PROBE_FAILED: "解析失败",
        STATE_UNAVAILABLE: "不可用",
    }

    def __init__(self, owner: "FileListWidget", row: _FileRow) -> None:
        super().__init__(owner._list)
        self.setObjectName("BatchStructuredFileRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.setSpacing(8)

        dot = QLabel(self)
        dot.setObjectName("BatchFileStateDot")
        dot.setFixedSize(8, 8)
        dot.setProperty("ready", row.state == STATE_LOADED)
        dot.setProperty(
            "failed", row.state in {STATE_PROBE_FAILED, STATE_UNAVAILABLE},
        )
        lay.addWidget(dot)

        copy_host = QWidget(self)
        copy_host.setObjectName("BatchFileRowCopy")
        copy_host.setAttribute(Qt.WA_StyledBackground, True)
        copy_host.setAutoFillBackground(False)
        copy_lay = QVBoxLayout(copy_host)
        copy_lay.setContentsMargins(0, 0, 0, 0)
        copy_lay.setSpacing(1)
        name = QLabel(row.display_name or os.path.basename(row.path) or row.path, copy_host)
        name.setObjectName("BatchFileRowName")
        path = QLabel(os.path.dirname(row.path) or row.path, copy_host)
        path.setObjectName("BatchFileRowPath")
        copy_lay.addWidget(name)
        copy_lay.addWidget(path)
        lay.addWidget(copy_host, 1)

        state = QLabel(self._STATE_TEXT.get(row.state, row.state), self)
        state.setObjectName("BatchFileRowState")
        state.setProperty("ready", row.state == STATE_LOADED)
        state.setProperty(
            "failed", row.state in {STATE_PROBE_FAILED, STATE_UNAVAILABLE},
        )
        lay.addWidget(state)

        remove = QPushButton("×", self)
        remove.setObjectName("BatchFileRowRemove")
        remove.setFixedSize(28, 28)
        remove.setToolTip("移除数据源")
        remove.clicked.connect(partial(owner._remove_path_clicked, row.path))
        lay.addWidget(remove)


class _BoundaryForwardingListWidget(QListWidget):
    """Let the outer Input pane keep scrolling at this list's boundaries."""

    def viewportEvent(self, event) -> bool:  # noqa: N802 - Qt API
        # QAbstractScrollArea owns the viewport.  Route its real wheel events
        # through the boundary logic instead of depending on platform-specific
        # ignored-event bubbling from that child widget.
        if event.type() == QEvent.Wheel:
            self.wheelEvent(event)
            return event.isAccepted()
        return super().viewportEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y()
        at_top = bar.value() <= bar.minimum()
        at_bottom = bar.value() >= bar.maximum()
        if (delta > 0 and at_top) or (delta < 0 and at_bottom):
            outer = self._outer_scroll_area()
            if outer is not None and self._scroll_outer(outer, event):
                event.accept()
                return
            event.ignore()
            return
        super().wheelEvent(event)

    def _outer_scroll_area(self) -> QAbstractScrollArea | None:
        """Find the enclosing Batch pane without coupling to ``BatchSheet``."""

        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QAbstractScrollArea):
                if ancestor.verticalScrollBar().maximum() > ancestor.verticalScrollBar().minimum():
                    return ancestor
            ancestor = ancestor.parentWidget()
        return None

    @staticmethod
    def _scroll_outer(outer: QAbstractScrollArea, event) -> bool:
        """Consume a boundary wheel notch in the enclosing pane.

        Ignoring a wheel event alone does not reliably re-dispatch it from a
        QListWidget viewport to an ancestor QScrollArea on every Qt platform.
        Move the outer scrollbar explicitly, retaining ``ignore`` only for a
        non-scrollable ancestor.
        """

        bar = outer.verticalScrollBar()
        angle_delta = event.angleDelta().y()
        if angle_delta:
            # Qt's ordinary wheel action is three single-step lines per notch.
            step = -angle_delta / 120.0 * max(1, bar.singleStep()) * 3
        else:
            step = -event.pixelDelta().y()
        if not step:
            return False
        old_value = bar.value()
        bar.setValue(round(old_value + step))
        return bar.value() != old_value


class FileListWidget(QWidget):
    """List of files with explicit state machine + probe wiring."""

    filesChanged = pyqtSignal()
    intersectionChanged = pyqtSignal(frozenset)
    stateChanged = pyqtSignal(str, str)  # (path, state)

    def __init__(
        self,
        parent: QWidget | None = None,
        files: dict | None = None,
        *,
        source_registry=None,
        source_context: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("BatchInlineFileManagerBody")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._files_source = files or {}
        self._rows: dict[str, _FileRow] = {}
        self._last_intersection: frozenset = frozenset()
        self._source_registry = (
            source_registry or DEFAULT_SOURCE_ADAPTER_REGISTRY
        )
        self._source_context = dict(source_context or {})

        self._probe_signals_for = lambda path: self._source_registry.probe_sources(
            path, context=self._source_context,
        )
        self._pool = QThreadPool.globalInstance()
        # Optional BatchSheet hook: resolve BLF/DBC before add_disk_path.
        self._disk_paths_handler = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # First-level action row. Facts live in InputPanel's section header so
        # the two stable add actions never compete with status text.
        header = QHBoxLayout()
        header.setContentsMargins(9, 9, 9, 9)
        header.setSpacing(7)
        self._count_label = QLabel("文件 (0)")
        self._count_label.hide()
        self._btn_loaded = QPushButton("+ 已加载")
        self._btn_loaded.setObjectName("BatchFileAddLoaded")
        self._btn_loaded.clicked.connect(self._open_loaded_menu)
        header.addWidget(self._btn_loaded)
        self._btn_disk = QPushButton("+ 从磁盘…")
        self._btn_disk.setObjectName("BatchFileAddDisk")
        self._btn_disk.clicked.connect(self._open_disk_dialog)
        header.addWidget(self._btn_disk)
        header.addStretch(1)
        outer.addLayout(header)

        self._empty_label = QLabel(
            "还没有数据文件\n从已加载文件选择，或直接从磁盘添加。", self,
        )
        self._empty_label.setObjectName("BatchFileEmptyState")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self._empty_label, 1)

        self._list = _BoundaryForwardingListWidget(self)
        self._list.setObjectName("BatchFileList")
        self._list.setSpacing(0)
        self._list.setAutoFillBackground(False)
        self._list.viewport().setAutoFillBackground(False)
        self._list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._list.hide()
        self.setProperty("structuredRows", True)
        outer.addWidget(self._list, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_source_context(self, source_context: dict | None) -> None:
        """Replace probe/availability context (e.g. BLF ``dbc_paths``)."""
        self._source_context = dict(source_context or {})
        # Hold the probe helper weakly: a plain lambda here is a self-cycle
        # that outlives the C++ side under parentless pytest-qt teardown.
        self._probe_signals_for = as_weak_callable(self._probe_signals_with_context)

    def _probe_signals_with_context(self, path):
        return self._source_registry.probe_sources(
            path, context=self._source_context,
        )

    def set_disk_paths_handler(self, handler) -> None:
        """Optional ``handler(list[str])`` invoked instead of bare disk adds."""
        self._disk_paths_handler = handler

    def add_loaded_file(
        self, fid: object, path: str, channels: frozenset
    ) -> None:
        source_id = fid
        if source_id in self._rows:
            return
        fd = (self._files_source or {}).get(fid)
        units = getattr(fd, "channel_units", {}) if fd is not None else {}
        metadata = dict(
            getattr(fd, "source_metadata", {}) or {}
        ) if fd is not None else {}
        metadata["channel_metadata"] = dict(
            getattr(fd, "channel_metadata", {}) or {}
        ) if fd is not None else {}
        group_id = str((metadata or {}).get("group_id", "root"))
        row = _FileRow(
            path, STATE_LOADED, fid, frozenset(channels), source_id=source_id,
            group_id=group_id, display_name=os.path.basename(path) or str(path),
            units=units, metadata=metadata, availability="ready",
            probe_cost="loaded",
        )
        self._rows[source_id] = row
        self._render_row(row)
        self.stateChanged.emit(str(source_id), STATE_LOADED)
        self._after_change()

    def add_disk_path(self, path: str) -> None:
        canonical = canonical_source_path(path)
        if any(r.path == canonical for r in self._rows.values()):
            return
        try:
            adapter = self._source_registry.adapter_for(path)
            availability = self._source_registry.availability_for(
                path, context=self._source_context,
            )
        except Exception as exc:  # unsupported declarations are UI-visible
            adapter = None
            availability = type("Availability", (), {
                "status": "unavailable", "reason": str(exc), "is_ready": False,
            })()
        pending_id = (
            stable_source_id(adapter.key, canonical, "root")
            if adapter is not None else f"unavailable:{canonical}"
        )
        probe_cost = getattr(adapter, "probe_cost", "")
        state = STATE_PATH_PENDING if availability.is_ready else STATE_UNAVAILABLE
        row = _FileRow(
            canonical, state, None, frozenset(),
            error=str(availability.reason or ""), source_id=pending_id,
            display_name=os.path.basename(path) or path,
            availability=str(availability.status), probe_cost=probe_cost,
            metadata={"adapter_key": getattr(adapter, "key", "")},
        )
        self._rows[pending_id] = row
        self._render_row(row)
        self.stateChanged.emit(canonical, state)
        self._after_change()
        if not availability.is_ready:
            return
        # Schedule probe on the next event-loop tick so callers can
        # override `_probe_signals_for` between add_disk_path() and the
        # actual probe run (matches the test pattern).
        QTimer.singleShot(0, lambda p=canonical: self._start_probe(p))

    def _remove_path_clicked(self, path, _checked=False):
        self.remove_path(path)

    def remove_path(self, path: str) -> None:
        keys = [
            key for key, row in self._rows.items()
            if key == path or row.path == path
        ]
        if not keys:
            return
        for key in keys:
            row = self._rows.pop(key)
            item = row._item
            if item is not None:
                self._list.takeItem(self._list.row(item))
        self._after_change()

    def row_state(self, path: str) -> str:
        row = self._rows.get(path)
        if row is None:
            row = next((item for item in self._rows.values() if item.path == path), None)
        return row.state if row else ""

    def _set_row_state(self, path: str, state: str) -> None:
        """Test/internal hook: explicitly set a row's state."""
        row = self._rows.get(path)
        if row is None:
            row = next((item for item in self._rows.values() if item.path == path), None)
        if row is None:
            # Create a minimal row so tests can drive transitions on
            # paths that were never `add_*`'d (the test fixtures do this).
            row = _FileRow(path, state, None, frozenset(), source_id=path)
            self._rows[path] = row
            self._render_row(row)
        else:
            row.state = state
            self._render_row(row)
        self.stateChanged.emit(path, state)
        self._after_change()

    def loaded_file_ids(self) -> tuple:
        return tuple(
            r.fid for r in self._rows.values()
            if r.state == STATE_LOADED and r.fid is not None
        )

    def loaded_disk_paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            r.path for r in self._rows.values()
            if r.state == STATE_LOADED and r.fid is None
        ))

    def loaded_source_ids(self) -> tuple:
        return tuple(
            r.source_id for r in self._rows.values()
            if r.state == STATE_LOADED
        )

    def source_paths(self) -> tuple[str, ...]:
        return tuple(
            r.path for r in self._rows.values()
            if r.state == STATE_LOADED
        )

    def loaded_rows(self) -> tuple[_FileRow, ...]:
        return tuple(
            row for row in self._rows.values() if row.state == STATE_LOADED
        )

    def all_loaded_paths(self) -> tuple[str, ...]:
        return tuple(r.path for r in self._rows.values() if r.state == STATE_LOADED)

    def current_intersection(self) -> frozenset:
        loaded = list(self.loaded_rows())
        if not loaded:
            return frozenset()
        out = set(loaded[0].channels)
        for row in loaded[1:]:
            out &= row.channels
        return frozenset(out)

    def per_file_channel_sets(self) -> list[frozenset]:
        return [r.channels for r in self.loaded_rows()]

    def has_pending_probe(self) -> bool:
        return any(
            r.state in (STATE_PATH_PENDING, STATE_PROBING)
            for r in self._rows.values()
        )

    def has_probe_failed(self) -> bool:
        """True iff any row is currently in the ``probe_failed`` state.

        Used by ``BatchSheet._recompute_pipeline_status`` so the INPUT
        card surfaces a ``warn`` badge instead of ``ok`` when a probe has
        failed (ultrareview bug_005). Note: ``is_runnable`` deliberately
        does NOT consult this — the runner skips failed rows so a Run
        with a probe_failed row visible is still allowed.
        """
        return any(
            r.state == STATE_PROBE_FAILED for r in self._rows.values()
        )

    def unavailable_reasons(self) -> tuple[str, ...]:
        return tuple(
            row.error or "来源不可用"
            for row in self._rows.values()
            if row.state == STATE_UNAVAILABLE
        )

    # ------------------------------------------------------------------
    # Probe lifecycle
    # ------------------------------------------------------------------
    def _start_probe(self, path: str) -> None:
        row = next((item for item in self._rows.values() if item.path == path), None)
        if row is None:
            return
        if row.state != STATE_PATH_PENDING:
            return
        # Move into PROBING.
        row.state = STATE_PROBING
        self._render_row(row)
        self.stateChanged.emit(path, STATE_PROBING)
        self._after_change()

        runnable = _ProbeRunnable(path, self._probe_signals_for)
        runnable.signals.finished.connect(self._on_probe_finished)
        runnable.signals.failed.connect(self._on_probe_failed)
        self._pool.start(runnable)

    def _on_probe_finished(self, path: str, channels) -> None:
        row_key = next(
            (key for key, item in self._rows.items() if item.path == path), None,
        )
        row = self._rows.get(row_key) if row_key is not None else None
        if row is None:
            return
        result = channels if channels is not None else ()
        # Backward compatibility for injected tests and the public legacy MDF
        # helper: a frozenset/sequence of strings is one logical source.
        if isinstance(result, frozenset) or (
            isinstance(result, (tuple, list, set))
            and all(isinstance(item, str) for item in result)
        ):
            row.channels = frozenset(result)
            row.state = STATE_LOADED
            row.error = ""
            self._render_row(row)
            self.stateChanged.emit(path, STATE_LOADED)
            self._after_change()
            return

        try:
            descriptors = tuple(result)
        except TypeError:
            self._on_probe_failed(path, "bad probe result: expected source descriptors")
            return
        if not descriptors or not all(
            isinstance(descriptor, SourceDescriptor) for descriptor in descriptors
        ):
            self._on_probe_failed(path, "bad probe result: expected source descriptors")
            return

        # Replace the physical-path placeholder with every logical group.  The
        # rows are keyed by source_id, so duplicate physical paths remain valid.
        item = row._item
        if item is not None:
            self._list.takeItem(self._list.row(item))
        self._rows.pop(row_key, None)
        for descriptor in descriptors:
            metadata = dict(descriptor.metadata or {})
            source_row = _FileRow(
                str(descriptor.source_path), STATE_LOADED, None,
                frozenset(descriptor.channel_names), source_id=descriptor.source_id,
                group_id=descriptor.group_id, display_name=descriptor.display_name,
                units=dict(descriptor.units or {}), metadata=metadata,
                availability="ready",
                probe_cost=str(metadata.get("probe_cost", row.probe_cost) or ""),
            )
            self._rows[descriptor.source_id] = source_row
            self._render_row(source_row)
            self.stateChanged.emit(str(descriptor.source_id), STATE_LOADED)
        self._after_change()

    def _on_probe_failed(self, path: str, error: str) -> None:
        row = next((item for item in self._rows.values() if item.path == path), None)
        if row is None:
            return
        row.state = STATE_PROBE_FAILED
        row.error = error
        self._render_row(row)
        self.stateChanged.emit(path, STATE_PROBE_FAILED)
        self._after_change()

    # ------------------------------------------------------------------
    # Rendering / button handlers
    # ------------------------------------------------------------------
    def _badge_for(self, state: str) -> str:
        return {
            STATE_LOADED: "",
            STATE_PATH_PENDING: "  …",
            STATE_PROBING: "  …",
            STATE_PROBE_FAILED: "  ⚠",
            STATE_UNAVAILABLE: "  ⛔",
        }.get(state, "")

    def _render_row(self, row: _FileRow) -> None:
        name = row.display_name or os.path.basename(row.path) or row.path
        details: list[str] = []
        if row.group_id and row.group_id != "root" and row.group_id not in name:
            details.append(f"group:{row.group_id}")
        if row.probe_cost == "full":
            details.append("full probe")
        if row.state == STATE_UNAVAILABLE and row.error:
            details.append(row.error)
        suffix = f" · {' · '.join(details)}" if details else ""
        text = f"{name}{suffix}{self._badge_for(row.state)}"
        row.label = text
        if row._item is None:
            # The real row is a widget.  Keep the backing item text empty so
            # Qt never paints a second name underneath that widget, while
            # retaining the full label for assistive technology.
            item = QListWidgetItem("", self._list)
            item.setData(Qt.UserRole, row.source_id)
            item.setSizeHint(QSize(0, 46))
            row._item = item
        else:
            row._item.setText("")
        row._item.setData(Qt.AccessibleTextRole, text)
        tooltip = [row.path, f"source_id: {row.source_id}"]
        if row.group_id:
            tooltip.append(f"group: {row.group_id}")
        if row.availability:
            tooltip.append(f"availability: {row.availability}")
        if row.probe_cost:
            tooltip.append(f"probe cost: {row.probe_cost}")
        if row.error:
            tooltip.append(row.error)
        row._item.setToolTip("\n".join(tooltip))
        self._list.setItemWidget(row._item, _StructuredFileRow(self, row))

    def _after_change(self) -> None:
        self._count_label.setText(f"文件 ({len(self._rows)})")
        row_count = self._list.count()
        self._empty_label.setVisible(row_count == 0)
        self._list.setVisible(row_count > 0)
        self.filesChanged.emit()
        new_int = self.current_intersection()
        if new_int != self._last_intersection:
            self._last_intersection = new_int
            self.intersectionChanged.emit(new_int)

    def _open_loaded_menu(self) -> None:
        menu = apply_rounded_menu_chrome(QMenu(self))
        any_added = False
        for fid, fd in (self._files_source or {}).items():
            # FileData stores the basename in `.filename` already; fall back
            # to the synthetic fid only when fd is missing it (defensive —
            # in normal use FileData always populates filename).
            label = getattr(fd, "filename", None) or str(fid)
            act = QAction(str(label), menu)

            def _trigger(_checked=False, fid=fid, fd=fd):
                self._add_from_files_source(fid, fd)
            act.triggered.connect(_trigger)
            menu.addAction(act)
            any_added = True
        if not any_added:
            empty = QAction("(没有已加载文件)", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
        menu.exec_(self._btn_loaded.mapToGlobal(self._btn_loaded.rect().bottomLeft()))

    def _add_from_files_source(self, fid, fd) -> None:
        # FileData.filepath is a Path; coerce to str for the row key. Fall
        # back to fid only if fd has no filepath (defensive).
        fp = getattr(fd, "filepath", None)
        path = str(fp) if fp is not None else str(fid)
        if fid in self._rows:
            return
        # Channels: route through FileData.get_signal_channels() so the
        # time master is excluded (ultrareview bug_001). Fall back to an
        # empty set if anything is missing — the row still becomes 'loaded'
        # since the user explicitly imported it from the main window.
        try:
            channels = frozenset(fd.get_signal_channels())
        except Exception:  # noqa: BLE001
            channels = frozenset()
        self.add_loaded_file(fid, path, channels)

    def _open_disk_dialog(self) -> None:
        file_glob = self._source_registry.file_dialog_glob
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择数据文件", "", f"所有支持的数据 ({file_glob})"
        )
        selected = [str(path) for path in (paths or ()) if path]
        if not selected:
            return
        if callable(self._disk_paths_handler):
            self._disk_paths_handler(selected)
            return
        for path in selected:
            self.add_disk_path(path)


# ---------------------------------------------------------------------------
# Input panel composition
# ---------------------------------------------------------------------------
class InputPanel(QWidget):
    """Compact INPUT column with first-level authoritative file management."""

    changed = pyqtSignal()
    channelUniverseChanged = pyqtSignal(tuple, dict)

    def __init__(
        self,
        parent: QWidget | None = None,
        files: dict | None = None,
        *,
        source_registry=None,
        source_context: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("BatchInputPanel")

        outer = QVBoxLayout(self)
        self._outer_layout = outer
        outer.setContentsMargins(12, 14, 12, 18)
        outer.setSpacing(12)

        files_head = QWidget(self)
        files_head_lay = QHBoxLayout(files_head)
        files_head_lay.setContentsMargins(0, 0, 0, 0)
        files_head_lay.setSpacing(6)
        title = QLabel("数据文件", files_head)
        title.setObjectName("BatchSectionTitle")
        files_head_lay.addWidget(title)
        self._file_facts = QLabel("0 个数据源 · 0 个共同信号", files_head)
        self._file_facts.setObjectName("BatchFileFacts")
        self._file_facts.setMinimumWidth(0)
        self._file_facts.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._file_facts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        files_head_lay.addWidget(self._file_facts, 1)
        self._file_ready = QLabel("待配置", files_head)
        self._file_ready.setObjectName("BatchFileReadyPill")
        files_head_lay.addWidget(self._file_ready)
        outer.addWidget(files_head)

        self._file_manager_host = QFrame(self)
        self._file_manager_host.setObjectName("BatchInlineFileManager")
        self._file_manager_host.setAttribute(Qt.WA_StyledBackground, True)
        self._file_manager_host.setFixedHeight(BATCH_INLINE_FILE_MANAGER_HEIGHT)
        self._file_manager_host.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed,
        )
        manager_lay = QVBoxLayout(self._file_manager_host)
        manager_lay.setContentsMargins(0, 0, 0, 0)
        manager_lay.setSpacing(0)
        self._file_list = FileListWidget(
            self._file_manager_host, files=files, source_registry=source_registry,
            source_context=source_context,
        )
        manager_lay.addWidget(self._file_list)
        outer.addWidget(self._file_manager_host)

        # Form block
        target_head = QWidget(self)
        target_head_lay = QHBoxLayout(target_head)
        target_head_lay.setContentsMargins(0, 0, 0, 0)
        target_head_lay.setSpacing(6)
        target_title = QLabel("目标", target_head)
        target_title.setObjectName("BatchSectionTitle")
        target_head_lay.addWidget(target_title)
        target_head_lay.addStretch(1)
        target_note = QLabel("文件间匹配", target_head)
        target_note.setObjectName("BatchSectionNote")
        target_head_lay.addWidget(target_note)
        outer.addWidget(target_head)

        form_host = QFrame(self)
        form_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(4)

        self._target_policy_combo = QComboBox(form_host)
        self._target_policy_combo.addItem("所有来源共有", "common")
        self._target_policy_combo.addItem("按来源可用", "available_per_source")
        self._target_policy_combo.setToolTip(
            "共有：只选择每个来源都有的信号；按来源可用：选择并集，跳过缺失组合。"
        )
        self._target_policy_choice = SegmentedChoice(form_host)
        self._target_policy_choice.bind(self._target_policy_combo)
        # Keep the Batch column shrinkable to its supported 288px width.  At
        # layout time this field still receives the full form slot; ``Ignored``
        # only prevents its two label hints from becoming the panel minimum.
        self._target_policy_choice.setMinimumWidth(0)
        self._target_policy_choice.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed,
        )
        form.addRow("目标策略", self._target_policy_choice)

        self._target_stack = _TargetStack(form_host)
        self._target_stack.setMinimumWidth(0)
        self._target_stack.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred,
        )
        self._signal_picker = SignalPickerPopup(parent=self._target_stack)
        # Use an explicit label widget for both paired rows.  QFormLayout then
        # owns one shared label column instead of allowing one string label to
        # pick up a different effective margin on a later relayout.
        self._target_signal_label = QLabel("目标信号", form_host)
        self._target_stack.addWidget(self._signal_picker)

        self._frf_pair_editor = FrfPairEditor(self._target_stack)
        self._frf_pair_editor.setMinimumWidth(0)
        self._frf_pair_editor.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred,
        )
        self._target_stack.addWidget(self._frf_pair_editor)
        self._target_stack.setCurrentWidget(self._signal_picker)
        form.addRow(self._target_signal_label, self._target_stack)
        self._method = "fft"

        # ----- RPM channel row -----
        rpm_host = QWidget(form_host)
        rpm_lay = QHBoxLayout(rpm_host)
        rpm_lay.setContentsMargins(0, 0, 0, 0)
        rpm_lay.setSpacing(6)

        self._rpm_picker = SignalPickerPopup(parent=rpm_host, single_select=True)
        self._rpm_picker.setMinimumWidth(0)
        self._rpm_picker.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        rpm_lay.addWidget(self._rpm_picker, 1)

        # ----- RPM coefficient row -----
        # Keep sufficient precision for a user-supplied coefficient to
        # round-trip through a saved Batch preset.
        self._rpm_factor_spin = CompactDoubleSpinBox(form_host)
        self._rpm_factor_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._rpm_factor_spin.setDecimals(10)
        self._rpm_factor_spin.setRange(0.0001, 10000.0)
        self._rpm_factor_spin.setValue(1.0)
        self._rpm_factor_spin.setAccessibleName("RPM 转换系数")
        self._rpm_factor_spin.setMinimumWidth(0)
        self._rpm_factor_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._rpm_factor_spin.setToolTip(
            "转换为 RPM 的系数：原始通道值 × 系数。可直接输入自定义系数。"
        )

        # Form row labels
        self._rpm_label_widget = QLabel("RPM 通道", form_host)
        form.addRow(self._rpm_label_widget, rpm_host)
        self._rpm_factor_label_widget = QLabel("RPM系数", form_host)
        form.addRow(self._rpm_factor_label_widget, self._rpm_factor_spin)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._rpm_row_host = rpm_host  # referenced by set_method visibility

        # Form reference + row index, captured for set_method's takeRow /
        # insertRow toggle (PyQt5 5.15.11 has no QFormLayout.setRowVisible —
        # verified against this repo's pinned PyQt5; revisit once we move
        # to PyQt5 5.15+ where setRowVisible exists). We MUST keep widgets
        # reparented to ``self`` while detached so they survive the layout
        # round-trip (matches the DynamicParamForm._render_for pattern).
        self._form_ref = form
        # Snap both paired RPM rows from QFormLayout itself so their original
        # order remains correct even if fields above them move in the future.
        idx, _role = form.getWidgetPosition(self._rpm_row_host)
        if idx < 0:
            raise RuntimeError("RPM row not found in form layout")
        self._rpm_row_index = idx
        factor_idx, _role = form.getWidgetPosition(self._rpm_factor_spin)
        if factor_idx < 0:
            raise RuntimeError("RPM coefficient row not found in form layout")
        self._rpm_factor_row_index = factor_idx
        self._rpm_row_visible = True  # initial state matches addRow above

        # Compatibility holder for legacy direct callers.  It is deliberately
        # not inserted into the compact Input form: BatchSheet maps ranges to
        # time-axis controls (time) or source interval (FFT) instead.
        self._time_edit = QLineEdit(self)
        self._time_edit.hide()

        self._filter_panel = BatchFilterPanel(form_host)
        self._filter_panel.setMinimumWidth(0)
        self._filter_panel.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        form.addRow(self._filter_panel)
        outer.addWidget(form_host)
        outer.addStretch(1)

        # Wiring
        self._file_list.filesChanged.connect(self._on_files_changed)
        self._file_list.filesChanged.connect(self._refresh_file_summary)
        self._disk_paths_handler = None
        self._signal_picker.selectionChanged.connect(self.changed)
        self._frf_pair_editor.changed.connect(self.changed)
        self._target_policy_combo.currentIndexChanged.connect(
            self._on_target_policy_changed
        )
        self._rpm_picker.selectionChanged.connect(self.changed)
        self._signal_picker.relaxPolicyRequested.connect(
            self._on_relax_policy_requested
        )
        self._frf_pair_editor.relaxPolicyRequested.connect(
            self._on_relax_policy_requested
        )
        self._rpm_picker.relaxPolicyRequested.connect(
            self._on_relax_policy_requested
        )
        self._rpm_factor_spin.valueChanged.connect(self.changed)
        self._time_edit.textChanged.connect(self._on_time_text_changed)
        self._filter_panel.changed.connect(self.changed)

        # Seed picker / RPM with initial empty intersection.
        self._refresh_signal_universe()
        self._refresh_file_summary()

    # ------------------------------------------------------------------
    # Internal change handlers
    # ------------------------------------------------------------------
    def _on_files_changed(self) -> None:
        self._refresh_signal_universe()
        self.changed.emit()

    def _refresh_file_summary(self) -> None:
        rows = tuple(self._file_list._rows.values())
        loaded = sum(row.state == STATE_LOADED for row in rows)
        failed = sum(
            row.state in {STATE_PROBE_FAILED, STATE_UNAVAILABLE} for row in rows
        )
        common = len(self._file_list.current_intersection())
        self._file_facts.setText(
            f"{len(rows)} 个数据源 · {common} 个共同信号"
        )
        if failed:
            self._file_ready.setText(f"{failed} 异常")
            self._file_ready.setProperty("status", "error")
        elif rows and loaded == len(rows):
            self._file_ready.setText("全部就绪")
            self._file_ready.setProperty("status", "ready")
        elif rows:
            self._file_ready.setText("解析中")
            self._file_ready.setProperty("status", "pending")
        else:
            self._file_ready.setText("待配置")
            self._file_ready.setProperty("status", "pending")
        self._file_ready.style().unpolish(self._file_ready)
        self._file_ready.style().polish(self._file_ready)

    def set_compact_mode(self, compact: bool) -> None:
        side = 12 if compact else 18
        self._outer_layout.setContentsMargins(side, 14, side, 18)

    def _on_target_policy_changed(self, _index: int) -> None:
        self._refresh_signal_universe()
        self.changed.emit()

    def _on_relax_policy_requested(self) -> None:
        """Honour a picker's request to allow partially-available channels.

        The pickers report the request but never act on it: switching policy
        changes which outputs a run produces, so it has to be a deliberate
        click, never an automatic reaction to a greyed-out list.  Moving the
        combo re-enters ``_on_target_policy_changed``, which refreshes both
        universes and emits ``changed``.
        """

        if self.target_policy() == "available_per_source":
            return
        self.apply_target_policy("available_per_source")

    def _on_time_text_changed(self, _text: str) -> None:
        error = self.time_range_error()
        self._time_edit.setToolTip(error)
        self._time_edit.setProperty("invalid", bool(error))
        self._time_edit.style().unpolish(self._time_edit)
        self._time_edit.style().polish(self._time_edit)
        self.changed.emit()

    def set_method(self, method: str) -> None:
        """Show/hide the paired RPM channel/coefficient rows by method.

        Driven by ``BatchSheet`` on ``methodChanged``. Per the
        ``conditional-visibility-init-sync-and-paired-field-children``
        lesson, ``BatchSheet.__init__`` MUST call this once after
        constructing both sub-widgets so the initial state is correct
        before ``show()``.

        Implementation note: PyQt5 5.15.11 does NOT expose
        ``QFormLayout.setRowVisible``, and a plain ``setVisible(False)``
        on the row's label + field leaves a blank gap (Qt reserves the
        row's vertical space). We therefore use ``takeRow`` /
        ``insertRow`` to fully detach and re-insert at the original
        index — matching the ``DynamicParamForm._render_for`` pattern
        already in use elsewhere in the batch UI. Detached widgets are
        reparented to ``self`` so they survive the layout round-trip
        and can be re-inserted later.
        """
        self._method = str(method)
        self._filter_panel.set_method(method)
        is_frf = self._method == "frf"
        self._target_signal_label.setText("FRF 配对" if is_frf else "目标信号")
        # FRF: pin the form label to the top of the tall field cell, then
        # inset it so its text centers on the first pair-group header row
        # ("配对组 N" + delete).  Non-FRF pickers are one row tall, so their
        # label stays vertically centered in the shared form label column.
        self._target_signal_label.setAlignment(
            Qt.AlignLeft | (Qt.AlignTop if is_frf else Qt.AlignVCenter)
        )
        top_inset = (
            self._frf_pair_editor.form_label_top_inset(
                self._target_signal_label.font()
            )
            if is_frf else 0
        )
        self._target_signal_label.setContentsMargins(0, top_inset, 0, 0)
        self._target_stack.setCurrentWidget(
            self._frf_pair_editor if is_frf else self._signal_picker
        )
        self._frf_pair_editor.set_channel_universe(
            self._file_list.current_intersection(),
            self._partial_channel_facts(),
            policy=self.target_policy(),
            source_count=len(self._file_list.per_file_channel_sets()),
        )
        visible = method in _RPM_USING_METHODS
        if visible == self._rpm_row_visible:
            return
        if visible:
            # Re-insert in original order.  The second insertion shifts any
            # row below it, leaving the two RPM controls consecutive.
            self._form_ref.insertRow(
                self._rpm_row_index, self._rpm_label_widget, self._rpm_row_host,
            )
            self._form_ref.insertRow(
                self._rpm_factor_row_index,
                self._rpm_factor_label_widget,
                self._rpm_factor_spin,
            )
            self._rpm_label_widget.setVisible(True)
            self._rpm_row_host.setVisible(True)
            self._rpm_factor_label_widget.setVisible(True)
            self._rpm_factor_spin.setVisible(True)
        else:
            # Remove bottom first so taking the channel row cannot shift the
            # coefficient row before we locate it.
            for field in (self._rpm_factor_spin, self._rpm_row_host):
                idx, _role = self._form_ref.getWidgetPosition(field)
                if idx < 0:
                    continue
                taken = self._form_ref.takeRow(idx)
                # Reparent both label and field widgets to ``self`` so they
                # persist (they're orphaned otherwise once the layout drops
                # them — Qt would eventually GC them).
                if taken.labelItem is not None:
                    lw = taken.labelItem.widget()
                    if lw is not None:
                        lw.setParent(self)
                        lw.hide()
                if taken.fieldItem is not None:
                    fw = taken.fieldItem.widget()
                    if fw is not None:
                        fw.setParent(self)
                        fw.hide()
        self._rpm_row_visible = visible

    def _refresh_signal_universe(self) -> None:
        per_file = self._file_list.per_file_channel_sets()
        loaded_count = len(per_file)
        if loaded_count == 0:
            available: list[str] = []
            partial: dict[str, str] = {}
        else:
            counts: dict[str, int] = {}
            for s in per_file:
                for name in s:
                    counts[name] = counts.get(name, 0) + 1
            available = sorted(n for n, c in counts.items() if c == loaded_count)
            partial = {
                n: f"({c}/{loaded_count})"
                for n, c in counts.items() if c < loaded_count
            }
            partial = {k: partial[k] for k in sorted(partial.keys())}
        selectable = self.target_policy() == "available_per_source"
        self._signal_picker.set_available(available)
        self._signal_picker.set_partially_available(partial, selectable=selectable)

        # RPM picker shares the same universe *and* the same policy.  A RPM
        # channel present in only some sources is legitimate: BatchRunner's
        # ``_rpm_values`` resamples a cross-source RPM onto the target's time
        # base with ``np.interp``.  Pinning it to unselectable contradicted
        # that and left the row permanently grey.
        self._rpm_picker.set_available(available)
        self._rpm_picker.set_partially_available(partial, selectable=selectable)
        self._frf_pair_editor.set_channel_universe(
            tuple(available), partial,
            policy=self.target_policy(), source_count=loaded_count,
        )
        self.channelUniverseChanged.emit(tuple(available), dict(partial))

    def _partial_channel_facts(self) -> dict[str, str]:
        per_file = self._file_list.per_file_channel_sets()
        count = len(per_file)
        if not count:
            return {}
        totals: dict[str, int] = {}
        for channels in per_file:
            for name in channels:
                totals[str(name)] = totals.get(str(name), 0) + 1
        return {
            name: f"({total}/{count})"
            for name, total in sorted(totals.items()) if total < count
        }

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def selected_signals(self) -> tuple[str, ...]:
        if self._method == "frf":
            return self._frf_pair_editor.selected_channels()
        return self._signal_picker.selected()

    def frf_pair_rules(self):
        return self._frf_pair_editor.rules() if self._method == "frf" else ()

    def frf_pair_validation_message(self) -> str:
        return (
            self._frf_pair_editor.validation_message()
            if self._method == "frf" else ""
        )

    def target_policy(self) -> str:
        return str(self._target_policy_combo.currentData() or "common")

    def rpm_channel(self) -> str:
        sel = self._rpm_picker.selected()
        return sel[0] if sel else ""

    def rpm_params(self) -> dict:
        """Return InputPanel-owned analysis params (currently rpm_factor).

        Pairs with ``apply_rpm_factor`` for round-trip preset import/export.
        BatchSheet.get_preset merges this dict into ``params``.
        """
        return {"rpm_factor": float(self._rpm_factor_spin.value())}

    def filter_params(self) -> dict:
        return self._filter_panel.filter_params()

    def time_range(self) -> tuple[float, float] | None:
        text = self._time_edit.text().strip()
        if not text:
            return None
        parts = split_list_text(text)
        if len(parts) != 2:
            return None
        try:
            lo, hi = float(parts[0]), float(parts[1])
        except ValueError:
            return None
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            return None
        return lo, hi

    def time_range_error(self) -> str:
        text = self._time_edit.text().strip()
        if not text:
            return ""
        parts = split_list_text(text)
        if len(parts) != 2 or not all(parts):
            return "时间范围：请输入两个逗号分隔的数字（中英文均可）"
        try:
            lo, hi = float(parts[0]), float(parts[1])
        except ValueError:
            return "时间范围：请输入两个逗号分隔的数字（中英文均可）"
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return "时间范围：起点和终点必须是有限数"
        if lo >= hi:
            return "时间范围：起点必须小于终点"
        return ""

    def set_source_context(self, source_context: dict | None) -> None:
        """Push BLF/DBC (or other) context into the file list probe path."""
        self._file_list.set_source_context(source_context)

    def set_disk_paths_handler(self, handler) -> None:
        """Let BatchSheet intercept disk/drop adds for BLF DBC resolution."""
        self._disk_paths_handler = handler
        self._file_list.set_disk_paths_handler(handler)

    def add_disk_paths(self, paths) -> None:
        """Add local disk paths via the existing ``FileListWidget.add_disk_path`` sink.

        When a disk-paths handler is installed (BatchSheet BLF/DBC orchestration),
        route through it so dialog and programmatic adds share one path.
        """
        selected = [str(path) for path in (paths or ()) if path]
        if not selected:
            return
        if callable(self._disk_paths_handler):
            self._disk_paths_handler(selected)
            return
        for path in selected:
            self._file_list.add_disk_path(path)

    def add_disk_paths_resolved(self, paths) -> None:
        """Add paths after BLF/DBC context is already ensured (no re-entry)."""
        for path in paths or ():
            self._file_list.add_disk_path(path)

    def file_ids(self) -> tuple:
        return self._file_list.loaded_file_ids()

    def file_paths(self) -> tuple[str, ...]:
        return self._file_list.loaded_disk_paths()

    def source_ids(self) -> tuple:
        return self._file_list.loaded_source_ids()

    def source_paths(self) -> tuple[str, ...]:
        return self._file_list.source_paths()

    def source_channel_sets(self) -> dict:
        """Return ``{source key: frozenset(channel names)}`` for loaded rows.

        The keys match what ``BatchRunner._expand_tasks`` yields as its source
        key (``source_ids()``), so ``preview_outputs`` can tell which planned
        group actually holds the selected channels.  Both accessors walk
        ``loaded_rows()`` in the same order, which is what makes the zip safe.
        """

        return dict(zip(
            self._file_list.loaded_source_ids(),
            self._file_list.per_file_channel_sets(),
        ))

    def signals_marked_unavailable(self) -> tuple[str, ...]:
        intersection = self._file_list.current_intersection()
        return tuple(
            s for s in self._signal_picker.selected()
            if s not in intersection
        )

    # ------------------------------------------------------------------
    # Mutators (Wave 7 apply_preset path)
    # ------------------------------------------------------------------
    def apply_signals(self, signals: Iterable[str]) -> None:
        self._signal_picker.set_selected(tuple(signals))

    def apply_frf_pair_rules(self, rules) -> None:
        self._frf_pair_editor.apply_rules(tuple(rules or ()))

    def apply_target_policy(self, policy: str) -> None:
        token = str(policy or "common")
        if token == "exact_pairs":
            # Internal exact-pair policy has no regular authoring choice.  Keep
            # the union visible while BatchSheet preserves the exact pairs.
            token = "available_per_source"
        index = self._target_policy_combo.findData(token)
        if index >= 0:
            self._target_policy_combo.setCurrentIndex(index)

    def apply_rpm_channel(self, ch: str) -> None:
        self._rpm_picker.set_selected((str(ch),) if ch else ())

    def apply_rpm_factor(self, value: float) -> None:
        """Restore the explicitly saved RPM coefficient from a preset.

        Pairs with ``rpm_params()`` so a saved preset's ``rpm_factor``
        round-trips through export → JSON → import without resetting.
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        self._rpm_factor_spin.setValue(v)

    def apply_filter_params(self, params: dict | None) -> None:
        self._filter_panel.apply_filter_params(params)

    def apply_time_range(self, rng: tuple[float, float] | None) -> None:
        if rng is None:
            self._time_edit.setText("")
            return
        a, b = rng
        self._time_edit.setText(f"{a},{b}")

    def apply_files(
        self,
        file_ids: tuple,
        file_paths: tuple[str, ...],
    ) -> None:
        # Replace current state. Loaded ids are looked up against the
        # parent's files_source if we have it; otherwise we just retain
        # the fid with an empty channel set.
        # Wipe rows.
        for path in list(self._file_list._rows.keys()):
            self._file_list.remove_path(path)
        for fid in file_ids or ():
            fd = (self._file_list._files_source or {}).get(fid)
            if fd is not None:
                fp = getattr(fd, "filepath", None)
                path = str(fp) if fp is not None else str(fid)
                try:
                    # Filter time master via FileData.get_signal_channels()
                    # (ultrareview bug_001).
                    channels = frozenset(fd.get_signal_channels())
                except Exception:  # noqa: BLE001
                    channels = frozenset()
            else:
                path = str(fid)
                channels = frozenset()
            self._file_list.add_loaded_file(fid, path, channels)
        for path in file_paths or ():
            self._file_list.add_disk_path(path)

    def apply_sources(
        self,
        source_ids: tuple,
        source_paths: tuple[str, ...],
    ) -> None:
        """Restore a parallel runtime source scope without eager file loading."""
        ids = tuple(source_ids or ())
        paths = tuple(source_paths or ())
        if len(paths) == 1 and len(ids) > 1:
            paths = paths * len(ids)
        if ids and paths and len(ids) != len(paths):
            raise ValueError("source_ids/source_paths must be parallel")
        for key in list(self._file_list._rows):
            self._file_list.remove_path(key)
        if not ids:
            for path in paths:
                self._file_list.add_disk_path(path)
            return
        if not paths:
            paths = tuple(str(source_id) for source_id in ids)
        for source_id, path in zip(ids, paths):
            fd = (self._file_list._files_source or {}).get(source_id)
            try:
                channels = frozenset(fd.get_signal_channels()) if fd is not None else frozenset()
            except Exception:  # noqa: BLE001
                channels = frozenset()
            self._file_list.add_loaded_file(source_id, str(path), channels)

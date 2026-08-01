"""Input column for the batch dialog.

Two widgets:

* ``FileListWidget`` — manages the file list rows with a four-state machine
  (``loaded`` / ``path_pending`` / ``probing`` / ``probe_failed``) per
  spec §3.2. Disk-add delegates the registry probe via ``QThreadPool``;
  tests inject ``w._probe_signals_for = ...`` to make probing synchronous,
  so the production code calls ``self._probe_signals_for(path)`` (not a
  free function). No ``thread.wait()`` is used (per
  ``pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md``).

* ``InputPanel`` — composes the file list + signal picker + RPM channel
  combo + time-range field. Re-emits a single ``changed`` signal whenever
  any sub-control mutates.
"""
from __future__ import annotations

import math
import os
from typing import Iterable

from PyQt5.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal,
)
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QAction, QComboBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ....io.source_adapters import (
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
    SourceDescriptor,
    canonical_source_path,
    stable_source_id,
)
from ....ui_kit.menus import apply_rounded_menu_chrome
from ...widgets.compact_spinbox import CompactDoubleSpinBox
from .filter_panel import BatchFilterPanel
from .signal_picker import SignalPickerPopup


# Unit-preset → rpm_factor coefficient. The "自定义" sentinel leaves the
# spinbox alone so users can free-type. Factors derived analytically:
#   rad/s → rpm: 60 / (2π) ≈ 9.5492965855
#   deg/s → rpm: 1 / 6     ≈ 0.1666666667
_RPM_UNIT_FACTORS: dict[str, float] = {
    "rpm":   1.0,
    "rad/s": 60.0 / (2.0 * 3.141592653589793),
    "deg/s": 1.0 / 6.0,
}
_RPM_UNIT_CUSTOM = "自定义"

# Methods whose backend dispatch consumes RPM. Drives InputPanel.set_method
# row visibility — fft / fft_time skip the row entirely.
_RPM_USING_METHODS = frozenset({"order_time"})


# State machine values (spec §3.2). Run-time-only states (`loading`,
# `load_failed`) are NOT managed here — they belong to the runner thread
# in W6.
STATE_LOADED = "loaded"
STATE_PATH_PENDING = "path_pending"
STATE_PROBING = "probing"
STATE_PROBE_FAILED = "probe_failed"
STATE_UNAVAILABLE = "unavailable"


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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Header row: count + "+ 已加载" + "+ 磁盘…"
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("文件 (0)")
        header.addWidget(self._count_label, 1)
        self._btn_loaded = QPushButton("+ 已加载")
        self._btn_loaded.clicked.connect(self._open_loaded_menu)
        header.addWidget(self._btn_loaded)
        self._btn_disk = QPushButton("+ 磁盘…")
        self._btn_disk.clicked.connect(self._open_disk_dialog)
        header.addWidget(self._btn_disk)
        outer.addLayout(header)

        self._list = QListWidget(self)
        self._list.setObjectName("BatchFileList")
        outer.addWidget(self._list, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
            item = QListWidgetItem(text, self._list)
            item.setData(Qt.UserRole, row.source_id)
            row._item = item
        else:
            row._item.setText(text)
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

    def _after_change(self) -> None:
        self._count_label.setText(f"文件 ({len(self._rows)})")
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
        for p in paths or ():
            self.add_disk_path(p)


# ---------------------------------------------------------------------------
# Input panel composition
# ---------------------------------------------------------------------------
class InputPanel(QWidget):
    """Composes the INPUT column: file list + signal picker + RPM + time."""

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
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        title = QLabel("INPUT")
        title.setStyleSheet("color:#3b82f6;font-weight:600;font-size:13px;")
        outer.addWidget(title)

        # File list block
        self._file_list = FileListWidget(
            self, files=files, source_registry=source_registry,
            source_context=source_context,
        )
        outer.addWidget(self._file_list, 1)

        # Form block
        form_host = QFrame(self)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(4)

        self._target_policy_combo = QComboBox(form_host)
        self._target_policy_combo.addItem("所有来源共有", "common")
        self._target_policy_combo.addItem("按来源可用", "available_per_source")
        self._target_policy_combo.setToolTip(
            "共有：只选择每个来源都有的信号；按来源可用：选择并集，跳过缺失组合。"
        )
        form.addRow("目标策略", self._target_policy_combo)

        self._signal_picker = SignalPickerPopup(parent=form_host)
        form.addRow("目标信号", self._signal_picker)

        # ----- RPM row (single-select picker + unit + factor) -----
        rpm_host = QWidget(form_host)
        rpm_lay = QHBoxLayout(rpm_host)
        rpm_lay.setContentsMargins(0, 0, 0, 0)
        rpm_lay.setSpacing(6)

        self._rpm_picker = SignalPickerPopup(parent=rpm_host, single_select=True)
        self._rpm_picker.setMinimumWidth(0)
        self._rpm_picker.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        rpm_lay.addWidget(self._rpm_picker, 1)

        self._rpm_unit_combo = QComboBox(rpm_host)
        for unit in _RPM_UNIT_FACTORS.keys():
            self._rpm_unit_combo.addItem(unit)
        self._rpm_unit_combo.addItem(_RPM_UNIT_CUSTOM)
        self._rpm_unit_combo.setMinimumWidth(0)
        self._rpm_unit_combo.setMaximumWidth(64)
        self._rpm_unit_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        rpm_lay.addWidget(self._rpm_unit_combo)

        # NOTE: setDecimals(10) so unit-preset factors with infinite
        # decimal expansions (1/6 ≈ 0.1666666667, 60/(2π) ≈ 9.5492965855)
        # round-trip through QDoubleSpinBox without losing more than
        # ~1e-10 of precision. The display stays readable; the maximum
        # width below keeps the column from ballooning.
        self._rpm_factor_spin = CompactDoubleSpinBox(rpm_host)
        self._rpm_factor_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._rpm_factor_spin.setDecimals(10)
        self._rpm_factor_spin.setRange(0.0001, 10000.0)
        self._rpm_factor_spin.setValue(1.0)
        self._rpm_factor_spin.setMinimumWidth(0)
        self._rpm_factor_spin.setMaximumWidth(86)
        self._rpm_factor_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        rpm_lay.addWidget(self._rpm_factor_spin)

        # Form row label
        self._rpm_label_widget = QLabel("RPM 通道", form_host)
        form.addRow(self._rpm_label_widget, rpm_host)
        self._rpm_row_host = rpm_host  # referenced by set_method visibility

        # Form reference + row index, captured for set_method's takeRow /
        # insertRow toggle (PyQt5 5.15.11 has no QFormLayout.setRowVisible —
        # verified against this repo's pinned PyQt5; revisit once we move
        # to PyQt5 5.15+ where setRowVisible exists). We MUST keep widgets
        # reparented to ``self`` while detached so they survive the layout
        # round-trip (matches the DynamicParamForm._render_for pattern).
        self._form_ref = form
        # _rpm_row_index = the QFormLayout row position of the RPM row at
        # construction time (after target-signals row is row 0). We snap
        # it from getWidgetPosition so the value is honest even if rows
        # are added in a different order in the future.
        idx, _role = form.getWidgetPosition(self._rpm_row_host)
        if idx < 0:
            raise RuntimeError("RPM row not found in form layout")
        self._rpm_row_index = idx
        self._rpm_row_visible = True  # initial state matches addRow above

        # Internal flag so unit→factor and factor→unit don't ping-pong.
        self._rpm_factor_sync_busy = False

        self._time_edit = QLineEdit(form_host)
        self._time_edit.setPlaceholderText('留空=全段；"a,b" 表示 [a,b]s')
        form.addRow("时间范围", self._time_edit)

        self._filter_panel = BatchFilterPanel(form_host)
        self._filter_panel.setMinimumWidth(0)
        self._filter_panel.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        form.addRow("滤波", self._filter_panel)
        outer.addWidget(form_host)

        # Wiring
        self._file_list.filesChanged.connect(self._on_files_changed)
        self._file_list.intersectionChanged.connect(self._on_intersection_changed)
        self._signal_picker.selectionChanged.connect(lambda *_: self.changed.emit())
        self._target_policy_combo.currentIndexChanged.connect(
            self._on_target_policy_changed
        )
        self._rpm_picker.selectionChanged.connect(lambda *_: self.changed.emit())
        self._rpm_unit_combo.currentTextChanged.connect(self._on_rpm_unit_changed)
        self._rpm_factor_spin.valueChanged.connect(self._on_rpm_factor_value_changed)
        self._time_edit.textChanged.connect(self._on_time_text_changed)
        self._filter_panel.changed.connect(lambda *_: self.changed.emit())

        # Seed picker / RPM with initial empty intersection.
        self._refresh_signal_universe()

    # ------------------------------------------------------------------
    # Internal change handlers
    # ------------------------------------------------------------------
    def _on_files_changed(self) -> None:
        self._refresh_signal_universe()
        self.changed.emit()

    def _on_intersection_changed(self, _intersection: frozenset) -> None:
        self._refresh_signal_universe()
        # changed signal already fired through filesChanged path

    def _on_target_policy_changed(self, _index: int) -> None:
        self._refresh_signal_universe()
        self.changed.emit()

    def _on_rpm_unit_changed(self, unit: str) -> None:
        if unit in _RPM_UNIT_FACTORS:
            self._rpm_factor_sync_busy = True
            try:
                self._rpm_factor_spin.setValue(_RPM_UNIT_FACTORS[unit])
            finally:
                self._rpm_factor_sync_busy = False
        # When unit is "自定义", leave spinbox alone.
        self.changed.emit()

    def _on_rpm_factor_value_changed(self, value: float) -> None:
        if self._rpm_factor_sync_busy:
            self.changed.emit()
            return
        # Identify if the new value matches a known unit (within tolerance).
        match = None
        for unit, factor in _RPM_UNIT_FACTORS.items():
            if abs(value - factor) < 1e-6:
                match = unit
                break
        target = match if match is not None else _RPM_UNIT_CUSTOM
        if self._rpm_unit_combo.currentText() != target:
            self._rpm_unit_combo.blockSignals(True)
            try:
                idx = self._rpm_unit_combo.findText(target)
                if idx >= 0:
                    self._rpm_unit_combo.setCurrentIndex(idx)
            finally:
                self._rpm_unit_combo.blockSignals(False)
        self.changed.emit()

    def _on_time_text_changed(self, _text: str) -> None:
        error = self.time_range_error()
        self._time_edit.setToolTip(error)
        self._time_edit.setProperty("invalid", bool(error))
        self._time_edit.style().unpolish(self._time_edit)
        self._time_edit.style().polish(self._time_edit)
        self.changed.emit()

    def set_method(self, method: str) -> None:
        """Show/hide the RPM row based on whether the method consumes RPM.

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
        self._filter_panel.set_method(method)
        visible = method in _RPM_USING_METHODS
        if visible == self._rpm_row_visible:
            return
        if visible:
            # Re-insert at the original row position. ``insertRow`` accepts
            # the original index even if rows below have shifted up while
            # the RPM row was absent.
            self._form_ref.insertRow(
                self._rpm_row_index, self._rpm_label_widget, self._rpm_row_host,
            )
            self._rpm_label_widget.setVisible(True)
            self._rpm_row_host.setVisible(True)
        else:
            idx, _role = self._form_ref.getWidgetPosition(self._rpm_row_host)
            if idx >= 0:
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
        self._signal_picker.set_available(available)
        self._signal_picker.set_partially_available(
            partial, selectable=self.target_policy() == "available_per_source",
        )

        # RPM picker shares the same universe.
        self._rpm_picker.set_available(available)
        self._rpm_picker.set_partially_available(partial)
        self.channelUniverseChanged.emit(tuple(available), dict(partial))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def selected_signals(self) -> tuple[str, ...]:
        return self._signal_picker.selected()

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
        parts = [p.strip() for p in text.split(",")]
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
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 2 or not all(parts):
            return "时间范围：请输入两个以逗号分隔的数字"
        try:
            lo, hi = float(parts[0]), float(parts[1])
        except ValueError:
            return "时间范围：请输入两个以逗号分隔的数字"
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return "时间范围：起点和终点必须是有限数"
        if lo >= hi:
            return "时间范围：起点必须小于终点"
        return ""

    def file_ids(self) -> tuple:
        return self._file_list.loaded_file_ids()

    def file_paths(self) -> tuple[str, ...]:
        return self._file_list.loaded_disk_paths()

    def source_ids(self) -> tuple:
        return self._file_list.loaded_source_ids()

    def source_paths(self) -> tuple[str, ...]:
        return self._file_list.source_paths()

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
        """Restore the RPM factor spinbox + unit combo from a preset.

        Pairs with ``rpm_params()`` so a saved preset's ``rpm_factor``
        round-trips through export → JSON → import without resetting.
        Picks the matching unit-preset label if ``value`` matches one
        within tolerance, else "自定义".
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        # Sync the spinbox first; _on_rpm_factor_value_changed will then
        # pick the matching unit ("自定义" if no match) via the existing
        # bidirectional logic. Do NOT block signals — we want the
        # combo to follow.
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

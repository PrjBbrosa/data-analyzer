"""Input column for the batch dialog.

Two widgets:

* ``FileListWidget`` — manages the file list rows with a four-state machine
  (``loaded`` / ``path_pending`` / ``probing`` / ``probe_failed``) per
  spec §3.2. Disk-add fires a metadata-only probe via ``QThreadPool``;
  tests inject ``w._probe_signals_for = ...`` to make probing synchronous,
  so the production code calls ``self._probe_signals_for(path)`` (not a
  free function). No ``thread.wait()`` is used (per
  ``pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md``).

* ``InputPanel`` — composes the file list + signal picker + RPM channel
  combo + time-range field. Re-emits a single ``changed`` signal whenever
  any sub-control mutates.
"""
from __future__ import annotations

import os
import traceback
from typing import Iterable

from PyQt5.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal,
)
from PyQt5.QtWidgets import (
    QAction, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
    QWidget,
)

from .signal_picker import SignalPickerPopup


# State machine values (spec §3.2). Run-time-only states (`loading`,
# `load_failed`) are NOT managed here — they belong to the runner thread
# in W6.
STATE_LOADED = "loaded"
STATE_PATH_PENDING = "path_pending"
STATE_PROBING = "probing"
STATE_PROBE_FAILED = "probe_failed"


# ---------------------------------------------------------------------------
# Background probe worker
# ---------------------------------------------------------------------------
class _ProbeSignals(QObject):
    """Signal carrier for ``_ProbeRunnable``; lives on the UI thread."""

    finished = pyqtSignal(str, object)   # (path, frozenset_or_None)
    failed = pyqtSignal(str, str)        # (path, error_msg)


class _ProbeRunnable(QRunnable):
    """Reads channel names of an MF4 path on a thread-pool worker."""

    def __init__(self, path: str, probe_fn) -> None:
        super().__init__()
        self._path = path
        self._probe_fn = probe_fn
        self.signals = _ProbeSignals()

    def run(self) -> None:  # noqa: D401 (Qt naming)
        try:
            channels = self._probe_fn(self._path)
        except Exception as exc:  # broad on purpose: convert to UI state
            msg = f"{type(exc).__name__}: {exc}"
            self.signals.failed.emit(self._path, msg)
            return
        if not isinstance(channels, frozenset):
            try:
                channels = frozenset(channels)
            except Exception as exc:  # noqa: BLE001
                self.signals.failed.emit(self._path, f"bad probe result: {exc}")
                return
        self.signals.finished.emit(self._path, channels)


def _default_probe_signals_for(path: str) -> frozenset:
    """Open an MF4 by ``path``, read its channel names, close.

    Pure metadata; does NOT decode samples. Falls back to a clear error if
    asammdf is not installed (so probe_failed surfaces a useful message).
    """
    try:
        from asammdf import MDF  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"asammdf unavailable: {exc}")
    mdf = MDF(path)
    try:
        keys = frozenset(mdf.channels_db.keys())
    finally:
        try:
            mdf.close()
        except Exception:  # noqa: BLE001  (close may not exist)
            pass
    return keys


# ---------------------------------------------------------------------------
# File list widget
# ---------------------------------------------------------------------------
class _FileRow:
    """Per-row state + cached channel set."""

    __slots__ = ("path", "state", "fid", "channels", "error", "label", "_item")

    def __init__(
        self,
        path: str,
        state: str,
        fid: object | None,
        channels: frozenset,
        error: str = "",
    ) -> None:
        self.path = path
        self.state = state
        self.fid = fid
        self.channels = channels
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
    ) -> None:
        super().__init__(parent)
        self._files_source = files or {}
        self._rows: dict[str, _FileRow] = {}
        self._last_intersection: frozenset = frozenset()

        self._probe_signals_for = _default_probe_signals_for
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
    def set_files_source(self, files: dict) -> None:
        """Update the source for the '+ 已加载' submenu."""
        self._files_source = files or {}

    def add_loaded_file(
        self, fid: object, path: str, channels: frozenset
    ) -> None:
        if path in self._rows:
            return
        row = _FileRow(path, STATE_LOADED, fid, frozenset(channels))
        self._rows[path] = row
        self._render_row(row)
        self.stateChanged.emit(path, STATE_LOADED)
        self._after_change()

    def add_disk_path(self, path: str) -> None:
        if path in self._rows:
            return
        row = _FileRow(path, STATE_PATH_PENDING, None, frozenset())
        self._rows[path] = row
        self._render_row(row)
        self.stateChanged.emit(path, STATE_PATH_PENDING)
        self._after_change()
        # Schedule probe on the next event-loop tick so callers can
        # override `_probe_signals_for` between add_disk_path() and the
        # actual probe run (matches the test pattern).
        QTimer.singleShot(0, lambda p=path: self._start_probe(p))

    def remove_path(self, path: str) -> None:
        row = self._rows.pop(path, None)
        if row is None:
            return
        item = row._item
        if item is not None:
            self._list.takeItem(self._list.row(item))
        self._after_change()

    def row_state(self, path: str) -> str:
        row = self._rows.get(path)
        return row.state if row else ""

    def _set_row_state(self, path: str, state: str) -> None:
        """Test/internal hook: explicitly set a row's state."""
        row = self._rows.get(path)
        if row is None:
            # Create a minimal row so tests can drive transitions on
            # paths that were never `add_*`'d (the test fixtures do this).
            row = _FileRow(path, state, None, frozenset())
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
        return tuple(
            r.path for r in self._rows.values()
            if r.state == STATE_LOADED and r.fid is None
        )

    def all_loaded_paths(self) -> tuple[str, ...]:
        return tuple(r.path for r in self._rows.values() if r.state == STATE_LOADED)

    def current_intersection(self) -> frozenset:
        loaded = [r for r in self._rows.values() if r.state == STATE_LOADED]
        if not loaded:
            return frozenset()
        out = set(loaded[0].channels)
        for row in loaded[1:]:
            out &= row.channels
        return frozenset(out)

    def per_file_channel_sets(self) -> list[frozenset]:
        return [r.channels for r in self._rows.values() if r.state == STATE_LOADED]

    def has_pending_probe(self) -> bool:
        return any(
            r.state in (STATE_PATH_PENDING, STATE_PROBING)
            for r in self._rows.values()
        )

    # ------------------------------------------------------------------
    # Probe lifecycle
    # ------------------------------------------------------------------
    def _start_probe(self, path: str) -> None:
        row = self._rows.get(path)
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
        row = self._rows.get(path)
        if row is None:
            return
        row.channels = frozenset(channels) if channels is not None else frozenset()
        row.state = STATE_LOADED
        row.error = ""
        self._render_row(row)
        self.stateChanged.emit(path, STATE_LOADED)
        self._after_change()

    def _on_probe_failed(self, path: str, error: str) -> None:
        row = self._rows.get(path)
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
        }.get(state, "")

    def _render_row(self, row: _FileRow) -> None:
        name = os.path.basename(row.path) or row.path
        text = f"{name}{self._badge_for(row.state)}"
        row.label = text
        if row._item is None:
            item = QListWidgetItem(text, self._list)
            item.setData(Qt.UserRole, row.path)
            row._item = item
        else:
            row._item.setText(text)
        if row.state == STATE_PROBE_FAILED and row.error:
            row._item.setToolTip(row.error)
        else:
            row._item.setToolTip(row.path)

    def _after_change(self) -> None:
        self._count_label.setText(f"文件 ({len(self._rows)})")
        self.filesChanged.emit()
        new_int = self.current_intersection()
        if new_int != self._last_intersection:
            self._last_intersection = new_int
            self.intersectionChanged.emit(new_int)

    def _open_loaded_menu(self) -> None:
        menu = QMenu(self)
        any_added = False
        for fid, fd in (self._files_source or {}).items():
            label = getattr(fd, "fp", None) or str(fid)
            label = os.path.basename(str(label))
            act = QAction(label, menu)

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
        path = getattr(fd, "fp", None) or str(fid)
        path = str(path)
        if path in self._rows:
            return
        # Channels = keys of fd.data (the FileData channel dict). Fall back to
        # an empty set if anything is missing — the row still becomes 'loaded'
        # since the user explicitly imported it from the main window.
        try:
            channels = frozenset(fd.data.keys())
        except Exception:  # noqa: BLE001
            channels = frozenset()
        self.add_loaded_file(fid, path, channels)

    def _open_disk_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 MF4 文件", "", "MF4 files (*.mf4 *.MF4)"
        )
        for p in paths or ():
            self.add_disk_path(p)


# ---------------------------------------------------------------------------
# Input panel composition
# ---------------------------------------------------------------------------
class InputPanel(QWidget):
    """Composes the INPUT column: file list + signal picker + RPM + time."""

    changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        files: dict | None = None,
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
        self._file_list = FileListWidget(self, files=files)
        outer.addWidget(self._file_list, 1)

        # Form block
        form_host = QFrame(self)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)

        self._signal_picker = SignalPickerPopup(parent=form_host)
        form.addRow("目标信号", self._signal_picker)

        self._rpm_combo = QComboBox(form_host)
        self._rpm_combo.setEditable(True)
        form.addRow("RPM 通道", self._rpm_combo)

        self._time_edit = QLineEdit(form_host)
        self._time_edit.setPlaceholderText('留空=全段；"a,b" 表示 [a,b]s')
        form.addRow("时间范围", self._time_edit)
        outer.addWidget(form_host)

        # Wiring
        self._file_list.filesChanged.connect(self._on_files_changed)
        self._file_list.intersectionChanged.connect(self._on_intersection_changed)
        self._signal_picker.selectionChanged.connect(lambda *_: self.changed.emit())
        self._rpm_combo.currentTextChanged.connect(lambda *_: self.changed.emit())
        self._time_edit.textChanged.connect(lambda *_: self.changed.emit())

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
        self._signal_picker.set_partially_available(partial)

        # RPM combo: keep current text if user already typed; just rebuild
        # the dropdown options. Editable so user can free-type.
        cur = self._rpm_combo.currentText()
        self._rpm_combo.blockSignals(True)
        self._rpm_combo.clear()
        for name in available:
            self._rpm_combo.addItem(name)
        if cur:
            idx = self._rpm_combo.findText(cur)
            if idx >= 0:
                self._rpm_combo.setCurrentIndex(idx)
            else:
                self._rpm_combo.setEditText(cur)
        self._rpm_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def selected_signals(self) -> tuple[str, ...]:
        return self._signal_picker.selected()

    def rpm_channel(self) -> str:
        return self._rpm_combo.currentText().strip()

    def time_range(self) -> tuple[float, float] | None:
        text = self._time_edit.text().strip()
        if not text:
            return None
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) != 2:
            return None
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None

    def file_ids(self) -> tuple:
        return self._file_list.loaded_file_ids()

    def file_paths(self) -> tuple[str, ...]:
        return self._file_list.loaded_disk_paths()

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

    def apply_rpm_channel(self, ch: str) -> None:
        self._rpm_combo.setEditText(str(ch or ""))

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
                path = str(getattr(fd, "fp", None) or fid)
                try:
                    channels = frozenset(fd.data.keys())
                except Exception:  # noqa: BLE001
                    channels = frozenset()
            else:
                path = str(fid)
                channels = frozenset()
            self._file_list.add_loaded_file(fid, path, channels)
        for path in file_paths or ():
            self._file_list.add_disk_path(path)

"""ReviewModal — post-record review dialog.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§State Machine Contract / `ReviewModal`.

The modal exposes four actions:

- ``丢弃（不归档）`` — always enabled; deletes the finalized MF4 + sidecar
  and returns to ``ConnectedIdle``.
- ``仅保存文件`` — keeps the finalized MF4 + ``session_summary.json``.
- ``保存并归档`` — keeps the file and appends a new ``Mf4DatasetEntry``
  to the project manifest using
  ``mf4_analyzer.acquisition.manifest`` helpers. Archive failure leaves
  the MF4 saved and reports the failure separately — NEVER corrupt the
  saved MF4.
- ``在 Analyzer 打开`` — enabled ONLY after the finalized save/archive
  path has completed and the file is non-empty on disk.

The auto-stop banner is shown when ``SessionSummary.auto_stop`` is True
("自动停止 · ring buffer 持续告警"), per the S4-fix Fix #6 contract.

Idempotency: ``QDialog.done`` is NOT idempotent on macOS Cocoa (see
``docs/lessons-learned/pyqt-ui/2026-04-26-popover-accept-deactivate-race.md``)
so accept/reject are wrapped in an ``_is_closing`` guard.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition.manifest import sha256_file
from mf4_analyzer.acquisition.preflight import PreflightResult, analyze_mf4
from mf4_analyzer.acquisition_capture.session import SessionSummary
from mf4_analyzer.ui_kit.message_box_buttons import fit_message_box_buttons_to_text

logger = logging.getLogger(__name__)


# Action constants — exact spec strings (the buttons MUST display these
# verbatim because tests / accessibility readers consume them).
ACTION_DISCARD = "丢弃（不归档）"
ACTION_SAVE_ONLY = "仅保存文件"
ACTION_SAVE_AND_ARCHIVE = "保存并归档"
ACTION_OPEN_ANALYZER = "在 Analyzer 打开"

# Auto-stop banner (S4-fix Fix #6).
AUTO_STOP_BANNER_TEXT = "自动停止 · ring buffer 持续告警"


@dataclass
class ReviewContext:
    """Inputs the review modal consumes; built by cockpit code.

    The modal does NOT compute these — it only displays them. The
    ``CockpitMainWindow._open_review_modal`` builds the context from the
    finalized writer + session summary.
    """

    mf4_path: Path
    sidecar_path: Path  # session_summary.json
    summary: SessionSummary
    preflight: PreflightResult
    preflight_sidecar_path: Path  # <basename>.preflight.json
    expected_channels: tuple[str, ...]
    # Optional project manifest target; when None, "保存并归档" reports
    # "no manifest configured" rather than crashing.
    manifest_path: Path | None = None
    # Vehicle / scenario hints used to seed the manifest entry. Default
    # empty so the demo path keeps working.
    vehicle: str = ""
    platform: str = ""
    scenario: str = ""


class ReviewModal(QDialog):
    """Review modal.

    The dialog is non-modal-friendly: it uses ``open()``-style semantics
    in production so the cockpit's event loop is not blocked, and exposes
    public methods for each action so tests can drive them directly
    (avoiding offscreen-Qt button-press flakiness).

    Signals:

    - ``analyzer_open_requested(str)`` — emitted with the MF4 path when
      the user clicks ``在 Analyzer 打开``. Cockpit listens and bridges
      to ``MainWindow.load_file(path)``.
    """

    analyzer_open_requested = pyqtSignal(str)

    def __init__(
        self,
        context: ReviewContext,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("acquisitionReviewModal")
        self.setWindowTitle("复盘")
        self.setModal(True)
        self._ctx = context
        # ``_is_closing`` guards the accept/reject race per
        # ``2026-04-26-popover-accept-deactivate-race.md``.
        self._is_closing = False
        # Tracks which action terminated the modal so the caller can route
        # the post-close flow.
        self._chosen_action: str | None = None
        # Tracks whether the file is finalized + (optionally) archived,
        # gating the ``在 Analyzer 打开`` button per spec §ReviewModal.
        self._archive_ok: bool = False
        self._save_ok: bool = False
        # Tracks whether the user has chosen to discard. After discard
        # the MF4 is deleted; analyzer-open must be disabled regardless
        # of save_ok.
        self._discarded: bool = False
        # Optional injection point for archive append (kept on the
        # instance so tests can swap a stub). Returns the appended entry
        # dict on success or raises on failure.
        self._archive_writer: Callable[[ReviewContext], dict] | None = None
        self._archive_failure_box: QMessageBox | None = None
        self._discard_confirm_box: QMessageBox | None = None

        self._build_ui()
        self._refresh_action_enabled()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # P0-2 fix: the modal must remain bounded on small screens and
        # never balloon off-screen when the preflight reports a long
        # ``missing_channels`` list. We give the dialog a size grip + a
        # usable minimum size, wrap the variable-height body in a
        # ``QScrollArea`` so it can scroll instead of pushing the
        # action buttons off the bottom, and render
        # ``missing_channels`` in a capped ``QListWidget`` rather than
        # joining the names into one ever-widening label.
        #
        # The save action MUST NOT call ``accept()`` (see
        # ``docs/lessons-learned/pyqt-ui/2026-05-15-save-action-must-not-close-gating-modal.md``):
        # the scroll wrapper does not introduce any new closure path.
        self.setSizeGripEnabled(True)
        self.setMinimumSize(420, 320)
        # Open at a compact default so the body's natural overflow path
        # (banner + header + preflight + capped missing-channels list)
        # surfaces the QScrollArea's vertical scrollbar when the
        # missing-channels list is long. The user can drag the size
        # grip to enlarge the modal.
        self.resize(560, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Auto-stop banner — only shown when summary.auto_stop is True.
        # Lives OUTSIDE the scroll area so the warning stays pinned at
        # the top regardless of body scroll position.
        if self._ctx.summary.auto_stop:
            banner = QLabel(AUTO_STOP_BANNER_TEXT, self)
            banner.setObjectName("reviewAutoStopBanner")
            banner.setStyleSheet(
                "background: #fef3c7; color: #92400e; "
                "padding: 6px 10px; border-radius: 4px; font-weight: 600;"
            )
            root.addWidget(banner)
            self._auto_stop_banner: QLabel | None = banner
        else:
            self._auto_stop_banner = None

        # Scrollable body host. ``widgetResizable=True`` so the inner
        # body widget tracks the viewport width and we never get an
        # unwanted horizontal scrollbar.
        scroll = QScrollArea(self)
        scroll.setObjectName("reviewBodyScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(scroll)
        body.setObjectName("reviewBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        # Header hierarchy (spec 2026-07-08 G4): title / facts / file name.
        title = QLabel("录制完成", body)
        title.setObjectName("reviewTitle")
        body_layout.addWidget(title)

        facts = QLabel(
            f"时长 {self._ctx.summary.duration_s:.2f} s · "
            f"接收 {self._ctx.summary.rx_count} 帧 · "
            f"丢帧 {self._ctx.summary.dropped_frames}",
            body,
        )
        facts.setObjectName("reviewFacts")
        facts.setWordWrap(True)
        body_layout.addWidget(facts)

        file_line = QLabel(self._ctx.mf4_path.name, body)
        file_line.setObjectName("reviewFileName")
        file_line.setWordWrap(True)
        body_layout.addWidget(file_line)

        # Preflight summary block. ``missing_channels`` is rendered as a
        # capped ``QListWidget`` so a 100-entry list does not blow up the
        # label width; the label retains the count for at-a-glance
        # context.
        pf = self._ctx.preflight
        pf_text_parts = [
            f"已选通道 {len(self._ctx.expected_channels)} · "
            f"缺失 {len(pf.missing_channels)} · "
            f"fs≈{pf.estimated_fs_hz:.1f} Hz",
        ]
        if pf.problems:
            pf_text_parts.append(
                "警告: " + " | ".join(pf.problems)
            )
        pf_label = QLabel("\n".join(pf_text_parts), body)
        pf_label.setObjectName("reviewPreflight")
        pf_label.setWordWrap(True)
        pf_label.setToolTip(
            f"rows={pf.rows} · MDF 通道总数 {len(pf.channels)}（含时间通道）"
        )
        body_layout.addWidget(pf_label)

        if pf.missing_channels:
            missing_list = self._build_missing_channels_list(
                pf.missing_channels, parent=body
            )
            body_layout.addWidget(missing_list)
            self._missing_channels_list: QListWidget | None = missing_list
        else:
            self._missing_channels_list = None

        # Inline status label — shows non-blocking confirmations like
        # "已保存" / "已归档" after the save/archive action completes.
        # The modal stays open after save/archive so the now-enabled
        # ``在 Analyzer 打开`` button is reachable; this label tells the
        # user the save half succeeded.
        self._status_label = QLabel("", body)
        self._status_label.setObjectName("reviewStatusLabel")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        body_layout.addWidget(self._status_label)

        # Spacer inside the scroll body so the visible content stays
        # top-aligned when the body is taller than its content.
        body_layout.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._body_scroll = scroll

        # Action buttons row — pinned OUTSIDE the scroll area so the
        # primary actions remain visible regardless of body scroll.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_discard = QPushButton(ACTION_DISCARD, self)
        self._btn_discard.setObjectName("reviewBtnDiscard")
        self._btn_discard.setProperty("role", "danger")
        self._btn_discard.clicked.connect(
            lambda _checked=False: self.do_discard()
        )
        btn_row.addWidget(self._btn_discard)
        btn_row.addSpacing(48)
        btn_row.addStretch(1)

        self._btn_save_only = QPushButton(ACTION_SAVE_ONLY, self)
        self._btn_save_only.setObjectName("reviewBtnSaveOnly")
        self._btn_save_only.clicked.connect(self.do_save_only)
        btn_row.addWidget(self._btn_save_only)

        self._btn_archive = QPushButton(ACTION_SAVE_AND_ARCHIVE, self)
        self._btn_archive.setObjectName("reviewBtnArchive")
        self._btn_archive.clicked.connect(self.do_archive)
        btn_row.addWidget(self._btn_archive)

        self._btn_open_analyzer = QPushButton(ACTION_OPEN_ANALYZER, self)
        self._btn_open_analyzer.setObjectName("reviewBtnOpenAnalyzer")
        self._btn_open_analyzer.clicked.connect(self.do_open_in_analyzer)
        btn_row.addWidget(self._btn_open_analyzer)

        self._btn_close = QPushButton("关闭", self)
        self._btn_close.setObjectName("reviewBtnClose")
        self._btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_close)

        root.addLayout(btn_row)

    def _build_missing_channels_list(
        self,
        missing_channels: tuple[str, ...],
        *,
        parent: QWidget,
    ) -> QListWidget:
        """Render ``missing_channels`` as a capped, scrollable list.

        Replaces the previous ``", ".join(...)`` rendering inside a
        single ``QLabel`` so a 100-entry list does not push the modal
        width past the screen. Selection is ``ExtendedSelection`` and
        a ``Ctrl+C`` shortcut bound to
        :meth:`_copy_missing_channels_to_clipboard` lets the user
        paste channel names into ticketing / A2L editors — a
        ``QListWidget`` has no native clipboard handler so the
        shortcut is mandatory for copy to work.
        """
        widget = QListWidget(parent)
        widget.setObjectName("reviewMissingChannelsList")
        widget.setMaximumHeight(180)
        widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        for name in missing_channels:
            widget.addItem(name)
        copy_shortcut = QShortcut(QKeySequence.Copy, widget)
        copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        copy_shortcut.activated.connect(self._copy_missing_channels_to_clipboard)
        return widget

    def _copy_missing_channels_to_clipboard(self) -> None:
        """Copy the selected rows of the missing-channels list to the
        system clipboard as a newline-joined string.

        When no rows are selected (e.g. the shortcut fires before the
        user clicks anything), the entire list is copied — matching
        what most users want when they press ``Ctrl+C`` on a short
        diagnostic readout.
        """
        widget = getattr(self, "_missing_channels_list", None)
        if widget is None:
            return
        selected = widget.selectedItems()
        if selected:
            names = [item.text() for item in selected]
        else:
            names = [widget.item(i).text() for i in range(widget.count())]
        if not names:
            return
        QApplication.clipboard().setText("\n".join(names))

    # ------------------------------------------------------------------
    # Action handlers — also callable directly from tests.
    # ------------------------------------------------------------------

    def do_discard(self, *, confirmed: bool = False) -> None:
        """``丢弃（不归档）`` — delete finalized MF4 + sidecar, return to idle.

        Spec §ReviewModal: this is always enabled. The deletion is
        explicit (no recovery), then the dialog closes. Discard is the
        "no save" terminal action so it routes through ``reject()`` —
        ``_on_review_modal_closed`` ignores the result code and routes
        every close back to ``ConnectedIdle`` via
        ``request_review_close``.
        """
        if not confirmed:
            self._show_discard_confirm()
            return

        self._chosen_action = ACTION_DISCARD
        # File-policy: explicitly remove the finalized artifacts. We
        # tolerate missing files (tests sometimes drive the modal without
        # a real file on disk).
        for p in (
            self._ctx.mf4_path,
            self._ctx.sidecar_path,
            self._ctx.preflight_sidecar_path,
        ):
            try:
                if Path(p).exists():
                    Path(p).unlink()
            except OSError as exc:
                logger.warning("review modal: discard could not remove %s: %s", p, exc)
        self._discarded = True
        self._save_ok = False
        self._archive_ok = False
        self._refresh_action_enabled()
        self.reject()

    def _show_discard_confirm(self) -> None:
        box = QMessageBox(self)
        box.setObjectName("reviewDiscardConfirm")
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("丢弃录制")
        box.setText(
            f"将删除 {self._ctx.mf4_path.name} 及其 sidecar，不可恢复。"
        )
        confirm_btn = box.addButton("确认删除", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setWindowModality(Qt.WindowModal)
        fit_message_box_buttons_to_text(box)

        def _handle_clicked(button) -> None:
            if button is confirm_btn:
                self.do_discard(confirmed=True)

        box.buttonClicked.connect(_handle_clicked)
        self._discard_confirm_box = box
        if self.isVisible():
            box.open()

    def do_save_only(self) -> None:
        """``仅保存文件`` — keep MF4 + summary; mark save-complete.

        CR3 fix: do NOT close the modal here. The save completes
        synchronously, ``_save_ok`` flips True, and ``在 Analyzer 打开``
        becomes enabled — the user must then explicitly click that
        button (which calls ``accept()``) or dismiss the modal (Esc /
        close → ``reject()``). An inline status label confirms the save
        without blocking further interaction.
        """
        self._chosen_action = ACTION_SAVE_ONLY
        self._save_ok = True
        # No SHA, no manifest write — the finalized MF4 stays where it
        # was finalized.
        self._refresh_action_enabled()
        self._set_status("已保存")

    def do_archive(self) -> None:
        """``保存并归档`` — compute SHA-256, append manifest entry, mark
        archive-complete. Archive failure leaves the MF4 saved and
        surfaces the failure separately (NEVER corrupts the MF4).

        CR3 fix: do NOT close the modal on success. ``_archive_ok``
        flips and ``在 Analyzer 打开`` becomes enabled; the user
        explicitly clicks Analyzer-open or dismisses the modal.
        """
        self._chosen_action = ACTION_SAVE_AND_ARCHIVE
        # File is finalized at this point — cockpit sequencing guarantees
        # so. Mark save-complete unconditionally.
        self._save_ok = True
        archive_error: Exception | None = None
        try:
            if self._archive_writer is not None:
                self._archive_writer(self._ctx)
            else:
                self._write_manifest_entry()
            self._archive_ok = True
        except Exception as exc:  # noqa: BLE001 — surface, don't corrupt
            archive_error = exc
            logger.exception("review modal: archive write failed")
            self._archive_ok = False
            # Surface separately (toast / dialog) — do NOT delete the MF4.
            self._show_archive_failure(exc)
        self._refresh_action_enabled()
        if archive_error is None:
            self._set_status("已归档")
        else:
            self._set_status("归档失败 · MF4 已保存")

    def do_open_in_analyzer(self) -> None:
        """``在 Analyzer 打开`` — request handoff via the public signal.

        Gating per spec §ReviewModal: enabled only after finalized save
        or archive. The button's enabled state already enforces this,
        but we double-check defensively so test-driven calls also obey.
        """
        if not self._can_open_in_analyzer():
            return
        self._chosen_action = ACTION_OPEN_ANALYZER
        # Emit the path; the cockpit slot is responsible for finding /
        # creating the Analyzer window and calling MainWindow.load_file.
        self.analyzer_open_requested.emit(str(self._ctx.mf4_path))
        self.accept()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _can_open_in_analyzer(self) -> bool:
        """Spec §ReviewModal: enabled only when finalized save/archive
        completed and the file is on disk."""
        if self._discarded:
            return False
        if not (self._save_ok or self._archive_ok):
            return False
        try:
            return self._ctx.mf4_path.exists() and self._ctx.mf4_path.stat().st_size > 0
        except OSError:
            return False

    def _refresh_action_enabled(self) -> None:
        # Discard / save / archive enabled unconditionally except after
        # discard (which deletes the file). After a successful
        # save/archive the buttons remain enabled — the user can still
        # click Discard to undo, or run archive after a save-only — but
        # CR3 keeps the simple gating: once the user picked Discard the
        # other actions are no-ops.
        self._btn_discard.setEnabled(not self._discarded)
        self._btn_save_only.setEnabled(not self._discarded)
        self._btn_archive.setEnabled(not self._discarded)
        self._btn_open_analyzer.setEnabled(self._can_open_in_analyzer())

    def _set_status(self, text: str) -> None:
        """Render an inline non-blocking confirmation in the modal body.

        Used by save/archive to confirm completion without closing the
        modal — the modal must stay open so ``在 Analyzer 打开`` is
        reachable (CR3 finding 6).
        """
        if not hasattr(self, "_status_label") or self._status_label is None:
            return
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))

    def _write_manifest_entry(self) -> None:
        """Append a new ``Mf4DatasetEntry`` to the project manifest.

        Uses the existing helpers in ``mf4_analyzer.acquisition.manifest``
        (``sha256_file`` for hashing). The manifest module is read-only
        with respect to entries (no public ``append`` helper), so we
        produce the JSON shape that ``load_manifest`` consumes back —
        loading the existing manifest, appending an entry, and writing
        it back via ``Path.write_text``.

        Spec §Persistence Contract `Relationship to manifest.json`:

        - ``issue_tags`` from ``summary.warnings``.
        - ``expected_channels`` from selected measurement names (passed
          in via ``ReviewContext``).
        - ``sha256`` computed during save.
        """
        if self._ctx.manifest_path is None:
            raise RuntimeError("no manifest configured for archive write")
        sha = sha256_file(self._ctx.mf4_path)
        entry_id = self._ctx.mf4_path.stem
        new_entry = {
            "id": entry_id,
            "path": str(self._ctx.mf4_path),
            "sets": ["acquisition_cockpit"],
            "path_kind": "local",
            "vehicle": self._ctx.vehicle,
            "platform": self._ctx.platform,
            "scenario": self._ctx.scenario,
            "issue_tags": list(self._ctx.summary.warnings),
            "expected_channels": list(self._ctx.expected_channels),
            "sha256": sha,
            "required": True,
        }
        # Read-modify-write the manifest. Encoding is explicit utf-8
        # (lesson: 2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows).
        manifest_path = Path(self._ctx.manifest_path)
        if manifest_path.exists():
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError(
                    f"manifest at {manifest_path} is not v1 — refusing to append"
                )
            entries = list(raw.get("entries") or [])
        else:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {"version": 1, "entries": []}
            entries = []
        entries.append(new_entry)
        raw["entries"] = entries
        manifest_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _show_archive_failure(self, exc: Exception) -> None:
        """Surface the archive error without aborting the save.

        Gated on ``isVisible()`` per
        ``docs/lessons-learned/pyqt-ui/2026-04-27-modal-from-qthread-finished-segfaults-offscreen.md``
        so headless tests don't open a nested modal in a
        ``qtbot.waitUntil`` loop.
        """
        if not self.isVisible():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("归档失败")
        box.setText(
            f"MF4 已保存，但归档写入失败: {exc}\n"
            f"已保存路径: {self._ctx.mf4_path}"
        )
        box.setWindowModality(Qt.WindowModal)
        if not box.buttons():
            box.setStandardButtons(QMessageBox.Ok)
        fit_message_box_buttons_to_text(box)
        self._archive_failure_box = box
        box.open()

    # ------------------------------------------------------------------
    # accept/reject overrides — idempotency guard
    # (lesson 2026-04-26-popover-accept-deactivate-race.md)
    # ------------------------------------------------------------------

    def accept(self) -> None:  # type: ignore[override]
        if self._is_closing:
            return
        self._is_closing = True
        super().accept()

    def reject(self) -> None:  # type: ignore[override]
        if self._is_closing:
            return
        self._is_closing = True
        super().reject()

    # ------------------------------------------------------------------
    # Introspection helpers (used by tests + cockpit)
    # ------------------------------------------------------------------

    @property
    def chosen_action(self) -> str | None:
        return self._chosen_action

    @property
    def save_ok(self) -> bool:
        return self._save_ok

    @property
    def archive_ok(self) -> bool:
        return self._archive_ok

    @property
    def discarded(self) -> bool:
        return self._discarded

    @property
    def context(self) -> ReviewContext:
        return self._ctx

    def is_open_in_analyzer_enabled(self) -> bool:
        """Public predicate matching the button's enabled state."""
        return self._btn_open_analyzer.isEnabled()


# ---------------------------------------------------------------------------
# Stop / flush / finalize sequence helpers.
# ---------------------------------------------------------------------------


@dataclass
class StopFlushFinalizeResult:
    """Return shape of :func:`run_stop_flush_finalize`.

    The cockpit consumes this to build a :class:`ReviewContext` and open
    the review modal. Tests inspect ``order`` to verify the sequence.

    ``selected_measurement_names`` preserves the *expected* channel-name
    tuple that was passed into diagnostics. The cockpit must use this
    exact tuple when building ``ReviewContext.expected_channels`` so the
    manifest records the selection contract, NOT
    ``PreflightResult.channels`` (which is just "what we ended up
    writing"). Using preflight channels here would make
    ``missing_channels`` permanently empty for archived files — CR3
    finding 4.
    """

    summary: SessionSummary
    sidecar_path: Path
    preflight: PreflightResult
    preflight_sidecar_path: Path
    sha256: str | None
    order: list[str]
    selected_measurement_names: tuple[str, ...] = ()


def run_stop_flush_finalize(
    *,
    controller,
    expected_channels: tuple[str, ...],
    compute_sha: bool = False,
    order_sink: list[str] | None = None,
) -> StopFlushFinalizeResult:
    """Execute the canonical stop/flush/finalize sequence.

    Spec §State Machine Contract ``Recording → ReviewModal`` requires
    these steps in this exact order:

    1. stop backend (via ``CaptureController.stop`` which itself flushes
       writer + closes handles per Stage 2).
    2. drain writer (folded into step 1 — controller's ``stop`` calls
       ``_stop_locked`` which drains the ring then finalizes).
    3. close file handles (also inside ``_stop_locked``).
    4. write session summary (``SessionSummary.write_sidecar``).
    5. if archive: compute SHA-256.
    6. run post-record diagnostics (``analyze_mf4``) and write
       ``<basename>.preflight.json`` sidecar.
    7. caller opens review modal.

    Steps are factored so tests can spy on ordering via ``order_sink``.
    Each step appends its name to the list passed in (default: internal
    list returned via ``StopFlushFinalizeResult.order``).
    """
    order = order_sink if order_sink is not None else []

    # Preserve the exact selection tuple used for diagnostics so the
    # cockpit can re-use it when building ReviewContext.expected_channels
    # (CR3 finding 4: the manifest's expected_channels must reflect what
    # was *selected*, not what was *written*).
    selected_names: tuple[str, ...] = tuple(expected_channels)

    # Step 1-3: stop the controller. The controller's internal
    # implementation drains the ring buffer and finalizes the writer
    # before returning the summary. The order entries are coalesced into
    # the three logical sub-steps so tests can assert them individually.
    order.append("stop_backend")
    order.append("drain_writer")
    order.append("close_handles")
    summary = controller.stop()

    # Step 4: write session summary sidecar.
    order.append("write_session_summary")
    mf4_path = Path(summary.output_mf4)
    sidecar_path = summary.write_sidecar(mf4_path)

    # Step 5: optional SHA.
    sha: str | None = None
    if compute_sha:
        order.append("compute_sha256")
        sha = sha256_file(mf4_path)

    # Step 6: post-record diagnostics + sidecar.
    order.append("post_record_diagnostics")
    pf = analyze_mf4(mf4_path, expected_channels=selected_names)
    preflight_sidecar = mf4_path.with_suffix(".preflight.json")
    preflight_sidecar.write_text(pf.to_json(), encoding="utf-8")

    return StopFlushFinalizeResult(
        summary=summary,
        sidecar_path=sidecar_path,
        preflight=pf,
        preflight_sidecar_path=preflight_sidecar,
        sha256=sha,
        order=order,
        selected_measurement_names=selected_names,
    )

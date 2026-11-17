"""Content-sized import progress window.

The dialog only renders a snapshot and emits a cancel intent. File,
session, and result ownership stay with the import coordinator. Geometry
uses the content purpose so a short window is not lifted to the workspace
floor. The first apply and the post-show frame correction share that purpose.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFontMetrics, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .control_style import CONTROL_HEIGHTS
from .dialog_geometry import (
    PURPOSE_CONTENT,
    Size,
    apply_plan,
    as_rect,
    client_budget,
    frame_insets_of,
    install_geometry_relayout,
    plan_geometry,
    resolve_available_rect,
)
from .message_dialog import outer_button_width


MARGIN_LEFT = 24
MARGIN_RIGHT = 24
MARGIN_TOP = 18
MARGIN_BOTTOM = 20
ROW_GAP = 8
ACTION_GAP = 16
PREFERRED_WIDTH = 420
SOFT_WIDTH_MAX = 560
_BAR_HEIGHT = 16

KIND_WAITING = "waiting"
KIND_READING = "reading"
KIND_STAGE = "stage"
KIND_HANDOFF = "handoff"
KIND_SUCCESS = "success"
KIND_PARTIAL = "partial"
KIND_FAILED = "failed"
KIND_CANCELLING = "cancelling"
KIND_CANCELLED = "cancelled"
KIND_WAITING_USER = "waiting_user"

_KINDS = frozenset({
    KIND_WAITING,
    KIND_READING,
    KIND_STAGE,
    KIND_HANDOFF,
    KIND_SUCCESS,
    KIND_PARTIAL,
    KIND_FAILED,
    KIND_CANCELLING,
    KIND_CANCELLED,
    KIND_WAITING_USER,
})
_TERMINAL_KINDS = frozenset({
    KIND_SUCCESS,
    KIND_PARTIAL,
    KIND_FAILED,
    KIND_CANCELLED,
})
_BUSY_KINDS = frozenset({
    KIND_WAITING,
    KIND_READING,
    KIND_HANDOFF,
    KIND_CANCELLING,
})


def format_elapsed(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"耗时 {whole // 60}:{whole % 60:02d}"


def _join(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


def _index_text(index: int, total: int) -> str:
    if index > 0 and total > 0:
        return f"当前第 {int(index)} 个/共 {int(total)} 个"
    return ""


def _stage_marks(fraction: float | None) -> tuple[int, int]:
    try:
        value = float(0.0 if fraction is None else fraction)
    except (TypeError, ValueError):
        value = 0.0
    if value != value:
        value = 0.0
    value = min(1.0, max(0.0, value))
    percent = max(0, min(100, int(round(value * 100))))
    current = max(0, min(1000, int(round(value * 1000))))
    return percent, current


@dataclass(frozen=True)
class ImportProgressSnapshot:
    """One rendering of a request. Dialog and status bar both read these fields."""

    kind: str
    title: str
    file_name: str
    full_path: str
    phase: str
    headline: str
    status_label: str
    indeterminate: bool
    bar_current: int
    bar_total: int
    cancel_enabled: bool
    action_label: str
    terminal: bool
    copy_text: str
    index: int = 0
    total: int = 0


def build_import_progress_snapshot(
    *,
    kind: str,
    title: str,
    file_name: str,
    full_path: str,
    index: int,
    total: int,
    phase: str,
    elapsed_s: float,
    stage_fraction: float | None,
    loaded: int = 0,
    failed: int = 0,
    message: str = "",
    action_label: str | None = None,
) -> ImportProgressSnapshot:
    """Map one kind onto labels and a bar. Callers do not keep a second copy."""
    if kind not in _KINDS:
        raise ValueError(f"unknown import progress kind {kind!r}")
    phase_text = str(phase or "").strip()
    elapsed = format_elapsed(elapsed_s)
    where = _index_text(index, total)
    loaded = max(0, int(loaded))
    failed = max(0, int(failed))
    terminal = kind in _TERMINAL_KINDS
    indeterminate = kind in _BUSY_KINDS
    bar_current = 0
    bar_total = 0
    if kind == KIND_CANCELLING:
        headline = "正在取消…"
    elif kind == KIND_CANCELLED:
        if loaded:
            headline = f"已取消，已保留 {loaded} 个已加载文件"
        else:
            headline = "已取消"
        bar_total = 100
    elif kind == KIND_WAITING_USER:
        headline = str(message or "等待处理")
        if elapsed:
            headline = _join(headline, elapsed)
        bar_total = 100
    elif kind == KIND_SUCCESS:
        done = f"已导入 {loaded} 个文件" if loaded else "导入完成"
        headline = _join(done, "100%")
        bar_current = 1000
        bar_total = 1000
    elif kind == KIND_PARTIAL:
        headline = f"已加载 {loaded} 个，失败 {failed} 个"
        bar_total = 100
    elif kind == KIND_FAILED:
        headline = f"导入失败，失败 {failed} 个" if failed else "导入失败"
        bar_total = 100
    elif kind == KIND_STAGE:
        percent, bar_current = _stage_marks(stage_fraction)
        bar_total = 1000
        headline = _join(where, f"当前阶段 {percent}%", phase_text, elapsed)
        indeterminate = False
    elif kind == KIND_HANDOFF:
        headline = _join(where, phase_text or "正在交接", elapsed)
    else:
        # Waiting and reading are busy. A file index is not a percent.
        headline = _join(where, phase_text, elapsed)
    if kind == KIND_CANCELLING:
        action = "正在取消…"
        enabled = False
    elif action_label:
        action = str(action_label)
        enabled = not terminal
    elif terminal:
        action = "关闭"
        enabled = True
    else:
        action = "取消导入"
        enabled = True
    if kind == KIND_SUCCESS:
        # The status bar appends its own percent from the same full bar.
        status_label = f"已导入 {loaded} 个文件" if loaded else "导入完成"
    elif kind == KIND_STAGE:
        percent, _current = _stage_marks(stage_fraction)
        status_label = _join(where, phase_text) or f"当前阶段 {percent}%"
    elif kind in _TERMINAL_KINDS or kind == KIND_WAITING_USER:
        status_label = headline
    else:
        status_label = _join(where, phase_text) or headline
    return ImportProgressSnapshot(
        kind=kind,
        title=str(title or "导入文件"),
        file_name=str(file_name or ""),
        full_path=str(full_path or ""),
        phase=phase_text,
        headline=headline,
        status_label=status_label,
        indeterminate=indeterminate,
        bar_current=int(bar_current),
        bar_total=int(bar_total),
        cancel_enabled=bool(enabled),
        action_label=action,
        terminal=terminal,
        copy_text=str(full_path or file_name or ""),
        index=int(index),
        total=int(total),
    )


class _PathLabel(QLabel):
    """One-line file name. The tooltip and copy text keep the full path."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display = ""
        self._full = ""
        self.setObjectName("importProgressFile")
        self.setTextFormat(Qt.PlainText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setWordWrap(False)

    def set_paths(self, display: str, full_path: str) -> None:
        self._display = str(display or "")
        self._full = str(full_path or display or "")
        self.setToolTip(self._full)
        self.setAccessibleDescription(self._full)
        self.elide()

    def full_text(self) -> str:
        return self._full

    def elide(self) -> None:
        width = self.contentsRect().width()
        if width <= 1:
            width = max(1, self.width())
        shown = self._display or self._full
        if not shown:
            self.setText("")
            return
        elided = QFontMetrics(self.font()).elidedText(shown, Qt.ElideMiddle, max(1, width))
        if self.text() != elided:
            self.setText(elided)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.elide()

    def sizeHint(self):  # noqa: N802 - Qt API
        metrics = QFontMetrics(self.font())
        return metrics.size(0, "文件.mf4")

    def minimumSizeHint(self):  # noqa: N802 - Qt API
        metrics = QFontMetrics(self.font())
        from PyQt5.QtCore import QSize
        return QSize(0, metrics.height())

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        modifiers = event.modifiers()
        copy = event.matches(QKeySequence.Copy) or (
            event.key() == Qt.Key_C and modifiers & (Qt.ControlModifier | Qt.MetaModifier)
        )
        if copy:
            QApplication.clipboard().setText(self._full)
            event.accept()
            return
        super().keyPressEvent(event)


class ImportProgressDialog(QDialog):
    """Lightweight progress window. Programmatic close does not emit cancel."""

    cancel_requested = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "导入文件",
        available_rect=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("importProgressDialog")
        self.setWindowTitle(title)
        self.setWindowModality(Qt.NonModal)
        # The title-bar help button has no handler on this window.
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumSize(0, 0)
        self._available_override = None if available_rect is None else as_rect(available_rect)
        self._snapshot: ImportProgressSnapshot | None = None
        self._cancel_sent = False
        self._allow_close = False
        self._layout_signature = None
        self._applying = False

        self.file_label = _PathLabel(self)
        self.phase_label = QLabel(self)
        self.phase_label.setObjectName("importProgressPhase")
        self.phase_label.setTextFormat(Qt.PlainText)
        self.phase_label.setWordWrap(True)
        self.phase_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.phase_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.phase_label.setMinimumWidth(0)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("importProgressBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(_BAR_HEIGHT)
        self.progress_bar.setMinimumWidth(0)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress_bar.setRange(0, 0)

        self.cancel_button = QPushButton("取消导入", self)
        self.cancel_button.setObjectName("importProgressCancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        self.cancel_button.setFocusPolicy(Qt.NoFocus)
        self.cancel_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.cancel_button.clicked.connect(self._emit_cancel_once)
        self._apply_button_metrics()

        root = QVBoxLayout(self)
        root.setContentsMargins(MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM)
        root.setSpacing(0)
        root.addWidget(self.file_label)
        root.addSpacing(ROW_GAP)
        root.addWidget(self.phase_label)
        root.addSpacing(ROW_GAP)
        root.addWidget(self.progress_bar)
        root.addSpacing(ACTION_GAP)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(0)
        footer.addStretch(1)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

        self._geometry = install_geometry_relayout(self, self._apply_geometry)

    def apply_snapshot(self, snapshot: ImportProgressSnapshot) -> None:
        self._snapshot = snapshot
        if snapshot.title:
            self.setWindowTitle(snapshot.title)
        self.file_label.set_paths(snapshot.file_name, snapshot.full_path or snapshot.copy_text)
        self.phase_label.setText(snapshot.headline)
        self._apply_bar(snapshot)
        if self.cancel_button.text() != snapshot.action_label:
            self.cancel_button.setText(snapshot.action_label)
        self.cancel_button.setEnabled(bool(snapshot.cancel_enabled))
        self._apply_button_metrics()
        signature = (
            snapshot.kind,
            snapshot.file_name,
            snapshot.phase,
            snapshot.action_label,
            snapshot.title,
            snapshot.index,
            snapshot.total,
            snapshot.terminal,
        )
        if signature != self._layout_signature:
            self._layout_signature = signature
            self._geometry.notify_content_changed()

    def relayout(self) -> None:
        self._apply_geometry()

    def set_available_rect(self, rect) -> None:
        self._available_override = None if rect is None else as_rect(rect)
        self.relayout()

    def dismiss(self) -> None:
        """Close without a cancel intent.

        ``QDialog.close`` emits a close that a user reads as cancel. Blocking
        signals first is what keeps a successful close from cancelling this
        request or the next one.
        """
        self._allow_close = True
        self.blockSignals(True)
        self.close()
        self.deleteLater()

    def reject(self) -> None:  # noqa: N802 - Qt API
        if self.signalsBlocked() or self._allow_close:
            super().reject()
            return
        self._emit_cancel_once()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Escape:
            self._emit_cancel_once()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.signalsBlocked() or self._allow_close:
            event.accept()
            super().closeEvent(event)
            return
        self._emit_cancel_once()
        event.ignore()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.file_label.elide()

    def _emit_cancel_once(self) -> None:
        if self._cancel_sent or self.signalsBlocked() or self._allow_close:
            return
        snapshot = self._snapshot
        if snapshot is not None and not snapshot.cancel_enabled:
            return
        self._cancel_sent = True
        self.cancel_requested.emit()

    def _apply_bar(self, snapshot: ImportProgressSnapshot) -> None:
        if snapshot.indeterminate or snapshot.bar_total <= 0:
            self.progress_bar.setRange(0, 0)
            return
        total = int(snapshot.bar_total)
        current = max(0, min(int(snapshot.bar_current), total))
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)

    def _apply_button_metrics(self) -> None:
        text = self.cancel_button.text() or "取消导入"
        metrics = self.cancel_button.fontMetrics()
        self.cancel_button.setMinimumWidth(outer_button_width(metrics, text))
        text_height = metrics.height() + 2 * 4 + 2
        height = CONTROL_HEIGHTS["base"]
        if text_height > height:
            height = text_height
        self.cancel_button.setFixedHeight(height)

    def _resolve_available(self):
        if self._available_override is not None:
            return self._available_override
        return resolve_available_rect(widget=self, parent=self.parentWidget())

    def _host_rect(self):
        parent = self.parentWidget()
        if parent is None:
            return None
        try:
            top = parent.window()
            if top is None:
                return None
            return as_rect(top.frameGeometry())
        except RuntimeError:
            return None

    def _apply_geometry(self) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            self._apply_button_metrics()
            available = self._resolve_available()
            insets = frame_insets_of(self)
            budget = client_budget(available, insets)
            max_w = max(1, int(budget.width))
            soft = min(SOFT_WIDTH_MAX, max_w)
            width = min(PREFERRED_WIDTH, soft)
            button_w = max(
                int(self.cancel_button.minimumWidth()),
                int(self.cancel_button.sizeHint().width()),
            )
            needed = button_w + MARGIN_LEFT + MARGIN_RIGHT
            if needed > width:
                width = min(soft, max(width, needed))
            width = max(1, min(width, max_w))
            content_w = max(1, width - MARGIN_LEFT - MARGIN_RIGHT)

            file_h = max(
                self.file_label.fontMetrics().height(),
                self.file_label.minimumSizeHint().height(),
            )
            self.file_label.setFixedHeight(file_h)
            phase_h = self.phase_label.heightForWidth(content_w)
            if phase_h <= 0:
                phase_h = self.phase_label.fontMetrics().height()
            phase_h = max(phase_h, self.phase_label.fontMetrics().height())
            self.phase_label.setFixedHeight(phase_h)
            button_h = max(CONTROL_HEIGHTS["base"], self.cancel_button.height())
            height = (
                MARGIN_TOP
                + file_h
                + ROW_GAP
                + phase_h
                + ROW_GAP
                + _BAR_HEIGHT
                + ACTION_GAP
                + button_h
                + MARGIN_BOTTOM
            )
            content_min = Size(min(width, max_w), min(height, max(1, int(budget.height))))
            plan = plan_geometry(
                available,
                Size(width, height),
                frame=insets,
                content_minimum=content_min,
                host=self._host_rect(),
            )
            apply_plan(self, plan, purpose=PURPOSE_CONTENT)
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self.file_label.elide()
        finally:
            self._applying = False

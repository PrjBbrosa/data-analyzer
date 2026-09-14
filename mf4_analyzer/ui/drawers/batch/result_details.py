"""Read-only Batch run-result projection and footer overlay panel."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


EMPTY_DETAIL_MESSAGE = "未提供详细原因"
_NARROW_WIDTH_PX = 640
_STATUS_LABELS = {
    "done": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
    "cancelled": "已取消",
    "resumed": "已恢复",
    "degraded": "已完成（降级）",
    "blocked": "未运行",
}


@dataclass(frozen=True)
class ResultDetailRow:
    row_key: tuple
    file_id: object
    source_identity: str
    file_name: str
    method: str
    signal: str
    input_signal: str
    output_signal: str
    status: str
    message: str
    warnings: tuple[str, ...]
    data_path: str | None
    image_path: str | None
    group_identity: str


def result_has_detail_payload(result) -> bool:
    if result is None:
        return False
    return bool(
        getattr(result, "items", None)
        or getattr(result, "render_groups", None)
        or getattr(result, "blocked", None)
        or getattr(result, "warnings", None)
    )


def _optional_path(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _copy_warnings(*groups) -> tuple[str, ...]:
    seen: list[str] = []
    for group in groups:
        for raw in group or ():
            text = str(raw).strip()
            if text and text not in seen:
                seen.append(text)
    return tuple(seen)


def _message_text(value) -> str:
    text = str(value or "").strip()
    return text or EMPTY_DETAIL_MESSAGE


def project_result_rows(result, *, generation) -> tuple[ResultDetailRow, ...]:
    """Freeze one BatchRunResult into display rows. Does not mutate the DTO."""
    if result is None:
        return ()
    items = tuple(getattr(result, "items", None) or ())
    groups = tuple(getattr(result, "render_groups", None) or ())
    blocked = tuple(getattr(result, "blocked", None) or ())
    run_warnings = tuple(getattr(result, "warnings", None) or ())
    group_owned_paths = {
        path
        for path in (
            _optional_path(getattr(group, "image_path", None))
            for group in groups
        )
        if path
    }
    rows: list[ResultDetailRow] = []
    for index, item in enumerate(items):
        task_id = str(getattr(item, "task_id", "") or "").strip()
        row_key = (generation, task_id) if task_id else (generation, index)
        image_path = _optional_path(getattr(item, "image_path", None))
        if image_path in group_owned_paths:
            image_path = None
        degraded = str(getattr(item, "degraded_reason", "") or "").strip()
        warnings = _copy_warnings(
            getattr(item, "warnings", None),
            (degraded,) if degraded else (),
        )
        rows.append(ResultDetailRow(
            row_key=row_key,
            file_id=getattr(item, "file_id", None),
            source_identity=str(getattr(item, "source_identity", "") or ""),
            file_name=str(getattr(item, "file_name", "") or ""),
            method=str(getattr(item, "method", "") or ""),
            signal=str(getattr(item, "signal", "") or ""),
            input_signal=str(getattr(item, "input_signal", "") or ""),
            output_signal=str(getattr(item, "output_signal", "") or ""),
            status=str(getattr(item, "status", "") or ""),
            message=_message_text(getattr(item, "message", "")),
            warnings=warnings,
            data_path=_optional_path(getattr(item, "data_path", None)),
            image_path=image_path,
            group_identity=str(getattr(item, "group_identity", "") or ""),
        ))
    for index, group in enumerate(groups):
        group_id = str(getattr(group, "group_id", "") or "").strip()
        identity = group_id or str(index)
        rows.append(ResultDetailRow(
            row_key=(generation, "group", identity),
            file_id=None,
            source_identity="",
            file_name="",
            method="",
            signal="",
            input_signal="",
            output_signal="",
            status=str(getattr(group, "status", "") or ""),
            message=_message_text(getattr(group, "message", "")),
            warnings=_copy_warnings(getattr(group, "warnings", None)),
            data_path=None,
            image_path=_optional_path(getattr(group, "image_path", None)),
            group_identity=identity,
        ))
    for index, reason in enumerate(blocked):
        rows.append(ResultDetailRow(
            row_key=(generation, "run", "blocked", index),
            file_id=None,
            source_identity="",
            file_name="",
            method="",
            signal="",
            input_signal="",
            output_signal="",
            status="blocked",
            message=_message_text(reason),
            warnings=(),
            data_path=None,
            image_path=None,
            group_identity="",
        ))
    for index, warning in enumerate(run_warnings):
        rows.append(ResultDetailRow(
            row_key=(generation, "run", "warning", index),
            file_id=None,
            source_identity="",
            file_name="",
            method="",
            signal="",
            input_signal="",
            output_signal="",
            status="done",
            message=_message_text(warning),
            warnings=_copy_warnings((warning,)),
            data_path=None,
            image_path=None,
            group_identity="",
        ))
    return tuple(rows)


def _display_status(row: ResultDetailRow) -> str:
    status = str(row.status or "")
    if status == "done" and row.warnings:
        if any("降级" in warning or "degraded" in warning.lower() for warning in row.warnings):
            return "已完成（降级）"
        return "已完成（警告）"
    if status not in _STATUS_LABELS:
        return status or EMPTY_DETAIL_MESSAGE
    return _STATUS_LABELS[status]


def _status_tone(row: ResultDetailRow) -> str:
    status = str(row.status or "")
    if status in {"failed", "cancelled"}:
        return "error"
    if status in {"skipped", "blocked", "degraded"} or (
        status == "done" and row.warnings
    ):
        return "skip"
    if status in {"done", "resumed"}:
        return "success"
    return "skip" if status else "success"


def format_row_clipboard(row: ResultDetailRow) -> str:
    lines = [
        f"状态: {_display_status(row)}",
        f"来源: {row.source_identity or row.file_name or '—'}",
        f"输入: {row.input_signal or row.signal or '—'}",
        f"输出: {row.output_signal or '—'}",
        f"原因: {row.message}",
    ]
    if row.warnings:
        lines.append("警告: " + "；".join(row.warnings))
    return "\n".join(lines)


def _default_row_index(rows: tuple[ResultDetailRow, ...]) -> int:
    for index, row in enumerate(rows):
        if row.status == "failed":
            return index
    for index, row in enumerate(rows):
        if row.status in {"skipped", "degraded", "blocked"} or row.warnings:
            return index
    return 0 if rows else -1


def _row_list_label(row: ResultDetailRow) -> str:
    status = _display_status(row)
    if row.row_key[1:2] == ("group",):
        name = row.group_identity or "渲染组"
        return f"{status}  渲染组 {name}"
    if row.row_key[1:2] == ("run",):
        return f"{status}  本次运行"
    parts = [part for part in (row.file_name, row.signal, row.method) if part]
    detail = " · ".join(parts) if parts else "任务"
    return f"{status}  {detail}"


class BatchResultDetailsPanel(QWidget):
    """Read-only overlay: task list on the left, selected body on the right."""

    artifactRequested = pyqtSignal(str)
    locateRequested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchResultDetails")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._rows: tuple[ResultDetailRow, ...] = ()
        self._previous_run = False
        self._output_locate_enabled = True
        self._frf_locate_enabled = False
        self._frf_locate_reason = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(8)

        header = QWidget(self)
        header.setObjectName("BatchResultDetailsHeader")
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(8)
        title = QLabel("任务详情", header)
        title.setObjectName("BatchResultDetailsTitle")
        self._caption = QLabel("本次运行结果", header)
        self._caption.setObjectName("BatchResultDetailsCaption")
        self._btn_close = QPushButton("收起", header)
        self._btn_close.setObjectName("BatchResultDetailsClose")
        self._btn_close.setProperty("role", "quiet")
        self._btn_close.setAutoDefault(False)
        self._btn_close.setDefault(False)
        self._btn_close.setCursor(Qt.PointingHandCursor)
        self._btn_close.clicked.connect(self.hide)
        head_lay.addWidget(title)
        head_lay.addWidget(self._caption, 1)
        head_lay.addWidget(self._btn_close)
        outer.addWidget(header)

        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.setObjectName("BatchResultDetailsSplitter")
        self._splitter.setChildrenCollapsible(False)

        self._list = QListWidget(self._splitter)
        self._list.setObjectName("BatchResultDetailsList")
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setTextElideMode(Qt.ElideRight)
        self._list.currentRowChanged.connect(self._on_current_row_changed)
        palette = self._list.palette()
        palette.setColor(QPalette.HighlightedText, QColor("#111827"))
        palette.setColor(QPalette.Highlight, QColor("#e9f2ff"))
        self._list.setPalette(palette)
        self._list.viewport().setPalette(palette)

        self._body_host = QWidget(self._splitter)
        self._body_host.setObjectName("BatchResultDetailsBodyHost")
        body_lay = QVBoxLayout(self._body_host)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(8)

        self._body_scroll = QScrollArea(self._body_host)
        self._body_scroll.setObjectName("BatchResultDetailsBody")
        self._body_scroll.setWidgetResizable(True)
        self._body_scroll.setFrameShape(QFrame.NoFrame)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_inner = QWidget(self._body_scroll)
        body_inner.setObjectName("BatchResultDetailsBodyInner")
        inner_lay = QVBoxLayout(body_inner)
        inner_lay.setContentsMargins(10, 8, 10, 8)
        inner_lay.setSpacing(6)
        self._status = QLabel(body_inner)
        self._status.setObjectName("BatchResultDetailsStatus")
        self._status.setWordWrap(True)
        self._source = QLabel(body_inner)
        self._source.setObjectName("BatchResultDetailsSource")
        self._source.setWordWrap(True)
        self._io = QLabel(body_inner)
        self._io.setObjectName("BatchResultDetailsIO")
        self._io.setWordWrap(True)
        self._message = QLabel(body_inner)
        self._message.setObjectName("BatchResultDetailsMessage")
        self._message.setWordWrap(True)
        self._message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._warnings = QLabel(body_inner)
        self._warnings.setObjectName("BatchResultDetailsWarnings")
        self._warnings.setWordWrap(True)
        self._frf_reason = QLabel(body_inner)
        self._frf_reason.setObjectName("BatchResultDetailsFrfReason")
        self._frf_reason.setWordWrap(True)
        self._frf_reason.hide()
        inner_lay.addWidget(self._status)
        inner_lay.addWidget(self._source)
        inner_lay.addWidget(self._io)
        inner_lay.addWidget(self._message)
        inner_lay.addWidget(self._warnings)
        inner_lay.addWidget(self._frf_reason)
        inner_lay.addStretch(1)
        self._body_scroll.setWidget(body_inner)
        body_lay.addWidget(self._body_scroll, 1)

        self._actions = QWidget(self._body_host)
        self._actions.setObjectName("BatchResultDetailsActions")
        self._actions.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        actions_lay = QHBoxLayout(self._actions)
        actions_lay.setContentsMargins(0, 0, 0, 0)
        actions_lay.setSpacing(8)
        self._btn_data = QPushButton("打开数据位置", self._actions)
        self._btn_image = QPushButton("打开图片位置", self._actions)
        self._btn_output = QPushButton("查看输出目录设置", self._actions)
        self._btn_frf = QPushButton("检查信号配对", self._actions)
        self._btn_copy = QPushButton("复制诊断", self._actions)
        for button in (
            self._btn_data, self._btn_image, self._btn_output,
            self._btn_frf, self._btn_copy,
        ):
            button.setProperty("role", "quiet")
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            button.setMinimumHeight(max(24, button.sizeHint().height()))
            actions_lay.addWidget(button)
        actions_lay.addStretch(1)
        self._btn_data.clicked.connect(self._on_data_clicked)
        self._btn_image.clicked.connect(self._on_image_clicked)
        self._btn_output.clicked.connect(self._on_output_clicked)
        self._btn_frf.clicked.connect(self._on_frf_clicked)
        self._btn_copy.clicked.connect(self._on_copy_clicked)
        body_lay.addWidget(self._actions, 0)

        self._splitter.addWidget(self._list)
        self._splitter.addWidget(self._body_host)
        self._splitter.setStretchFactor(0, 45)
        self._splitter.setStretchFactor(1, 55)
        outer.addWidget(self._splitter, 1)

        self.installEventFilter(self)
        self._list.installEventFilter(self)
        self._body_scroll.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt override
        if (
            event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Escape
            and self.isVisible()
        ):
            self._btn_close.click()
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        stacked = self.width() <= _NARROW_WIDTH_PX
        orientation = Qt.Vertical if stacked else Qt.Horizontal
        if self._splitter.orientation() != orientation:
            self._splitter.setOrientation(orientation)

    def rows(self) -> tuple[ResultDetailRow, ...]:
        return self._rows

    def selected_row(self) -> ResultDetailRow | None:
        index = self._list.currentRow()
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def caption_text(self) -> str:
        return self._caption.text()

    def set_previous_run(self, previous: bool) -> None:
        self._previous_run = bool(previous)
        self._caption.setText("上次运行结果" if self._previous_run else "本次运行结果")

    def set_locate_context(
        self,
        *,
        output_enabled: bool,
        frf_enabled: bool,
        frf_reason: str = "",
    ) -> None:
        self._output_locate_enabled = bool(output_enabled)
        self._frf_locate_enabled = bool(frf_enabled)
        self._frf_locate_reason = str(frf_reason or "")
        self._fill_actions(self.selected_row())

    def set_result(self, result, *, generation) -> None:
        if result is None:
            self.clear()
            return
        self._rows = project_result_rows(result, generation=generation)
        self._previous_run = False
        self._caption.setText("本次运行结果")
        self._rebuild_list(_default_row_index(self._rows))

    def clear(self) -> None:
        self._rows = ()
        self._previous_run = False
        self._caption.setText("本次运行结果")
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)
        self._fill_body(None)

    def _rebuild_list(self, selected: int) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for row in self._rows:
            item = QListWidgetItem(_row_list_label(row))
            tone = _status_tone(row)
            color = {
                "error": QColor("#a44541"),
                "skip": QColor("#94641b"),
                "success": QColor("#168065"),
            }.get(tone, QColor("#334155"))
            item.setForeground(color)
            self._list.addItem(item)
        if selected >= 0 and self._rows:
            self._list.setCurrentRow(selected)
        self._list.blockSignals(False)
        self._fill_body(self.selected_row())

    def _on_current_row_changed(self, index: int) -> None:
        if 0 <= index < len(self._rows):
            self._fill_body(self._rows[index])
        else:
            self._fill_body(None)

    def _fill_body(self, row: ResultDetailRow | None) -> None:
        if row is None:
            self._status.setText("没有可用详情")
            self._status.setProperty("tone", "")
            self._source.clear()
            self._io.clear()
            self._message.clear()
            self._message.setProperty("tone", "")
            self._warnings.clear()
            self._frf_reason.hide()
            self._fill_actions(None)
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            self._message.style().unpolish(self._message)
            self._message.style().polish(self._message)
            return
        tone = _status_tone(row)
        self._status.setText(_display_status(row))
        self._status.setProperty("tone", tone)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        source = row.source_identity or row.file_name or (
            f"渲染组 {row.group_identity}" if row.group_identity else "本次运行"
        )
        self._source.setText(f"来源: {source}")
        input_text = row.input_signal or row.signal or "—"
        output_text = row.output_signal or "—"
        self._io.setText(f"输入: {input_text}\n输出: {output_text}")
        self._message.setText(row.message)
        self._message.setProperty("tone", tone)
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
        if row.warnings:
            self._warnings.setText("警告: " + "；".join(row.warnings))
            self._warnings.show()
        else:
            self._warnings.clear()
            self._warnings.hide()
        self._fill_actions(row)

    def _fill_actions(self, row: ResultDetailRow | None) -> None:
        has_row = row is not None
        data_path = row.data_path if row is not None else None
        image_path = row.image_path if row is not None else None
        is_frf = bool(row is not None and str(row.method).strip().lower() == "frf")
        self._btn_data.setVisible(bool(data_path))
        self._btn_image.setVisible(bool(image_path))
        self._btn_output.setVisible(has_row)
        self._btn_output.setEnabled(has_row and self._output_locate_enabled)
        self._btn_frf.setVisible(is_frf)
        self._btn_frf.setEnabled(is_frf and self._frf_locate_enabled)
        self._btn_copy.setEnabled(has_row)
        if is_frf and not self._frf_locate_enabled and self._frf_locate_reason:
            self._frf_reason.setText(self._frf_locate_reason)
            self._frf_reason.show()
        else:
            self._frf_reason.hide()
            self._frf_reason.clear()

    def _on_data_clicked(self) -> None:
        row = self.selected_row()
        if row is None or not row.data_path:
            return
        self.artifactRequested.emit(row.data_path)

    def _on_image_clicked(self) -> None:
        row = self.selected_row()
        if row is None or not row.image_path:
            return
        self.artifactRequested.emit(row.image_path)

    def _on_output_clicked(self) -> None:
        self.locateRequested.emit("output")

    def _on_frf_clicked(self) -> None:
        self.locateRequested.emit("frf")

    def _on_copy_clicked(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        QApplication.clipboard().setText(format_row_clipboard(row))

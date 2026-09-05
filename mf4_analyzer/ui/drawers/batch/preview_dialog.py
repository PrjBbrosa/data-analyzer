"""Image-only representative-output preview for the Batch sheet."""
from __future__ import annotations

import re

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from mf4_analyzer.ui_kit.dialog_geometry import (
    fit_window,
    install_geometry_relayout,
)

#: 渲染层产出的警告可能带 ``slice.position_clamped: `` 这类机器标识前缀；
#: 界面上只保留冒号后的人话部分。前缀本身只由点分小写标识符构成、不含空格，
#: 借此和「data checksum unavailable: ...」这类本身就以自然语言开头、中途才
#: 出现冒号的英文提示区分开——后者不匹配这个模式，不会被误删。
_WARNING_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:\s*")

_PREVIEW_PREFERRED = (1040, 720)
_PREVIEW_CONTENT_MIN = (640, 420)
_IMAGE_FLOOR_PX = 72


def _humanize_warning(text: str) -> str:
    """去掉机器标识前缀，只留给用户看的部分。"""
    return _WARNING_PREFIX_RE.sub("", text, count=1)


def format_batch_run_warnings(
    warnings,
    *,
    max_visible: int = 3,
    style: str = "block",
) -> str:
    """Render run/item warnings for toast, footer, and task-list tooltips.

    More than ``max_visible`` unique warnings collapse to a manifest pointer
    so the modal/footer stay readable. Humanizer regex is intentionally
    unchanged — statistics diagnostics now arrive as message+suggestion text.
    """
    seen: list[str] = []
    for raw in warnings or ():
        text = _humanize_warning(str(raw).strip())
        if text and text not in seen:
            seen.append(text)
    if not seen:
        return ""
    if len(seen) > max_visible:
        return f"{len(seen)} 条警告，详见 manifest"
    if style == "inline":
        return "；".join(seen)
    return "\n".join(f"• {line}" for line in seen)


class _BoundedScrollArea(QScrollArea):
    """Scroll area whose size hints ignore unbounded inner content height."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setMinimumSize(0, 0)

    def sizeHint(self):  # noqa: N802
        inner = self.widget()
        height = 0 if inner is None else max(0, inner.sizeHint().height())
        cap = self.maximumHeight()
        if cap < 16777215:
            height = min(height, cap)
        return QSize(0, height)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(0, 0)


class BatchPreviewDialog(QDialog):
    """Modal chrome around a PNG; the chrome is never part of the image."""

    regenerate_requested = pyqtSignal()
    run_all_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchPreviewDialog")
        self.setWindowTitle("代表最终图预览")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._busy = False
        self._layout_ready = False
        self._source_pixmap = QPixmap()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        self._facts = QLabel(self)
        self._facts.setObjectName("batchPreviewFacts")
        self._facts.setWordWrap(True)
        self._facts.setMinimumHeight(0)
        self._warnings = QLabel(self)
        self._warnings.setObjectName("batchPreviewWarnings")
        self._warnings.setWordWrap(True)
        self._warnings.setMinimumHeight(0)
        self._warnings.hide()
        self._status = QLabel(self)
        self._status.setObjectName("batchPreviewStatus")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(0)

        body = QWidget(self)
        body.setObjectName("batchPreviewBodyInner")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        body_layout.addWidget(self._facts)
        body_layout.addWidget(self._warnings)
        body_layout.addWidget(self._status)
        self._body_inner = body
        self._body_scroll = _BoundedScrollArea(self)
        self._body_scroll.setObjectName("batchPreviewBody")
        self._body_scroll.setWidget(body)
        self._body_scroll.setMaximumHeight(160)
        root.addWidget(self._body_scroll, 0)

        self._image = QLabel(self)
        self._image.setObjectName("batchPreviewImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(0, 0)
        self._image.setStyleSheet("background:#f8fafc; border:1px solid #dce4ef;")
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("batchPreviewImageScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._image)
        self._scroll.setMinimumSize(0, 0)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._scroll, 1)

        self._footer = QWidget(self)
        self._footer.setObjectName("batchPreviewFooter")
        self._footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        actions = QHBoxLayout(self._footer)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self._btn_back = QPushButton("返回修改", self._footer)
        self._btn_back.clicked.connect(self.reject)
        actions.addWidget(self._btn_back)
        actions.addStretch(1)
        self._btn_regenerate = QPushButton("重新生成", self._footer)
        self._btn_regenerate.setProperty("role", "secondary")
        self._btn_regenerate.clicked.connect(self.regenerate_requested)
        actions.addWidget(self._btn_regenerate)
        self._btn_run_all = QPushButton("运行全部", self._footer)
        self._btn_run_all.setDefault(True)
        self._btn_run_all.setProperty("role", "primary")
        self._btn_run_all.clicked.connect(self.run_all_requested)
        actions.addWidget(self._btn_run_all)
        self._btn_cancel = QPushButton("取消生成", self._footer)
        self._btn_cancel.setProperty("role", "danger")
        self._btn_cancel.clicked.connect(self.cancel_requested)
        self._btn_cancel.hide()
        actions.addWidget(self._btn_cancel)
        root.addWidget(self._footer, 0)

        self._layout_ready = True
        install_geometry_relayout(self, self._fit_to_work_area)
        self._fit_to_work_area()

    def set_loading(self, facts: str) -> None:
        self._busy = True
        self._facts.setText(facts)
        self._set_warnings(())
        self._status.setText("正在读取来源并生成代表最终图…")
        self._image.clear()
        self._source_pixmap = QPixmap()
        self._btn_back.setEnabled(False)
        self._btn_regenerate.setEnabled(False)
        self._btn_run_all.setEnabled(False)
        self._btn_cancel.show()
        self._fit_to_work_area()

    def set_result(self, result) -> None:
        self._busy = False
        self._btn_back.setEnabled(True)
        self._btn_regenerate.setEnabled(True)
        self._btn_run_all.setEnabled(True)
        self._btn_cancel.hide()
        self._set_warnings(getattr(result, "warnings", ()) or ())
        image_path = str(getattr(result, "image_path", "") or "")
        if not image_path:
            self._status.setText(
                str(getattr(result, "message", "") or "未能生成代表图")
            )
            self._fit_to_work_area()
            return
        self._status.setText("")
        self._source_pixmap = QPixmap(image_path)
        self._facts.setText(
            f"{getattr(result, 'display_name', '')} · "
            f"已读取 {int(getattr(result, 'loaded_source_count', 0))} 个来源 · 临时图片"
        )
        self._fit_to_work_area()

    def set_cancelled(self) -> None:
        self._busy = False
        self._set_warnings(())
        self._status.setText("已取消代表图生成")
        self._btn_back.setEnabled(True)
        self._btn_regenerate.setEnabled(True)
        self._btn_run_all.setEnabled(True)
        self._btn_cancel.hide()
        self._fit_to_work_area()

    def _set_warnings(self, warnings) -> None:
        """按序去重、去掉机器标识前缀后逐条列出；没有警告时整块隐藏、不占位。"""
        text = format_batch_run_warnings(warnings, max_visible=10**9, style="block")
        if not text:
            self._warnings.clear()
            self._warnings.hide()
            self._warnings.updateGeometry()
            return
        self._warnings.setText(text)
        self._warnings.show()
        self._warnings.updateGeometry()

    def closeEvent(self, event):  # noqa: N802
        if self._busy:
            self.cancel_requested.emit()
            event.ignore()
            return
        super().closeEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._fit_to_work_area()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._fit_image()

    def _fit_to_work_area(self) -> None:
        if not self._layout_ready:
            return
        # Long warning lists must not keep a previous content-driven floor.
        self.setMinimumSize(0, 0)
        self._body_scroll.setMinimumSize(0, 0)
        self._scroll.setMinimumSize(0, 0)
        parent = self.parentWidget()
        fit_window(
            self,
            _PREVIEW_PREFERRED,
            parent=parent,
            content_minimum=_PREVIEW_CONTENT_MIN,
            clamp_width_to_parent=bool(self.isModal() and parent is not None),
        )
        self._constrain_body_to_client(self.height())
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self._fit_image()

    def _constrain_body_to_client(self, client_height: int) -> None:
        layout = self.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        footer_h = max(self._footer.sizeHint().height(), self._footer.minimumSizeHint().height())
        chrome = margins.top() + margins.bottom() + layout.spacing() * 2 + footer_h
        leftover = max(0, int(client_height) - chrome)
        if leftover <= 0:
            self._body_scroll.setMaximumHeight(0)
            return
        image_floor = min(_IMAGE_FLOOR_PX, leftover // 2)
        self._body_scroll.setMaximumHeight(max(0, leftover - image_floor))
        self._body_scroll.updateGeometry()

    def _fit_image(self) -> None:
        if self._source_pixmap.isNull():
            return
        size = self._scroll.viewport().size()
        if size.width() <= 0 or size.height() <= 0:
            return
        self._image.setPixmap(self._source_pixmap.scaled(
            size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))

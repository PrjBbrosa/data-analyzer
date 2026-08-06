"""Image-only representative-output preview for the Batch sheet."""
from __future__ import annotations

import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from ._geometry import fit_dialog_to_available_screen

#: 渲染层产出的警告可能带 ``slice.position_clamped: `` 这类机器标识前缀；
#: 界面上只保留冒号后的人话部分。前缀本身只由点分小写标识符构成、不含空格，
#: 借此和「data checksum unavailable: ...」这类本身就以自然语言开头、中途才
#: 出现冒号的英文提示区分开——后者不匹配这个模式，不会被误删。
_WARNING_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:\s*")


def _humanize_warning(text: str) -> str:
    """去掉机器标识前缀，只留给用户看的部分。"""
    return _WARNING_PREFIX_RE.sub("", text, count=1)


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
        fit_dialog_to_available_screen(
            self, parent, 1040, 720, min_w=640, min_h=420,
        )
        self._busy = False
        self._source_pixmap = QPixmap()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        self._facts = QLabel(self)
        self._facts.setObjectName("batchPreviewFacts")
        self._facts.setWordWrap(True)
        root.addWidget(self._facts)
        self._warnings = QLabel(self)
        self._warnings.setObjectName("batchPreviewWarnings")
        self._warnings.setWordWrap(True)
        self._warnings.hide()
        root.addWidget(self._warnings)
        self._status = QLabel(self)
        self._status.setObjectName("batchPreviewStatus")
        self._status.setAlignment(Qt.AlignCenter)
        root.addWidget(self._status)

        self._image = QLabel(self)
        self._image.setObjectName("batchPreviewImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(640, 420)
        self._image.setStyleSheet("background:#f8fafc; border:1px solid #dce4ef;")
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._image)
        root.addWidget(self._scroll, 1)

        actions = QHBoxLayout()
        self._btn_back = QPushButton("返回修改", self)
        self._btn_back.clicked.connect(self.reject)
        actions.addWidget(self._btn_back)
        actions.addStretch(1)
        self._btn_regenerate = QPushButton("重新生成", self)
        self._btn_regenerate.setProperty("role", "accent")
        self._btn_regenerate.clicked.connect(self.regenerate_requested)
        actions.addWidget(self._btn_regenerate)
        self._btn_run_all = QPushButton("运行全部", self)
        self._btn_run_all.setDefault(True)
        self._btn_run_all.setProperty("role", "primary")
        self._btn_run_all.clicked.connect(self.run_all_requested)
        actions.addWidget(self._btn_run_all)
        self._btn_cancel = QPushButton("取消生成", self)
        self._btn_cancel.setProperty("role", "destructive")
        self._btn_cancel.clicked.connect(self.cancel_requested)
        self._btn_cancel.hide()
        actions.addWidget(self._btn_cancel)
        root.addLayout(actions)

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
            return
        self._status.setText("")
        self._source_pixmap = QPixmap(image_path)
        self._fit_image()
        self._facts.setText(
            f"{getattr(result, 'display_name', '')} · "
            f"已读取 {int(getattr(result, 'loaded_source_count', 0))} 个来源 · 临时图片"
        )

    def set_cancelled(self) -> None:
        self._busy = False
        self._set_warnings(())
        self._status.setText("已取消代表图生成")
        self._btn_back.setEnabled(True)
        self._btn_regenerate.setEnabled(True)
        self._btn_run_all.setEnabled(True)
        self._btn_cancel.hide()

    def _set_warnings(self, warnings) -> None:
        """按序去重、去掉机器标识前缀后逐条列出；没有警告时整块隐藏、不占位。"""
        seen: list[str] = []
        for raw in warnings:
            text = _humanize_warning(str(raw).strip())
            if text and text not in seen:
                seen.append(text)
        if not seen:
            self._warnings.clear()
            self._warnings.hide()
            return
        self._warnings.setText("\n".join(f"• {line}" for line in seen))
        self._warnings.show()

    def closeEvent(self, event):  # noqa: N802
        if self._busy:
            self.cancel_requested.emit()
            event.ignore()
            return
        super().closeEvent(event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._fit_image()

    def _fit_image(self) -> None:
        if self._source_pixmap.isNull():
            return
        size = self._scroll.viewport().size()
        self._image.setPixmap(self._source_pixmap.scaled(
            size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))

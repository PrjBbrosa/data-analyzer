"""Floating copy-preview thumbnail for copied chart images."""

from __future__ import annotations

import time

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class CopyThumbnail(QWidget):
    """Small bottom-right preview shown after an image is copied."""

    clicked = pyqtSignal(QPixmap)

    _AUTO_HIDE_MS = 3000
    _MARGIN = 18
    _PREVIEW_SIZE = QSize(220, 124)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("copyThumbnail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._original_pixmap = QPixmap()
        self._remaining_ms = self._AUTO_HIDE_MS
        self._deadline = 0.0

        self._preview = QLabel(self)
        self._preview.setObjectName("copyThumbnailPreview")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setFixedSize(self._PREVIEW_SIZE)
        self._preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._close = QPushButton("×", self)
        self._close.setObjectName("copyThumbnailClose")
        self._close.setFixedSize(22, 22)
        self._close.setCursor(Qt.ArrowCursor)
        self._close.setFocusPolicy(Qt.NoFocus)
        self._close.clicked.connect(self.dismiss)

        self._progress = QProgressBar(self)
        self._progress.setObjectName("copyThumbnailCountdown")
        self._progress.setRange(0, self._AUTO_HIDE_MS)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addStretch(1)
        header.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._preview)
        layout.addWidget(self._progress)

        self.setStyleSheet(
            """
            QWidget#copyThumbnail {
                background: #ffffff;
                border: 1px solid #dfe5ee;
                border-radius: 10px;
            }
            QLabel#copyThumbnailPreview {
                background: #f7f9fc;
                border: 1px solid #dfe5ee;
                border-radius: 8px;
            }
            QPushButton#copyThumbnailClose {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #667085;
                font-size: 15px;
                font-weight: 600;
                padding: 0;
            }
            QPushButton#copyThumbnailClose:hover {
                background: #eef4ff;
                color: #1769e0;
            }
            QProgressBar#copyThumbnailCountdown {
                background: #edf2f7;
                border: none;
                border-radius: 2px;
            }
            QProgressBar#copyThumbnailCountdown::chunk {
                background: #1769e0;
                border-radius: 2px;
            }
            """
        )

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(50)
        self._progress_timer.timeout.connect(self._update_progress)

        if parent is not None:
            parent.installEventFilter(self)

        self.hide()

    def present(self, pix: QPixmap):
        """Show a scaled preview while retaining the original pixmap."""
        self._original_pixmap = pix
        preview = pix.scaled(
            self._PREVIEW_SIZE,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._preview.setPixmap(preview)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._start_countdown(self._AUTO_HIDE_MS)

    def dismiss(self):
        """Hide the thumbnail and stop active timers."""
        self._hide_timer.stop()
        self._progress_timer.stop()
        self.hide()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._pause_countdown()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.isVisible():
            self._start_countdown(self._remaining_ms)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._original_pixmap.isNull():
            self.clicked.emit(self._original_pixmap)
            event.accept()
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self._reposition()
        return super().eventFilter(watched, event)

    def _start_countdown(self, duration_ms: int):
        self._remaining_ms = max(1, int(duration_ms))
        self._deadline = time.monotonic() + self._remaining_ms / 1000.0
        self._progress.setValue(self._remaining_ms)
        self._hide_timer.start(self._remaining_ms)
        self._progress_timer.start()

    def _pause_countdown(self):
        if not self._hide_timer.isActive():
            return
        remaining = self._hide_timer.remainingTime()
        self._remaining_ms = max(1, remaining)
        self._hide_timer.stop()
        self._progress_timer.stop()
        self._progress.setValue(self._remaining_ms)

    def _update_progress(self):
        remaining = int((self._deadline - time.monotonic()) * 1000)
        self._remaining_ms = max(0, remaining)
        self._progress.setValue(self._remaining_ms)
        if self._remaining_ms <= 0:
            self._progress_timer.stop()

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        x = max(0, parent.width() - self.width() - self._MARGIN)
        y = max(0, parent.height() - self.height() - self._MARGIN)
        self.move(x, y)

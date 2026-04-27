"""Output column for the batch dialog.

Mirrors the pre-W4 ``batch_sheet.py`` output group (recovered from commit
``ad28d29~1``): directory ``QLineEdit`` + 选择… ``QPushButton`` opening
``QFileDialog.getExistingDirectory``, ``chk_data`` / ``chk_image`` checkboxes,
and a ``csv``/``xlsx`` format ``QComboBox``.

Note: ``BatchOutput`` in ``mf4_analyzer.batch`` does NOT carry a ``directory``
field — the directory is owned by this panel and threaded into
``BatchRunner.run`` separately. ``apply_outputs`` therefore only consumes the
three persisted fields (``export_data``, ``export_image``, ``data_format``).
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ....batch import BatchOutput


class OutputPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchOutputPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        title = QLabel("OUTPUT")
        title.setStyleSheet("color:#f59e0b;font-weight:600;font-size:13px;")
        outer.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        # Directory
        self._dir_edit = QLineEdit(self)
        self._dir_edit.setText(str(Path.home() / "Desktop" / "mf4_batch_output"))
        self._btn_browse = QPushButton("选择…", self)
        self._btn_browse.clicked.connect(self._choose_dir)
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(self._btn_browse)
        form.addRow("输出目录", dir_row)

        # Export checkboxes
        self._chk_data = QCheckBox("数据文件", self)
        self._chk_data.setChecked(True)
        self._chk_image = QCheckBox("图片", self)
        self._chk_image.setChecked(True)
        chk_row = QHBoxLayout()
        chk_row.setContentsMargins(0, 0, 0, 0)
        chk_row.addWidget(self._chk_data)
        chk_row.addWidget(self._chk_image)
        chk_row.addStretch(1)
        form.addRow("导出内容", chk_row)

        # Format
        self._combo_format = QComboBox(self)
        self._combo_format.addItems(["csv", "xlsx"])
        form.addRow("数据格式", self._combo_format)
        outer.addLayout(form)
        outer.addStretch(1)

        # Wiring
        self._dir_edit.textChanged.connect(lambda *_: self.changed.emit())
        self._chk_data.toggled.connect(lambda *_: self.changed.emit())
        self._chk_image.toggled.connect(lambda *_: self.changed.emit())
        self._combo_format.currentTextChanged.connect(lambda *_: self.changed.emit())

    # ------------------------------------------------------------------
    def _choose_dir(self) -> None:
        start = self._dir_edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if path:
            self._dir_edit.setText(path)

    # ------------------------------------------------------------------
    def directory(self) -> str:
        return self._dir_edit.text().strip()

    def export_data(self) -> bool:
        return bool(self._chk_data.isChecked())

    def export_image(self) -> bool:
        return bool(self._chk_image.isChecked())

    def data_format(self) -> str:
        return self._combo_format.currentText()

    # ------------------------------------------------------------------
    def apply_directory(self, path: str) -> None:
        self._dir_edit.setText(str(path or ""))

    def apply_outputs(self, out: BatchOutput) -> None:
        if out is None:
            return
        self._chk_data.setChecked(bool(out.export_data))
        self._chk_image.setChecked(bool(out.export_image))
        idx = self._combo_format.findText(str(out.data_format))
        if idx >= 0:
            self._combo_format.setCurrentIndex(idx)

"""BatchSheet — pipeline-style batch dialog (placeholder shell, Wave 4)."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ....batch import AnalysisPreset
from .pipeline_strip import PipelineStrip


class BatchSheet(QDialog):
    def __init__(self, parent, files, current_preset=None):
        super().__init__(parent)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("批处理分析")
        self.resize(1080, 760)
        self._files = files
        self._current_preset = current_preset

        root = QVBoxLayout(self)

        # Toolbar (placeholder buttons, Wave 7 wires)
        bar = QHBoxLayout()
        bar.addStretch(1)
        for label in ("从当前单次填入", "导入 preset…", "导出 preset…"):
            b = QPushButton(label)
            b.setEnabled(False)  # enabled in Wave 7
            bar.addWidget(b)
        root.addLayout(bar)

        # Pipeline strip
        self.strip = PipelineStrip(self)
        root.addWidget(self.strip)

        # Detail placeholder (Waves 5-6)
        detail = QWidget(self)
        detail_lay = QHBoxLayout(detail)
        for txt in ("INPUT 详情", "ANALYSIS 详情", "OUTPUT 详情"):
            placeholder = QLabel(txt)
            placeholder.setStyleSheet(
                "background:#fff;border:1px solid #cbd5e1;border-radius:10px;"
                "padding:14px;color:#94a3b8;"
            )
            detail_lay.addWidget(placeholder, 1)
        root.addWidget(detail, 1)

        # Footer
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("运行")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_preset(self):
        # TODO Wave 5+: assemble from real input/analysis/output panels
        return AnalysisPreset.free_config(name="placeholder", method="fft")

    def output_dir(self) -> str:
        # TODO Wave 5+: pull from real output panel
        return str(Path.home() / "Desktop" / "mf4_batch_output")

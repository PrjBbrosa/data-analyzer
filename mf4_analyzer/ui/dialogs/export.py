"""Export dialog: pick channels for the Excel export."""
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt


class ExportDialog(QDialog):
    def __init__(self, parent, chs):
        super().__init__(parent)
        self.setWindowTitle("导出Excel");
        self.setMinimumSize(280, 300)
        layout = QVBoxLayout(self)
        self.list_ch = QListWidget()
        for ch in chs:
            item = QListWidgetItem(ch);
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable);
            item.setCheckState(Qt.Checked)
            self.list_ch.addItem(item)
        layout.addWidget(self.list_ch)
        self.chk_time = QCheckBox("包含时间列");
        self.chk_time.setChecked(True);
        layout.addWidget(self.chk_time)
        self.chk_range = QCheckBox("仅导出选定范围");
        layout.addWidget(self.chk_range)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept);
        bb.rejected.connect(self.reject);
        layout.addWidget(bb)

    def get_selected(self):
        return [self.list_ch.item(i).text() for i in range(self.list_ch.count()) if
                self.list_ch.item(i).checkState() == Qt.Checked]

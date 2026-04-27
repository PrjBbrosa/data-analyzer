"""
图标方案对比工具 — 直接运行查看三套候选方案
用法: .venv/bin/python tools/icon_compare.py
"""
import sys
import qtawesome as qta
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QToolButton, QFrame
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont

SLOTS = [
    ("home",    "回首页"),
    ("back",    "上一视图"),
    ("forward", "下一视图"),
    ("pan",     "平移"),
    ("zoom",    "缩放框选"),
    ("trend",   "自动缩放"),
    ("copy",    "复制图表"),
    ("save",    "保存图表"),
]

SCHEMES = {
    "方案 A — Font Awesome 5 Solid": {
        "home":    "fa5s.home",
        "back":    "fa5s.arrow-left",
        "forward": "fa5s.arrow-right",
        "pan":     "fa5s.arrows-alt",
        "zoom":    "fa5s.search",
        "trend":   "fa5s.expand-arrows-alt",
        "copy":    "fa5s.copy",
        "save":    "fa5s.save",
    },
    "方案 B — Material Design Icons": {
        "home":    "mdi.home",
        "back":    "mdi.arrow-left",
        "forward": "mdi.arrow-right",
        "pan":     "mdi.cursor-move",
        "zoom":    "mdi.magnify-plus-outline",
        "trend":   "mdi.chart-line",
        "copy":    "mdi.content-copy",
        "save":    "mdi.content-save-outline",
    },
    "方案 C — Font Awesome 6 Solid（工程感）": {
        "home":    "fa6s.house",
        "back":    "fa6s.rotate-left",
        "forward": "fa6s.rotate-right",
        "pan":     "fa6s.up-down-left-right",
        "zoom":    "fa6s.magnifying-glass-plus",
        "trend":   "fa6s.maximize",
        "copy":    "fa6s.copy",
        "save":    "fa6s.floppy-disk",
    },
}

ICON_COLOR   = "#374151"
ACTIVE_COLOR = "#2563eb"
BTN_SIZE     = QSize(32, 32)
ICON_SIZE    = QSize(18, 18)


def make_slot(icon_key: str, label: str, active: bool = False) -> QWidget:
    col_w = QWidget()
    col = QVBoxLayout(col_w)
    col.setSpacing(2)
    col.setContentsMargins(0, 0, 0, 0)

    btn = QToolButton()
    btn.setFixedSize(BTN_SIZE)
    btn.setIconSize(ICON_SIZE)
    btn.setToolTip(label)
    color = ACTIVE_COLOR if active else ICON_COLOR
    try:
        btn.setIcon(qta.icon(icon_key, color=color))
    except Exception:
        btn.setText("?")

    border = "#93c5fd" if active else "#e5e7eb"
    bg     = "#eff6ff" if active else "#ffffff"
    btn.setStyleSheet(f"""
        QToolButton {{
            border: 1px solid {border};
            border-radius: 6px;
            background: {bg};
        }}
        QToolButton:hover {{
            background: #f0f4ff;
            border-color: #93c5fd;
        }}
    """)

    lbl = QLabel(label)
    lbl.setAlignment(Qt.AlignHCenter)
    lbl.setStyleSheet("color:#9ca3af; font-size:9px;")

    col.addWidget(btn, alignment=Qt.AlignHCenter)
    col.addWidget(lbl, alignment=Qt.AlignHCenter)
    return col_w


def make_row(scheme_name: str, icons: dict) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(
        "QFrame { background:#f8fafc; border-radius:10px; "
        "border: 1px solid #e2e8f0; }"
    )
    outer = QVBoxLayout(frame)
    outer.setSpacing(8)
    outer.setContentsMargins(14, 10, 14, 12)

    title = QLabel(scheme_name)
    f = QFont()
    f.setBold(True)
    f.setPointSize(11)
    title.setFont(f)
    title.setStyleSheet("color:#1e293b; border:none; background:transparent;")
    outer.addWidget(title)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)

    for i, (key, label) in enumerate(SLOTS):
        icon_id = icons.get(key, "")
        active  = (key == "pan")          # 平移 = 激活态示意
        btn_row.addWidget(make_slot(icon_id, label, active))

    btn_row.addStretch()
    outer.addLayout(btn_row)
    return frame


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = QMainWindow()
    win.setWindowTitle("图标方案对比 — MF4 Analyzer")
    win.resize(800, 460)

    central = QWidget()
    central.setStyleSheet("background:#f1f5f9;")
    win.setCentralWidget(central)
    lay = QVBoxLayout(central)
    lay.setSpacing(10)
    lay.setContentsMargins(18, 18, 18, 18)

    note = QLabel("💡 蓝色高亮按钮 = 激活态示意（平移工具）    鼠标悬停可查看 tooltip")
    note.setStyleSheet("color:#64748b; font-size:11px; padding:2px 0 6px 0;")
    lay.addWidget(note)

    for name, icons in SCHEMES.items():
        lay.addWidget(make_row(name, icons))

    lay.addStretch()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

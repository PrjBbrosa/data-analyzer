"""Statistics surfaces: the 6-metric table and the compact strip that wraps it."""
from PyQt5.QtWidgets import (
    QFrame,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class StatisticsPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken);
        self.setMaximumHeight(110)
        layout = QVBoxLayout(self);
        layout.setContentsMargins(4, 2, 4, 2)
        self.tree = QTreeWidget();
        self.tree.setHeaderLabels(['Channel', 'Min', 'Max', 'Mean', 'RMS', 'Std', 'P-P'])
        self.tree.setAlternatingRowColors(True);
        self.tree.setRootIsDecorated(False);
        h = self.tree.header();
        h.setStretchLastSection(False);
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7): h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree)

    def update_stats(self, stats):
        self.tree.clear()
        for ch, s in stats.items():
            # The stats key may be a composite (data_id, name) identity key
            # (canvas.get_statistics, multi-file same-name decouple); prefer the
            # human-readable display_label for the Channel column when present,
            # else fall back to the key itself (window.py's live strip passes
            # the plain display name as the key with no display_label).
            header = s.get('display_label', ch) if isinstance(s, dict) else ch
            self.tree.addTopLevelItem(QTreeWidgetItem(
                [header, f"{s['min']:.3g}", f"{s['max']:.3g}", f"{s['mean']:.3g}", f"{s['rms']:.3g}",
                 f"{s['std']:.3g}", f"{s['p2p']:.3g}"]))


class StatsStrip(QFrame):
    """Compact stats line + click-to-expand full table.

    Collapsed: one-liner per channel joined with ' │ '.
    Expanded: full StatisticsPanel with the 6-metric tree.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        top = QHBoxLayout()
        self._btn_expand = QToolButton()
        self._btn_expand.setObjectName("statsExpand")
        self._btn_expand.setText(">")
        self._btn_expand.setToolTip("展开统计信息")
        self._btn_expand.setAccessibleName("展开统计信息")
        self._btn_expand.setProperty("role", "icon")
        self._btn_expand.clicked.connect(self.toggle)
        top.addWidget(self._btn_expand)
        self._lbl_summary = QLabel("— 无通道 —")
        top.addWidget(self._lbl_summary, stretch=1)
        lay.addLayout(top)
        self._panel = StatisticsPanel(self)
        self._panel.setVisible(False)
        lay.addWidget(self._panel)

    def toggle(self):
        self._expanded = not self._expanded
        self._btn_expand.setText("v" if self._expanded else ">")
        action = "收起统计信息" if self._expanded else "展开统计信息"
        self._btn_expand.setToolTip(action)
        self._btn_expand.setAccessibleName(action)
        self._panel.setVisible(self._expanded)

    def update_stats(self, stats):
        if not stats:
            self._lbl_summary.setText("— 无通道 —")
            self._panel.update_stats({})
            return
        parts = []
        for ch, s in stats.items():
            parts.append(
                f"● {ch}: min={s['min']:.3g} max={s['max']:.3g} "
                f"rms={s['rms']:.3g} p2p={s['p2p']:.3g}"
            )
        self._lbl_summary.setText(" │ ".join(parts))
        self._panel.update_stats(stats)

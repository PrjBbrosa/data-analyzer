"""Channel editor dialog: create/rename/remove derived channels."""
import re

import numpy as np

from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from ...signal import ChannelMath
from ...signal.expression import ExpressionError
from ...signal.expression import evaluate as eval_expression
from ...signal.expression import normalize as normalize_expression
from ...signal.expression import referenced_names as expression_names
from ...ui_kit.widgets import SearchField
from ...ui_kit.widgets.searchable_combo import SearchableComboBox
from ..expression_help import ExpressionHelpPopup, help_tooltip_text
from ..widgets.compact_spinbox import CompactDoubleSpinBox

# Hover text for the ? badge — same reference the pinnable help card renders,
# so the two can never drift apart (see ui/expression_help.py).
EXPR_TOOLTIP = help_tooltip_text()
EXPR_HELP_HINT = "点 ? 打开可拖动的帮助卡片"


class ChannelEditorDialog(QDialog):
    # Sizing for the narrow "方案 A" single-column layout. The panel target is
    # ~336px overall. ``INPUT_WIDTH`` is now a MINIMUM (floor) for input
    # controls, not a cap: inputs fill the row's available width so long
    # channel names stay visible and no blank gutter is left on the right (see
    # ``_narrow``). Tokens mirror style.qss (input radius 7 / button radius 8 /
    # primary #1769e0).
    # fid, channels, include_time, use_range, format ("excel" | "wwt")
    export_requested = pyqtSignal(str, list, bool, bool, str)
    INPUT_WIDTH = 178
    PANEL_WIDTH = 336
    # Last entry of the 双通道运算 op combo — free-form expression over A/B/t.
    CUSTOM_OP_INDEX = 6

    def __init__(self, parent, files, active_fid):
        super().__init__(parent)
        self.setObjectName("ChannelEditorDialog")
        # ``files`` is a dict[fid -> fd] of all loaded files; one file is
        # edited at a time. Switching the top file combo resets the in-flight
        # edit (new/removed) and repopulates every channel combo.
        self._files = dict(files)
        self.current_fid = active_fid if active_fid in self._files else (
            next(iter(self._files)) if self._files else None
        )
        self.fd = self._files.get(self.current_fid)
        self.new_channels = {}
        self.removed_channels = set()
        self.setMinimumWidth(self.PANEL_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- top file selector (stays put, does not scroll) ---
        file_bar = QWidget(self)
        file_bar.setObjectName("channelEditorFileBar")
        fb = QHBoxLayout(file_bar)
        fb.setContentsMargins(12, 10, 12, 8)
        fb.setSpacing(8)
        self._file_bar_layout = fb
        lbl_file = QLabel("文件")
        lbl_file.setMinimumWidth(34)
        fb.addWidget(lbl_file)
        self.combo_file = QComboBox()
        # Fill the file row: a Fixed-width label on the left, the combo
        # expanding to the right edge (no trailing stretch gutter).
        self.combo_file.setMinimumWidth(self.INPUT_WIDTH)
        self.combo_file.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for fid, fd in self._files.items():
            self.combo_file.addItem(self._file_label(fd), fid)
        if self.current_fid is not None:
            idx = self.combo_file.findData(self.current_fid)
            if idx >= 0:
                self.combo_file.setCurrentIndex(idx)
        self.combo_file.currentIndexChanged.connect(self._on_file_changed)
        fb.addWidget(self.combo_file, 1)
        root.addWidget(file_bar)

        # --- scrollable body (operations + delete) ---
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("channelEditorScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("channelEditorBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 6, 12, 10)
        bl.setSpacing(14)

        # 单通道运算
        g = QGroupBox("单通道运算")
        gl = QGridLayout(g)
        gl.setVerticalSpacing(8)
        gl.setHorizontalSpacing(8)
        gl.addWidget(QLabel("源"), 0, 0)
        self.combo_src = SearchableComboBox()
        self._narrow(self.combo_src)
        self.combo_src.currentTextChanged.connect(self.combo_src.setToolTip)
        gl.addWidget(self.combo_src, 0, 1)
        gl.addWidget(QLabel("运算"), 1, 0)
        self.combo_op = QComboBox()
        self.combo_op.addItems(["d/dt", "∫dt", "× 系数", "+ 偏移", "滑动平均", "|x| 绝对值"])
        self._narrow(self.combo_op)
        gl.addWidget(self.combo_op, 1, 1)
        gl.addWidget(QLabel("参数"), 2, 0)
        self.spin_p = CompactDoubleSpinBox()
        self.spin_p.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_p.setRange(-1e12, 1e12)
        self.spin_p.setValue(1)
        self._narrow(self.spin_p)
        gl.addWidget(self.spin_p, 2, 1)
        btn = QPushButton("✚ 创建单通道")
        btn.setObjectName("channelCreateBtn")
        btn.setProperty("role", "secondary")
        btn.clicked.connect(self._create_single)
        gl.addWidget(btn, 3, 1, Qt.AlignLeft)
        # Stretch the INPUT column (col 1) so controls fill to the right edge;
        # no ghost spacer column. The create button keeps Qt.AlignLeft so it
        # stays compact and left-anchored inside the now-stretched column.
        gl.setColumnStretch(1, 1)
        bl.addWidget(g)

        # 双通道运算
        g2 = QGroupBox("双通道运算 (A ⊕ B)")
        gl2 = QGridLayout(g2)
        gl2.setVerticalSpacing(8)
        gl2.setHorizontalSpacing(8)
        gl2.addWidget(QLabel("通道A"), 0, 0)
        self.combo_a = SearchableComboBox()
        self._narrow(self.combo_a)
        self.combo_a.currentTextChanged.connect(self.combo_a.setToolTip)
        gl2.addWidget(self.combo_a, 0, 1)
        gl2.addWidget(QLabel("运算"), 1, 0)
        self.combo_op2 = QComboBox()
        self.combo_op2.addItems(
            ["A + B", "A - B", "A × B", "A ÷ B", "max(A,B)", "min(A,B)", "自定义表达式…"]
        )
        self.combo_op2.currentIndexChanged.connect(self._sync_expr_row)
        self._narrow(self.combo_op2)
        gl2.addWidget(self.combo_op2, 1, 1)
        gl2.addWidget(QLabel("通道B"), 2, 0)
        self.combo_b = SearchableComboBox()
        self._narrow(self.combo_b)
        self.combo_b.currentTextChanged.connect(self.combo_b.setToolTip)
        gl2.addWidget(self.combo_b, 2, 1)
        # 自定义表达式行 — only shown for the 自定义 op; A / B / t bind to the
        # two combos above and the file's time base.
        self.lbl_expr = QLabel("表达式")
        gl2.addWidget(self.lbl_expr, 3, 0)
        # The input and its ? badge share ONE grid cell (a nested HBox) so the
        # other rows keep filling column 1 to the same right edge — adding a
        # third grid column would indent every combo above by the badge width.
        self._expr_row = QWidget()
        erl = QHBoxLayout(self._expr_row)
        erl.setContentsMargins(0, 0, 0, 0)
        erl.setSpacing(6)
        self.edit_expr = QLineEdit()
        self.edit_expr.setObjectName("channelExprEdit")
        self.edit_expr.setPlaceholderText("例: sqrt(A^2 + B^2) * 0.5")
        self.edit_expr.setToolTip(EXPR_TOOLTIP)
        self.edit_expr.returnPressed.connect(self._create_dual)
        self.edit_expr.setMinimumWidth(self.INPUT_WIDTH - 24)
        self.edit_expr.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        erl.addWidget(self.edit_expr, 1)
        # Hover shows the reference; clicking pins it as a draggable card so
        # the user can keep reading while typing the formula.
        self.btn_expr_help = QToolButton()
        self.btn_expr_help.setObjectName("channelExprHelp")
        self.btn_expr_help.setText("?")
        self.btn_expr_help.setCheckable(True)
        self.btn_expr_help.setFixedSize(18, 18)
        self.btn_expr_help.setFocusPolicy(Qt.NoFocus)
        self.btn_expr_help.setCursor(Qt.PointingHandCursor)
        self.btn_expr_help.setToolTip(f"{EXPR_TOOLTIP}\n\n{EXPR_HELP_HINT}")
        self.btn_expr_help.toggled.connect(self._toggle_expr_help)
        self._expr_help_popup = None
        # AlignVCenter: without it the 18px glyph rides the row's top edge and
        # reads as misaligned against the taller input next to it.
        erl.addWidget(self.btn_expr_help, 0, Qt.AlignVCenter)
        gl2.addWidget(self._expr_row, 3, 1)
        self.lbl_expr_hint = QLabel(
            "A=通道A · B=通道B · t=时间 · ^ 为幂 · 点 ? 看全部"
        )
        self.lbl_expr_hint.setObjectName("channelExprHint")
        self.lbl_expr_hint.setWordWrap(True)
        self.lbl_expr_hint.setToolTip(EXPR_TOOLTIP)
        gl2.addWidget(self.lbl_expr_hint, 4, 0, 1, 2)
        gl2.addWidget(QLabel("名称"), 5, 0)
        self.edit_name2 = QLineEdit()
        self.edit_name2.setPlaceholderText("留空自动生成")
        self._narrow(self.edit_name2)
        gl2.addWidget(self.edit_name2, 5, 1)
        btn2 = QPushButton("✚ 创建双通道")
        btn2.setObjectName("channelCreateBtn")
        btn2.setProperty("role", "secondary")
        btn2.clicked.connect(self._create_dual)
        gl2.addWidget(btn2, 6, 1, Qt.AlignLeft)
        self._sync_expr_row()
        # Stretch the INPUT column (col 1) so controls fill to the right edge;
        # no ghost spacer column. The create button keeps Qt.AlignLeft.
        gl2.setColumnStretch(1, 1)
        bl.addWidget(g2)

        # 导出 / 删除：同一勾选列表；底部左导出、右删除
        # Toolbar mirrors the left channel pane: search + 全选/全不/已选, plus
        # 反选 which export pickers commonly need when lists are long.
        gx = QGroupBox("导出 / 删除")
        gxl = QVBoxLayout(gx)
        gxl.setSpacing(6)
        self.export_search = SearchField("搜索通道…")
        self.export_search.setObjectName("channelExportSearch")
        self.export_search.textChanged.connect(self._apply_export_filters)
        gxl.addWidget(self.export_search)
        export_tools = QHBoxLayout()
        export_tools.setContentsMargins(0, 0, 0, 0)
        export_tools.setSpacing(4)
        self.btn_export_all = QPushButton("全选")
        self.btn_export_none = QPushButton("全不")
        self.btn_export_invert = QPushButton("反选")
        self.btn_export_selected_only = QPushButton("已选")
        for btn, handler in (
            (self.btn_export_all, self._export_check_all),
            (self.btn_export_none, self._export_check_none),
            (self.btn_export_invert, self._export_check_invert),
        ):
            btn.setMaximumWidth(48)
            btn.setProperty("role", "quiet")
            btn.clicked.connect(handler)
            export_tools.addWidget(btn)
        self.btn_export_selected_only.setMaximumWidth(48)
        self.btn_export_selected_only.setProperty("role", "quiet")
        self.btn_export_selected_only.setCheckable(True)
        self.btn_export_selected_only.toggled.connect(self._apply_export_filters)
        export_tools.addWidget(self.btn_export_selected_only)
        export_tools.addStretch(1)
        gxl.addLayout(export_tools)
        self.list_export = QListWidget()
        self.list_export.setObjectName("channelExportList")
        self.list_export.setMinimumHeight(108)
        self.list_export.setMaximumHeight(140)
        gxl.addWidget(self.list_export)
        # 兼容旧引用（对齐测试等）：删除与导出共用勾选列表
        self.list_rm = self.list_export
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(8)
        lbl_fmt = QLabel("格式")
        lbl_fmt.setMinimumWidth(34)
        fmt_row.addWidget(lbl_fmt)
        self.combo_export_format = QComboBox()
        self.combo_export_format.setObjectName("channelExportFormat")
        self.combo_export_format.addItem("Excel (.xlsx)", "excel")
        self.combo_export_format.addItem("WinWert 无损 (.wwt)", "wwt")
        self.combo_export_format.addItem("WinWert 紧凑 (.wwt)", "wwt_compact")
        # Per-item tips: QComboBox shows the current item's tip on hover.
        self.combo_export_format.setItemData(
            0,
            "表格导出：体积通常更大，便于二次处理。",
            Qt.ToolTipRole,
        )
        self.combo_export_format.setItemData(
            1,
            "每个样点 8 字节双精度，体积最大，无量化误差。",
            Qt.ToolTipRole,
        )
        self.combo_export_format.setItemData(
            2,
            "按通道量程写入 int16（约 1/4 体积）。最大误差约为量程的 1/65534"
            "（例：±450° ≈ 0.007°）。WinWert / TraceLab 均可打开。",
            Qt.ToolTipRole,
        )
        self.combo_export_format.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        self.combo_export_format.currentIndexChanged.connect(
            self._sync_export_format_ui
        )
        fmt_row.addWidget(self.combo_export_format, 1)
        gxl.addLayout(fmt_row)
        self.chk_export_time = QCheckBox("包含时间列")
        self.chk_export_time.setChecked(True)
        self.chk_export_range = QCheckBox("仅导出选定时间范围")
        gxl.addWidget(self.chk_export_time)
        gxl.addWidget(self.chk_export_range)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setObjectName("channelCreateBtn")
        self.btn_export.setProperty("role", "secondary")
        self.btn_export.clicked.connect(self._on_export_clicked)
        action_row.addWidget(self.btn_export, 0, Qt.AlignLeft)
        action_row.addStretch(1)
        self.btn_delete = QPushButton("🗑 删除选中通道")
        self.btn_delete.setObjectName("channelDeleteBtn")
        self.btn_delete.setProperty("role", "danger")
        self.btn_delete.clicked.connect(self._remove)
        action_row.addWidget(self.btn_delete, 0, Qt.AlignRight)
        gxl.addLayout(action_row)
        self._sync_export_format_ui()
        bl.addWidget(gx)
        bl.addStretch(1)

        self._scroll.setWidget(body)
        root.addWidget(self._scroll, 1)

        # --- footer (stays put): count + 取消/确定 ---
        footer = QWidget(self)
        footer.setObjectName("channelEditorFooter")
        ft = QHBoxLayout(footer)
        ft.setContentsMargins(12, 8, 12, 10)
        ft.setSpacing(10)
        self.lbl = QLabel("新增: 0")
        self.lbl.setObjectName("channelEditorCount")
        ft.addWidget(self.lbl)
        ft.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        ft.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setProperty("role", "primary")
        self.btn_ok.clicked.connect(self.accept)
        ft.addWidget(self.btn_ok)
        root.addWidget(footer)

        self._populate_channels()
        QTimer.singleShot(0, self._sync_file_bar_right_edge)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_file_bar_right_edge)

    def _sync_file_bar_right_edge(self):
        if not hasattr(self, "_file_bar_layout"):
            return
        if not hasattr(self, "combo_src") or self.combo_src.width() <= 0:
            return
        target = self.combo_src.mapTo(self, self.combo_src.rect().topLeft()).x()
        target += self.combo_src.width()
        current = self.combo_file.mapTo(self, self.combo_file.rect().topLeft()).x()
        current += self.combo_file.width()
        delta = current - target
        if abs(delta) <= 1:
            return
        left, top, right, bottom = self._file_bar_layout.getContentsMargins()
        self._file_bar_layout.setContentsMargins(
            left,
            top,
            max(0, right + delta),
            bottom,
        )
        self._file_bar_layout.activate()
        if self.layout() is not None:
            self.layout().activate()

    def _file_label(self, fd):
        """File display name: filepath.stem, falling back to filename."""
        fp = getattr(fd, "filepath", None)
        if fp is not None:
            return fp.stem
        name = getattr(fd, "filename", "") or getattr(fd, "short_name", "")
        return name.rsplit(".", 1)[0] if "." in name else name

    def _narrow(self, widget):
        """Let an input control FILL its row's available width.

        Previously this capped controls at ``INPUT_WIDTH`` (178px), which
        left a wide blank gutter on the right and truncated long channel
        names. The semantics are now "fill, with a sane floor": horizontal
        ``Expanding`` so the control grows into the row's slack, plus a
        ``setMinimumWidth`` floor so the control does not collapse when the
        panel is dragged narrow. Vertical policy stays ``Fixed``."""
        widget.setMinimumWidth(self.INPUT_WIDTH)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _on_file_changed(self, _index):
        fid = self.combo_file.currentData()
        if fid is None or fid == self.current_fid:
            return
        # Switching files discards the in-flight edit (one file at a time).
        self.current_fid = fid
        self.fd = self._files.get(fid)
        self.new_channels = {}
        self.removed_channels = set()
        self._populate_channels()

    def _populate_channels(self):
        """Refill source/A/B combos + delete list from the current fd, and
        reset the title and 新增 count. Called at construction and on every
        file switch."""
        chs = self.fd.get_signal_channels() if self.fd is not None else []
        title = self._file_label(self.fd) if self.fd is not None else ""
        self.setWindowTitle(f"通道编辑 - {title}" if title else "通道编辑")
        for combo in (self.combo_src, self.combo_a, self.combo_b):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(chs)
            combo.blockSignals(False)
            # Signals were blocked during refill, so the currentTextChanged →
            # setToolTip wiring did not fire; seed the hover tooltip for the
            # current selection so the full (possibly elided) channel name is
            # visible on hover even when the box width crops it.
            combo.setToolTip(combo.currentText())
        self.export_search.blockSignals(True)
        self.export_search.clear()
        self.export_search.blockSignals(False)
        self.btn_export_selected_only.blockSignals(True)
        self.btn_export_selected_only.setChecked(False)
        self.btn_export_selected_only.blockSignals(False)
        self.list_export.clear()
        for ch in chs:
            self._append_export_item(ch, checked=True)
        self.lbl.setText("新增: 0")

    def _append_export_item(self, name, *, checked=True):
        it = QListWidgetItem(str(name))
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list_export.addItem(it)

    def _iter_export_items(self, *, visible_only=False):
        for i in range(self.list_export.count()):
            item = self.list_export.item(i)
            if visible_only and item.isHidden():
                continue
            yield item

    def _apply_export_filters(self, *_):
        query = self.export_search.text().strip().lower()
        selected_only = self.btn_export_selected_only.isChecked()
        for item in self._iter_export_items():
            matches_text = (not query) or (query in item.text().lower())
            matches_selected = (
                (not selected_only) or item.checkState() == Qt.Checked
            )
            item.setHidden(not (matches_text and matches_selected))

    def _export_check_all(self):
        for item in self._iter_export_items(visible_only=True):
            item.setCheckState(Qt.Checked)
        self._apply_export_filters()

    def _export_check_none(self):
        for item in self._iter_export_items(visible_only=True):
            item.setCheckState(Qt.Unchecked)
        self._apply_export_filters()

    def _export_check_invert(self):
        for item in self._iter_export_items(visible_only=True):
            item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            )
        self._apply_export_filters()

    def _export_format(self) -> str:
        data = self.combo_export_format.currentData()
        return str(data or "excel")

    def _sync_export_format_ui(self, *_args):
        fmt = self._export_format()
        tip = self.combo_export_format.currentData(Qt.ToolTipRole)
        self.combo_export_format.setToolTip(str(tip or ""))
        if fmt in ("wwt", "wwt_compact"):
            self.btn_export.setText("导出 WWT")
            # WWT always carries a Zeit record; keep the checkbox checked but
            # disabled so the Excel wording does not imply an optional column.
            self.chk_export_time.setChecked(True)
            self.chk_export_time.setEnabled(False)
            self.chk_export_time.setText("写入 Zeit 时基（必需）")
            self.chk_export_range.setToolTip(
                "可勾选：只导出选定时间范围（采样率与点数按原始数据保留）。"
            )
        else:
            self.btn_export.setText("导出 Excel")
            self.chk_export_time.setEnabled(True)
            self.chk_export_time.setText("包含时间列")
            self.chk_export_range.setToolTip("")

    def _on_export_clicked(self):
        if self.current_fid is None:
            return
        channels = [
            item.text()
            for item in self._iter_export_items()
            if item.checkState() == Qt.Checked
        ]
        if not channels:
            QMessageBox.information(self, "导出", "请先勾选要导出的通道。")
            return
        self.export_requested.emit(
            self.current_fid, channels,
            self.chk_export_time.isChecked(),
            self.chk_export_range.isChecked(),
            self._export_format(),
        )

    def _create_single(self):
        src = self.combo_src.currentText()
        if src not in self.fd.data.columns:
            QMessageBox.warning(self, "无法创建", "源通道不存在或参数越界")
            return
        sig = self.fd.data[src].values.astype(float)
        t = self.fd.time_array;
        op = self.combo_op.currentIndex();
        p = self.spin_p.value()
        prefixes = ["d_dt_", "int_", "scaled_", "offset_", "mavg_", "abs_"]
        try:
            if op == 0:
                r = ChannelMath.derivative(t, sig)
            elif op == 1:
                r = ChannelMath.integral(t, sig)
            elif op == 2:
                r = ChannelMath.scale(sig, p)
            elif op == 3:
                r = ChannelMath.offset(sig, p)
            elif op == 4:
                r = ChannelMath.moving_avg(sig, max(int(p), 3))
            elif op == 5:
                r = np.abs(sig)
            else:
                QMessageBox.warning(self, "无法创建", "不支持的运算类型")
                return
            name = f"{prefixes[op]}{src}"
            while name in self.fd.data.columns or name in self.new_channels: name += "_1"
            self._register_new(name, r, self.fd.channel_units.get(src, ''))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _sync_expr_row(self, *_):
        """Show the 表达式 row only for the 自定义 operation."""
        custom = self.combo_op2.currentIndex() == self.CUSTOM_OP_INDEX
        for w in (self.lbl_expr, self._expr_row, self.edit_expr,
                  self.btn_expr_help, self.lbl_expr_hint):
            w.setVisible(custom)
        if not custom:
            # Leaving 自定义 takes the help card with it.
            self.btn_expr_help.setChecked(False)

    def _toggle_expr_help(self, checked):
        """Open / close the pinnable, draggable expression help card."""
        if not checked:
            if self._expr_help_popup is not None:
                self._expr_help_popup.hide()
            return
        if self._expr_help_popup is None:
            # Parented to the editor so the drawer's application modality does
            # not block it (Qt exempts a modal window's own child windows).
            self._expr_help_popup = ExpressionHelpPopup(self)
            self._expr_help_popup.closed.connect(
                lambda: self.btn_expr_help.setChecked(False)
            )
        self._expr_help_popup.show_beside(self.edit_expr)

    def hideEvent(self, event):
        # The card is a separate top-level window; it must not outlive the
        # editor it documents. hideEvent also fires while the editor is being
        # torn down, when the child popup's C++ side may already be gone —
        # hence the RuntimeError guard.
        if self._expr_help_popup is not None:
            try:
                self._expr_help_popup.hide()
            except RuntimeError:
                self._expr_help_popup = None
        super().hideEvent(event)

    def _channel_signal(self, name):
        """Signal for a channel name, including ones staged in this session."""
        if name in self.new_channels:
            return np.asarray(self.new_channels[name][0], dtype=float)
        return self.fd.data[name].values.astype(float)

    def _unique_name(self, name):
        while name in self.fd.data.columns or name in self.new_channels:
            name += "_1"
        return name

    def _register_new(self, name, values, unit):
        self.new_channels[name] = (values, unit)
        self.lbl.setText(f"新增: {len(self.new_channels)} ({name})")
        self.combo_src.addItem(name)
        self.combo_a.addItem(name)
        self.combo_b.addItem(name)
        self._append_export_item(name, checked=True)
        self._apply_export_filters()

    def _create_expression(self, ch_a, ch_b):
        """Build a channel from the user's free-form expression.

        Only the variables the expression actually references are required, so
        an ``A``-only formula does not care what 通道B is set to.
        """
        expr = self.edit_expr.text().strip()
        if not expr:
            QMessageBox.warning(self, "无法创建", "请先输入表达式，例如 sqrt(A^2 + B^2)")
            return
        try:
            used = {n.lower() for n in expression_names(expr)}
        except ExpressionError as e:
            QMessageBox.warning(self, "表达式错误", str(e))
            return

        t = np.asarray(self.fd.time_array, dtype=float)
        variables = {"t": t, "time": t}
        for key, ch in (("A", ch_a), ("B", ch_b)):
            if key.lower() not in used:
                # Still expose the name so a typo reports "未知变量" against the
                # full variable list, but skip the existence/length checks.
                variables[key] = np.zeros(t.size)
                continue
            if ch not in self.fd.data.columns and ch not in self.new_channels:
                QMessageBox.warning(self, "无法创建", f"通道{key} 不存在")
                return
            sig = self._channel_signal(ch)
            if sig.size != t.size:
                QMessageBox.warning(
                    self, "错误", f"通道{key} 长度不匹配: {sig.size} vs {t.size}")
                return
            variables[key] = sig

        try:
            r = eval_expression(expr, variables, size=t.size)
        except ExpressionError as e:
            QMessageBox.warning(self, "表达式错误", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "错误", f"表达式计算失败：{e}")
            return
        if not np.any(np.isfinite(r)):
            QMessageBox.warning(self, "无法创建", "表达式结果全为 NaN/Inf，请检查公式")
            return

        name = self.edit_name2.text().strip() or self._auto_expr_name(expr)
        self._register_new(self._unique_name(name), r, '')
        self.edit_name2.clear()

    @staticmethod
    def _auto_expr_name(expr):
        """``sqrt(A^2+B^2)`` → ``expr_sqrt_A_2_B_2`` (safe as a column name)."""
        cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", normalize_expression(expr)).strip("_")
        return f"expr_{cleaned[:28]}" if cleaned else "expr"

    def _create_dual(self):
        ch_a = self.combo_a.currentText()
        ch_b = self.combo_b.currentText()
        op = self.combo_op2.currentIndex()
        if op == self.CUSTOM_OP_INDEX:
            self._create_expression(ch_a, ch_b)
            return
        if ch_a not in self.fd.data.columns and ch_a not in self.new_channels:
            QMessageBox.warning(self, "无法创建", "源通道不存在或参数越界")
            return
        if ch_b not in self.fd.data.columns and ch_b not in self.new_channels:
            QMessageBox.warning(self, "无法创建", "源通道不存在或参数越界")
            return

        # 获取数据
        sig_a = self._channel_signal(ch_a)
        sig_b = self._channel_signal(ch_b)

        if len(sig_a) != len(sig_b):
            QMessageBox.warning(self, "错误", f"通道长度不匹配: {len(sig_a)} vs {len(sig_b)}")
            return

        op_symbols = ["add", "sub", "mul", "div", "max", "min"]
        try:
            if op == 0:
                r = sig_a + sig_b
            elif op == 1:
                r = sig_a - sig_b
            elif op == 2:
                r = sig_a * sig_b
            elif op == 3:
                with np.errstate(divide='ignore', invalid='ignore'):
                    r = np.where(sig_b != 0, sig_a / sig_b, 0)
            elif op == 4:
                r = np.maximum(sig_a, sig_b)
            elif op == 5:
                r = np.minimum(sig_a, sig_b)
            else:
                QMessageBox.warning(self, "无法创建", "不支持的运算类型")
                return

            # 生成名称
            name = self.edit_name2.text().strip()
            if not name:
                name = f"{op_symbols[op]}_{ch_a}_{ch_b}"

            # 合并单位
            unit_a = self.fd.channel_units.get(ch_a, '')
            unit_b = self.fd.channel_units.get(ch_b, '')
            unit = unit_a if unit_a == unit_b else f"{unit_a}/{unit_b}" if op == 3 else ""

            self._register_new(self._unique_name(name), r, unit)
            self.edit_name2.clear()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _remove(self):
        sel = [
            item.text()
            for item in self._iter_export_items()
            if item.checkState() == Qt.Checked
        ]
        if not sel:
            QMessageBox.information(self, "删除", "请先勾选要删除的通道。")
            return
        if QMessageBox.question(
            self, "确认", f"删除 {len(sel)} 通道?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.removed_channels.update(sel)
        for name in sel:
            self.new_channels.pop(name, None)
        remove = set(sel)
        for row in range(self.list_export.count() - 1, -1, -1):
            if self.list_export.item(row).text() in remove:
                self.list_export.takeItem(row)
        self.lbl.setText(f"新增: {len(self.new_channels)}")
        self._apply_export_filters()

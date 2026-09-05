"""Pinnable, draggable help cards for the channel editor.

Two cards share the same chrome (frameless Tool window, header drag, Esc /
× close, show_beside):

* :class:`ExpressionHelpPopup` — 自定义表达式 row ``?``
* :class:`SingleParamHelpPopup` — 单通道运算 参数/窗长/系数 row ``?``

Reference content lives next to each card and is also rendered as the badge
hover tooltip (via ``help_tooltip_text`` / ``param_help_tooltip_text``) so the
two surfaces cannot drift apart.
"""
from PyQt5.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Expression help content
# ---------------------------------------------------------------------------

HELP_TITLE = "表达式帮助"
HELP_SUBTITLE = "A = 通道A　B = 通道B　t = 时间"

EXAMPLES = (
    ("sqrt(A^2 + B^2)", "合成幅值"),
    ("(A - B) * 0.5 + 1.2", "括号与系数"),
    ("A / max(abs(B), 0.001)", "避免除零"),
    ("A - mean(A)", "去直流偏置"),
    ("where(t > 5, A, B)", "按时间切换"),
)

FUNCTION_GROUPS = (
    ("数学", "sqrt cbrt abs exp log ln log2 log10"),
    ("三角", "sin cos tan asin acos atan atan2 sinh cosh tanh deg rad"),
    ("取值", "min max clip sign floor ceil round hypot where cumsum"),
    ("统计", "mean median std sum rms（对整条通道求值）"),
)

OPERATORS = "+ - * / // % ^（幂）、比较、& |；常量 pi e"

FOOTNOTES = (
    "名称留空时按公式自动命名",
    "inf / nan 处曲线断开，不会拉爆 Y 轴",
)

# Hand-wrapped so the app-wide glass tooltip (which sizes to its longest line)
# stays narrow. The card below renders the same data with real layout.
_TOOLTIP_WRAP = {
    "三角": ("sin cos tan asin acos atan atan2", "sinh cosh tanh deg rad"),
    "取值": ("min max clip sign floor ceil round", "hypot where cumsum"),
}


def help_tooltip_text():
    """Plain-text rendering of the expression reference, for the hover tooltip."""
    lines = [f"自定义表达式 —— 变量 {HELP_SUBTITLE}", "", "示例"]
    lines += [f"· {expr}  →  {what}" for expr, what in EXAMPLES]
    lines += ["", "可用函数"]
    for label, funcs in FUNCTION_GROUPS:
        wrapped = _TOOLTIP_WRAP.get(label)
        if wrapped:
            lines.append(f"· {label} {wrapped[0]}")
            lines += [f"         {tail}" for tail in wrapped[1:]]
        else:
            lines.append(f"· {label} {funcs}")
    lines += ["", f"运算符 {OPERATORS}"]
    lines += FOOTNOTES
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Single-op parameter help content
# ---------------------------------------------------------------------------

PARAM_HELP_TITLE = "参数帮助"
PARAM_HELP_SUBTITLE = "随「运算」变化：系数 / 偏移 / 窗长"

PARAM_OP_ROWS = (
    ("d/dt · ∫dt · |x|", "不使用参数（输入框会灰掉）"),
    ("× 系数", "整体乘常数，如 0.001 换单位"),
    ("+ 偏移", "加常数做零点对齐"),
    ("滑动平均", "窗长 = 样点数（≥ 3，取整）"),
)

PARAM_MAVG_EXAMPLES = (
    ("窗长 50 @ 1 kHz", "约 50 ms 平滑"),
    ("窗长 100 @ 1 kHz", "约 0.1 s 平滑"),
    ("窗长越小", "越接近原信号"),
    ("窗长越大", "越平滑、越钝"),
)

PARAM_FOOTNOTES = (
    "窗长按整数取；填 1.0 也会抬到至少 3",
    "窗长 ≥ 信号长度时，整段取均值",
    "系数 / 偏移可为任意实数（含负数）",
)


def param_help_tooltip_text():
    """Plain-text rendering of the parameter reference, for the hover tooltip."""
    lines = [f"{PARAM_HELP_TITLE} —— {PARAM_HELP_SUBTITLE}", "", "运算对照"]
    lines += [f"· {op}  →  {what}" for op, what in PARAM_OP_ROWS]
    lines += ["", "滑动平均 · 窗长示例"]
    lines += [f"· {ex}  →  {what}" for ex, what in PARAM_MAVG_EXAMPLES]
    lines += ["", *PARAM_FOOTNOTES]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared chrome
# ---------------------------------------------------------------------------

_MONO = '"SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", monospace'

_QSS = f"""
QFrame#exprHelpCard {{
    background-color: #ffffff;
    border: 1px solid #dfe5ee;
    border-radius: 10px;
}}
QWidget#exprHelpHeader {{ background-color: transparent; }}
QLabel#exprHelpTitle {{
    color: #111827;
    font-size: 12px;
    font-weight: 600;
    background-color: transparent;
}}
QLabel#exprHelpSubtitle {{
    color: #4b6b9a;
    font-size: 11px;
    background-color: transparent;
}}
QLabel#exprHelpSection {{
    color: #64748b;
    font-size: 11px;
    font-weight: 600;
    background-color: transparent;
}}
QLabel#exprHelpCode {{
    color: #0f3f8f;
    font-family: {_MONO};
    font-size: 11px;
    background-color: transparent;
}}
QLabel#exprHelpText {{
    color: #475569;
    font-size: 11px;
    background-color: transparent;
}}
QLabel#exprHelpFoot {{
    color: #94a3b8;
    font-size: 10px;
    background-color: transparent;
}}
QFrame#exprHelpRule {{
    background-color: #eef2f7;
    border: none;
    max-height: 1px;
}}
QToolButton#exprHelpClose {{
    color: #64748b;
    /* padding:0 is load-bearing: without it the styled QToolButton's content
     * rect collapses at this 18px size and Qt logs "QPainter::begin: Paint
     * device returned engine == 0" on every repaint. */
    padding: 0;
    min-width: 18px; max-width: 18px;
    min-height: 18px; max-height: 18px;
    border: none;
    border-radius: 4px;
    background-color: transparent;
    font-size: 13px;
}}
QToolButton#exprHelpClose:hover {{
    color: #b42318;
    background-color: #fdf4f3;
}}
"""


class ReferenceHelpPopup(QWidget):
    """Frameless card shell: drag by the header, close with × or Esc.

    Parented to the channel editor so it is NOT blocked by that dialog's
    application modality (Qt exempts a modal window's own child windows), and
    so it dies with the editor. Subclasses fill the body via ``_fill_body``.
    """

    closed = pyqtSignal()

    WIDTH = 330
    TITLE = ""
    SUBTITLE = ""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self._drag_offset = None
        # Translucency on the OUTER window only — the inner card carries the
        # QSS fill (CLAUDE.md gotcha: WA_TranslucentBackground kills a widget's
        # own QSS background, so a child frame has to paint it).
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setStyleSheet(_QSS)
        self._build()
        self.resize(self.WIDTH, self.sizeHint().height())

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self)
        card.setObjectName("exprHelpCard")
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)

        self._header = QWidget(card)
        self._header.setObjectName("exprHelpHeader")
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        title = QLabel(self.TITLE)
        title.setObjectName("exprHelpTitle")
        hl.addWidget(title)
        hl.addStretch(1)
        self._close_btn = QToolButton(self._header)
        self._close_btn.setObjectName("exprHelpClose")
        self._close_btn.setFixedSize(18, 18)
        self._close_btn.setCursor(Qt.ArrowCursor)
        self._close_btn.setToolTip("关闭（Esc）")
        self._close_btn.clicked.connect(self.close_card)
        try:
            import qtawesome as qta
            self._close_btn.setIcon(qta.icon("mdi.close", color="#64748b"))
            self._close_btn.setIconSize(QSize(13, 13))
        except Exception:
            # Same fallback as the quickref panel: a text glyph keeps the
            # button usable if qtawesome is missing.
            self._close_btn.setText("×")
        hl.addWidget(self._close_btn)
        lay.addWidget(self._header)
        # The header doubles as the drag handle.
        self._header.setCursor(Qt.OpenHandCursor)
        title.setCursor(Qt.OpenHandCursor)

        if self.SUBTITLE:
            subtitle = QLabel(self.SUBTITLE)
            subtitle.setObjectName("exprHelpSubtitle")
            lay.addWidget(subtitle)
        lay.addWidget(self._rule(card))
        body = QWidget(card)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)
        self._fill_body(body_lay, body)
        scroll = QScrollArea(card)
        scroll.setObjectName("exprHelpScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

    def _fill_body(self, lay, card):
        raise NotImplementedError

    @staticmethod
    def _section(text, parent):
        label = QLabel(text, parent)
        label.setObjectName("exprHelpSection")
        return label

    @staticmethod
    def _rule(parent):
        line = QFrame(parent)
        line.setObjectName("exprHelpRule")
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _code_note_row(code_text, note_text):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        code = QLabel(code_text)
        code.setObjectName("exprHelpCode")
        row.addWidget(code, 1)
        note = QLabel(note_text)
        note.setObjectName("exprHelpText")
        row.addWidget(note, 0, Qt.AlignRight)
        return row

    @staticmethod
    def _foot_block(notes):
        feet = QVBoxLayout()
        feet.setContentsMargins(0, 0, 0, 0)
        feet.setSpacing(2)
        for note in notes:
            foot = QLabel(f"· {note}")
            foot.setObjectName("exprHelpFoot")
            foot.setWordWrap(True)
            feet.addWidget(foot)
        return feet

    # -- show / hide -------------------------------------------------------
    GAP = 10

    def show_beside(self, anchor):
        """Open just OUTSIDE the editor window, level with ``anchor``.

        Anchoring to the host window's edge (not the widget's) keeps the card
        clear of the panel it documents — the user can read and type at the
        same time without dragging first. Flips to the other side, then clamps,
        when the screen has no room.
        """
        self.adjustSize()
        from mf4_analyzer.ui_kit.dialog_geometry import (
            SCREEN_MARGIN,
            clamp_frame_rect,
            client_budget,
            frame_insets_of,
            resolve_available_rect,
        )

        host = anchor.window() if anchor is not None else None
        available = resolve_available_rect(
            widget=self,
            parent=host,
            anchor_global=anchor.mapToGlobal(anchor.rect().center()) if anchor is not None else None,
        )
        budget = client_budget(available, frame_insets_of(self))
        width = min(self.WIDTH, max(160, budget.width))
        height = min(max(self.sizeHint().height(), 160), max(120, budget.height))
        self.setMaximumSize(max(1, budget.width), max(1, budget.height))
        self.resize(width, height)
        if host is not None:
            frame = host.frameGeometry()
            x = frame.right() + self.GAP
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - 40
            if x + self.width() - 1 > available.right:
                x = frame.left() - self.width() - self.GAP
            placed = clamp_frame_rect(
                (x, y, self.width(), self.height()),
                available,
                SCREEN_MARGIN,
            )
            self.resize(placed.width, placed.height)
            self.move(placed.x, placed.y)
        self.show()
        self.raise_()

    def close_card(self):
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.close_card()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def closeEvent(self, ev):  # noqa: N802
        self.closed.emit()
        super().closeEvent(ev)

    # -- drag by header ----------------------------------------------------
    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton and self._in_header(ev.pos()):
            self._drag_offset = ev.globalPos() - self.frameGeometry().topLeft()
            self._header.setCursor(Qt.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._drag_offset is not None and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPos() - self._drag_offset)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self._header.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(ev)

    def _in_header(self, pos):
        if self._close_btn.rect().translated(
            self._close_btn.mapTo(self, QPoint(0, 0))
        ).contains(pos):
            return False
        top_left = self._header.mapTo(self, QPoint(0, 0))
        return self._header.rect().translated(top_left).contains(pos)


class ExpressionHelpPopup(ReferenceHelpPopup):
    """表达式帮助 card behind the dual-op ``?`` badge."""

    TITLE = HELP_TITLE
    SUBTITLE = HELP_SUBTITLE

    def _fill_body(self, lay, card):
        lay.addWidget(self._section("示例", card))
        examples = QVBoxLayout()
        examples.setContentsMargins(0, 0, 0, 0)
        examples.setSpacing(3)
        for expr, what in EXAMPLES:
            examples.addLayout(self._code_note_row(expr, what))
        lay.addLayout(examples)

        lay.addWidget(self._rule(card))
        lay.addWidget(self._section("可用函数", card))
        groups = QVBoxLayout()
        groups.setContentsMargins(0, 0, 0, 0)
        groups.setSpacing(3)
        for label, funcs in FUNCTION_GROUPS:
            group = QLabel(f"{label}　{funcs}")
            group.setObjectName("exprHelpText")
            group.setWordWrap(True)
            groups.addWidget(group)
        lay.addLayout(groups)

        lay.addWidget(self._rule(card))
        ops = QLabel(f"运算符　{OPERATORS}")
        ops.setObjectName("exprHelpText")
        ops.setWordWrap(True)
        lay.addWidget(ops)
        lay.addLayout(self._foot_block(FOOTNOTES))


class SingleParamHelpPopup(ReferenceHelpPopup):
    """参数帮助 card behind the single-op parameter ``?`` badge."""

    TITLE = PARAM_HELP_TITLE
    SUBTITLE = PARAM_HELP_SUBTITLE

    def _fill_body(self, lay, card):
        lay.addWidget(self._section("运算对照", card))
        ops = QVBoxLayout()
        ops.setContentsMargins(0, 0, 0, 0)
        ops.setSpacing(3)
        for op, what in PARAM_OP_ROWS:
            ops.addLayout(self._code_note_row(op, what))
        lay.addLayout(ops)

        lay.addWidget(self._rule(card))
        lay.addWidget(self._section("滑动平均 · 窗长示例", card))
        examples = QVBoxLayout()
        examples.setContentsMargins(0, 0, 0, 0)
        examples.setSpacing(3)
        for ex, what in PARAM_MAVG_EXAMPLES:
            examples.addLayout(self._code_note_row(ex, what))
        lay.addLayout(examples)

        lay.addWidget(self._rule(card))
        lay.addLayout(self._foot_block(PARAM_FOOTNOTES))

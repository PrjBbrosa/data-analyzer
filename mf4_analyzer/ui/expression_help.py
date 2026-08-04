"""Pinnable, draggable help card for the channel editor's 表达式 row.

The ? badge next to the expression input opens this card. Unlike a tooltip it
stays put — the user reads the function list while typing the formula, and can
drag it out of the way by its header. It is deliberately NOT focus-sensitive:
typing in the expression field must never dismiss it.

The reference content lives here as structured data and is rendered twice: as
this card, and (via :func:`help_tooltip_text`) as the badge's hover tooltip, so
the two can never drift apart.
"""
from PyQt5.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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
    """Plain-text rendering of the same reference, for the hover tooltip."""
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


class ExpressionHelpPopup(QWidget):
    """Frameless card: drag by the header, close with × or Esc.

    Parented to the channel editor so it is NOT blocked by that dialog's
    application modality (Qt exempts a modal window's own child windows), and
    so it dies with the editor.
    """

    closed = pyqtSignal()

    WIDTH = 330

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
        self.setFixedWidth(self.WIDTH)
        self.adjustSize()

    # -- construction ------------------------------------------------------
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
        title = QLabel(HELP_TITLE)
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

        subtitle = QLabel(HELP_SUBTITLE)
        subtitle.setObjectName("exprHelpSubtitle")
        lay.addWidget(subtitle)
        lay.addWidget(self._rule(card))

        lay.addWidget(self._section("示例", card))
        examples = QVBoxLayout()
        examples.setContentsMargins(0, 0, 0, 0)
        examples.setSpacing(3)
        for expr, what in EXAMPLES:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            code = QLabel(expr)
            code.setObjectName("exprHelpCode")
            row.addWidget(code, 1)
            note = QLabel(what)
            note.setObjectName("exprHelpText")
            row.addWidget(note, 0, Qt.AlignRight)
            examples.addLayout(row)
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
        feet = QVBoxLayout()
        feet.setContentsMargins(0, 0, 0, 0)
        feet.setSpacing(2)
        for note in FOOTNOTES:
            foot = QLabel(f"· {note}")
            foot.setObjectName("exprHelpFoot")
            foot.setWordWrap(True)
            feet.addWidget(foot)
        lay.addLayout(feet)

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
        host = anchor.window() if anchor is not None else None
        if host is not None:
            frame = host.frameGeometry()
            x = frame.right() + self.GAP
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - 40
            screen = (
                QApplication.screenAt(frame.center())
                or QApplication.primaryScreen()
            )
            if screen is not None:
                avail = screen.availableGeometry()
                if x + self.width() > avail.right():
                    x = frame.left() - self.width() - self.GAP
                x = max(avail.left() + 4, min(x, avail.right() - self.width()))
                y = max(avail.top() + 4, min(y, avail.bottom() - self.height()))
            self.move(x, y)
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

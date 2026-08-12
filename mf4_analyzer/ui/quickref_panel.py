"""操作速查 (Quick-Reference) floating panel.

A non-modal, pinnable, draggable frosted card that renders the
:mod:`mf4_analyzer.ui.quickref` catalog (see the design spec
``docs/superpowers/specs/2026-06-25-operations-quickref-panel-design.md``).

Behavior contract (★ from the spec):

* Non-modal — uses ``show()`` not ``exec_()``; the main window stays fully
  operable while it is open. No dim/modal backdrop.
* Pinnable — pinned adds ``Qt.WindowStaysOnTopHint`` and the panel stays open
  on focus-out; unpinned is a lightweight peek that ``Esc`` / click-outside
  closes.
* Draggable by the header (frameless reposition).
* Live search filters rows (and hides now-empty groups).

Rounded corners + drop shadow WITHOUT ``WA_TranslucentBackground`` on the panel
itself (that breaks the widget's own QSS background → gray box on macOS, per
CLAUDE.md). Instead the translucency lives on the OUTER frameless window and the
white card surface rides on an inner ``QFrame#quickrefCard`` child whose QSS
background therefore stays intact — the same split used by ``glass_tooltip`` and
the RebuildTimePopover (``QFrame#PopoverSurface``).
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import quickref
from ..ui_kit.widgets import SearchField


# --- Precision Light tokens (read from ui_kit/style.qss; do NOT hardcode the
# mockup's approximate hexes). ---
_TRAY = "#f7faff"          # search field rest (blue-white, not tray gray)
_CARD = "#ffffff"          # floating card
_SUB = "#ffffff"           # group sub-card; keep panel off the old gray fill
_DIVIDER = "#dbe5f2"       # card edge / strong seam
_HAIRLINE = "#e9eff7"      # within-card soft separators
_INK = "#111827"           # body / title
_INK2 = "#475569"          # secondary text
_INK3 = "#64748b"          # caption / meta
_ICON = "#5b6472"          # line-icon gray
_ACCENT = "#1769e0"        # chrome accent (selection / primary)
_ACCENT_WASH = "#e8efff"   # accent wash
_SOON_BG = "#eef1ff"
_SOON_FG = "#5b6bd6"
_CHIP_BORDER = "#dfe5ee"

# Shadow geometry: the outer window is translucent and carries an N-px margin
# all around the inner card so the drop shadow has room to render.
_SHADOW_MARGIN = 14
_CARD_RADIUS = 14
_SHADOW_LAYERS = (
    (5, 8, QColor(13, 20, 31, 16)),
    (2, 3, QColor(13, 20, 31, 22)),
)


def _qss():
    """Stylesheet scoped to the panel's object names.

    Scoped so it cannot leak into the global cascade and so the inner
    ``#quickrefCard`` (not the translucent outer window) carries the white fill.
    """
    return f"""
    QFrame#quickrefCard {{
        background-color: {_CARD};
        border: 1px solid {_DIVIDER};
        border-radius: {_CARD_RADIUS}px;
    }}
    QWidget#quickrefHeader {{ background-color: transparent; }}
    QLabel#quickrefTitle {{
        color: {_INK}; font-size: 18px; font-weight: 700;
        background: transparent;
    }}
    QLabel#quickrefSubtitle {{
        color: {_INK3}; font-size: 12px; background: transparent;
    }}
    QLineEdit#quickrefSearch {{
        min-height: 22px;
        padding: 4px 10px;
        border: 1px solid #e2eaf5;
        border-radius: 9px;
        background-color: {_TRAY};
        color: {_INK};
        selection-background-color: {_ACCENT};
        selection-color: #ffffff;
    }}
    QLineEdit#quickrefSearch:focus {{
        border-color: {_ACCENT};
        background-color: #ffffff;
    }}
    QToolButton#quickrefPin, QToolButton#quickrefClose {{
        min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
        padding: 0;
        border: 1px solid transparent;
        border-radius: 7px;
        background-color: transparent;
    }}
    QToolButton#quickrefPin:hover, QToolButton#quickrefClose:hover {{
        background-color: {_HAIRLINE};
        border-color: {_CHIP_BORDER};
    }}
    QToolButton#quickrefPin:checked {{
        background-color: {_ACCENT_WASH};
        border-color: {_ACCENT};
    }}
    QToolButton#quickrefBottomHintsToggle {{
        min-height: 28px;
        padding: 0 9px;
        border: 1px solid {_CHIP_BORDER};
        border-radius: 7px;
        background-color: #ffffff;
        color: {_INK3};
        font-size: 11px;
        font-weight: 600;
    }}
    QToolButton#quickrefBottomHintsToggle:hover {{
        background-color: {_HAIRLINE};
        border-color: #b9c9e5;
    }}
    QToolButton#quickrefBottomHintsToggle:checked {{
        background-color: {_ACCENT_WASH};
        border-color: {_ACCENT};
        color: {_ACCENT};
    }}
    QFrame#quickrefHeaderSep {{
        background-color: {_HAIRLINE};
        max-height: 1px; min-height: 1px; border: none;
    }}
    QScrollArea#quickrefScroll {{ border: none; background: transparent; }}
    QScrollArea#quickrefScroll > QWidget > QWidget {{ background: transparent; }}
    QWidget#quickrefBody {{ background-color: transparent; }}

    QFrame#quickrefGroup {{
        background-color: {_SUB};
        border: 1px solid #e2eaf5;
        border-radius: 11px;
    }}
    QLabel#quickrefGroupTitle {{
        color: #3a3f47; font-size: 13px; font-weight: 700;
        background: transparent;
    }}
    QLabel#quickrefGroupNote {{
        color: {_INK3}; font-size: 11px; background: transparent;
    }}
    QLabel#quickrefGroupDot {{
        min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px;
        border-radius: 3px; background-color: {_ACCENT};
    }}
    QLabel#quickrefDesc {{
        color: {_INK2}; font-size: 13px; background: transparent;
    }}
    QLabel#quickrefDesc[mode="true"] {{
        color: {_INK}; font-weight: 700;
    }}
    QLabel#quickrefSub {{
        color: {_INK3}; font-size: 11px; background: transparent;
    }}
    QLabel#quickrefKbd {{
        background-color: #ffffff;
        border: 1px solid {_CHIP_BORDER};
        border-radius: 6px;
        padding: 1px 7px;
        color: {_INK2};
        font-size: 12px;
    }}
    QLabel#quickrefGesture {{
        background-color: {_ACCENT_WASH};
        color: {_ACCENT};
        border-radius: 6px;
        padding: 1px 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#quickrefSoon {{
        background-color: {_SOON_BG};
        color: {_SOON_FG};
        border-radius: 5px;
        padding: 0px 6px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#quickrefPlus {{
        color: {_INK3}; font-size: 11px; background: transparent;
    }}
    QFrame#quickrefRowSep {{
        background-color: {_HAIRLINE};
        max-height: 1px; min-height: 1px; border: none;
    }}
    QFrame#quickrefModeBar {{
        border-radius: 2px;
        min-width: 3px; max-width: 3px;
    }}
    QFrame#quickrefFoot {{
        background-color: #f8fbff;
        border: none;
        border-top: 1px solid {_HAIRLINE};
        border-bottom-left-radius: {_CARD_RADIUS}px;
        border-bottom-right-radius: {_CARD_RADIUS}px;
    }}
    QLabel#quickrefFootText {{
        color: {_INK3}; font-size: 12px; background: transparent;
    }}
    """


def _kbd_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("quickrefKbd")
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


def _gesture_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("quickrefGesture")
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


class _RowChips(QWidget):
    """Right-aligned chip strip: keyboard chips (gray) + gesture pill (blue)."""

    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addStretch(1)
        # Keyboard chips, with a "+" separator only when the row is a true
        # modifier combo (multiple chips that combine). The single-chip-list
        # rows (e.g. 游标 关/单/双 lists three independent chips) read fine
        # space-separated, so we only insert "+" for the known combo rows by
        # length heuristic: 2-chip combos use "+", >2 are independent.
        keys = row.keys
        combo = len(keys) == 2 and keys[1] in ("滚轮", "拖曲线")
        for i, chip in enumerate(keys):
            if i and combo:
                plus = QLabel("+")
                plus.setObjectName("quickrefPlus")
                lay.addWidget(plus)
            lay.addWidget(_kbd_label(chip))
        if row.gesture:
            lay.addWidget(_gesture_label(row.gesture))


class _GroupCard(QFrame):
    """One titled sub-card; tracks its rows for live filtering."""

    def __init__(self, group, parent=None):
        super().__init__(parent)
        self.setObjectName("quickrefGroup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.group = group
        self._row_widgets = []  # (QuickRow, container, separator-or-None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 11, 14, 8)
        outer.setSpacing(0)

        # Header: accent dot + title (+ optional right note).
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 6)
        head.setSpacing(8)
        dot = QLabel()
        dot.setObjectName("quickrefGroupDot")
        head.addWidget(dot, 0, Qt.AlignVCenter)
        title = QLabel(group.title)
        title.setObjectName("quickrefGroupTitle")
        head.addWidget(title, 0, Qt.AlignVCenter)
        head.addStretch(1)
        if group.note:
            note = QLabel(group.note)
            note.setObjectName("quickrefGroupNote")
            head.addWidget(note, 0, Qt.AlignVCenter)
        outer.addLayout(head)

        for idx, qrow in enumerate(group.rows):
            sep = None
            if idx:
                sep = QFrame()
                sep.setObjectName("quickrefRowSep")
                sep.setFrameShape(QFrame.NoFrame)
                outer.addWidget(sep)
            container = self._build_row(qrow)
            outer.addWidget(container)
            self._row_widgets.append((qrow, container, sep))

    def _build_row(self, qrow) -> QWidget:
        container = QWidget()
        container.setAttribute(Qt.WA_StyledBackground, False)

        if qrow.accent:
            # Mode row: stacked desc + sub with a left color bar (the four modes).
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 8, 2, 8)
            row.setSpacing(8)
            bar = QFrame()
            bar.setObjectName("quickrefModeBar")
            bar.setStyleSheet(f"background-color: {qrow.accent}; border-radius: 2px;")
            bar.setFixedWidth(3)
            row.addWidget(bar)
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            desc = QLabel(qrow.desc)
            desc.setObjectName("quickrefDesc")
            desc.setProperty("mode", "true")
            col.addWidget(desc)
            if qrow.sub:
                sub = QLabel(qrow.sub)
                sub.setObjectName("quickrefSub")
                sub.setWordWrap(True)
                col.addWidget(sub)
            row.addLayout(col, 1)
            return container

        # Standard row: desc (+sub stacked under it) on the left, chips right.
        row = QHBoxLayout(container)
        row.setContentsMargins(2, 7, 2, 7)
        row.setSpacing(10)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(1)
        desc_row = QHBoxLayout()
        desc_row.setContentsMargins(0, 0, 0, 0)
        desc_row.setSpacing(6)
        desc = QLabel(qrow.desc)
        desc.setObjectName("quickrefDesc")
        desc.setWordWrap(True)
        desc_row.addWidget(desc, 0, Qt.AlignVCenter)
        if qrow.soon:
            soon = QLabel("即将")
            soon.setObjectName("quickrefSoon")
            soon.setAlignment(Qt.AlignCenter)
            desc_row.addWidget(soon, 0, Qt.AlignVCenter)
        desc_row.addStretch(1)
        left.addLayout(desc_row)
        if qrow.sub:
            sub = QLabel(qrow.sub)
            sub.setObjectName("quickrefSub")
            sub.setWordWrap(True)
            left.addWidget(sub)
        row.addLayout(left, 1)

        if qrow.keys or qrow.gesture:
            chips = _RowChips(qrow)
            row.addWidget(chips, 0, Qt.AlignTop)
        return container

    def apply_filter(self, needle: str) -> bool:
        """Show only rows matching ``needle``; return True if any row visible."""
        any_visible = False
        first_visible_idx = None
        for idx, (qrow, container, sep) in enumerate(self._row_widgets):
            match = (not needle) or (needle in quickref.search_text(qrow))
            container.setVisible(match)
            if sep is not None:
                sep.setVisible(match)
            if match:
                if first_visible_idx is None:
                    first_visible_idx = idx
                any_visible = True
        # Hide the leading separator of the first still-visible row so the card
        # never opens with a dangling top hairline after filtering.
        if first_visible_idx is not None:
            _qrow, _c, sep = self._row_widgets[first_visible_idx]
            if sep is not None:
                sep.setVisible(False)
        self.setVisible(any_visible)
        return any_visible


class QuickRefPanel(QWidget):
    """Frameless, non-modal, pinnable quick-reference card.

    Construct once (lazily) and ``toggle()`` to show/hide. The translucency
    rides on this outer window; the white surface is the inner
    ``#quickrefCard`` so its QSS background survives (CLAUDE.md gotcha).
    """

    def __init__(
        self,
        parent=None,
        open_guide=None,
        *,
        bottom_hints_visible=False,
        set_bottom_hints_visible=None,
    ):
        # Qt.Tool keeps the window off the taskbar and tied to the app without
        # being modal; FramelessWindowHint lets us draw our own header + shape.
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self._open_guide = open_guide
        self._pinned = False
        self._drag_offset = None
        self._group_cards = []
        self._set_bottom_hints_visible = set_bottom_hints_visible
        self._bottom_hints_visible = bool(bottom_hints_visible)

        # Translucency on the OUTER window only — the inner card carries QSS.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        # StrongFocus + setFocus(self) on show so an unpinned panel can self-close
        # on FocusOut (a child-owned focus would make clearFocus a no-op — see
        # lesson 2026-04-27-popup-clearfocus-needs-strongfocus-on-popup-itself).
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet(_qss())

        self._build()
        self.resize(940, 660)
        self._apply_window_flags()

    # -- construction ------------------------------------------------------
    def _build(self):
        shell = QVBoxLayout(self)
        # The margin is the transparent gutter where the drop shadow renders.
        shell.setContentsMargins(
            _SHADOW_MARGIN, _SHADOW_MARGIN, _SHADOW_MARGIN, _SHADOW_MARGIN
        )
        shell.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("quickrefCard")
        self._card.setAttribute(Qt.WA_StyledBackground, True)
        shell.addWidget(self._card)

        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        card_lay.addWidget(self._build_header())
        sep = QFrame()
        sep.setObjectName("quickrefHeaderSep")
        sep.setFrameShape(QFrame.NoFrame)
        card_lay.addWidget(sep)
        card_lay.addWidget(self._build_body(), 1)
        card_lay.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("quickrefHeader")
        header.setAttribute(Qt.WA_StyledBackground, False)
        self._header = header
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 16, 16, 12)
        lay.setSpacing(12)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        title = QLabel("操作速查")
        title.setObjectName("quickrefTitle")
        titles.addWidget(title)
        subtitle = QLabel("所有手势 / 快捷键 / 功能一览 — 按 ? 随时唤出")
        subtitle.setObjectName("quickrefSubtitle")
        titles.addWidget(subtitle)
        lay.addLayout(titles, 0)
        lay.addStretch(1)

        self._search = SearchField("搜索操作…")
        self._search.setObjectName("quickrefSearch")
        self._search.setFixedWidth(220)
        self._search.textChanged.connect(self._on_search)
        self._search.installEventFilter(self)
        lay.addWidget(self._search, 0, Qt.AlignVCenter)

        self._bottom_hints_toggle = QToolButton()
        self._bottom_hints_toggle.setObjectName("quickrefBottomHintsToggle")
        self._bottom_hints_toggle.setText("底部提示")
        self._bottom_hints_toggle.setCheckable(True)
        self._bottom_hints_toggle.setCursor(Qt.PointingHandCursor)
        self._bottom_hints_toggle.toggled.connect(self._on_bottom_hints_toggled)
        self.set_bottom_hints_visible(self._bottom_hints_visible)
        lay.addWidget(self._bottom_hints_toggle, 0, Qt.AlignVCenter)

        self._pin_btn = QToolButton()
        self._pin_btn.setObjectName("quickrefPin")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setCursor(Qt.PointingHandCursor)
        self._pin_btn.setToolTip("钉住（常驻置顶）")
        self._pin_btn.clicked.connect(self._on_pin_clicked)
        lay.addWidget(self._pin_btn, 0, Qt.AlignVCenter)

        self._close_btn = QToolButton()
        self._close_btn.setObjectName("quickrefClose")
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setToolTip("关闭 (Esc)")
        self._close_btn.clicked.connect(self.hide)
        lay.addWidget(self._close_btn, 0, Qt.AlignVCenter)

        self._refresh_header_icons()
        return header

    def _refresh_header_icons(self):
        from PyQt5.QtCore import QSize
        try:
            import qtawesome as qta
            self._pin_btn.setIcon(
                qta.icon(
                    "mdi.pin" if self._pinned else "mdi.pin-outline",
                    color=(_ACCENT if self._pinned else _ICON),
                )
            )
            self._pin_btn.setIconSize(QSize(18, 18))
            self._close_btn.setIcon(qta.icon("mdi.close", color=_ICON))
            self._close_btn.setIconSize(QSize(18, 18))
        except Exception:
            # qtawesome absent (shouldn't happen in this app) — fall back to text
            # glyphs so the buttons stay usable.
            self._pin_btn.setText("📌")
            self._close_btn.setText("✕")

    def _build_body(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("quickrefScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("quickrefBody")
        body.setAttribute(Qt.WA_StyledBackground, False)
        self._grid = QGridLayout(body)
        self._grid.setContentsMargins(20, 16, 20, 18)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)

        self._populate_grid()
        scroll.setWidget(body)
        self._scroll = scroll
        return scroll

    def _populate_grid(self):
        """Two-column responsive grid; the wide modes group spans both columns.

        Placed in catalog order, left-to-right, top-to-bottom. The wide group is
        forced to start on a fresh row and span 2 columns.
        """
        cols = 2
        r = c = 0
        for group in quickref.QUICKREF:
            card = _GroupCard(group)
            self._group_cards.append(card)
            if group.wide:
                if c != 0:
                    r += 1
                    c = 0
                self._grid.addWidget(card, r, 0, 1, cols)
                r += 1
                c = 0
            else:
                self._grid.addWidget(card, r, c, 1, 1)
                c += 1
                if c >= cols:
                    c = 0
                    r += 1
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        # Keep cards top-anchored (no vertical stretch into the last row).
        self._grid.setRowStretch(r + 1, 1)

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setObjectName("quickrefFoot")
        foot.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(foot)
        lay.setContentsMargins(20, 11, 20, 11)
        lay.setSpacing(6)
        text = QLabel("想深入某个模式 → 各模式右上角的「? 使用说明」打开图文手册")
        text.setObjectName("quickrefFootText")
        lay.addWidget(text, 0, Qt.AlignVCenter)
        lay.addStretch(1)
        # Clicking the footer opens the whole-app manual (deep-dive link target).
        foot.setCursor(Qt.PointingHandCursor)
        foot.mousePressEvent = self._on_footer_clicked  # type: ignore[assignment]
        return foot

    def _on_footer_clicked(self, _ev):
        if callable(self._open_guide):
            try:
                self._open_guide("manual")
            except Exception:
                pass

    # -- search ------------------------------------------------------------
    def _on_search(self, text):
        needle = (text or "").strip().lower()
        for card in self._group_cards:
            card.apply_filter(needle)

    # -- pin / show / hide -------------------------------------------------
    def _on_pin_clicked(self):
        self.set_pinned(self._pin_btn.isChecked())

    def _on_bottom_hints_toggled(self, visible):
        self._bottom_hints_visible = bool(visible)
        self._refresh_bottom_hints_toggle()
        if callable(self._set_bottom_hints_visible):
            try:
                self._set_bottom_hints_visible(self._bottom_hints_visible)
            except Exception:
                pass

    def set_bottom_hints_visible(self, visible):
        """Synchronize the header toggle without re-notifying its host."""
        self._bottom_hints_visible = bool(visible)
        old = self._bottom_hints_toggle.blockSignals(True)
        try:
            self._bottom_hints_toggle.setChecked(self._bottom_hints_visible)
        finally:
            self._bottom_hints_toggle.blockSignals(old)
        self._refresh_bottom_hints_toggle()

    def _refresh_bottom_hints_toggle(self):
        self._bottom_hints_toggle.setToolTip(
            "隐藏窗口底部的操作提示"
            if self._bottom_hints_visible
            else "显示窗口底部的操作提示"
        )

    def set_pinned(self, pinned: bool):
        pinned = bool(pinned)
        if pinned == self._pinned and self._pin_btn.isChecked() == pinned:
            self._refresh_header_icons()
            return
        self._pinned = pinned
        self._pin_btn.setChecked(pinned)
        self._pin_btn.setToolTip(
            "已钉住（再次点击取消）" if pinned else "钉住（常驻置顶）"
        )
        self._refresh_header_icons()
        # Re-applying window flags re-creates the native window → must re-show.
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()
            self.raise_()

    def _apply_window_flags(self):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        if self._pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def is_pinned(self) -> bool:
        return self._pinned

    def toggle(self, anchor_widget=None):
        if self.isVisible():
            self.hide()
        else:
            self.show_panel(anchor_widget)

    def show_panel(self, anchor_widget=None):
        self._search.clear()
        self._on_search("")
        self._position(anchor_widget)
        self.show()
        self.raise_()
        self.activateWindow()
        # Own focus on the panel frame so an unpinned panel reliably closes on
        # FocusOut; give visible keyboard focus to the search box afterwards.
        self.setFocus(Qt.OtherFocusReason)
        self._search.setFocus(Qt.OtherFocusReason)

    def _position(self, anchor_widget):
        """Center over the anchor's top-level window (or the screen)."""
        from PyQt5.QtWidgets import QApplication
        host = None
        if anchor_widget is not None:
            host = anchor_widget.window()
        if host is not None and host.isVisible():
            geo = host.frameGeometry()
        else:
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else None
        if geo is not None:
            x = geo.center().x() - self.width() // 2
            y = geo.top() + max(24, (geo.height() - self.height()) // 3)
            self.move(int(x), int(y))

    # -- frameless drag by header -----------------------------------------
    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton and self._in_header(ev.pos()):
            self._drag_offset = (
                ev.globalPos() - self.frameGeometry().topLeft()
            )
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
        self._drag_offset = None
        super().mouseReleaseEvent(ev)

    def _in_header(self, pos: QPoint) -> bool:
        if not hasattr(self, "_header"):
            return False
        top_left = self._header.mapTo(self, QPoint(0, 0))
        rect = self._header.rect().translated(top_left)
        # Exclude interactive header controls from the drag area.
        for ctrl in (
            self._search,
            self._bottom_hints_toggle,
            self._pin_btn,
            self._close_btn,
        ):
            tl = ctrl.mapTo(self, QPoint(0, 0))
            if ctrl.rect().translated(tl).contains(pos):
                return False
        return rect.contains(pos)

    # -- close semantics ---------------------------------------------------
    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.hide()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def eventFilter(self, obj, ev):  # noqa: N802
        # Esc inside the search box also closes (search owns focus there).
        if obj is getattr(self, "_search", None) and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, ev)

    def focusOutEvent(self, ev):  # noqa: N802
        # Unpinned = lightweight peek: close on focus-out (click-away). Pinned
        # stays open. A child (search) holding focus does NOT fire this because
        # focus is still within the window; Qt only delivers FocusOut to the
        # panel when focus leaves the whole window — which is the click-away we
        # want. Defer the hide so an in-window focus shuffle does not flicker it.
        if not self._pinned:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self._hide_if_unfocused)
        super().focusOutEvent(ev)

    def _hide_if_unfocused(self):
        from PyQt5.QtWidgets import QApplication
        if self._pinned or not self.isVisible():
            return
        active = QApplication.activeWindow()
        # If focus moved to a child of THIS window, keep it open.
        if active is self:
            return
        fw = QApplication.focusWidget()
        if fw is not None and self.isAncestorOf(fw):
            return
        self.hide()

    # -- rounded card + drop shadow ---------------------------------------
    def paintEvent(self, ev):  # noqa: N802
        """Paint a soft drop shadow into the transparent shell margin.

        The card surface + border are drawn by QSS on ``#quickrefCard``; here we
        only add the shadow so the card appears to float. We do NOT fill the
        card area (that would double-paint over the QSS border) — we draw
        expanding translucent rounded outlines behind the card rect.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = _SHADOW_MARGIN
        card_rect = self.rect().adjusted(m, m, -m, -m)
        # Keep the float cue subtle: no native shadow, just a small custom lift.
        for grow, dy, color in _SHADOW_LAYERS:
            r = card_rect.adjusted(-grow, -grow + dy, grow, grow + dy)
            path = QPainterPath()
            path.addRoundedRect(
                float(r.x()), float(r.y()),
                float(r.width()), float(r.height()),
                _CARD_RADIUS + grow, _CARD_RADIUS + grow,
            )
            p.fillPath(path, color)
        p.end()

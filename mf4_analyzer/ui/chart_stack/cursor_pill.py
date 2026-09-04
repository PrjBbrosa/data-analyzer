"""CursorPill, _QualityStatusIndicator, and the readout-formatting helpers.

The formatting half of this module is pure text processing: it turns the
separator-joined HTML the canvases emit on ``cursor_info`` into the pill's
primary line, its full and mini detail tables, and the mini-mode tooltip.
It knows nothing about Qt, so it is unit-testable on its own.
"""
import logging
import re
from html import escape, unescape

from PyQt5.QtCore import QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout,
)

from PyQt5.QtCore import QRectF

from ._helpers import _format_mini_html

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CURSOR_PILL_RADIUS = 9.0
_CURSOR_PILL_BG = QColor(255, 255, 255, 235)
_CURSOR_PILL_BORDER = QColor("#d8e0eb")

# Gap kept on the toggle's right and the clearance reserved on the first line so
# the corner-pinned +/- button never overlaps the primary readout text.
_TOGGLE_EDGE_GAP = 4
_TOGGLE_FIRST_LINE_RESERVE = 24

_CURSOR_HTML_SEP = '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'

_COLOR_RE = re.compile(r'color:\s*([^;"\']+)')
_BOLD_VALUE_RE = re.compile(r'<b[^>]*>(.*?)</b>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')

# Colours the canvas uses for chrome rather than for a channel — the dimmed
# "[file]" prefix. Skipped when picking the colour that represents a channel.
_CURSOR_PREFIX_COLORS = {"#64748b"}

_MINI_VALUE_FONT = "font-family:'SF Mono',Menlo,Consolas,monospace;"

logger = logging.getLogger(__name__)


def _frequency_cursor_label(label):
    """Keep the compact frequency table channel-first in mini mode."""
    text = str(label or '').strip()
    if text.startswith('[') and ']' in text:
        text = text.split(']', 1)[-1].strip()
    if ' · ' in text:
        text = text.rsplit(' · ', 1)[-1].strip()
    return text or '曲线'


def _format_frequency_dual_html(rows):
    """Full FFT A/B readout: one compact table block per spectrum curve."""
    parts = ['<table cellspacing="0" cellpadding="0" '
             'style="font-size:11px; color:#111827;">']
    for index, row in enumerate(rows):
        label, a_value, b_value, delta, unit, color = row[:6]
        top_pad = '7px' if index else '0'
        name = escape(str(label or '曲线'))
        unit_html = escape(str(unit or ''))
        cell = (f'padding:1px 8px 1px 0; color:{color}; font-family:'
                "'SF Mono',Menlo,Consolas,monospace;")
        label_cell = 'padding:1px 4px 1px 0; color:#94a3b8;'
        parts.append(
            f'<tr><td colspan="6" style="padding-top:{top_pad}; '
            f'padding-bottom:2px;"><b style="color:{color};">{name}</b></td></tr>'
            '<tr>'
            f'<td style="{label_cell}">A</td>'
            f'<td style="{cell}" align="right">{a_value:.4g}{unit_html}</td>'
            f'<td style="{label_cell}; padding-left:8px;">B</td>'
            f'<td style="{cell}" align="right">{b_value:.4g}{unit_html}</td>'
            f'<td style="{label_cell}; padding-left:8px;">△</td>'
            f'<td style="{cell} font-weight:700;" align="right">'
            f'{delta:+.4g}{unit_html}</td>'
            '</tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


def _format_frequency_mini_html(rows):
    """Collapsed FFT A/B readout: channel identity plus the useful delta."""
    parts = ['<table cellspacing="0" cellpadding="0" style="font-size:11px;">']
    for index, row in enumerate(rows):
        label, _a_value, _b_value, delta, unit, color = row[:6]
        top_pad = '5px' if index else '0'
        name = escape(_frequency_cursor_label(label))
        unit_html = escape(str(unit or ''))
        parts.append(
            '<tr>'
            f'<td style="padding-top:{top_pad};"><span style="color:{color};">●</span></td>'
            f'<td style="padding-left:4px; color:{color}; font-weight:600; '
            f'padding-top:{top_pad};">{name}</td>'
            f'<td style="padding-left:8px; color:{color}; {_MINI_VALUE_FONT} '
            f'font-weight:700; padding-top:{top_pad};">△&nbsp;{delta:+.4g}{unit_html}</td>'
            '</tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Readout formatting (pure text — no Qt)
# ---------------------------------------------------------------------------

def strip_html(value):
    """Return ``value`` with tags removed and entities resolved."""
    return unescape(_TAG_RE.sub('', value or ''))


def single_cursor_channel_color(part):
    """Pick the colour that stands for the channel in one readout segment.

    A segment is typically ``[file]`` in the dimmed prefix colour followed by
    ``name=<b>value</b>`` in the channel's own colour, so the last colour before
    the bold value wins and prefix colours are skipped.
    """
    colors = [m.group(1).strip() for m in _COLOR_RE.finditer(part or '')]
    if not colors:
        return '#111827'
    value_match = _BOLD_VALUE_RE.search(part or '')
    if value_match:
        before_value = part[:value_match.start()]
        value_colors = [
            m.group(1).strip()
            for m in _COLOR_RE.finditer(before_value)
        ]
        for color in reversed(value_colors):
            if color.lower() not in _CURSOR_PREFIX_COLORS:
                return color
    for color in reversed(colors):
        if color.lower() not in _CURSOR_PREFIX_COLORS:
            return color
    return colors[-1]


def mini_single_cursor_part(part, top_pad):
    """Render one readout segment as a mini-mode table row: a coloured dot plus
    the bare value, with the channel name dropped."""
    color = single_cursor_channel_color(part)
    value_match = _BOLD_VALUE_RE.search(part or '')
    if value_match:
        value = strip_html(value_match.group(1)).strip()
    else:
        plain = strip_html(part).strip()
        value = plain.split('=', 1)[-1].strip() if '=' in plain else plain
    value = value or '—'
    mono = _MINI_VALUE_FONT
    value_html = escape(value)
    return (
        '<tr>'
        f'<td style="padding-top:{top_pad}; padding-right:5px; '
        'line-height:1.15;">'
        f'<span style="color:{color};">●</span></td>'
        f'<td style="padding-top:{top_pad}; color:{color}; '
        f'line-height:1.15; {mono} font-weight:650;">{value_html}</td>'
        '</tr>'
    )


def plain_single_cursor_tooltip_line(part):
    """Flatten one readout segment to ``name=value`` plain text for the tooltip
    shown while the pill is collapsed to values only."""
    plain = strip_html(part).replace('\xa0', ' ').strip()
    plain = re.sub(r'\s+', ' ', plain)
    if not plain:
        return ''
    if '=' not in plain:
        return re.sub(r'^\[[^\]]+\]\s*', '', plain).strip()
    name, value = plain.split('=', 1)
    name = re.sub(r'^\[[^\]]+\]\s*', '', name).strip()
    value = value.strip()
    return f'{name}={value}' if name else value


def format_single_cursor_variants(text):
    """Split a single-cursor readout into ``(primary, full, mini, tooltip)``.

    The first separator-delimited segment is the time readout and stays on the
    pill's primary line; the rest become one detail row each, rendered twice —
    full (name and value) and mini (value only) — plus a plain-text tooltip that
    restores the names the mini variant drops. Text with no separator has no
    per-channel detail and passes straight through as the primary line.
    """
    parts = [part for part in (text or '').split(_CURSOR_HTML_SEP) if part]
    if len(parts) <= 1:
        return text, '', '', ''
    full_rows = ['<table cellspacing="0" cellpadding="0">']
    mini_rows = [
        '<table cellspacing="0" cellpadding="0" '
        'style="font-size:12px;">'
    ]
    tooltip_lines = []
    for i, part in enumerate(parts[1:]):
        top_pad = '2px' if i > 0 else '0'
        full_rows.append(
            '<tr><td style="padding-top:'
            f'{top_pad}; padding-bottom:0; line-height:1.15;">'
            f'{part}</td></tr>'
        )
        mini_rows.append(mini_single_cursor_part(part, top_pad))
        tooltip_line = plain_single_cursor_tooltip_line(part)
        if tooltip_line:
            tooltip_lines.append(tooltip_line)
    full_rows.append('</table>')
    mini_rows.append('</table>')
    return (
        parts[0],
        ''.join(full_rows),
        ''.join(mini_rows),
        '\n'.join(tooltip_lines),
    )


def format_cursor_info(text, mode):
    """Return ``(primary, detail)`` for ``text`` under cursor ``mode``.

    Only single-cursor readouts carrying the separator are split; everything
    else is the primary line verbatim. ``mode`` is required here — resolving it
    from live state is the caller's job.
    """
    if mode != 'single' or _CURSOR_HTML_SEP not in (text or ''):
        return text, ''
    primary, detail, _mini_detail, _tooltip = format_single_cursor_variants(text)
    return primary, detail


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class CursorPill(QFrame):
    """Draggable floating pill with a primary line (time / A·B / ΔT) and an
    optional detail block (per-channel Min/Max/Avg/△ as RichText). The
    user can drag it anywhere inside the canvas area."""

    display_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cursorPill")
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(2)
        self._primary = QLabel("", self)
        self._primary.setObjectName("cursorPillPrimary")
        self._primary.setTextFormat(Qt.RichText)
        self._primary.setTextInteractionFlags(Qt.NoTextInteraction)
        # Reserve room on the first line's right so the corner-pinned toggle
        # never overlaps the readout even when the primary line is the widest
        # row (e.g. dual-cursor A·B·ΔT·1/ΔT). Only the first line is padded; the
        # detail block below keeps the full width.
        self._primary.setContentsMargins(0, 0, _TOGGLE_FIRST_LINE_RESERVE, 0)
        self._detail = QLabel("", self)
        self._detail.setObjectName("cursorPillDetail")
        self._detail.setTextFormat(Qt.RichText)
        self._detail.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail.setVisible(False)
        lay.addWidget(self._primary)
        lay.addWidget(self._detail)
        self._drag_offset = None
        # User-positioned flag — true after first manual drag, so resize events
        # respect the chosen spot instead of snapping back to default corner.
        self._user_placed = False
        self._mode = "full"
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._display_projection = None
        self._display_layout_category = "natural"
        self._visible_channel_count = 0
        self._avoidance_restore_anchor = None
        self._avoidance_obstacle = None
        # Free-floating child pinned to the top-right corner. Repositioned from
        # adjustSize() (every content/width change funnels through it) and
        # resizeEvent, so it stays in the corner without depending on event
        # delivery timing.
        self._toggle_btn = QPushButton("−", self)
        self._toggle_btn.setObjectName("cursorPillToggle")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.setCursor(Qt.ArrowCursor)
        self._toggle_btn.clicked.connect(self._toggle_mode)
        self._update_toggle_button()
        self._position_toggle()

    def _position_toggle(self):
        """Pin the +/- toggle to the pill's top-right corner."""
        btn = self._toggle_btn
        btn.move(self.width() - btn.width() - _TOGGLE_EDGE_GAP, _TOGGLE_EDGE_GAP)
        btn.raise_()

    def adjustSize(self):
        # Every content/width change funnels through adjustSize(); reposition the
        # corner toggle here so it never depends on resize-event delivery timing.
        super().adjustSize()
        self._position_toggle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_toggle()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(_CURSOR_PILL_BG)
            painter.setPen(QPen(_CURSOR_PILL_BORDER, 1.0))
            painter.drawRoundedRect(rect, _CURSOR_PILL_RADIUS, _CURSOR_PILL_RADIUS)
        finally:
            painter.end()

    def primary_text(self):
        return self._primary.text()

    def detail_text(self):
        return self._detail.text()

    def set_primary(self, text):
        old_right = self.geometry().right()
        old_top = self.y()
        self._primary.setText(text)
        self.adjustSize()
        self.move_preserving_right_edge(old_right, old_top)

    def set_detail_html(self, html):
        self._clear_display_projection()
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        if html:
            self._detail.setText(html)
            self._detail.setToolTip("")
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setToolTip("")
            self._detail.setVisible(False)
        self.adjustSize()

    def set_single_detail_html(self, full_html, mini_html, tooltip=""):
        self._clear_display_projection()
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = full_html or ""
        self._single_mini_detail = mini_html or ""
        self._single_tooltip = tooltip or ""
        self._refresh_detail()
        self.adjustSize()

    def snapshot(self):
        return {
            "primary": self._primary.text(),
            "detail": self.detail_text(),
            "detail_visible": self.has_detail(),
            "detail_tooltip": self._detail.toolTip(),
            "mode": self._mode,
            "dual_rows": list(self._dual_rows),
            "frequency_dual_rows": list(self._frequency_dual_rows),
            "single_full_detail": self._single_full_detail,
            "single_mini_detail": self._single_mini_detail,
            "single_tooltip": self._single_tooltip,
        }

    def restore_snapshot(self, snapshot):
        self._clear_display_projection()
        self._mode = snapshot.get("mode") or "full"
        if self._mode not in {"full", "mini"}:
            self._mode = "full"
        self._primary.setText(snapshot.get("primary") or "")
        self._dual_rows = list(snapshot.get("dual_rows") or [])
        self._frequency_dual_rows = list(
            snapshot.get("frequency_dual_rows") or []
        )
        self._single_full_detail = snapshot.get("single_full_detail") or ""
        self._single_mini_detail = snapshot.get("single_mini_detail") or ""
        self._single_tooltip = snapshot.get("single_tooltip") or ""
        self._update_toggle_button()
        if (
            self._dual_rows
            or self._frequency_dual_rows
            or self._single_full_detail
        ):
            self._refresh_detail()
        else:
            detail = snapshot.get("detail") if snapshot.get("detail_visible") else ""
            if detail:
                self._detail.setText(detail)
                self._detail.setToolTip(snapshot.get("detail_tooltip") or "")
                self._detail.setVisible(True)
            else:
                self._detail.clear()
                self._detail.setToolTip("")
                self._detail.setVisible(False)
        self.adjustSize()

    def has_detail(self):
        return not self._detail.isHidden() and bool(self._detail.text())

    def clear(self):
        self._primary.clear()
        self._detail.clear()
        self._detail.setToolTip("")
        self._detail.setVisible(False)
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._clear_display_projection()
        self.setVisible(False)

    def mark_user_placed(self, value=True):
        self._user_placed = bool(value)

    def is_user_placed(self):
        return self._user_placed

    def _clear_display_projection(self):
        self._display_projection = None
        self._display_layout_category = "natural"
        self._visible_channel_count = 0
        self._avoidance_restore_anchor = None
        self._avoidance_obstacle = None

    def safe_rect(self):
        parent = self.parentWidget()
        if parent is None:
            return QRect(self.rect())
        rect = parent.contentsRect().adjusted(8, 8, -8, -8)
        return rect if rect.isValid() else QRect(parent.contentsRect())

    def layout_category(self):
        return self._display_layout_category

    def display_mode(self):
        return self._mode

    def visible_channel_count(self):
        return self._visible_channel_count

    def set_display_projection(self, projection):
        """Show a structured projection and adapt it to the parent safe rect."""
        old_right = self.geometry().right()
        old_top = self.y()
        had_geometry = self.width() > 0 and self.height() > 0
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._display_projection = projection
        self._mode = "mini" if bool(getattr(projection, "mini", False)) else "full"
        self._update_toggle_button()
        self._detail.setToolTip(getattr(projection, "tooltip", "") or "")
        self.reflow_to_parent(
            preserved_right=old_right if self._user_placed and had_geometry else None,
            preserved_top=old_top if self._user_placed and had_geometry else None,
        )

    def _middle_elide_label(self, text, width):
        """Return a width-aware middle elision that keeps both identities visible."""
        text = str(text or "")
        metrics = self._detail.fontMetrics()
        if metrics.horizontalAdvance(text) <= width:
            return text
        marker = "..."
        if metrics.horizontalAdvance(marker) >= width:
            return marker
        # Preserve a meaningful source prefix and channel suffix when the
        # available width permits it; these are the two identity cues users
        # need to distinguish similar long labels.
        head = min(14, max(1, len(text) - 1))
        tail = min(12, max(1, len(text) - head))
        if metrics.horizontalAdvance(f"{text[:head]}{marker}{text[-tail:]}") > width:
            head = tail = 1
        while head + tail < len(text):
            candidate = f"{text[:head]}{marker}{text[-tail:]}"
            if metrics.horizontalAdvance(candidate) > width:
                break
            if head <= tail:
                head += 1
            else:
                tail += 1
        return f"{text[:max(1, head - 1)]}{marker}{text[-max(1, tail - 1):]}"

    def _apply_display_projection(self, category, count):
        from .cursor_display import render_cursor_presentation, visible_block_label

        projection = self._display_projection
        self._display_layout_category = category
        self._visible_channel_count = min(count, len(projection.blocks))
        self._detail.setWordWrap(category == "constrained")
        header_overrides = None
        if category == "constrained":
            header_width = max(20, int(self._detail.maximumWidth() * 1.2))
            omit_prefix = bool(projection.omit_visible_source_prefix)
            header_overrides = tuple(
                self._middle_elide_label(
                    visible_block_label(block, omit_prefix), header_width
                )
                for block in projection.blocks[:self._visible_channel_count]
            )
        self._detail.setText(render_cursor_presentation(
            projection,
            layout_category=category,
            visible_count=self._visible_channel_count,
            header_overrides=header_overrides,
        ))
        self._detail.setToolTip(projection.tooltip or "")
        self._detail.setVisible(bool(projection.blocks))
        self._detail.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()
        self.adjustSize()

    def reflow_to_parent(self, *, preserved_right=None, preserved_top=None):
        projection = self._display_projection
        if projection is None:
            return
        safe = self.safe_rect()
        if safe.width() <= 0 or safe.height() <= 0:
            return
        if preserved_right is None and self._user_placed:
            preserved_right = self.geometry().right()
            preserved_top = self.y()

        self._detail.setMaximumWidth(16777215)
        self.layout().setContentsMargins(10, 7, 10, 8)
        self._apply_display_projection("natural", len(projection.blocks))
        hint = self.sizeHint()
        category = (
            "natural"
            if hint.width() <= safe.width() and hint.height() <= safe.height()
            else "constrained"
        )
        if category == "constrained":
            detail_width = max(20, safe.width() - 20)
            self._detail.setMaximumWidth(detail_width)
            self.layout().setContentsMargins(10, 1, 10, 1)
            low = 0
            high = len(projection.blocks)
            last_count = None
            while low < high:
                count = (low + high + 1) // 2
                self._apply_display_projection("constrained", count)
                last_count = count
                if self.sizeHint().height() <= safe.height():
                    low = count
                else:
                    high = count - 1
            chosen = low
            if last_count != chosen:
                self._apply_display_projection("constrained", chosen)
            target = self.sizeHint()
            self.resize(
                min(target.width(), safe.width()),
                min(target.height(), safe.height()),
            )
        if preserved_right is not None:
            self.move_preserving_right_edge(preserved_right, preserved_top or safe.top())
        elif not self._user_placed:
            self.move(safe.right() - self.width() + 1, safe.top())
        self._clamp_to_safe_rect()
        if (
            self._avoidance_restore_anchor is not None
            and self._avoidance_obstacle is not None
        ):
            obstacle, gap = self._avoidance_obstacle
            self.avoid_rect(obstacle, gap=gap)

    def _clamp_to_safe_rect(self):
        safe = self.safe_rect()
        x = max(safe.left(), min(self.x(), safe.right() - self.width() + 1))
        y = max(safe.top(), min(self.y(), safe.bottom() - self.height() + 1))
        self.move(x, y)

    def avoid_rect(self, obstacle, *, gap=8):
        """Displace away from a parent-coordinate obstacle without drift."""
        obstacle = QRect(obstacle)
        padded = obstacle.adjusted(-gap, -gap, gap, gap)
        if self._avoidance_restore_anchor is not None:
            self._avoidance_obstacle = (QRect(obstacle), int(gap))
        if not self.geometry().intersects(padded):
            return
        if self._avoidance_restore_anchor is None:
            self._avoidance_restore_anchor = (self.geometry().right(), self.y())
            self._avoidance_obstacle = (QRect(obstacle), int(gap))
        safe = self.safe_rect()
        left_x = padded.left() - self.width() - 1
        right_x = padded.right() + 1
        if left_x >= safe.left():
            self.move(left_x, self.y())
        elif right_x + self.width() - 1 <= safe.right():
            self.move(right_x, self.y())
        else:
            above_y = padded.top() - self.height() - 1
            below_y = padded.bottom() + 1
            self.move(self.x(), above_y if above_y >= safe.top() else below_y)
        self._clamp_to_safe_rect()

    def avoid_global_rect(self, obstacle, *, gap=8):
        """Displace from a screen-coordinate popup rectangle."""
        parent = self.parentWidget()
        if parent is None:
            return
        obstacle = QRect(obstacle)
        top_left = parent.mapFromGlobal(obstacle.topLeft())
        bottom_right = parent.mapFromGlobal(obstacle.bottomRight())
        self.avoid_rect(QRect(top_left, bottom_right), gap=gap)

    def restore_after_avoidance(self):
        if self._avoidance_restore_anchor is None:
            return
        right, top = self._avoidance_restore_anchor
        self._avoidance_restore_anchor = None
        self._avoidance_obstacle = None
        safe = self.safe_rect()
        x = int(right) - self.width() + 1
        x = max(safe.left(), min(x, safe.right() - self.width() + 1))
        y = max(safe.top(), min(int(top), safe.bottom() - self.height() + 1))
        self.move(x, y)

    # ---- drag handling ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            parent = self.parentWidget()
            new_top_left = self.mapToParent(e.pos() - self._drag_offset)
            if parent is not None:
                safe = self.safe_rect()
                x = max(safe.left(), min(
                    new_top_left.x(), safe.right() - self.width() + 1
                ))
                y = max(safe.top(), min(
                    new_top_left.y(), safe.bottom() - self.height() + 1
                ))
                self.move(x, y)
            else:
                self.move(new_top_left)
            self._user_placed = True
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def _toggle_mode(self):
        old_right = self.x() + self.width()
        old_top = self.y()
        self._mode = "mini" if self._mode == "full" else "full"
        self._update_toggle_button()
        if self._display_projection is not None:
            self.display_mode_changed.emit(self._mode)
            return
        self._refresh_detail()
        self.adjustSize()
        self.move_preserving_right_edge(old_right, old_top)
        self.display_mode_changed.emit(self._mode)

    def move_preserving_right_edge(self, right_edge, top):
        parent = self.parentWidget()
        new_x = int(right_edge) - self.width()
        new_y = int(top)
        if parent is not None:
            anchor_right = max(0, min(int(right_edge), parent.width()))
            max_x = max(parent.width() - self.width(), 0)
            max_y = max(parent.height() - self.height(), 0)
            new_x = max(0, min(anchor_right - self.width(), max_x))
            new_y = max(0, min(new_y, max_y))
        self.move(new_x, new_y)

    # Backwards-compatible private alias for internal callers.
    _move_preserving_right_edge = move_preserving_right_edge

    def _update_toggle_button(self):
        self._toggle_btn.setText("+" if self._mode == "mini" else "−")
        self._toggle_btn.setToolTip(
            "展开通道名" if self._mode == "mini" else "收起为数值"
        )
        self._toggle_btn.setProperty("cursorPillMode", self._mode)
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)

    def set_dual_rows(self, rows):
        self._clear_display_projection()
        self._dual_rows = rows or []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._refresh_detail()
        if self._dual_rows:
            self._detail.setVisible(True)
        self.adjustSize()

    def set_frequency_dual_rows(self, rows):
        """Set structured FFT A/B rows for full/mini cursor-pill toggling."""
        self._clear_display_projection()
        self._frequency_dual_rows = rows or []
        self._dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._refresh_detail()
        if self._frequency_dual_rows:
            self._detail.setVisible(True)
        self.adjustSize()

    def _refresh_detail(self):
        if self._dual_rows:
            from ..plot_helpers import (
                _format_dual_html,
                format_dual_rows_tooltip,
            )
            html = (
                _format_dual_html(self._dual_rows)
                if self._mode == "full"
                else _format_mini_html(self._dual_rows)
            )
            tooltip = (
                format_dual_rows_tooltip(self._dual_rows)
                if self._mode == "mini"
                else ""
            )
        elif self._frequency_dual_rows:
            html = (
                _format_frequency_dual_html(self._frequency_dual_rows)
                if self._mode == "full"
                else _format_frequency_mini_html(self._frequency_dual_rows)
            )
            tooltip = ""
        elif self._single_full_detail:
            html = (
                self._single_mini_detail
                if self._mode == "mini" and self._single_mini_detail
                else self._single_full_detail
            )
            tooltip = self._single_tooltip if self._mode == "mini" else ""
        else:
            html = ""
            tooltip = ""
        if html:
            self._detail.setText(html)
            self._detail.setToolTip(tooltip)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setToolTip("")
            self._detail.setVisible(False)


class _QualityStatusIndicator(QFrame):
    """Small hoverable AA status dot overlaid on the chart card chrome."""

    _COLORS = {
        "idle": QColor("#9ca3af"),
        "preview": QColor("#60a5fa"),
        "green": QColor("#22c55e"),
        "yellow": QColor("#f59e0b"),
        "red": QColor("#ef4444"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chartQualityIndicator")
        self.setFixedSize(20, 20)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._state = "idle"
        self.set_quality_status({
            "state": "idle",
            "tooltip": "无曲线",
        })

    def set_quality_status(self, status):
        raw = (status or {}).get("state")
        state = str(raw) if raw else "idle"
        if state not in self._COLORS:
            logger.warning(
                "unknown quality-dot state %r; falling back to idle",
                state,
            )
            state = "idle"
        self._state = state
        self.setProperty("qualityState", state)
        self.setToolTip(str((status or {}).get("tooltip") or "抗锯齿状态未知"))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(5.0, 5.0, -5.0, -5.0)
            painter.setBrush(self._COLORS.get(self._state, self._COLORS["idle"]))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1.0))
            painter.drawEllipse(rect)
        finally:
            painter.end()

"""CursorPill, _QualityStatusIndicator, and the readout-formatting helpers.

The formatting half of this module is pure text processing: it turns the
separator-joined HTML the canvases emit on ``cursor_info`` into the pill's
primary line and its full and mini detail tables. It knows nothing about Qt,
so it is unit-testable on its own. The result panel itself never attaches a
hover tooltip; the visible face and the +/- toggle are the only readouts.
"""
import logging
import re
from html import escape, unescape
from math import ceil

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QTextDocument, QTextOption,
)
from PyQt5.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout,
)

from PyQt5.QtCore import QRectF, QSizeF

from ._helpers import _format_mini_html
from .cursor_table_layout import choose_table_layout, compute_wcap

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

# Shown when even a single primary fragment cannot fit the budget (R6).
_OUT_OF_SPACE_TEXT = "空间不足"

# Horizontal margins of the pill frame around the content labels (top, right,
# bottom, left in the current layout order 10,7,10,8).
_PILL_LEFT_MARGIN = 10
_PILL_RIGHT_MARGIN = 10
_PILL_TOP_MARGIN = 7
_PILL_BOTTOM_MARGIN = 8
# Trailing clearance between the numeric grid and frame; the shared paint
# document itself has zero margin so geometry does not depend on Qt defaults.
_TABLE_EDGE_CLEARANCE = 6.0

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
    """Flatten one readout segment to ``name=value`` plain text.

    Kept as a formatter helper for snapshot/compat callers. The result panel
    does not attach this string as a hover tooltip.
    """
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
    full (name and value) and mini (value only). The fourth return value is a
    plain-text identity dump kept for snapshot/compat callers; the pill does
    not show it as a hover tooltip. Text with no separator has no per-channel
    detail and passes straight through as the primary line.
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

class _DocumentLabel(QLabel):
    """A QLabel compatibility surface whose structured text paints its measured document.

    Legacy setters still use QLabel. Structured readouts explicitly install a
    document, so Qt cannot apply different hidden wrapping/indent during paint.
    """

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self.document = QTextDocument(self)
        self._document_active = False

    def setText(self, text):
        self._document_active = False
        super().setText(text)

    def clear(self):
        self._document_active = False
        super().clear()

    def set_document_html(self, text, width):
        self.ensurePolished()
        super().setText(text)
        self._document_active = True
        size = self.measure_document(text, width)
        self.updateGeometry()
        self.update()
        return size

    def measure_document(self, text, width):
        """Configure the paint document without applying intermediate label text."""
        self.ensurePolished()
        self.document.setDocumentMargin(0)
        self.document.setDefaultFont(self.font())
        option = self.document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document.setDefaultTextOption(option)
        self.document.setHtml(text)
        self.document.setTextWidth(max(1.0, width))
        return self.document.size()

    def sizeHint(self):
        if not self._document_active:
            return super().sizeHint()
        margins = self.contentsMargins()
        size = self.document.size()
        return QSize(ceil(size.width()) + margins.left() + margins.right(),
                     ceil(size.height()) + margins.top() + margins.bottom())

    def hasHeightForWidth(self):
        return False if self._document_active else super().hasHeightForWidth()

    def heightForWidth(self, width):
        if self._document_active:
            return self.sizeHint().height()
        return super().heightForWidth(width)

    def minimumSizeHint(self):
        if self._document_active:
            return QSize(0, self.sizeHint().height())
        return super().minimumSizeHint()

    def paintEvent(self, event):
        if not self._document_active:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        try:
            painter.translate(self.contentsRect().topLeft())
            self.document.drawContents(painter, QRectF(self.contentsRect().translated(
                -self.contentsRect().topLeft())))
        finally:
            painter.end()


class CursorPill(QFrame):
    """Draggable floating pill with a primary line (time / A·B / ΔT) and an
    optional detail block (per-channel Min/Max/Avg/△ as RichText). The
    user can drag it anywhere inside the canvas area."""

    display_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._space_hidden = False
        self._visibility_requested = False
        self.setObjectName("cursorPill")
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(2)
        self._primary = _DocumentLabel("", self)
        self._primary.setObjectName("cursorPillPrimary")
        self._primary.setVisible(False)
        self._primary.setTextFormat(Qt.RichText)
        self._primary.setTextInteractionFlags(Qt.NoTextInteraction)
        # Reserve room on the first line's right so the corner-pinned toggle
        # never overlaps the readout even when the primary line is the widest
        # row (e.g. dual-cursor A·B·ΔT·1/ΔT). Only the first line is padded; the
        # detail block below keeps the full width.
        self._primary.setContentsMargins(0, 0, _TOGGLE_FIRST_LINE_RESERVE, 0)
        self._detail = _DocumentLabel("", self)
        self._detail.setObjectName("cursorPillDetail")
        self._detail.setTextFormat(Qt.RichText)
        self._detail.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail.setVisible(False)
        self._clear_content_tooltip()
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
        # Shared-table layout state (R8). Structural inputs (host size,
        # font, field/channel sets, mode) rebuild the plan; value-only
        # updates reuse it and may only grow the value envelope.
        self._table_plan = None
        self._layout_signature = None
        self._value_envelope_width = 0.0
        self._name_elisions = ()
        self._pane_content_width = 0.0
        # ChartStack supplies the owning canvas's mapped safe rectangle for
        # managed pills. Standalone/compatibility users retain the parent
        # contents-rect fallback in ``safe_rect`` below.
        self._safe_rect_override = None
        self._primary_original = ""
        self._text_measure_cache = {}
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

    def setVisible(self, visible):
        self._visibility_requested = bool(visible)
        super().setVisible(bool(visible) and not self._space_hidden)

    def show(self):
        self.setVisible(True)

    def awaiting_space(self):
        """Whether a requested visible readout awaits a larger owning pane."""
        return self._space_hidden and self._visibility_requested

    def _set_space_hidden(self, hidden):
        was_hidden = self._space_hidden
        self._space_hidden = bool(hidden)
        if hidden:
            super().setVisible(False)
        elif was_hidden:
            super().setVisible(self._visibility_requested)

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
        self._primary_original = text or ""
        self._apply_primary_layout()
        self.adjustSize()
        self.move_preserving_right_edge(old_right, old_top)

    # ---- primary budget (R7) ---------------------------------------------

    def _primary_budget(self):
        """Content width available to the primary line; 0 until geometry."""
        if self._pane_content_width > 0:
            return self._pane_content_width
        safe = self.safe_rect()
        if safe.width() <= 0:
            return 0.0
        return max(0.0, compute_wcap(safe.width()) - 20.0)

    def _apply_primary_layout(self, budget=None):
        """Apply primary wrapping within ``budget`` (or this pill's width).

        Shared tables deliberately settle to their measured grid width rather
        than the pane ceiling.  Passing that settled width here keeps a later
        high-rate primary update from reopening the whitespace the table just
        removed.
        """
        if budget is None:
            budget = self._primary_budget()
        text = self._primary_original
        self._primary.setVisible(bool(text))
        if budget > 0:
            text = self._primary_for_budget(text, max(1, budget - _TOGGLE_FIRST_LINE_RESERVE))
        if budget > 0:
            if self._display_projection is None:
                # Legacy full/mini details retain their intrinsic widths. The
                # primary has a ceiling, not a permanently occupied grid.
                budget = min(budget, self._primary_html_width(text) + _TOGGLE_FIRST_LINE_RESERVE)
            self._primary.set_document_html(text, max(1, budget - _TOGGLE_FIRST_LINE_RESERVE))
        else:
            self._primary.setText(text)
        if budget > 0:
            self._primary.setWordWrap(True)
            self._primary.setMaximumWidth(int(ceil(budget)))
        else:
            self._primary.setWordWrap(False)
            self._primary.setMaximumWidth(16777215)

    def _primary_for_budget(self, text, budget):
        """Regroup the separator-delimited primary into whole fragments (R7).

        Only readouts with 3–4 ``│``-separated segments (time dual A/B and
        ΔT/1/ΔT) are regrouped; everything else passes through unchanged and
        relies on word wrap. Segments are the existing formatting contract —
        no value is parsed or recomputed.
        """
        if not text:
            return text
        if self._primary_html_width(text) <= budget:
            return text
        segments = [part for part in text.split(_CURSOR_HTML_SEP) if part]
        if not 3 <= len(segments) <= 4:
            return text
        grouped = (
            _CURSOR_HTML_SEP.join(segments[:2]) + "<br>"
            + _CURSOR_HTML_SEP.join(segments[2:])
        )
        if self._primary_html_width(grouped) <= budget:
            return grouped
        each = "<br>".join(segments)
        if self._primary_html_width(each) <= budget:
            return each
        # One segment alone still exceeds the budget: show the short
        # out-of-space state instead of splitting a number mid-token (R6).
        return _OUT_OF_SPACE_TEXT

    def _primary_html_width(self, html):
        self._primary.ensurePolished()
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self._primary.font())
        doc.setHtml(html)
        return doc.idealWidth()

    def _primary_doc_size(self, width=None):
        if not (self._primary.text() or "").strip():
            return QSizeF(0.0, 0.0)
        return self._primary.document.size()

    def _clear_content_tooltip(self):
        """The result panel never uses a hover tooltip for readout content."""
        self.setToolTip("")
        self._primary.setToolTip("")
        self._detail.setToolTip("")

    def set_detail_html(self, html):
        self._clear_display_projection()
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        if html:
            self._detail.setText(html)
            self._clear_content_tooltip()
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._clear_content_tooltip()
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
        self._primary_original = snapshot.get("primary") or ""
        self._primary.setText(self._primary_original)
        self._primary.setVisible(bool(self._primary_original))
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
                self._clear_content_tooltip()
                self._detail.setVisible(True)
            else:
                self._detail.clear()
                self._clear_content_tooltip()
                self._detail.setVisible(False)
        self.adjustSize()

    def has_detail(self):
        return not self._detail.isHidden() and bool(self._detail.text())

    def clear(self):
        self._primary.clear()
        self._primary.setVisible(False)
        self._primary_original = ""
        self._detail.clear()
        self._clear_content_tooltip()
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
        self._reset_table_state()

    def _reset_table_state(self):
        """Drop every structural measurement/layout artifact (R8 cleanup)."""
        self._table_plan = None
        self._layout_signature = None
        self._value_envelope_width = 0.0
        self._name_elisions = ()
        self._text_measure_cache = {}
        self._pane_content_width = 0.0
        self._space_hidden = False

    def safe_rect(self):
        if self._safe_rect_override is not None:
            return QRect(self._safe_rect_override)
        parent = self.parentWidget()
        if parent is None:
            return QRect(self.rect())
        rect = parent.contentsRect().adjusted(8, 8, -8, -8)
        return rect if rect.isValid() else QRect(parent.contentsRect())

    def set_safe_rect(self, rect):
        """Set a parent-coordinate safe rectangle supplied by ChartStack.

        The pill remains parented to the shared stack for compositing, while
        this override keeps geometry, width budgets and drag clamping inside
        its own canvas when time-domain split mode is active. ``None`` keeps
        the legacy parent-contents fallback for standalone callers.
        """
        next_rect = QRect(rect) if rect is not None and rect.isValid() else None
        if next_rect == self._safe_rect_override:
            return False
        self._safe_rect_override = next_rect
        return True

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
        if self._avoidance_restore_anchor is not None:
            # While displaced by a popover, the user anchor is the avoidance
            # anchor, not the displaced geometry (which would drift).
            old_right = self._avoidance_restore_anchor[0]
            old_top = self._avoidance_restore_anchor[1]
        had_geometry = self.width() > 0 and self.height() > 0
        self._dual_rows = []
        self._frequency_dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._display_projection = projection
        self._mode = "mini" if bool(getattr(projection, "mini", False)) else "full"
        self._update_toggle_button()
        self._clear_content_tooltip()
        self.reflow_to_parent(
            preserved_right=old_right if self._user_placed and had_geometry else None,
            preserved_top=old_top if self._user_placed and had_geometry else None,
        )

    def _middle_elide_label(self, text, width, measure=None):
        """Return a width-aware middle elision that keeps both identities visible."""
        text = str(text or "")
        if measure is None:
            measure = self._detail.fontMetrics().horizontalAdvance
        if measure(text) <= width:
            return text
        marker = "..."
        if measure(marker) >= width:
            return marker
        # Preserve a meaningful source prefix and channel suffix when the
        # available width permits it; these are the two identity cues users
        # need to distinguish similar long labels.
        head = min(14, max(1, len(text) - 1))
        tail = min(12, max(1, len(text) - head))
        if measure(f"{text[:head]}{marker}{text[-tail:]}") > width:
            head = tail = 1
        while head + tail < len(text):
            candidate = f"{text[:head]}{marker}{text[-tail:]}"
            if measure(candidate) > width:
                break
            if head <= tail:
                head += 1
            else:
                tail += 1
        return f"{text[:max(1, head - 1)]}{marker}{text[-max(1, tail - 1):]}"

    def _apply_display_projection(self, category, count, *, table_html=None):
        from .cursor_display import render_cursor_presentation, visible_block_label

        projection = self._display_projection
        self._display_layout_category = category
        self._visible_channel_count = min(count, len(projection.blocks))
        if table_html is not None:
            self._detail.setWordWrap(False)
            self._detail.set_document_html(table_html, self._pane_content_width)
        else:
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
        self._clear_content_tooltip()
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

        self._reflow_shared_table(
            projection, safe, preserved_right, preserved_top
        )

    def _reflow_legacy(self, projection, safe, preserved_right, preserved_top):
        """Previous natural/constrained reflow for non-table projections."""
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
        self._settle_position(preserved_right, preserved_top, safe)

    def _settle_position(self, preserved_right, preserved_top, safe):
        if preserved_right is not None:
            self.move_preserving_right_edge(
                preserved_right, preserved_top or safe.top()
            )
        elif not self._user_placed:
            self.move(safe.right() - self.width() + 1, safe.top())
        self._clamp_to_safe_rect()
        if (
            self._avoidance_restore_anchor is not None
            and self._avoidance_obstacle is not None
        ):
            obstacle, gap = self._avoidance_obstacle
            self.avoid_rect(obstacle, gap=gap)

    # ---- shared table reflow (R4/R5/R8) -----------------------------------

    def _reflow_shared_table(self, projection, safe,
                             preserved_right, preserved_top):
        from .cursor_display import visible_block_label

        self._detail.ensurePolished()
        self._primary.ensurePolished()
        # The ratio budget is a preference; a fitting horizontal table may
        # grow up to the owning pane / absolute ceiling.
        wcap = min(640.0, float(safe.width()))
        content = max(
            0.0, wcap - _PILL_LEFT_MARGIN - _PILL_RIGHT_MARGIN - _TABLE_EDGE_CLEARANCE
        )
        # Start from the pane's *ceiling*.  It becomes the settled content
        # width below once the table's actual grid width is known.
        self._pane_content_width = content
        # Structural change rebuilds the plan and resets the envelope;
        # value-only updates keep both and may only grow the envelope (R8).
        signature = self._layout_signature_for(projection)
        if signature != self._layout_signature:
            self._layout_signature = signature
            self._value_envelope_width = 0.0
            self._text_measure_cache = {}
        envelope = self._refresh_value_envelope(projection)
        label_widths = tuple(
            self._measure_body_text(label)
            for label in projection.metric_labels
        )
        plan = choose_table_layout(
            content_width=content,
            value_envelope_width=envelope,
            field_labels=projection.metric_labels,
            field_label_widths=label_widths,
            signal_width=max((self._signal_width(block, projection)
                              for block in projection.blocks), default=0.0),
            branch_width=max((self._measure_body_text(row.branch_label) + 10
                              for block in projection.blocks for row in block.table_rows
                              if row.branch_label), default=0.0),
        )
        self._table_plan = plan
        if plan.required_width > content:
            self._show_space_state(projection, safe, preserved_right, preserved_top)
            return
        self._name_elisions = tuple(
            self._fit_name_html(
                visible_block_label(
                    block, bool(projection.omit_visible_source_prefix)
                ),
                plan, block.unit_text,
            )
            for block in projection.blocks
        )
        # A QTextDocument with setTextWidth(content) reports that imposed
        # width, not its intrinsic table width.  Treating it as a measurement
        # made every panel expand to Wcap and created the large blank slabs in
        # the cursor screenshots.  The layout plan's shared column sum is the
        # width contract; use it as the settled content width instead.
        table_width = (
            min(content, max((self._signal_width(block, projection)
                              for block in projection.blocks), default=1.0))
            if plan.kind == "identity" else min(
                content,
                max(1.0, plan.required_width + _TABLE_EDGE_CLEARANCE),
            )
        )
        primary_fragments = [part for part in self._primary_original.split(_CURSOR_HTML_SEP) if part]
        primary_min = max((self._primary_html_width(part)
                           for part in primary_fragments), default=0.0)
        table_width = min(content + _TABLE_EDGE_CLEARANCE,
                          max(table_width, min(primary_min + _TOGGLE_FIRST_LINE_RESERVE,
                                               compute_wcap(safe.width()) - 20)))
        self._pane_content_width = table_width
        self._detail.setMaximumWidth(int(ceil(table_width)))
        self._apply_primary_layout(table_width)
        primary_h = self._primary_doc_size(table_width).height()
        available = max(
            0.0,
            safe.height()
            - _PILL_TOP_MARGIN - _PILL_BOTTOM_MARGIN - 2.0
            - primary_h,
        )
        total = len(projection.blocks)
        low, high = 0, total
        while low < high:
            count = (low + high + 1) // 2
            _w, h = self._measure_html(
                self._table_html_for_count(projection, count), table_width
            )
            if h <= available:
                low = count
            else:
                high = count - 1
        chosen = low
        final_html = self._table_html_for_count(projection, chosen)
        if self._measure_html(final_html, table_width)[1] > available:
            self._show_space_state(projection, safe, preserved_right, preserved_top)
            return
        self._apply_table_html(projection, chosen, final_html)
        _measured_w, detail_h = self._measure_html(final_html, table_width)
        # ``setTextWidth`` makes documentSize().width() equal its constraint,
        # so it is intentionally not used to choose frame width here.
        frame_w = int(ceil(table_width)) + _PILL_LEFT_MARGIN + _PILL_RIGHT_MARGIN
        frame_h = int(
            primary_h + 2.0 + detail_h
        ) + _PILL_TOP_MARGIN + _PILL_BOTTOM_MARGIN
        self.resize(int(frame_w), min(int(frame_h), safe.height()))
        self._settle_position(preserved_right, preserved_top, safe)
        self._set_space_hidden(False)

    def _show_space_state(self, projection, safe, preserved_right, preserved_top):
        """Keep an unfit readout explicit without splitting a numeric token."""
        self._primary.hide()
        width = min(max(1, safe.width() - 20),
                    ceil(self._measure_body_text(_OUT_OF_SPACE_TEXT)) + _TOGGLE_FIRST_LINE_RESERVE)
        self._pane_content_width = width
        self._detail.setMaximumWidth(ceil(width))
        html = f'<span style="font-size:11px;color:#64748b;">{_OUT_OF_SPACE_TEXT}</span>'
        self._apply_table_html(projection, 0, html)
        height = ceil(self._detail.document.size().height()) + 15
        minimum_width = (ceil(self._measure_body_text(_OUT_OF_SPACE_TEXT))
                         + self._toggle_btn.width() + _TOGGLE_EDGE_GAP + 20)
        if safe.height() < height or safe.width() < minimum_width:
            self._set_space_hidden(True)
            return
        self.resize(min(safe.width(), ceil(width) + 20), min(safe.height(), height))
        self._settle_position(preserved_right, preserved_top, safe)
        self._set_space_hidden(False)

    def _layout_signature_for(self, projection):
        return (
            projection.cursor_mode,
            projection.x_mode,
            bool(projection.mini),
            self.safe_rect().width(),
            self._detail.font().key(), self._primary.font().key(),
            self.logicalDpiX(), self.logicalDpiY(),
            projection.metric_labels,
            tuple((str(block.identity), block.channel_label, block.qualified_label,
                   block.unit_text, tuple(row.branch_label for row in block.table_rows))
                  for block in projection.blocks),
        )

    def _refresh_value_envelope(self, projection):
        """Width reserve for the formatted value columns (R8).

        Starts from the widest current value text (not the global .4g worst
        case, which would starve narrow hosts) and only ever grows within a
        structural period; it never shrinks after a short value. A structural
        change resets it via ``_layout_signature``.
        """
        envelope = self._value_envelope_width
        for block in projection.blocks:
            for row in block.table_rows:
                for text in row.metric_texts:
                    if text:
                        envelope = max(envelope, self._measure_mono_text(text))
        self._value_envelope_width = envelope
        return envelope

    def _measure_span(self, text, style):
        key = (style, str(text))
        if key not in self._text_measure_cache:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setDefaultFont(self._detail.font())
            doc.setHtml(f'<span style="font-size:11px;{style}">{escape(str(text))}</span>')
            self._text_measure_cache[key] = float(doc.idealWidth())
        return self._text_measure_cache[key]

    def _measure_mono_text(self, text):
        # Delta is bold; reserve the wider variant for every shared column.
        return max(self._measure_span(text, _MINI_VALUE_FONT),
                   self._measure_span(text, _MINI_VALUE_FONT + "font-weight:700;"))

    def _measure_body_text(self, text):
        return self._measure_span(text, "font-weight:400;")

    def _measure_name_text(self, text):
        return self._measure_span(text, "font-weight:600;")

    def _signal_width(self, block, projection):
        from .cursor_display import visible_block_label
        name = visible_block_label(block, bool(projection.omit_visible_source_prefix))
        if projection.mini and projection.cursor_mode == "single":
            name = ""
        return (self._measure_name_text(name) + self._measure_body_text("● ")
                + (self._measure_body_text(block.unit_text) + 6 if block.unit_text else 0)
                + 16)

    def _measure_html(self, html, width):
        # The same persistent document is subsequently used by paintEvent.
        size = self._detail.measure_document(html, width)
        return size.width(), size.height()

    def _table_html_for_count(self, projection, count):
        from .cursor_display import render_cursor_presentation

        return render_cursor_presentation(
            projection,
            layout_plan=self._table_plan,
            visible_count=count,
            header_lines=self._name_elisions,
        )

    def _apply_table_html(self, projection, count, html):
        category = "natural" if count >= len(projection.blocks) else "constrained"
        self._apply_display_projection(category, count, table_html=html)

    def _fit_name_html(self, name, plan, unit=""):
        # Raw text crosses the renderer seam. Reserve all actual adjacent ink
        # before eliding; escaped entities must never be measured as letters.
        budget = max(0.0, plan.name_budget - self._measure_body_text("● ") - 16)
        if unit:
            budget = max(0.0, budget - self._measure_body_text(unit) - 6)
        if budget <= 0:
            return ("",)
        return tuple(self._fit_name_lines(str(name or ""), budget, plan.name_max_lines))

    def _fit_name_lines(self, text, budget, max_lines):
        measure = self._measure_name_text
        remaining = str(text)
        lines = []
        while len(lines) < max_lines - 1 and measure(remaining) > budget:
            # Keep underscore-delimited engineering names readable too. One
            # unbroken Rte_* token is not a reason to discard the second line.
            low, high = 0, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if measure(remaining[:middle]) <= budget:
                    low = middle
                else:
                    high = middle - 1
            if low == 0:
                break
            boundary = max(remaining.rfind(" ", 0, low + 1),
                           remaining.rfind("_", 0, low))
            split = boundary + 1 if boundary >= low // 2 else low
            lines.append(remaining[:split].rstrip())
            remaining = remaining[split:].lstrip()
        lines.append(self._middle_elide_label(remaining, budget, measure))
        return lines

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
            from ..plot_helpers import _format_dual_html
            html = (
                _format_dual_html(self._dual_rows)
                if self._mode == "full"
                else _format_mini_html(self._dual_rows)
            )
        elif self._frequency_dual_rows:
            html = (
                _format_frequency_dual_html(self._frequency_dual_rows)
                if self._mode == "full"
                else _format_frequency_mini_html(self._frequency_dual_rows)
            )
        elif self._single_full_detail:
            html = (
                self._single_mini_detail
                if self._mode == "mini" and self._single_mini_detail
                else self._single_full_detail
            )
        else:
            html = ""
        if html:
            self._detail.setText(html)
            self._clear_content_tooltip()
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._clear_content_tooltip()
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

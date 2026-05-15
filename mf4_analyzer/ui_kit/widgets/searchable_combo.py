"""Drop-in replacement for QComboBox that supports type-to-filter search.

Usage:
    cb = SearchableComboBox(parent)
    cb.addItems(channel_names)

The completer matches anywhere in the string (substring), case-insensitive.
After every model change (addItem, addItems, clear, insertItem) the completer
is re-bound to the live model so its filter stays correct.
"""
import re

from PyQt5.QtCore import QSortFilterProxyModel, QSize, Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QComboBox, QCompleter, QStyledItemDelegate, QStyle


_TOKEN_SPLIT_RE = re.compile(r"[\s_\-:./\\|,;()[\]{}]+")


def _normalized_tokens(text):
    return [
        token for token in _TOKEN_SPLIT_RE.split(str(text).casefold())
        if token
    ]


def _normalized_text(text):
    return " ".join(_normalized_tokens(text))


def _token_matches(text, token):
    normalized = _normalized_text(text)
    if not token:
        return True
    if token in normalized:
        return True
    pos = 0
    for ch in normalized:
        if ch == token[pos]:
            pos += 1
            if pos == len(token):
                return True
    return False


def _highlight_char_indexes(text, query):
    text = str(text)
    indexes = set()
    for token in _normalized_tokens(query):
        lowered = text.casefold()
        start = lowered.find(token)
        if start >= 0:
            indexes.update(range(start, start + len(token)))
            continue

        best_match = None
        for chunk, chunk_indexes in _search_chunks(text):
            matched = _fuzzy_indexes_in_chunk(chunk, chunk_indexes, token)
            if matched is None:
                continue
            span = matched[-1] - matched[0] if matched else 0
            if best_match is None or span < best_match[0]:
                best_match = (span, matched)
        if best_match is not None:
            indexes.update(best_match[1])
            continue

        matched = _fuzzy_indexes_in_chunk(text, list(range(len(text))), token)
        if matched is not None:
            indexes.update(matched)
    return indexes


def _search_chunks(text):
    chunks = []
    chars = []
    indexes = []

    def flush():
        if chars:
            chunks.append(("".join(chars), list(indexes)))
            chars.clear()
            indexes.clear()

    for i, ch in enumerate(str(text)):
        if not _normalized_text(ch):
            flush()
            continue
        if (
            chars
            and ch.isupper()
            and (chars[-1].islower() or chars[-1].isdigit())
        ):
            flush()
        chars.append(ch)
        indexes.append(i)
    flush()
    return chunks


def _fuzzy_indexes_in_chunk(chunk, chunk_indexes, token):
    pos = 0
    matched = []
    for local_i, ch in enumerate(chunk):
        if ch.casefold() == token[pos]:
            matched.append(chunk_indexes[local_i])
            pos += 1
            if pos == len(token):
                return matched
    return None


def _split_combo_label(text):
    raw = str(text)
    prefix = ""
    rest = raw
    if raw.startswith("[") and "]" in raw:
        end = raw.index("]")
        prefix = raw[: end + 1]
        rest = raw[end + 1:].strip()
    if ":" in rest:
        head, tail = rest.rsplit(":", 1)
        main = tail.strip() or rest
        meta = f"{prefix} {head.strip()}".strip()
    else:
        main = rest or raw
        meta = prefix
    return main, meta


class _FuzzyProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tokens = []

    def setFilterText(self, text):
        self._tokens = _normalized_tokens(text)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._tokens:
            return True
        idx = self.sourceModel().index(source_row, self.filterKeyColumn(), source_parent)
        text = idx.data(Qt.DisplayRole) or ""
        return all(_token_matches(text, token) for token in self._tokens)


class _FuzzyCompleter(QCompleter):
    def __init__(self, proxy_model, parent=None):
        super().__init__(proxy_model, parent)
        self._proxy_model = proxy_model

    def splitPath(self, path):
        self._proxy_model.setFilterText(path)
        return [""]


class _TwoLineChannelDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 48

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), self.ROW_HEIGHT))

    def _query_text(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "lineEdit"):
            line_edit = parent.lineEdit()
            if line_edit is not None:
                return line_edit.text()
        return ""

    def _draw_highlighted_text(
        self, painter, x, baseline, text, query, normal_color, highlight_color,
    ):
        highlights = _highlight_char_indexes(text, query)
        if not highlights:
            painter.setPen(normal_color)
            painter.drawText(x, baseline, text)
            return

        metrics = painter.fontMetrics()
        cursor = x
        for i, ch in enumerate(text):
            painter.setPen(highlight_color if i in highlights else normal_color)
            painter.drawText(cursor, baseline, ch)
            cursor += metrics.horizontalAdvance(ch)

    def paint(self, painter, option, index):
        opt = option
        text = index.data(Qt.DisplayRole) or ""
        main, meta = _split_combo_label(text)
        style = opt.widget.style() if opt.widget is not None else None
        if style is not None:
            style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)

        selected = bool(opt.state & QStyle.State_Selected)
        main_color = opt.palette.highlightedText().color() if selected else QColor("#111827")
        meta_color = QColor("#dbeafe") if selected else QColor("#64748b")
        highlight_color = QColor("#bfdbfe") if selected else QColor("#0b73e7")
        query = self._query_text()
        rect = opt.rect.adjusted(8, 4, -8, -4)

        painter.save()
        main_font = QFont(opt.font)
        main_font.setBold(True)
        painter.setFont(main_font)
        painter.setPen(main_color)
        main_metrics = painter.fontMetrics()
        main_text = main_metrics.elidedText(main, Qt.ElideMiddle, rect.width())
        self._draw_highlighted_text(
            painter, rect.x(), rect.y() + 16,
            main_text, query, main_color, highlight_color,
        )

        meta_font = QFont(opt.font)
        meta_font.setPointSize(max(8, opt.font.pointSize() - 1))
        painter.setFont(meta_font)
        painter.setPen(meta_color)
        meta_metrics = painter.fontMetrics()
        meta_text = meta_metrics.elidedText(meta or text, Qt.ElideMiddle, rect.width())
        self._draw_highlighted_text(
            painter, rect.x(), rect.y() + 35,
            meta_text, query, meta_color, highlight_color,
        )
        painter.restore()


class SearchableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(10)
        delegate = _TwoLineChannelDelegate(self)
        self.setItemDelegate(delegate)
        self.view().setItemDelegate(delegate)
        self._completer_delegate = _TwoLineChannelDelegate(self)
        self._proxy_model = _FuzzyProxyModel(self)
        completer = _FuzzyCompleter(self._proxy_model, self)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.popup().setItemDelegate(self._completer_delegate)
        completer.popup().setUniformItemSizes(False)
        self.setCompleter(completer)
        if self.lineEdit() is not None:
            self.lineEdit().textChanged.connect(self._proxy_model.setFilterText)
        self._rebind_completer_model()
        self._sync_popup_geometry()

    def _rebind_completer_model(self):
        self._proxy_model.setSourceModel(self.model())
        c = self.completer()
        if c is not None:
            c.setModel(self._proxy_model)
            c.popup().setItemDelegate(self._completer_delegate)
        self._sync_popup_geometry()

    def _sync_popup_geometry(self):
        width = max(1, self.width())
        height = _TwoLineChannelDelegate.ROW_HEIGHT * self.maxVisibleItems() + 8
        views = [self.view()]
        c = self.completer()
        if c is not None:
            views.append(c.popup())
        for view in views:
            if view is None:
                continue
            view.setMinimumWidth(width)
            view.setMaximumWidth(width)
            view.setMaximumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_popup_geometry()

    def showPopup(self):
        self._sync_popup_geometry()
        super().showPopup()

    def _set_item_tooltip(self, index):
        text = self.itemText(index)
        if text:
            self.setItemData(index, text, Qt.ToolTipRole)

    # Methods that mutate the item set: re-bind after each.
    def addItem(self, *args, **kwargs):
        super().addItem(*args, **kwargs)
        self._set_item_tooltip(self.count() - 1)
        self._rebind_completer_model()

    def addItems(self, items):
        super().addItems(items)
        start = self.count() - len(items)
        for i in range(max(0, start), self.count()):
            self._set_item_tooltip(i)
        self._rebind_completer_model()

    def insertItem(self, *args, **kwargs):
        super().insertItem(*args, **kwargs)
        if args:
            try:
                self._set_item_tooltip(int(args[0]))
            except (TypeError, ValueError):
                pass
        self._rebind_completer_model()

    def insertItems(self, *args, **kwargs):
        super().insertItems(*args, **kwargs)
        if len(args) >= 2:
            try:
                start = int(args[0])
                for i in range(start, start + len(args[1])):
                    self._set_item_tooltip(i)
            except (TypeError, ValueError):
                pass
        self._rebind_completer_model()

    def clear(self):
        super().clear()
        self._rebind_completer_model()

    def setCurrentText(self, text):
        """Drop-in compatible: when ``text`` matches an existing item, also
        update ``currentIndex`` (default ``QComboBox.setCurrentText`` only sets
        the line-edit text on editable combos, leaving the index stale)."""
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            super().setCurrentText(text)

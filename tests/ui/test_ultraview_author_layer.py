"""Offscreen contracts for the interactive-safe UltraView author layer."""
from __future__ import annotations

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtGui import QFontMetrics, QImage, QInputMethodEvent, QPainter, QTextFormat
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.ultraview.author_layer import (
    AuthorLayerModel,
    AuthorPaintLayer,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_widgets import (
    BoardTextEditor,
    StickyNoteWidget,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import GridMetrics
from mf4_analyzer.ui.ultraview_state import BoardBox, StickyObject


def _metrics() -> GridMetrics:
    return GridMetrics(
        board_width=640,
        board_height=420,
        column_width=120,
        row_height=88,
        gutter=16,
        padding=20,
        resolution=2,
    )


def test_author_paint_layer_is_transparent_sibling_and_reprojects_selection(qapp):
    host = QWidget()
    host.resize(700, 500)
    layer = AuthorPaintLayer(host)
    editor = BoardTextEditor(host)
    layer.setGeometry(host.rect())
    model = AuthorLayerModel(
        metrics=_metrics(),
        origin_offset=(-2.0, -1.0),
        selection_boxes=((0.0, 1.0, 2.0, 1.0),),
    )
    layer.set_model(model)

    assert layer.parentWidget() is host
    assert editor.parentWidget() is host
    assert editor.parentWidget() is not layer
    assert layer.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert layer.focusPolicy() == Qt.NoFocus
    assert layer.model().selection_boxes == ((0.0, 1.0, 2.0, 1.0),)

    # Render only the transparent sibling: the injected selection chrome is
    # visible, while the layer has no interactive child surface of its own.
    image = QImage(700, 500, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    layer.render(painter)
    painter.end()
    assert image.pixelColor(156, 124).blue() > image.pixelColor(156, 124).red()

    # The current geometry is evaluated with the supplied signed origin, not
    # stored as stale screen pixels; a later extent rebase updates projection.
    layer.set_view_geometry(_metrics(), origin_offset=(-3.0, -1.0), zoom=1.0)
    assert layer.model().origin_offset == (-3.0, -1.0)
    assert layer.model().lod == "full"
    layer.set_zoom(0.2)
    assert layer.model().lod == "minimal"
    layer.set_zoom(1.0)
    assert layer.model().lod == "full"


def test_sticky_widget_bounds_text_projects_geometry_and_emits_ime_commit(qapp):
    host = QWidget()
    host.resize(700, 500)
    host.show()
    sticky = StickyNoteWidget(host)
    item = StickyObject(
        "sticky-1",
        "sticky",
        box=BoardBox(-1.0, 1.0, 2.0, 1.5),
        text="初始",
        palette="cyan",
    )
    sticky.apply_object(item, _metrics(), origin_offset=(-2.0, -1.0))
    qapp.processEvents()

    assert sticky.geometry().getRect() == (88, 124, 136, 78)
    assert sticky.editor().toPlainText() == "初始"
    sticky.editor().setPlainText("x" * 3_100)
    assert len(sticky.editor().toPlainText()) == 3_000

    ime_spy = QSignalSpy(sticky.ime_committed)
    event = QInputMethodEvent()
    event.setCommitString("中文")
    QCoreApplication.sendEvent(sticky.editor(), event)
    assert len(ime_spy) == 1
    assert ime_spy[0] == ["sticky-1", "中文"]

    commit_spy = QSignalSpy(sticky.text_committed)
    sticky.begin_edit()
    QTest.keyClick(sticky.editor(), Qt.Key_Return, Qt.ControlModifier)
    assert len(commit_spy) == 1
    assert commit_spy[0][0] == "sticky-1"
    assert len(commit_spy[0][1]) == 3_000


def test_temporary_text_editor_is_sibling_and_supports_ime_commit_cancel(qapp):
    host = QWidget()
    host.resize(700, 500)
    host.show()
    editor = BoardTextEditor(host)
    editor.begin_edit(
        object_id="text-1",
        box=BoardBox(0.0, 0.0, 2.0, 1.0),
        text="",
        metrics=_metrics(),
        origin_offset=(-1.0, -1.0),
    )
    qapp.processEvents()

    assert editor.parentWidget() is host
    assert editor.is_editing()
    assert editor.geometry().getRect() == (88, 72, 136, 52)

    ime_spy = QSignalSpy(editor.ime_text_committed)
    event = QInputMethodEvent()
    event.setCommitString("中文输入")
    QCoreApplication.sendEvent(editor, event)
    assert len(ime_spy) == 1
    assert ime_spy[0] == ["text-1", "中文输入"]

    cancel_spy = QSignalSpy(editor.edit_cancelled)
    QTest.keyClick(editor, Qt.Key_Escape)
    assert len(cancel_spy) == 1
    assert cancel_spy[0] == ["text-1"]
    assert not editor.is_editing()

    editor.begin_edit(
        object_id="text-1",
        box=BoardBox(0.0, 0.0, 2.0, 1.0),
        text="要提交",
        metrics=_metrics(),
        origin_offset=(-1.0, -1.0),
    )
    commit_spy = QSignalSpy(editor.text_committed)
    QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
    assert len(commit_spy) == 1
    assert commit_spy[0] == ["text-1", "要提交"]
    assert not editor.is_editing()


def test_board_text_editor_live_font_size_updates_document_pixels(qapp):
    from mf4_analyzer.ui.ultraview_state import TextObject

    host = QWidget()
    host.resize(700, 500)
    host.show()
    editor = BoardTextEditor(host)
    style = TextObject(
        "text-1",
        "text",
        box=BoardBox(0.0, 0.0, 3.0, 1.5),
        text="的他",
        font_size=14,
    )
    editor.begin_edit(
        object_id="text-1",
        box=style.box,
        text=style.text,
        metrics=_metrics(),
        style=style,
    )
    qapp.processEvents()
    assert editor.font().pixelSize() == 14
    assert editor.document().defaultFont().pixelSize() == 14

    larger = TextObject(
        "text-1",
        "text",
        box=style.box,
        text="的他",
        font_size=24,
    )
    editor.apply_live_style(larger)
    qapp.processEvents()
    assert editor.font().pixelSize() == 24
    assert editor.document().defaultFont().pixelSize() == 24
    cursor = editor.textCursor()
    cursor.select(cursor.Document)
    assert cursor.charFormat().font().pixelSize() == 24
    assert cursor.charFormat().property(QTextFormat.FontPixelSize) == 24


def test_board_text_editor_bold_large_size_keeps_positive_glyph_advance(qapp):
    """Regression: stylesheet polish + Bold used to collapse advance to ~0 (stacking)."""
    from mf4_analyzer.ui.ultraview_state import TextObject

    host = QWidget()
    host.resize(700, 500)
    host.show()
    editor = BoardTextEditor(host)
    style = TextObject(
        "text-1",
        "text",
        box=BoardBox(0.0, 0.0, 4.0, 2.0),
        text="mw,",
        font_size=14,
        bold=True,
    )
    editor.begin_edit(
        object_id="text-1",
        box=style.box,
        text=style.text,
        metrics=_metrics(),
        style=style,
    )
    qapp.processEvents()
    large = TextObject(
        "text-1",
        "text",
        box=style.box,
        text="mw,",
        font_size=32,
        bold=True,
    )
    editor.apply_live_style(large)
    qapp.processEvents()
    font = editor.document().defaultFont()
    assert font.pixelSize() == 32
    assert font.bold() is True
    metrics = QFontMetrics(font)
    advance = metrics.horizontalAdvance("mw,")
    assert advance >= metrics.horizontalAdvance("m") * 2
    cursor = editor.textCursor()
    cursor.select(cursor.Document)
    assert cursor.charFormat().property(QTextFormat.FontPixelSize) == 32

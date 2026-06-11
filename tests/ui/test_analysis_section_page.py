"""AnalysisSectionPage: pane container structure + focus + split + link."""
import pytest

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent

from mf4_analyzer.ui.analysis_section_page import AnalysisSectionPage
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState


def _make_manager():
    return ViewManager(state_factory=AnalysisViewState)


class _FakeCard:
    """Card stub: AnalysisSectionPage only needs .canvas and QWidget-ness."""
    def __new__(cls):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.setObjectName("chartCard")
        w.canvas = PgHeatmapCanvas(w)
        return w


class _FakeLineCard:
    """Line-canvas card variant (FFT section): canvas has no ._plot/_img."""
    def __new__(cls):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.setObjectName("chartCard")
        w.canvas = PgLineCanvas(w)
        return w


@pytest.fixture
def page(qapp):
    mgr = _make_manager()
    p = AnalysisSectionPage(
        section='order',
        manager=mgr,
        card_factory=lambda: _FakeCard(),
    )
    p.resize(800, 500)
    p.show()  # 见教训：QSplitter.setSizes 前需 show()+resize
    yield p
    p.deleteLater()


@pytest.fixture
def line_page(qapp):
    mgr = _make_manager()
    p = AnalysisSectionPage(
        section='fft',
        manager=mgr,
        card_factory=lambda: _FakeLineCard(),
    )
    p.resize(800, 500)
    p.show()
    yield p
    p.deleteLater()


def test_starts_with_one_pane(page):
    assert page.pane_count() == 1
    assert page.focused_index() == 0


def test_enter_exit_split(page):
    page.enter_split()
    assert page.pane_count() == 2
    page.exit_split()
    assert page.pane_count() == 1
    assert page.focused_index() == 0


def test_set_focus(page):
    page.enter_split()
    page.set_focused_index(1)
    assert page.focused_index() == 1


def test_x_link_toggle(page):
    page.enter_split()
    page.set_linked(True)
    vb0 = page.pane_canvas(0)._plot.vb
    vb1 = page.pane_canvas(1)._plot.vb
    assert vb1.linkedView(vb1.XAxis) is vb0
    page.set_linked(False)
    assert vb1.linkedView(vb1.XAxis) is None


def test_heatmap_link_locks_both_axes(page):
    """Heatmaps compare on BOTH axes (spec §6.1)."""
    page.enter_split()
    page.set_linked(True)
    vb0 = page.pane_canvas(0)._plot.vb
    vb1 = page.pane_canvas(1)._plot.vb
    assert vb1.linkedView(vb1.YAxis) is vb0
    page.set_linked(False)
    assert vb1.linkedView(vb1.YAxis) is None


def test_line_set_linked_no_attribute_error(line_page):
    """PgLineCanvas has _plot_amp/_plot_psd, NOT _plot — set_linked must not
    AttributeError, and the amp row's X axis must be linked (X only, no Y)."""
    line_page.enter_split()
    line_page.set_linked(True)  # would AttributeError on a naive ._plot.vb
    vb0 = line_page.pane_canvas(0)._plot_amp.vb
    vb1 = line_page.pane_canvas(1)._plot_amp.vb
    assert vb1.linkedView(vb1.XAxis) is vb0
    # Line sections do NOT Y-link (only heatmaps do).
    assert vb1.linkedView(vb1.YAxis) is None
    line_page.set_linked(False)
    assert vb1.linkedView(vb1.XAxis) is None


def test_click_pane_sets_focus(page):
    """eventFilter: a mouse press on pane 1 makes it the focused pane."""
    page.enter_split()
    assert page.focused_index() == 0
    card1 = page._cards[1]
    ev = QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(5, 5),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    page.eventFilter(card1, ev)
    assert page.focused_index() == 1


def test_focus_signal_emitted(page):
    received = []
    page.focus_changed.connect(received.append)
    page.enter_split()
    page.set_focused_index(1)
    assert received == [1]

"""Tests for the pure axis-hit detection helper used by all 4 canvases."""
import pytest
from matplotlib.figure import Figure


def _build_fig_with_axes():
    fig = Figure(figsize=(8, 6), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    fig.canvas.draw()  # ensure renderer + bbox available
    return fig, ax


def test_find_axis_hit_x_label_region():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    # 30 px below the axes bottom -- inside the 45 px gutter
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=(bbox.x0 + bbox.x1) / 2, y_px=bbox.y0 - 30, margin=45,
    )
    assert hit_ax is ax
    assert axis == 'x'


def test_find_axis_hit_y_label_region():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=bbox.x0 - 30, y_px=(bbox.y0 + bbox.y1) / 2, margin=45,
    )
    assert hit_ax is ax
    assert axis == 'y'


def test_find_axis_no_hit_returns_none():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    # Center of the axes -- far from any edge
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=(bbox.x0 + bbox.x1) / 2, y_px=(bbox.y0 + bbox.y1) / 2,
        margin=45,
    )
    assert hit_ax is None
    assert axis is None


def test_timedomain_canvas_dblclick_opens_chart_options_from_axis_gutter(qtbot, monkeypatch):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import TimeDomainCanvas

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)

    # Plot something so axes have a bbox
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    # Stub the dialog to auto-accept and mutate the target axes.
    from mf4_analyzer.ui import _axis_interaction
    called = {}

    def fake_edit(parent_widget, ax_):
        called['ax'] = ax_
        ax_.set_xlim(0, 10)
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_chart_options_dialog',
                        fake_edit, raising=False)

    # Synthesize a dblclick event in the X-axis gutter
    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=(bbox.x0 + bbox.x1) / 2,
                   y=bbox.y0 - 30, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)

    assert called.get('ax') is ax
    assert ax.get_xlim() == (0, 10)


def test_timedomain_canvas_dblclick_inside_axes_opens_chart_options(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import TimeDomainCanvas

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)

    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    from mf4_analyzer.ui import _axis_interaction
    called = {}

    def fake_edit(parent_widget, ax_):
        called['ax'] = ax_
        ax_.set_title("edited")
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_chart_options_dialog',
                        fake_edit, raising=False)

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=(bbox.x0 + bbox.x1) / 2,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    e.inaxes = ax
    canvas.callbacks.process('button_press_event', e)

    assert called.get('ax') is ax
    assert ax.get_title() == "edited"


def test_timedomain_canvas_hover_axis_changes_cursor(qtbot, monkeypatch):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import TimeDomainCanvas

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)

    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('motion_notify_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=None)
    canvas.callbacks.process('motion_notify_event', e)

    assert canvas.cursor().shape() == Qt.PointingHandCursor
    assert canvas.toolTip() == "双击打开图表选项"


def test_plot_canvas_dblclick_uses_chart_options_helper(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import PlotCanvas
    canvas = PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    from mf4_analyzer.ui import _axis_interaction
    called = {}

    def fake_edit(parent, ax_):
        called['ax'] = ax_
        ax_.set_ylim(-1, 99)
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_chart_options_dialog',
                        fake_edit, raising=False)

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert called.get('ax') is ax
    assert ax.get_ylim() == (-1, 99)


def test_plot_canvas_hover_axis(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import PlotCanvas
    canvas = PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('motion_notify_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=None)
    canvas.callbacks.process('motion_notify_event', e)
    assert canvas.cursor().shape() == Qt.PointingHandCursor


def test_plot_canvas_hover_short_circuit_during_drag(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import PlotCanvas
    canvas = PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    canvas.draw()

    canvas._mouse_button_pressed = True
    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('motion_notify_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=None)
    canvas.callbacks.process('motion_notify_event', e)
    # Cursor should NOT be PointingHandCursor since drag is active
    assert canvas.cursor().shape() != Qt.PointingHandCursor


def test_spectrogram_canvas_dblclick_main_axis_opens_chart_options(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.draw()

    # SpectrogramCanvas creates 2 axes (spec + slice) via gridspec; both
    # should accept dblclick.
    from mf4_analyzer.ui import _axis_interaction
    hits = []

    def fake_edit(parent, ax_):
        hits.append(ax_)
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_chart_options_dialog',
                        fake_edit, raising=False)

    # Force the canvas to build its 2-axes layout (plot_result requires a
    # SpectrogramResult; we instead build the gridspec directly so the
    # test exercises only the dblclick wiring, not the rendering path).
    canvas._ax_spec = canvas.fig.add_subplot(2, 1, 1)
    canvas._ax_slice = canvas.fig.add_subplot(2, 1, 2)
    canvas.draw()

    main_ax = canvas._ax_spec
    bbox = main_ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert any(ax is main_ax for ax in hits)


def test_spectrogram_canvas_dblclick_slice_axis_opens_chart_options(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.draw()
    from mf4_analyzer.ui import _axis_interaction
    hits = []
    monkeypatch.setattr(_axis_interaction, 'edit_chart_options_dialog',
                        lambda p, ax: (hits.append(ax), True)[1],
                        raising=False)

    canvas._ax_spec = canvas.fig.add_subplot(2, 1, 1)
    canvas._ax_slice = canvas.fig.add_subplot(2, 1, 2)
    canvas.draw()

    slice_ax = canvas._ax_slice
    bbox = slice_ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert any(ax is slice_ax for ax in hits)


def test_spectrogram_canvas_dblclick_inside_slice_axis_opens_chart_options(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.draw()
    from mf4_analyzer.ui import _axis_interaction
    hits = []
    monkeypatch.setattr(_axis_interaction, 'edit_chart_options_dialog',
                        lambda p, ax: (hits.append(ax), True)[1],
                        raising=False)

    canvas._ax_spec = canvas.fig.add_subplot(2, 1, 1)
    canvas._ax_slice = canvas.fig.add_subplot(2, 1, 2)
    canvas.draw()

    slice_ax = canvas._ax_slice
    bbox = slice_ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=(bbox.x0 + bbox.x1) / 2,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    e.inaxes = slice_ax
    canvas.callbacks.process('button_press_event', e)
    assert any(ax is slice_ax for ax in hits)

    hits.clear()
    canvas.open_chart_options_dialog()
    assert hits == [slice_ax]

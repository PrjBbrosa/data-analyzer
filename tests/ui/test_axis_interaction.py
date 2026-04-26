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


def test_timedomain_canvas_dblclick_opens_axis_dialog(qtbot, monkeypatch):
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

    # Stub the dialog to auto-accept and return a fixed range
    from mf4_analyzer.ui import _axis_interaction
    called = {}

    def fake_edit(parent_widget, ax_, axis):
        called['axis'] = axis
        ax_.set_xlim(0, 10) if axis == 'x' else ax_.set_ylim(0, 10)
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog', fake_edit)

    # Synthesize a dblclick event in the X-axis gutter
    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=(bbox.x0 + bbox.x1) / 2,
                   y=bbox.y0 - 30, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)

    assert called.get('axis') == 'x'
    assert ax.get_xlim() == (0, 10)


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
    assert canvas.toolTip() == "双击编辑坐标轴"


def test_plot_canvas_dblclick_uses_axis_interaction_helper(qtbot, monkeypatch):
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

    def fake_edit(parent, ax_, axis):
        called['axis'] = axis
        ax_.set_ylim(-1, 99) if axis == 'y' else ax_.set_xlim(-1, 99)
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog', fake_edit)

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert called.get('axis') == 'y'


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


def test_spectrogram_canvas_dblclick_main_axis(qtbot, monkeypatch):
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
    def fake_edit(parent, ax_, axis):
        hits.append((ax_, axis))
        return True
    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog', fake_edit)

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
    assert any(ax is main_ax for ax, _ in hits)


def test_spectrogram_canvas_dblclick_slice_axis(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.draw()
    from mf4_analyzer.ui import _axis_interaction
    hits = []
    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog',
                        lambda p, ax, axis: (hits.append((ax, axis)), True)[1])

    canvas._ax_spec = canvas.fig.add_subplot(2, 1, 1)
    canvas._ax_slice = canvas.fig.add_subplot(2, 1, 2)
    canvas.draw()

    slice_ax = canvas._ax_slice
    bbox = slice_ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert any(ax is slice_ax for ax, _ in hits)

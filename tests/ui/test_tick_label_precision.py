"""Production tick placement stays nice while labels retain fractional steps."""
import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication
from mf4_analyzer.qt_plot_helpers import BorderAlignedAxisItem, GridLabelSlackAxisItem
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.analysis_axes import _apply_target_bottom_ticks


@pytest.mark.parametrize('axis_type,orientation', [
    (BorderAlignedAxisItem, 'bottom'), (GridLabelSlackAxisItem, 'left'),
])
def test_axis_formatter_preserves_fractional_steps(qapp, axis_type, orientation):
    axis = axis_type(orientation)
    try:
        assert axis.tickStrings([2.5, 5, 7.5], 1, 2.5) == ['2.5', '5', '7.5']
        axis.setLogMode(True)
        assert axis.tickStrings([0, 1, 2], 1, 1) == axis.logTickStrings([0, 1, 2], 1, 1)
    finally:
        axis.deleteLater()


def test_both_target_tick_paths_keep_positions(qapp):
    canvas = TimeDomainCanvasPG()
    try:
        canvas.resize(1200, 700)
        canvas.show()
        x = np.linspace(0, 25, 501)
        canvas.plot_channels([('probe', True, x, np.sin(x), '#1769e0', '', 'f')], mode='subplot')
        QCoreApplication.processEvents()
        axis = canvas.axes_list[0].x_axis_item()
        controller = canvas._tick_density_controller
        controller.density = (10, 6)
        time_ticks = controller._compute_target_x_ticks(axis, 0, 25, 1000)
        axis.resize(1000, axis.height())

        class ViewRange:
            def viewRange(self):
                return [[0, 25], [0, 1]]

        assert _apply_target_bottom_ticks(axis, ViewRange(), 10)
        for ticks in (time_ticks, axis._tickLevels[0]):
            assert [v for v, _ in ticks] == pytest.approx(np.arange(2.5, 25, 2.5))
            assert [float(s) for _, s in ticks] == pytest.approx([v for v, _ in ticks])
    finally:
        canvas.close()
        canvas.deleteLater()

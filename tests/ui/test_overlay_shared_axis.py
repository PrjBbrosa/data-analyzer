"""overlay 共轴：meta 透传回归 + 共享 ViewBox 归并。

Task 4 guard tests:
- primary rows with axis_group meta MUST NOT be misclassified as companions
- companion predicate keys on companion_of (not meta-presence)
- 8-tuple vis unpacking must not break subplot, single, or overlay modes
"""
import numpy as np
from PyQt5.QtCore import QCoreApplication


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


class TestAxisGroupMetaIsPrimary:
    def test_primary_with_axis_group_meta_not_swallowed_as_companion(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 7}),
            ("b", True, t, np.cos(t), "#0a0", "rpm", "f2"),  # 7-tuple, ungrouped
        ]
        canvas.plot_channels(rows, mode="overlay")
        # 两个 primary（gid=7 单成员仍是独立 slot），都建轴 → 2 根轴
        assert len(canvas.axes_list) == 2

    def test_companion_still_separated_when_axis_group_present(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#00f", "Nm", "f2", {"axis_group": 2}),
            ("a (LP)", True, t, np.sin(t) * 0.5, "#f00", "Nm", "f1",
             {"companion_of": "a", "dash": True}),
        ]
        canvas.plot_channels(rows, mode="overlay")
        # 2 个 primary（gid 1/2 各单成员）→ 2 轴；companion 不另起轴
        assert len(canvas.axes_list) == 2

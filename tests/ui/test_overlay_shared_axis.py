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


class TestOverlaySharedViewBox:
    def test_group_members_share_one_viewbox_and_axis(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t),     "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t),     "#0a0", "Nm",  "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(2 * t), "#00f", "rpm", "f2"),  # ungrouped
        ]
        canvas.plot_channels(rows, mode="overlay")
        # a,b 塌成一个 slot；c 自己一个 → 共 2 根轴
        assert len(canvas.axes_list) == 2
        # 第 0 个 slot（组 1）的 ViewBox 同时持有 a、b 两条曲线
        shared_vb = canvas.axes_list[0].view_box
        assert shared_vb is not None
        assert len(shared_vb.addedItems) == 2
        # c 自己的 ViewBox 只有一条
        solo_vb = canvas.axes_list[1].view_box
        assert len(solo_vb.addedItems) == 1

    def test_shared_axis_union_range_covers_both(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.full_like(t, 1.0),  "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.full_like(t, 50.0), "#0a0", "Nm", "f1", {"axis_group": 1}),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        lo, hi = canvas.axes_list[0].get_ylim()
        # 并集量程必须同时覆盖 1 与 50（独立轴时各自只覆盖自己）
        assert lo <= 1.0 + 1e-6 and hi >= 50.0 - 1e-6


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


class TestOverlayGroupInteraction:
    def test_repin_and_emphasis_run_without_error_on_grouped(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "Nm", "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(3 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        # 触发网格重钉/强调（既有 API），grouped handle 不应抛异常
        canvas._overlay_axes._apply_overlay_emphasis()
        canvas._overlay_axes._repin_overlay_channel_ticks()
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 2

    def test_mixed_unit_group_does_not_crash(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t),  "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t),  "#0a0", "rpm", "f1", {"axis_group": 1}),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 1

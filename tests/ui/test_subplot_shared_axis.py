"""分屏共轴：归槽 helper + 分屏行合并 + 边界。"""
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.axis_group_palette import axis_group_color


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _curve_count(vb):
    return sum(1 for it in vb.addedItems if isinstance(it, pg.PlotDataItem))


def _vis(name, color, unit, data_id, gid):
    t = np.linspace(0.0, 1.0, 50, dtype=np.float64)
    # vis 元组：(name, t, sig, color, unit, data_id, p_visible, axis_group)
    return (name, t, np.sin(t), color, unit, data_id, True, gid)


class TestGroupIntoSlots:
    def test_ungrouped_each_own_slot(self, qapp):
        canvas = _pg_canvas(qapp)
        vis = [_vis("a", "#f00", "Nm", "f1", None),
               _vis("b", "#0a0", "Nm", "f2", None)]
        slots = canvas._group_visible_into_slots(vis)
        assert [s["gid"] for s in slots] == [None, None]
        assert [len(s["members"]) for s in slots] == [1, 1]

    def test_same_gid_merges_preserving_first_order(self, qapp):
        canvas = _pg_canvas(qapp)
        vis = [_vis("a", "#f00", "Nm", "f1", 1),
               _vis("c", "#00f", "rpm", "f2", None),
               _vis("b", "#0a0", "Nm", "f1", 1)]
        slots = canvas._group_visible_into_slots(vis)
        # a 与 b 同组 1 → 合到第 0 槽；c 未分组 → 第 1 槽
        assert [s["gid"] for s in slots] == [1, None]
        assert [m[0] for m in slots[0]["members"]] == ["a", "b"]
        assert [m[0] for m in slots[1]["members"]] == ["c"]


def _row(name, color, unit, data_id, gid=None):
    t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
    meta = {"axis_group": gid} if gid is not None else None
    base = (name, True, t, np.sin(t) if name != "b" else np.cos(t),
            color, unit, data_id)
    return base + (meta,) if meta is not None else base


class TestSubplotGroupMerge:
    def test_row_count_equals_slot_count(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1", gid=1),
            _row("b", "#0a0", "Nm", "f1", gid=1),
            _row("c", "#00f", "rpm", "f2"),  # ungrouped
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # a,b 合一行；c 一行 → 2 行
        assert len(canvas.axes_list) == 2

    def test_group_row_holds_all_member_curves(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1", gid=1),
            _row("b", "#0a0", "Nm", "f1", gid=1),
            _row("c", "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        assert _curve_count(canvas.axes_list[0].view_box) == 2  # a+b 同行
        assert _curve_count(canvas.axes_list[1].view_box) == 1  # c 单行

    def test_group_row_union_range_covers_all_members(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.full_like(t, 1.0),  "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.full_like(t, 50.0), "#0a0", "Nm", "f1", {"axis_group": 1}),
            ("c", True, t, np.full_like(t, 5.0),  "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        lo, hi = canvas.axes_list[0].get_ylim()
        assert lo <= 1.0 + 1e-6 and hi >= 50.0 - 1e-6

    def test_group_row_label_uses_group_color(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1", gid=1),
            _row("b", "#0a0", "Nm", "f1", gid=1),
            _row("c", "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        # 分屏标签每槽一条 → 2 条
        assert len(canvas._subplot_label_specs) == 2
        grp_color = canvas._subplot_label_specs[0][2]
        assert grp_color == axis_group_color(1)

    def test_ungrouped_subplot_unchanged(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1"),
            _row("b", "#0a0", "Nm", "f2"),
            _row("c", "#00f", "rpm", "f3"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 3
        assert all(_curve_count(h.view_box) == 1 for h in canvas.axes_list)

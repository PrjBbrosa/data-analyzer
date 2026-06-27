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

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


class TestSubplotGroupEdges:
    def test_group_with_one_visible_member_degrades_to_single_curve(self, qapp):
        # 组 1 两成员，但 b 未勾选(visible=False) → 该组只剩 1 可见 → 单曲线行
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True,  t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", False, t, np.cos(t), "#0a0", "Nm", "f1", {"axis_group": 1}),
            ("c", True,  t, np.sin(2 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # b 不可见且无 companion → 不入 vis；组 1 只剩 a → 退化单曲线
        assert len(canvas.axes_list) == 2
        assert _curve_count(canvas.axes_list[0].view_box) == 1

    def test_mixed_unit_group_does_not_crash(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "rpm", "f1", {"axis_group": 1}),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        canvas._recheck_subplot_label_placement()
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 1  # 两成员同组 → 1 行

    def test_subplot_and_overlay_group_into_same_slots(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "Nm",  "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(3 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        n_sub = len(canvas.axes_list)
        canvas.plot_channels(rows, mode="overlay")
        n_ovl = len(canvas.axes_list)
        assert n_sub == n_ovl == 2  # 两模式共用归槽 → 槽数一致

    def test_bottom_axis_on_last_slot(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "Nm",  "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(3 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # 最后一槽(c 行)底轴显示时间刻度值;非末槽隐藏刻度值。
        # 既有契约: _configure_subplot_bottom_axis 用 setStyle(showValues=...)
        # 切刻度值,AxisItem 本体常驻可见,故断言对齐到 style['showValues']。
        last_ax = canvas.axes_list[-1]._ax("bottom")
        first_ax = canvas.axes_list[0]._ax("bottom")
        assert last_ax is not None and last_ax.style["showValues"] is True
        assert first_ax is not None and first_ax.style["showValues"] is False

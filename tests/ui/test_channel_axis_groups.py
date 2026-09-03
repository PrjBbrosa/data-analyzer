"""共轴组数据模型 + 组色板测试。"""
from types import SimpleNamespace

import pytest

from mf4_analyzer.ui.view_bridge import capture_axis_opts
from mf4_analyzer.ui.view_state import ViewState
from mf4_analyzer.ui.axis_group_palette import axis_group_color
from mf4_analyzer.ui.widgets import MultiFileChannelWidget


class _AxisCaptureTop:
    """Minimal Inspector surface consumed by ``capture_axis_opts``."""

    def range_values(self):
        return (0.0, 0.0)

    def range_enabled(self):
        return False

    def tick_density(self):
        return (10, 6)

    def xaxis_label(self):
        return ""


class TestAxisGroupPalette:
    def test_distinct_colors_for_first_groups(self):
        cols = [axis_group_color(g) for g in (1, 2, 3)]
        assert len(set(cols)) == 3

    def test_cycles_and_is_hex(self):
        assert axis_group_color(1) == axis_group_color(1 + 6)  # 6-color cycle
        assert axis_group_color(1).startswith("#")

    def test_nonpositive_falls_back_to_first(self):
        assert axis_group_color(0) == axis_group_color(1)


class TestAxisGroupModel:
    def test_merge_assigns_one_group(self, qapp):
        w = MultiFileChannelWidget()
        gid = w.merge_axis_group([("f1", "a"), ("f1", "b")])
        assert gid == 1
        assert w.axis_group_for("f1", "a") == 1
        assert w.axis_group_for("f1", "b") == 1

    def test_merge_below_two_is_noop(self, qapp):
        w = MultiFileChannelWidget()
        assert w.merge_axis_group([("f1", "a")]) is None
        assert w.axis_group_for("f1", "a") is None

    def test_second_merge_makes_new_group_id(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        gid2 = w.merge_axis_group([("f1", "c"), ("f1", "d")])
        assert gid2 == 2

    def test_merge_folds_into_min_existing_group(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])   # group 1
        w.merge_axis_group([("f1", "c"), ("f1", "d")])   # group 2
        # selecting members of group 1 and group 2 → fold all into 1
        w.merge_axis_group([("f1", "b"), ("f1", "c")])
        for ch in ("a", "b", "c", "d"):
            assert w.axis_group_for("f1", ch) == 1

    def test_split_removes_and_dissolves_singleton(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        w.split_axis_group([("f1", "a")])
        # b left alone → group of one → auto-dissolved
        assert w.axis_group_for("f1", "a") is None
        assert w.axis_group_for("f1", "b") is None

    def test_split_allows_next_merge_to_reuse_first_group_id(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        w.split_axis_group([("f1", "a"), ("f1", "b")])

        gid = w.merge_axis_group([("f1", "c"), ("f1", "d")])

        assert gid == 1
        assert w.axis_group_for("f1", "c") == 1
        assert w.axis_group_for("f1", "d") == 1

    def test_prune_renumbers_remaining_groups_contiguously(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        w.merge_axis_group([("f1", "c"), ("f1", "d")])

        w.split_axis_group([("f1", "a"), ("f1", "b")])

        assert w.axis_group_for("f1", "c") == 1
        assert w.axis_group_for("f1", "d") == 1

    def test_merge_emits_signal(self, qapp):
        w = MultiFileChannelWidget()
        seen = []
        w.axis_groups_changed.connect(lambda: seen.append(1))
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        assert seen == [1]

    def test_effective_groups_drops_unchecked_and_singletons(self):
        groups = {("f1", "a"): 1, ("f1", "b"): 1, ("f1", "c"): 2, ("f1", "d"): 2}
        checked = {("f1", "a"), ("f1", "b"), ("f1", "c")}  # d unchecked
        eff = MultiFileChannelWidget._effective_groups(groups, checked)
        assert eff == {("f1", "a"): 1, ("f1", "b"): 1}  # group2 lost a member → singleton dropped

    def test_menu_plan(self, qapp):
        w = MultiFileChannelWidget()
        assert w._axis_group_menu_plan([("f1", "a")]) == (False, False)
        assert w._axis_group_menu_plan([("f1", "a"), ("f1", "b")]) == (True, False)
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        assert w._axis_group_menu_plan([("f1", "a"), ("f1", "b")]) == (True, True)

    def test_restored_group_uses_normal_badge_and_split_action(self, qapp):
        w = MultiFileChannelWidget()
        seen = []
        w.axis_groups_changed.connect(lambda: seen.append(1))
        w.set_restored_axis_group_projection({
            '["f1","a"]': "window-0-axis-2",
        })

        assert seen == []
        assert w.axis_group_for("f1", "a") == "window-0-axis-2"
        assert w._axis_group_menu_plan([("f1", "a")]) == (False, True)

        w.split_axis_group([("f1", "a")])

        assert seen == [1]
        assert w.axis_group_for("f1", "a") is None
        assert w.restored_axis_group_projection() == {}

    def test_merged_imported_axis_group_is_captured_into_view_state(self, qapp):
        w = MultiFileChannelWidget()
        w.set_restored_axis_group_projection({
            '["f1","imported"]': "wwt-axis-3",
        })

        w.merge_axis_group([("f1", "imported"), ("f1", "ordinary")])
        state = ViewState(
            name="WWT",
            tab_color="#2d7ff9",
            axis_opts=capture_axis_opts(SimpleNamespace(
                inspector=SimpleNamespace(top=_AxisCaptureTop()),
                channel_list=w,
            )),
        )

        assert state.axis_opts["channel_axis_groups"] == {
            '["f1","imported"]': "wwt-axis-3",
            '["f1","ordinary"]': "wwt-axis-3",
        }
        assert w._axis_groups == {}

    def test_collect_selected_channel_keys_then_merge(self, qapp):
        # 直接驱动数据模型，模拟 _on_context_menu 收集到的 sel_keys → 合并
        w = MultiFileChannelWidget()
        sel_keys = [("f1", "a"), ("f1", "b"), ("f1", "c")]
        can_merge, can_split = w._axis_group_menu_plan(sel_keys)
        assert (can_merge, can_split) == (True, False)
        w.merge_axis_group(sel_keys)
        assert {w.axis_group_for("f1", c) for c in ("a", "b", "c")} == {1}
        # 再对其中一个拆分
        can_merge, can_split = w._axis_group_menu_plan([("f1", "a")])
        assert can_split is True
        w.split_axis_group([("f1", "a")])
        assert w.axis_group_for("f1", "a") is None


class TestChannelTreeIndent:
    def test_indentation_is_narrowed(self, qapp):
        w = MultiFileChannelWidget()
        assert w.tree.indentation() == 16

    def test_owner_back_reference_set(self, qapp):
        w = MultiFileChannelWidget()
        assert w.tree._owner is w

    def test_drawbranches_smoke_renders_to_pixmap(self, qapp):
        # 兜底冒烟：分组状态下 grab() 不抛异常（真实观感在 Task 6 真机验）
        from PyQt5.QtCore import QCoreApplication
        w = MultiFileChannelWidget()
        w.resize(260, 300)
        w.show()
        QCoreApplication.processEvents()
        w._axis_groups[("f1", "a")] = 1  # 直接置状态绕过 add_file
        w.tree.viewport().update()
        QCoreApplication.processEvents()
        pm = w.grab()
        assert not pm.isNull()

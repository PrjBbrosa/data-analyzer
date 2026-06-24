"""共轴组数据模型 + 组色板测试。"""
import pytest

from mf4_analyzer.ui.axis_group_palette import axis_group_color
from mf4_analyzer.ui.widgets import MultiFileChannelWidget


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

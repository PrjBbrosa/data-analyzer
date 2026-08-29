import pytest
from PyQt5.QtCore import QObject

from mf4_analyzer.ui.view_state import (
    MAX_VIEWS,
    TIME_DOMAIN_MAX_VIEWS,
    ViewManager,
    default_view_tab_color,
)

# The six colors shipped before the palette grew to 12. Archived projects store
# these in ViewState.tab_color, so View 1-6 must keep resolving to them.
_LEGACY_PALETTE = ["#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad"]


def make():
    return ViewManager()


def test_starts_with_one_view():
    m = make()

    assert len(m.views) == 1
    assert m.active == 0
    assert m.split_with is None


def test_new_view_respects_cap(qtbot):
    m = make()
    for expected_idx in range(1, MAX_VIEWS):
        with qtbot.waitSignals(
            [m.views_changed, m.active_changed],
            timeout=100,
            check_params_cbs=[None, lambda idx, expected=expected_idx: idx == expected],
        ):
            assert m.new_view() == expected_idx
        assert m.active == expected_idx

    assert len(m.views) == MAX_VIEWS
    active_events = []
    m.active_changed.connect(active_events.append)
    assert m.new_view() == -1
    assert len(m.views) == MAX_VIEWS
    assert active_events == []


def test_new_view_can_append_before_activation(qtbot):
    manager = make()
    active_events = []
    manager.active_changed.connect(active_events.append)

    with qtbot.waitSignal(manager.views_changed, timeout=100):
        assert manager.new_view(activate=False) == 1

    assert len(manager.views) == 2
    assert manager.active == 0
    assert active_events == []

    with qtbot.waitSignal(manager.active_changed, timeout=100):
        manager.set_active(1)
    assert manager.active == 1


def test_delete_cannot_empty(qtbot):
    m = make()
    m.new_view()

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.delete_view(0)

    assert len(m.views) == 1
    m.delete_view(0)
    assert len(m.views) == 1


def test_duplicate_inserts_after_with_suffix(qtbot):
    m = make()
    m.views[0].name = "A"
    original_view_id = m.views[0].view_id

    with qtbot.waitSignals(
        [m.views_changed, m.active_changed],
        timeout=100,
        check_params_cbs=[None, lambda idx: idx == 1],
    ):
        idx = m.duplicate(0)

    assert idx == 1
    assert m.views[1].name == "A 副本"
    assert m.views[1].view_id != original_view_id
    assert m.active == 1


def test_duplicate_before_active_reindexes_old_active_and_emits(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.views[0].name, m.views[1].name, m.views[2].name = "A", "B", "C"
    m.set_active(2)

    with qtbot.waitSignals(
        [m.views_changed, m.active_changed],
        timeout=100,
        check_params_cbs=[None, lambda idx: idx == 1],
    ):
        idx = m.duplicate(0)

    assert idx == 1
    assert [v.name for v in m.views] == ["A", "A 副本", "B", "C"]
    assert m.active == 1


def test_rename_blank_falls_back(qtbot):
    m = make()

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.rename(0, "   ")

    assert m.views[0].name == "未命名"


def test_set_color_updates_tab_color_and_emits(qtbot):
    m = make()

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.set_color(0, "#e8590c")

    assert m.views[0].tab_color == "#e8590c"


def test_reorder_moves_item_and_preserves_active_view(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.views[0].name, m.views[1].name, m.views[2].name = "A", "B", "C"
    ids_by_name = {view.name: view.view_id for view in m.views}
    m.set_active(1)

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.reorder(0, 2)

    assert [v.name for v in m.views] == ["B", "C", "A"]
    assert {view.name: view.view_id for view in m.views} == ids_by_name
    assert m.active == 0


def test_set_split_is_directional_host_only(qtbot):
    m = make()
    m.new_view()
    m.set_active(0)

    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.set_split(1)

    assert blocker.args == [1]
    assert m.partner_for(0) == 1
    assert m.partner_for(1) is None
    assert m.split_with == 1

    split_events = []
    m.split_changed.connect(split_events.append)
    with qtbot.waitSignal(m.active_changed, timeout=100) as blocker:
        m.set_active(1)

    assert blocker.args == [1]
    assert m.split_with is None
    with qtbot.waitSignal(m.active_changed, timeout=100):
        m.set_active(0)
    assert m.split_with == 1
    # set_active must move active WITHOUT re-emitting split_changed; otherwise
    # switching views double-fires _on_view_split + _apply_active_view.
    assert split_events == []
    assert m.partner_for(0) == 1
    assert m.partner_for(1) is None


def test_set_active_to_unpaired_view_hides_split_without_deleting_pair(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.set_active(0)
    m.set_split(1)

    with qtbot.waitSignal(m.active_changed, timeout=100):
        m.set_active(2)

    assert m.split_with is None
    assert m.partner_for(0) == 1
    assert m.partner_for(1) is None

    with qtbot.waitSignal(m.active_changed, timeout=100):
        m.set_active(0)

    assert m.split_with == 1
    assert m.partner_for(0) == 1
    assert m.partner_for(1) is None


def test_clear_split_for_host_removes_pair(qtbot):
    m = make()
    m.new_view()
    m.set_active(0)
    m.set_split(1)

    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.clear_split_for(1)

    assert blocker.args == [None]
    assert m.partner_for(0) is None
    assert m.partner_for(1) is None
    assert m.split_with is None


def test_clear_split_for_source_also_unmerges_host(qtbot):
    m = make()
    m.new_view()
    m.set_active(0)
    m.set_split(1)

    m.clear_split_for(1)

    assert m.partner_for(0) is None
    assert m.partner_for(1) is None
    assert m.split_with is None


def test_set_active_current_view_is_noop():
    m = make()
    m.new_view()
    m.set_active(0)
    m.set_split(1)
    active_events = []
    split_events = []
    m.active_changed.connect(active_events.append)
    m.split_changed.connect(split_events.append)

    m.set_active(0)

    assert m.active == 0
    assert m.split_with == 1
    assert active_events == []
    assert split_events == []


def test_reorder_keeps_pair_with_view_objects(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.views[0].name = "A"
    m.views[1].name = "B"
    m.views[2].name = "C"
    m.set_active(0)
    m.set_split(1)

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.reorder(0, 2)

    names = [v.name for v in m.views]
    a_idx = names.index("A")
    b_idx = names.index("B")
    assert m.partner_for(a_idx) == b_idx
    assert m.partner_for(b_idx) is None


def test_delete_clears_pair_for_deleted_view_and_remaps_others(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.set_active(0)
    m.set_split(2)

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.delete_view(1)

    assert len(m.views) == 2
    assert m.partner_for(0) == 1
    assert m.partner_for(1) is None

    with qtbot.waitSignals([m.views_changed, m.split_changed], timeout=100):
        m.delete_view(1)

    assert m.partner_for(0) is None
    assert m.split_with is None


def test_delete_unrelated_view_preserves_pair_without_split_signal(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.set_active(0)
    m.set_split(1)
    split_events = []
    m.split_changed.connect(split_events.append)

    with qtbot.waitSignal(m.views_changed, timeout=100):
        m.delete_view(2)

    assert m.partner_for(0) == 1
    assert m.partner_for(1) is None
    assert m.split_with == 1
    assert split_events == []


def test_duplicate_remaps_unrelated_pair_after_insert(qtbot):
    m = make()
    m.new_view()
    m.new_view()
    m.set_active(0)
    m.set_split(2)

    with qtbot.waitSignals(
        [m.views_changed, m.active_changed],
        timeout=100,
        check_params_cbs=[None, lambda idx: idx == 1],
    ):
        m.duplicate(0)

    assert len(m.views) == 4
    assert m.partner_for(0) == 3
    assert m.partner_for(3) is None
    assert m.partner_for(1) is None


def test_set_split_rejects_self():
    m = make()
    m.new_view()
    m.set_active(0)

    m.set_split(0)

    assert m.split_with is None


def test_set_split_none_when_already_none_is_noop():
    m = make()
    split_events = []
    m.split_changed.connect(split_events.append)

    m.set_split(None)

    assert m.split_with is None
    assert split_events == []


def test_set_split_accepts_other_view_and_none(qtbot):
    m = make()
    m.new_view()
    m.set_active(0)

    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.set_split(1)

    assert blocker.args == [1]
    assert m.split_with == 1

    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.set_split(None)

    assert blocker.args == [None]
    assert m.split_with is None


def test_set_split_same_other_view_is_noop(qtbot):
    m = make()
    m.new_view()
    m.set_active(0)

    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.set_split(1)

    assert blocker.args == [1]
    split_events = []
    m.split_changed.connect(split_events.append)

    m.set_split(1)

    assert m.split_with == 1
    assert split_events == []


def test_get_returns_view_state():
    m = make()

    assert m.get(0) is m.views[0]


def test_get_rejects_negative_and_out_of_range_indexes():
    m = make()

    with pytest.raises(IndexError) as negative:
        m.get(-1)
    assert negative.value.args == (-1,)

    with pytest.raises(IndexError) as out_of_range:
        m.get(1)
    assert out_of_range.value.args == (1,)


# --- per-instance View cap -------------------------------------------------
# The cap is per manager: time-domain uses TIME_DOMAIN_MAX_VIEWS; FFT /
# fft_time / order / frf keep the MAX_VIEWS default.


def test_new_view_honors_raised_instance_cap():
    m = ViewManager(max_views=12)

    for expected_idx in range(1, 12):
        assert m.new_view() == expected_idx

    assert len(m.views) == 12
    assert m.new_view() == -1
    assert len(m.views) == 12


def test_new_view_honors_lowered_instance_cap_over_module_constant():
    m = ViewManager(max_views=2)

    assert m.new_view() == 1
    assert m.new_view() == -1
    assert len(m.views) == 2


def test_default_manager_keeps_module_constant_cap():
    m = ViewManager()

    while m.new_view() != -1:
        pass

    assert len(m.views) == MAX_VIEWS


def test_duplicate_honors_instance_cap():
    m = ViewManager(max_views=2)

    assert m.duplicate(0) == 1
    assert m.duplicate(0) == -1
    assert len(m.views) == 2


def test_max_views_does_not_displace_the_positional_parent_argument():
    parent = QObject()

    m = ViewManager(parent, max_views=12)

    assert m.parent() is parent
    assert m.max_views == 12


# --- tab-color palette -----------------------------------------------------


def test_first_six_views_keep_the_legacy_palette_colors():
    m = ViewManager(max_views=12)
    for _ in range(5):
        m.new_view()

    assert [v.tab_color for v in m.views] == _LEGACY_PALETTE


def test_twelve_views_get_pairwise_distinct_tab_colors():
    m = ViewManager(max_views=12)
    for _ in range(11):
        m.new_view()

    colors = [v.tab_color for v in m.views]
    assert len(colors) == 12
    assert len(set(colors)) == 12


def test_time_domain_cap_allows_twenty_four_views_and_rejects_the_twenty_fifth():
    m = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)

    for expected_idx in range(1, TIME_DOMAIN_MAX_VIEWS):
        assert m.new_view() == expected_idx

    assert len(m.views) == TIME_DOMAIN_MAX_VIEWS
    assert TIME_DOMAIN_MAX_VIEWS == 24
    assert m.new_view() == -1
    assert len(m.views) == TIME_DOMAIN_MAX_VIEWS


def test_time_domain_palette_cycles_twelve_colors_and_keeps_legacy_first_six():
    m = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    while m.new_view() != -1:
        pass

    colors = [view.tab_color for view in m.views]
    assert colors[:6] == _LEGACY_PALETTE
    assert colors[:12] == colors[12:24]
    assert len(set(colors[:12])) == 12
    for idx, view in enumerate(m.views):
        expected = default_view_tab_color(idx)
        assert view.tab_color == expected
        assert m._make(idx).tab_color == expected

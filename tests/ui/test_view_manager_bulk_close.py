from mf4_analyzer.ui.view_state import TIME_DOMAIN_MAX_VIEWS, ViewManager


def _fill(manager, count):
    while len(manager.views) < count:
        manager.new_view()
    return manager


def test_retain_only_view_preserves_exact_object_and_stable_id():
    manager = ViewManager()
    _fill(manager, 4)
    manager.views[2].name = "Keep me"
    manager.views[2].checked = [("fid", "torque")]
    keep = manager.views[2]
    keep_id = keep.view_id
    manager.set_active(2)

    removed = manager.retain_only_view(keep_id)

    assert len(manager.views) == 1
    assert manager.views[0] is keep
    assert manager.views[0].view_id == keep_id
    assert manager.views[0].name == "Keep me"
    assert manager.views[0].checked == [("fid", "torque")]
    assert manager.active == 0
    assert keep_id not in removed
    assert len(removed) == 3


def test_retain_only_view_normalizes_split_pairs_and_emits_once(qtbot):
    manager = ViewManager()
    _fill(manager, 4)
    manager.set_active(0)
    manager.set_split(1)
    keep_id = manager.views[0].view_id
    views_events, split_events, active_events = [], [], []
    manager.views_changed.connect(lambda: views_events.append(1))
    manager.split_changed.connect(split_events.append)
    manager.active_changed.connect(active_events.append)

    manager.retain_only_view(keep_id)

    assert views_events == [1]
    assert manager.split_with is None
    assert manager.partner_for(0) is None
    assert len(manager.views) == 1


def test_retain_only_stale_id_is_a_zero_mutation_noop():
    manager = ViewManager()
    _fill(manager, 3)
    ids = [view.view_id for view in manager.views]
    names = [view.name for view in manager.views]
    manager.set_active(1)

    assert manager.retain_only_view("missing-id") == ()
    assert [view.view_id for view in manager.views] == ids
    assert [view.name for view in manager.views] == names
    assert manager.active == 1


def test_reset_to_single_default_returns_removed_ids_and_emits_once(qtbot):
    manager = ViewManager()
    _fill(manager, 5)
    manager.views[0].checked = [("f0", "sig")]
    manager.set_split(1)
    old_ids = [view.view_id for view in manager.views]
    views_events = []
    manager.views_changed.connect(lambda: views_events.append(1))

    removed = manager.reset_to_single_default()

    assert views_events == [1]
    assert set(removed) == set(old_ids)
    assert len(manager.views) == 1
    assert manager.views[0].view_id not in old_ids
    assert manager.views[0].name == "View 1"
    assert manager.views[0].checked == []
    assert manager.split_with is None


def test_bulk_close_never_exposes_zero_views_to_observers():
    manager = ViewManager()
    _fill(manager, 3)
    seen_counts = []

    def _note():
        seen_counts.append(len(manager.views))

    manager.views_changed.connect(_note)
    manager.active_changed.connect(lambda _idx: _note())
    manager.retain_only_view(manager.views[1].view_id)
    assert seen_counts
    assert all(count >= 1 for count in seen_counts)

    seen_counts.clear()
    manager.new_view()
    manager.reset_to_single_default()
    assert seen_counts
    assert all(count >= 1 for count in seen_counts)


def test_duplicate_display_names_do_not_affect_bulk_identity():
    manager = ViewManager()
    _fill(manager, 3)
    manager.views[0].name = "Same"
    manager.views[1].name = "Same"
    manager.views[2].name = "Same"
    keep = manager.views[1]
    manager.retain_only_view(keep.view_id)
    assert manager.views[0] is keep
    assert len(manager.views) == 1


def test_retain_only_handles_time_domain_cap():
    manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    _fill(manager, TIME_DOMAIN_MAX_VIEWS)
    keep = manager.views[17]
    removed = manager.retain_only_view(keep.view_id)
    assert len(removed) == TIME_DOMAIN_MAX_VIEWS - 1
    assert manager.views[0] is keep

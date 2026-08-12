"""Product residency guards for analysis View cache pinning (spec §7).

These are mechanical watchdogs for
``docs/analyzer/specs/2026-08-11-analysis-cache-view-pinning-spec.md``:
red means fix the code, not relax the assertions.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from mf4_analyzer.ui.main_window import MainWindow


def _fake_heatmap(tag):
    return SimpleNamespace(tag=tag, amplitude=None)


@pytest.fixture
def win(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_store_helper_pins_immediately_and_dedupes(win):
    key = win.analysis_caches["fft_time"].make_key(
        "f1", "ch", {"nfft": 256, "time_range": None}
    )
    win._store_analysis_result("fft_time", "vid-a", 0, key, _fake_heatmap("a"))
    assert key in win._pinned_keys_for_section("fft_time")
    win._store_analysis_result("fft_time", "vid-a", 0, key, _fake_heatmap("a2"))
    assert win._analysis_pins[("fft_time", "vid-a", 0)] == {key}


def test_store_helper_caches_but_does_not_pin_when_view_id_is_none(win, caplog):
    """A dispatch path that forgot to carry a real view_id must not wedge a
    permanent ('fft_time', 'None', 0) pin slot -- render-time replace only
    ever touches real view_id slots, so such a slot can never be reclaimed
    (spec §4.1 footnote)."""
    section = "fft_time"
    cache = win.analysis_caches[section]
    key = cache.make_key("f1", "ch", {"nfft": 256, "time_range": None})
    with caplog.at_level(
        logging.WARNING, logger="mf4_analyzer.ui.main_window._analysis_mixin"
    ):
        win._store_analysis_result(section, None, 0, key, _fake_heatmap("orphan"))
    assert key in cache._store
    assert (section, "None", 0) not in win._analysis_pins
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_render_replace_self_cleans_stale_param_pins(win, monkeypatch):
    section = "fft_time"
    mgr = win.analysis_managers[section]
    state = mgr.get(0)
    state.panes[0].sources = [("f1", "sig")]
    cache = win.analysis_caches[section]
    old_key = cache.make_key("f1", "sig", {"nfft": 128, "time_range": None})
    new_key = cache.make_key("f1", "sig", {"nfft": 512, "time_range": None})
    win._store_analysis_result(section, state.view_id, 0, old_key, _fake_heatmap("old"))
    win._store_analysis_result(section, state.view_id, 0, new_key, _fake_heatmap("new"))
    assert {old_key, new_key} <= set(cache._store)
    assert win._analysis_pins[(section, state.view_id, 0)] == {old_key, new_key}

    monkeypatch.setattr(
        win,
        "_analysis_cache_key",
        lambda *args, **kwargs: new_key,
    )
    monkeypatch.setattr(win, "_render_cached_heatmap", lambda *a, **k: None)
    monkeypatch.setattr(win, "_show_analysis_empty_hint", lambda *a, **k: None)
    monkeypatch.setattr(win, "_clear_analysis_canvas", lambda *a, **k: None)

    win._render_analysis_view_from_cache(section, state)
    assert win._analysis_pins[(section, state.view_id, 0)] == {new_key}

    # Old key is unpinned: a capacity storm can evict it.
    for i in range(cache._capacity + 2):
        storm = cache.make_key("storm", str(i), {"nfft": i})
        cache.put(storm, _fake_heatmap(f"s{i}"))
    assert old_key not in cache._store
    assert new_key in cache._store


def test_heatmap_tour_twelve_views_never_misses(win, monkeypatch):
    section = "fft_time"
    mgr = win.analysis_managers[section]
    while len(mgr.views) < 12:
        assert mgr.new_view() >= 0
    cache = win.analysis_caches[section]
    keys = []
    for idx, state in enumerate(mgr.views):
        state.panes[0].sources = [("f1", f"ch{idx}")]
        key = cache.make_key("f1", f"ch{idx}", {"nfft": 256, "time_range": None})
        keys.append(key)
        win._store_analysis_result(
            section, state.view_id, 0, key, _fake_heatmap(idx)
        )
        win._replace_analysis_pane_pins(section, state.view_id, 0, (key,))

    empty_hints = []
    monkeypatch.setattr(
        win, "_show_analysis_empty_hint", lambda *_a, **_k: empty_hints.append(1)
    )
    monkeypatch.setattr(win, "_render_cached_heatmap", lambda *a, **k: None)
    monkeypatch.setattr(win, "_clear_analysis_canvas", lambda *a, **k: None)
    monkeypatch.setattr(
        win,
        "_analysis_cache_key",
        lambda section, fid, ch, rpm_source=None, pane_idx=None: cache.make_key(
            fid, ch, {"nfft": 256, "time_range": None}
        ),
    )

    order = list(range(12)) + list(range(11, -1, -1))
    for idx in order:
        win._render_analysis_view_from_cache(section, mgr.get(idx))
    assert empty_hints == []
    assert all(k in cache._store for k in keys)


def test_dual_pane_twenty_four_bindings_never_miss(win, monkeypatch):
    from mf4_analyzer.ui.analysis_view_state import PaneState

    section = "order"
    mgr = win.analysis_managers[section]
    while len(mgr.views) < 12:
        assert mgr.new_view() >= 0
    page = win._analysis_page(section)
    cache = win.analysis_caches[section]
    keys = []
    for v_idx, state in enumerate(mgr.views):
        while len(state.panes) < 2:
            state.panes.append(PaneState())
        for pane_idx in (0, 1):
            ch = f"ch{v_idx}-{pane_idx}"
            state.panes[pane_idx].sources = [("f1", ch)]
            key = cache.make_key(
                "f1", ch, {"nfft": 256, "rpm": None, "time_range": None}
            )
            keys.append(key)
            win._store_analysis_result(
                section, state.view_id, pane_idx, key, _fake_heatmap(ch)
            )
            win._replace_analysis_pane_pins(
                section, state.view_id, pane_idx, (key,)
            )

    monkeypatch.setattr(page, "pane_count", lambda: 2)
    monkeypatch.setattr(page, "pane_canvas", lambda _i: SimpleNamespace())
    empty_hints = []
    monkeypatch.setattr(
        win, "_show_analysis_empty_hint", lambda *_a, **_k: empty_hints.append(1)
    )
    monkeypatch.setattr(win, "_render_cached_heatmap", lambda *a, **k: None)
    monkeypatch.setattr(win, "_clear_analysis_canvas", lambda *a, **k: None)

    def _key(section, fid, ch, rpm_source=None, pane_idx=None):
        return cache.make_key(
            fid, ch, {"nfft": 256, "rpm": None, "time_range": None}
        )

    monkeypatch.setattr(win, "_analysis_cache_key", _key)

    assert len(keys) == 24
    assert cache._capacity == 12
    for state in mgr.views:
        win._render_analysis_view_from_cache(section, state)
    assert empty_hints == []
    assert all(k in cache._store for k in keys)


def test_param_storm_on_one_view_does_not_evict_others(win):
    section = "fft_time"
    mgr = win.analysis_managers[section]
    while len(mgr.views) < 12:
        assert mgr.new_view() >= 0
    cache = win.analysis_caches[section]
    bound = []
    for idx, state in enumerate(mgr.views):
        key = cache.make_key("f1", f"ch{idx}", {"nfft": 256, "time_range": None})
        bound.append(key)
        win._store_analysis_result(
            section, state.view_id, 0, key, _fake_heatmap(idx)
        )
        win._replace_analysis_pane_pins(section, state.view_id, 0, (key,))

    active = mgr.get(0)
    for i in range(20):
        key = cache.make_key(
            "f1", "ch0", {"nfft": 256 + i, "time_range": None}
        )
        win._store_analysis_result(
            section, active.view_id, 0, key, _fake_heatmap(f"storm-{i}")
        )

    for key in bound[1:]:
        assert key in cache._store


def test_delete_view_unpins_so_results_become_evictable(win, monkeypatch):
    section = "fft_time"
    mgr = win.analysis_managers[section]
    mgr.new_view()
    victim = mgr.get(1)
    keep = mgr.get(0)
    cache = win.analysis_caches[section]
    v_key = cache.make_key("f1", "victim", {"nfft": 1, "time_range": None})
    k_key = cache.make_key("f1", "keep", {"nfft": 1, "time_range": None})
    win._store_analysis_result(section, victim.view_id, 0, v_key, _fake_heatmap("v"))
    win._store_analysis_result(section, keep.view_id, 0, k_key, _fake_heatmap("k"))
    win._replace_analysis_pane_pins(section, victim.view_id, 0, (v_key,))
    win._replace_analysis_pane_pins(section, keep.view_id, 0, (k_key,))

    # Avoid switch-render rebinding pins to inspector-derived keys.
    monkeypatch.setattr(win, "_capture_active_analysis_view", lambda *_a, **_k: None)
    monkeypatch.setattr(win, "_render_analysis_view_from_cache", lambda *_a, **_k: None)
    win._on_analysis_delete(section, 1)
    assert (section, victim.view_id, 0) not in win._analysis_pins
    assert v_key in cache._store  # not eagerly cleared
    for i in range(cache._capacity + 2):
        cache.put(
            cache.make_key("storm", str(i), {"nfft": i}),
            _fake_heatmap(i),
        )
    assert v_key not in cache._store
    assert k_key in cache._store


def test_duplicate_view_shares_pin_until_one_is_deleted(win):
    section = "fft_time"
    mgr = win.analysis_managers[section]
    original = mgr.get(0)
    cache = win.analysis_caches[section]
    key = cache.make_key("f1", "sig", {"nfft": 256, "time_range": None})
    win._store_analysis_result(
        section, original.view_id, 0, key, _fake_heatmap("shared")
    )
    win._replace_analysis_pane_pins(section, original.view_id, 0, (key,))
    dup_idx = mgr.duplicate(0)
    dup = mgr.get(dup_idx)
    # Copy's first render would create its own pin; seed it the same way.
    win._replace_analysis_pane_pins(section, dup.view_id, 0, (key,))
    assert key in win._pinned_keys_for_section(section)

    win._drop_analysis_view_pins(section, original.view_id)
    assert key in win._pinned_keys_for_section(section)
    for i in range(cache._capacity + 2):
        cache.put(cache.make_key("x", str(i), {}), _fake_heatmap(i))
    assert key in cache._store


def test_async_order_completion_pins_dispatch_view_not_active(win, monkeypatch):
    section = "order"
    mgr = win.analysis_managers[section]
    mgr.new_view()
    dispatched = mgr.get(0)
    later = mgr.get(1)
    mgr.set_active(1)
    assert mgr.get(mgr.active) is later

    monkeypatch.setattr(win, "_render_order_time", lambda *a, **k: None)
    monkeypatch.setattr(win, "_render_order_on", lambda *a, **k: None)

    cache = win.analysis_caches[section]
    key = cache.make_key("f1", "sig", {"nfft": 64, "time_range": None})
    ctx = {
        "analysis_key": key,
        "pane_idx": 0,
        "view_id": dispatched.view_id,
        "source": ("f1", "sig"),
    }
    win._on_order_job_finished(ctx, _fake_heatmap("async"))
    assert key in win._analysis_pins[(section, dispatched.view_id, 0)]
    assert (section, later.view_id, 0) not in win._analysis_pins


def test_async_order_stale_view_skips_draw_keeps_dispatch_cache(win, monkeypatch):
    """A7: slow order job finishing after a View switch must not paint the
    active page, but must still cache/pin under the dispatch-time view_id so
    switching back can render from cache.
    """
    section = "order"
    mgr = win.analysis_managers[section]
    mgr.new_view()
    dispatched = mgr.get(0)
    later = mgr.get(1)
    dispatched.panes[0].sources = [("f1", "sig")]
    mgr.set_active(1)
    assert mgr.get(mgr.active) is later

    drawn = []
    monkeypatch.setattr(
        win, "_render_order_time", lambda *a, **k: drawn.append(("primary", a, k))
    )
    monkeypatch.setattr(
        win, "_render_order_on", lambda *a, **k: drawn.append(("pane", a, k))
    )

    cache = win.analysis_caches[section]
    key = cache.make_key("f1", "sig", {"nfft": 64, "time_range": None})
    result = _fake_heatmap("stale-order")
    ctx = {
        "analysis_key": key,
        "pane_idx": 0,
        "view_id": dispatched.view_id,
        "source": ("f1", "sig"),
    }
    win._on_order_job_finished(ctx, result)

    assert drawn == [], "stale completion must not paint the active View canvas"
    assert cache.get(key) is result
    assert key in win._analysis_pins[(section, dispatched.view_id, 0)]
    assert (section, later.view_id, 0) not in win._analysis_pins

    restored = []
    monkeypatch.setattr(
        win,
        "_analysis_cache_key",
        lambda *args, **kwargs: key,
    )
    monkeypatch.setattr(
        win,
        "_render_cached_heatmap",
        lambda sec, canvas, res, source=None: restored.append((sec, res, source)),
    )
    monkeypatch.setattr(win, "_show_analysis_empty_hint", lambda *a, **k: None)
    monkeypatch.setattr(win, "_clear_analysis_canvas", lambda *a, **k: None)
    mgr.set_active(0)
    restored.clear()  # set_active may already restore; assert the explicit path
    win._render_analysis_view_from_cache(section, dispatched)
    assert restored == [(section, result, ("f1", "sig"))]


def test_async_fft_time_stale_view_skips_draw_keeps_dispatch_cache(
    win, monkeypatch,
):
    """A7: FFT-vs-Time render_requested for a non-active view_id skips draw
    only — coordinator already stored cache/pin at dispatch view_id.
    """
    section = "fft_time"
    mgr = win.analysis_managers[section]
    mgr.new_view()
    dispatched = mgr.get(0)
    later = mgr.get(1)
    dispatched.panes[0].sources = [("f1", "sig")]
    mgr.set_active(1)
    assert mgr.get(mgr.active) is later

    # Simulate coordinator store_result before render_requested (production
    # order in fft_time_coordinator._on_job_finished).
    cache = win.analysis_caches[section]
    key = cache.make_key("f1", "sig", {"nfft": 256, "time_range": None})
    result = _fake_heatmap("stale-fft-time")
    result.metadata = {"frames": 3}
    result.params = SimpleNamespace(nfft=256)
    win._store_analysis_result(section, dispatched.view_id, 0, key, result)

    drawn = []
    monkeypatch.setattr(
        win, "_render_fft_time_on", lambda *a, **k: drawn.append(("on", a, k))
    )
    monkeypatch.setattr(
        win, "_render_fft_time", lambda *a, **k: drawn.append(("primary", a, k))
    )

    ctx = {
        "analysis_key": key,
        "pane_idx": 0,
        "view_id": dispatched.view_id,
        "source": ("f1", "sig"),
        "render_params": {"amplitude_mode": "Amplitude dB"},
    }
    win._on_fft_time_render_requested(ctx, result, False)

    assert drawn == [], "stale FFT-vs-Time completion must not paint active View"
    assert cache.get(key) is result
    assert key in win._analysis_pins[(section, dispatched.view_id, 0)]

    restored = []
    monkeypatch.setattr(win, "_analysis_cache_key", lambda *a, **k: key)
    monkeypatch.setattr(
        win,
        "_render_cached_heatmap",
        lambda sec, canvas, res, source=None: restored.append((sec, res, source)),
    )
    monkeypatch.setattr(win, "_show_analysis_empty_hint", lambda *a, **k: None)
    monkeypatch.setattr(win, "_clear_analysis_canvas", lambda *a, **k: None)
    mgr.set_active(0)
    restored.clear()  # set_active may already restore; assert the explicit path
    win._render_analysis_view_from_cache(section, dispatched)
    assert restored == [(section, result, ("f1", "sig"))]


def test_exit_split_drops_pane1_pins_for_analysis_sections(win):
    """F13: leaving analysis split must drop pane-1 pins, including FFT."""
    for section in ("fft", "fft_time", "order"):
        mgr = win.analysis_managers[section]
        state = mgr.get(mgr.active)
        assert state.add_pane()
        cache = win.analysis_caches[section]
        key0 = cache.make_key("f1", "p0", {"nfft": 64, "time_range": None})
        key1 = cache.make_key("f1", "p1", {"nfft": 64, "time_range": None})
        win._store_analysis_result(
            section, state.view_id, 0, key0, _fake_heatmap(f"{section}-p0")
        )
        win._store_analysis_result(
            section, state.view_id, 1, key1, _fake_heatmap(f"{section}-p1")
        )
        assert key1 in win._analysis_pins[(section, state.view_id, 1)]

        win._on_analysis_split(section, False)

        assert (section, state.view_id, 1) not in win._analysis_pins
        assert key0 in win._analysis_pins[(section, state.view_id, 0)]
        assert len(state.panes) == 1

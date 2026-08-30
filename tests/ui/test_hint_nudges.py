"""Situational nudges — a condition-gated footer surface.

Unlike the existing rotating/discovery hints (gated only by *page mode*), a
``surface="nudge"`` hint fires on the actual *data situation* — too many
channels, disparate amplitudes, a dead colour window, a clipped signal — so the
app can proactively point at the relevant capability the moment it becomes
useful. ``nudge_hint(state)`` returns the single highest-priority matching nudge
(or None); nudges self-clear when their condition clears and retire for good
once the user discovers the capability.
"""
import pytest
from PyQt5.QtCore import QCoreApplication, QSettings

from mf4_analyzer import db_reference
from mf4_analyzer.ui import hints
from mf4_analyzer.ui.hints import HintState
from mf4_analyzer.ui.chart_stack.cards import _ChartCard
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


def _ids(state):
    n = hints.nudge_hint(state)
    return n.id if n else None


def _fresh_settings(tmp_path, name):
    # A fresh QSettings file so a persisted `discovered` set from another
    # test/run can't retire (or otherwise contaminate) the nudge under test.
    return QSettings(str(tmp_path / name), QSettings.IniFormat)


# ---- A组: 绘图拥挤 / 幅值 -------------------------------------------------

def test_coaxis_nudge_fires_for_crowded_same_unit_overlay():
    crowded = HintState(
        mode="time", plot_mode="overlay",
        channel_count=4, same_unit=True, has_axis_group=False,
    )
    assert _ids(crowded) == "nudge.coaxis"


def test_coaxis_nudge_silent_below_threshold_or_mixed_units():
    few = HintState(mode="time", plot_mode="overlay",
                    channel_count=3, same_unit=True)
    assert _ids(few) != "nudge.coaxis"
    mixed = HintState(mode="time", plot_mode="overlay",
                      channel_count=6, same_unit=False)
    assert _ids(mixed) != "nudge.coaxis"


def test_coaxis_nudge_silent_once_a_group_exists():
    grouped = HintState(
        mode="time", plot_mode="overlay",
        channel_count=6, same_unit=True, has_axis_group=True,
    )
    assert _ids(grouped) != "nudge.coaxis"


def test_coaxis_nudge_also_fires_in_subplot():
    sub = HintState(
        mode="time", plot_mode="subplot",
        channel_count=5, same_unit=True, has_axis_group=False,
    )
    assert _ids(sub) == "nudge.coaxis"


def test_coaxis_nudge_retires_once_axis_group_menu_discovered():
    after = HintState(
        mode="time", plot_mode="overlay",
        channel_count=6, same_unit=True, has_axis_group=False,
        discovered=frozenset({"coaxis.merge"}),
    )
    assert _ids(after) != "nudge.coaxis"


def test_amp_disparate_nudge_points_at_alt_drag():
    state = HintState(
        mode="time", plot_mode="overlay",
        amp_disparate=True, has_axis_group=False,
    )
    assert _ids(state) == "nudge.amp_disparate"


def test_too_many_nudge_suggests_subplot_but_coaxis_wins_when_same_unit():
    flood_mixed = HintState(
        mode="time", plot_mode="overlay",
        channel_count=8, same_unit=False,
    )
    assert _ids(flood_mixed) == "nudge.too_many"

    flood_same = HintState(
        mode="time", plot_mode="overlay",
        channel_count=8, same_unit=True, has_axis_group=False,
    )
    # coaxis (compare amplitude) outranks the generic "switch to subplot".
    assert _ids(flood_same) == "nudge.coaxis"


# ---- B组: 数据质量 / 色阶 -------------------------------------------------

def test_colorbar_dead_nudge_fires_on_heatmap_pages_only():
    dead_ft = HintState(mode="fft_time", chart_kind="fft_time", colorbar_dead=True)
    assert _ids(dead_ft) == "nudge.colorbar_dead"
    dead_order = HintState(mode="order", chart_kind="order", colorbar_dead=True)
    assert _ids(dead_order) == "nudge.colorbar_dead"
    # A dead flag on a line page (no colorbar) must not surface it.
    not_heatmap = HintState(mode="time", plot_mode="overlay", colorbar_dead=True)
    assert _ids(not_heatmap) != "nudge.colorbar_dead"


def test_colorbar_dead_nudge_retires_once_colorbar_used():
    after = HintState(
        mode="order", chart_kind="order", colorbar_dead=True,
        discovered=frozenset({"spectrogram.colorbar"}),
    )
    assert _ids(after) != "nudge.colorbar_dead"


def test_clipped_nudge_warns_on_saturated_signal():
    state = HintState(mode="time", plot_mode="subplot", clipped=True)
    assert _ids(state) == "nudge.clipped"


# ---- C组: dB 参考迁移后果 (spec 2026-07-12 S5) ----------------------------

def test_db_reference_nudge_gates_on_manual_default_with_resolvable_source():
    # All three Inspector rows (FFT / FFT-vs-Time / Order) qualify: current
    # View stuck at the legacy manual default (1.0) while the focused source
    # would actually resolve a real (non-1.0) catalog/metadata reference.
    for mode in ("fft", "fft_time", "order"):
        state = HintState(
            mode=mode,
            db_reference_mode="manual",
            db_reference_value=1.0,
            db_reference_source_resolvable=True,
        )
        assert _ids(state) == "nudge.db_ref_manual_default", mode


def test_db_reference_nudge_absent_for_auto_or_non_default_manual():
    # Auto View: never nags (Auto already tracks the source).
    auto_view = HintState(
        mode="fft",
        db_reference_mode="auto",
        db_reference_value=1.0,
        db_reference_source_resolvable=True,
    )
    assert _ids(auto_view) != "nudge.db_ref_manual_default"

    # Manual but the user already moved off the legacy 1.0 default: they have
    # already made a deliberate choice, nothing to nudge.
    non_default_manual = HintState(
        mode="order",
        db_reference_mode="manual",
        db_reference_value=2.5e-6,
        db_reference_source_resolvable=True,
    )
    assert _ids(non_default_manual) != "nudge.db_ref_manual_default"

    # Manual at 1.0 but the source has nothing better to offer (generic/
    # fallback also resolve to 1.0) -- switching to Auto would change nothing.
    unresolvable_manual = HintState(
        mode="fft_time",
        db_reference_mode="manual",
        db_reference_value=1.0,
        db_reference_source_resolvable=False,
    )
    assert _ids(unresolvable_manual) != "nudge.db_ref_manual_default"


def test_db_reference_nudge_within_length_budget_and_time_mode_excluded():
    hint = next(h for h in hints.all_hints() if h.id == "nudge.db_ref_manual_default")
    assert hints.hint_display_width(hint.text) <= hints.HINT_MAX_WIDTH
    # Time-domain has no dB-reference control at all.
    time_state = HintState(
        mode="time",
        db_reference_mode="manual",
        db_reference_value=1.0,
        db_reference_source_resolvable=True,
    )
    assert _ids(time_state) != "nudge.db_ref_manual_default"


# ---- D组: live-feed integration (real _ChartCard path, spec 2026-07-12 S5 /
# acceptance A17) ------------------------------------------------------------
# The predicate tests above construct HintState directly -- they prove the
# TRIGGER CONDITION but not that anything ever actually populates
# db_reference_mode/value/source_resolvable at runtime. These drive the SAME
# merge path production code uses (_ChartCard._hint_state() ->
# _nudge_signals()), stamping ``canvas.db_reference_nudge_facts`` exactly the
# way ``AnalysisMixin._stamp_db_reference_nudge_facts`` does (spec §13 S5 /
# A17), so a regression in the cards.py merge (e.g. a typo'd dict key) fails
# here even though the predicate/HintState-construction tests above stay green.

def test_db_reference_nudge_fires_in_live_card_state(qapp, qtbot, tmp_path):
    # Simulates: a manual-mode analysis section whose focused source is a
    # real acceleration (m/s^2) channel. Resolve ``source_resolvable`` through
    # the SAME production resolver ``AnalysisMixin._stamp_db_reference_nudge_
    # facts`` calls (mode="auto", no metadata override) rather than a bare
    # literal, so this test also pins the acceleration-catalog claim itself:
    # Auto would give 1e-6 (system catalog), not the legacy 1.0 default.
    facts = db_reference.ChannelReferenceFacts(quantity="acceleration", unit="m/s²")
    auto_resolution = db_reference.resolve_db_reference(mode="auto", facts=facts)
    assert auto_resolution.value == pytest.approx(1e-6)
    assert auto_resolution.source == "system"
    source_resolvable = (
        auto_resolution.source in ("metadata", "user", "system")
        and auto_resolution.value != 1.0
    )

    canvas = PgLineCanvas()
    card = _ChartCard(canvas, chart_mode="fft")
    qtbot.addWidget(card)
    card.set_hint_settings(_fresh_settings(tmp_path, "live_fires.ini"))

    canvas.db_reference_nudge_facts = {
        "mode": "manual",
        "value": 1.0,
        "source_resolvable": source_resolvable,
    }
    QCoreApplication.processEvents()

    nudge = hints.nudge_hint(card._hint_state())
    assert nudge is not None and nudge.id == "nudge.db_ref_manual_default"


def test_db_reference_nudge_absent_in_live_card_state_for_auto_or_non_default(
    qapp, qtbot, tmp_path,
):
    canvas = PgLineCanvas()
    card = _ChartCard(canvas, chart_mode="order")
    qtbot.addWidget(card)
    card.set_hint_settings(_fresh_settings(tmp_path, "live_absent.ini"))

    # Auto View: never nags, even with a resolvable source.
    canvas.db_reference_nudge_facts = {
        "mode": "auto", "value": 1.0, "source_resolvable": True,
    }
    auto_nudge = hints.nudge_hint(card._hint_state())
    assert auto_nudge is None or auto_nudge.id != "nudge.db_ref_manual_default"

    # Manual but the user already moved off the legacy 1.0 default.
    canvas.db_reference_nudge_facts = {
        "mode": "manual", "value": 2.5e-6, "source_resolvable": True,
    }
    non_default_nudge = hints.nudge_hint(card._hint_state())
    assert (
        non_default_nudge is None
        or non_default_nudge.id != "nudge.db_ref_manual_default"
    )


def test_db_reference_nudge_facts_absent_is_inert(qapp, qtbot, tmp_path):
    """A canvas that never had ``db_reference_nudge_facts`` stamped (e.g. the
    time-domain canvas, or a section visited before this feature existed)
    must not crash the merge and must not surface the nudge."""
    canvas = PgLineCanvas()
    card = _ChartCard(canvas, chart_mode="fft")
    qtbot.addWidget(card)
    card.set_hint_settings(_fresh_settings(tmp_path, "live_unstamped.ini"))

    assert not hasattr(canvas, "db_reference_nudge_facts")
    nudge = hints.nudge_hint(card._hint_state())
    assert nudge is None or nudge.id != "nudge.db_ref_manual_default"


# ---- 机制隔离 ------------------------------------------------------------

def test_no_nudge_when_situation_is_calm():
    calm = HintState(mode="time", plot_mode="overlay",
                     channel_count=2, same_unit=True)
    assert hints.nudge_hint(calm) is None


def test_nudges_do_not_leak_into_other_surfaces():
    # A hot situation that would fire every nudge predicate must still keep the
    # nudge entries out of the discovery / context / rotation pools.
    hot = HintState(
        mode="time", plot_mode="overlay",
        channel_count=9, same_unit=True, amp_disparate=True, clipped=True,
    )
    for surface_fn in (hints.discovery_hint,):
        h = surface_fn(hot)
        assert h is None or not h.id.startswith("nudge.")
    for pool in (hints.context_hints(hot), hints.rotation_hints(hot)):
        assert not any(h.id.startswith("nudge.") for h in pool)


def test_nudge_entries_are_within_length_budget():
    # The footer slot the nudge occupies has the same width budget as any hint.
    for hint in hints.all_hints():
        if hint.surface != "nudge":
            continue
        assert hints.hint_display_width(hint.text) <= hints.HINT_MAX_WIDTH, hint.id


# ---- E组: 时域 View 紧凑标签 (12-View 扩容 4abd5f4) ------------------------
# The View tab bar degrades to dot + ordinal when the row narrows
# (view_tabbar._set_density), so the View NAMES vanish and survive only in the
# tooltip. Users read the first narrow drag as "我的 View 名字哪去了", not "这是
# 紧凑模式" -- the same class of confusion the sibling ``view.history`` footer
# entry answers.
#
# Why ``discovery`` and not ``nudge``, despite the situational feel: a nudge
# gates on a ``HintState`` DATA signal fed by ``_ChartCard._nudge_signals()``,
# and the tab bar is a SIBLING widget of the chart card that feeds nothing into
# that state -- a ``view_tabs_compact`` predicate would need new plumbing
# through cards.py. Discovery carries the same footer slot with no new feed.
#
# Why ``ship="now"``: the 12-View bar is live in HEAD, so the confusion exists
# today; ``_is_shipped`` filters ``ship="later"`` out of EVERY surface, which
# would register the hint and show it nowhere.


def _discovery_walk(**state_kwargs):
    """Ordered discovery-queue ids for a state (walk until exhausted)."""
    seen, walked = [], HintState(**state_kwargs)
    while (h := hints.discovery_hint(walked)) is not None and h.id not in seen:
        seen.append(h.id)
        walked = HintState(discovered=frozenset(seen), **state_kwargs)
    return seen


def test_view_compact_tabs_is_a_shipped_time_scoped_discovery_hint():
    hint = next(h for h in hints.all_hints() if h.id == "view.compact_tabs")
    assert hint.surface == "discovery"
    assert hint.scope == "chart"
    assert hint.ship == "now"  # the 12-View bar is live; staging hides it
    # Analysis sections share the same 12-View ceiling, but this discovery
    # hint stays time-scoped to match the quickref 时域 View row.
    assert hint.modes == frozenset({"time"})
    assert hint.plot_modes == frozenset()  # subplot AND overlay have the bar
    assert hints.hint_display_width(hint.text) <= hints.HINT_MAX_WIDTH
    # It must answer BOTH halves of the confusion: names gone, and how back.
    assert "全名" in hint.text
    assert "悬停" in hint.text


def test_view_compact_tabs_ranks_between_coaxis_custom_action_and_batch_export():
    # Exact-match queue order: a discovery hint's priority IS its rotation
    # position, so pin it. (view.history is ship="later" -> absent.)
    assert _discovery_walk(mode="time", plot_mode="overlay") == [
        "toolbar.shortcuts_exist",
        "chart.copy_image",
        "chart.right_click_menu",
        "time.drop_join_view",
        "time.drop_set_xaxis",
        "channel.right_click",
        "time.nav_reorder",
        "file.scope_follow",
        # 58030e4d: same priority 70 as coaxis.merge; registry order wins.
        "channel.export_wwt_storage",
        "coaxis.merge",
        # Same priority 65 as view.compact_tabs; registry order wins.
        "file.wwt_native_layout",
        "view.compact_tabs",
        "ultraview.view_rail",
        "ultraview.unplaced_badge",
        "ultraview.add_from_tab",
        "chart.custom_action_slot",
        "chart.range_tab",
        "time.record_curve_eye",
        "batch.export_options",
        "file.wwt_batch_choice",
        "time.custom_x_paths",
        "time.wwt_native_home",
        "toolbar.save_as_menu",
    ]


def test_view_compact_tabs_absent_outside_the_time_domain():
    for mode in ("fft", "fft_time", "order"):
        assert "view.compact_tabs" not in _discovery_walk(mode=mode), mode


def test_view_compact_tabs_retires_once_discovered():
    after = HintState(
        mode="time",
        plot_mode="overlay",
        discovered=frozenset({"view.compact_tabs"}),
    )
    walked = _discovery_walk(mode="time", plot_mode="overlay")
    assert "view.compact_tabs" in walked  # premise: it does surface
    for _ in range(len(walked)):
        h = hints.discovery_hint(after)
        if h is None:
            break
        assert h.id != "view.compact_tabs"
        after = HintState(
            mode="time",
            plot_mode="overlay",
            discovered=after.discovered | {h.id},
        )


# ---- E组 live wiring: the retire_on event actually fires -------------------
# The registry entry alone is inert: `discovery_hint` retires on
# `hint.id not in state.discovered`, so SOMETHING must call
# mark_discovered("view.compact_tabs") or the hint rotates forever (exactly the
# gap 2026-06-27-hint-ship-flip-test-blast-radius found in coaxis.merge). Note
# mark_discovered takes the HINT ID, never the `retire_on` descriptor string.


def _fit_bar(qtbot, count, budget_fn):
    """A live ViewTabBar sized so ``budget_fn(roomy, compact)`` is the strip's
    budget. Every width is MEASURED off the live row -- a literal px budget is
    how a degrade branch becomes a false green (2026-07-10-facts-degrade-budget
    -from-measured-not-literal-px)."""
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.view_state import ViewManager
    from mf4_analyzer.ui.view_tabbar import ViewTabBar

    manager = ViewManager(max_views=64)
    while len(manager.views) < count:
        manager.new_view()
    manager.set_active(0)
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    bar.resize(4000, 28)
    bar.show()
    QApplication.processEvents()

    tabs = bar.tabBar()
    bar._set_density(compact=False)
    roomy = tabs.sizeHint().width()
    overhead = bar.width() - bar._tabs_budget(include_overflow=False)
    bar._set_density(compact=True)
    compact = tabs.sizeHint().width()
    bar._set_density(compact=False)
    assert compact < roomy  # reachability premise for every caller below
    bar.resize(int(budget_fn(roomy, compact)) + overhead, 28)
    QApplication.processEvents()
    return manager, bar


def _spy_mark_discovered(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "mf4_analyzer.ui.view_tabbar.hints.mark_discovered",
        lambda _settings, hint_id: recorded.append(hint_id),
    )
    return recorded


def test_compact_tab_tooltip_retires_the_view_compact_tabs_discovery(
    qapp, qtbot, monkeypatch,
):
    """Hovering a compact tab shows the tooltip the hint promises ("悬停可看全
    名") -- the user has found the answer, so the hint must retire. This is the
    ONLY retire path for a row that compacts without ever overflowing (no »
    button exists there), so without it those users are nagged forever."""
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QHelpEvent
    from PyQt5.QtWidgets import QApplication

    recorded = _spy_mark_discovered(monkeypatch)
    _manager, bar = _fit_bar(qtbot, 10, lambda roomy, compact: (roomy + compact) // 2)
    tabs = bar.tabBar()
    assert bar.is_compact()  # premise
    assert bar.overflow_indices() == []  # compact alone fit: no » to click

    pos = tabs.tabRect(3).center()
    QApplication.sendEvent(
        tabs, QHelpEvent(QEvent.ToolTip, pos, tabs.mapToGlobal(pos))
    )
    assert recorded == ["view.compact_tabs"]

    # mark_discovered syncs QSettings to disk on every call and tooltips fire on
    # every hover -- the session guard must keep that to one write.
    QApplication.sendEvent(
        tabs, QHelpEvent(QEvent.ToolTip, pos, tabs.mapToGlobal(pos))
    )
    assert recorded == ["view.compact_tabs"]


def test_roomy_tab_tooltip_does_not_retire_the_hint_early(qapp, qtbot, monkeypatch):
    """A roomy row shows full names and carries NO tab tooltip, so a ToolTip
    event there is not a discovery -- retiring on it would kill the hint before
    the user ever met compact mode."""
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QHelpEvent
    from PyQt5.QtWidgets import QApplication

    recorded = _spy_mark_discovered(monkeypatch)
    _manager, bar = _fit_bar(qtbot, 10, lambda roomy, _compact: roomy * 4)
    tabs = bar.tabBar()
    assert not bar.is_compact()  # premise

    pos = tabs.tabRect(3).center()
    QApplication.sendEvent(
        tabs, QHelpEvent(QEvent.ToolTip, pos, tabs.mapToGlobal(pos))
    )
    assert recorded == []


def test_overflow_menu_open_retires_the_view_compact_tabs_discovery(
    qapp, qtbot, monkeypatch,
):
    """The » menu renders every View's FULL name -- opening it is the other way
    the user finds where the names went."""
    recorded = _spy_mark_discovered(monkeypatch)
    monkeypatch.setattr(
        "mf4_analyzer.ui.view_tabbar.QMenu.exec_", lambda *_a, **_k: None
    )
    _manager, bar = _fit_bar(qtbot, 14, lambda _roomy, compact: compact // 2)
    assert bar.overflow_indices()  # premise: we really are in the overflow regime

    bar._on_overflow_clicked()

    assert recorded == ["view.compact_tabs"]

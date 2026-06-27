"""Situational nudges — a condition-gated footer surface.

Unlike the existing rotating/discovery hints (gated only by *page mode*), a
``surface="nudge"`` hint fires on the actual *data situation* — too many
channels, disparate amplitudes, a dead colour window, a clipped signal — so the
app can proactively point at the relevant capability the moment it becomes
useful. ``nudge_hint(state)`` returns the single highest-priority matching nudge
(or None); nudges self-clear when their condition clears and retire for good
once the user discovers the capability.
"""
from mf4_analyzer.ui import hints
from mf4_analyzer.ui.hints import HintState


def _ids(state):
    n = hints.nudge_hint(state)
    return n.id if n else None


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

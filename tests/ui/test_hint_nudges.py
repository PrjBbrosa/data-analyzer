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

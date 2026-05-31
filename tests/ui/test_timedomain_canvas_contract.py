"""Contract-freeze tests for ``TimeDomainCanvas`` and ``TimeChartCard``.

Phase 1 of the pyqtgraph TimeDomain migration
(``docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md``
sections 3.1, 3.2, 4.1, 4.2, 6 Phase 1).

These tests pin the *current* matplotlib ``TimeDomainCanvas`` surface
before any renderer swap, so the future pyqtgraph implementation cannot
silently drift signal payloads, public method names, data semantics, or
TimeChartCard UI affordances. They construct REAL Qt widgets under the
offscreen platform (no MagicMock canvases), per the
``codex-phantom-api-surface-guards`` defensive gate.

Out of scope here: pyqtgraph parity (Task 5), AxisHandle (Task 3),
envelope C path (Task 4). Anything beyond contract assertions belongs
to a later task.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from PyQt5.QtCore import pyqtBoundSignal

from mf4_analyzer.ui import chart_stack as chart_stack_mod
from mf4_analyzer.ui.canvases import TimeDomainCanvas
from mf4_analyzer.ui.chart_stack import ChartStack, TimeChartCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal_signature(bound: pyqtBoundSignal) -> str:
    """Return the C++ signature substring for a bound pyqtSignal.

    ``pyqtBoundSignal.signal`` is a Qt-style decorated name such as
    ``"2cursor_info(QString)"`` (the leading ``2`` indicates SIGNAL).
    We strip the leading digits so callers can assert exact name and
    payload shape without worrying about the SIGNAL/SLOT prefix.
    """
    raw = bound.signal
    return raw.lstrip("0123456789")


# ---------------------------------------------------------------------------
# 3.1 — TimeDomainCanvas signal surface
# ---------------------------------------------------------------------------


def test_timedomain_canvas_exposes_four_signals_with_exact_payloads(qapp):
    """Design §3.1: the four pyqtSignals must exist on the class with
    the exact names and payload shapes downstream code consumes."""
    canvas = TimeDomainCanvas()

    expected = {
        "cursor_info": "cursor_info(QString)",
        "dual_cursor_info": "dual_cursor_info(QString)",
        "span_selected": "span_selected(double,double)",
        "overlay_channel_selected": "overlay_channel_selected(PyQt_PyObject)",
    }

    for name, want_sig in expected.items():
        bound = getattr(canvas, name, None)
        assert bound is not None, f"signal {name!r} missing on TimeDomainCanvas"
        assert isinstance(bound, pyqtBoundSignal), (
            f"attribute {name!r} is not a pyqtBoundSignal (got {type(bound)!r})"
        )
        got = _signal_signature(bound)
        assert got == want_sig, (
            f"signal {name!r}: expected payload {want_sig!r}, got {got!r}"
        )


# ---------------------------------------------------------------------------
# 3.1 — TimeDomainCanvas public method surface
# ---------------------------------------------------------------------------


def test_timedomain_canvas_exposes_public_methods(qapp):
    """Design §3.1: the listed methods/attributes are externally relied
    on (MainWindow, ChartStack, ChartOptionsDialog, tests). Freeze the
    surface before any renderer swap."""
    canvas = TimeDomainCanvas()

    required_methods = [
        "plot_channels",
        "clear",
        "full_reset",
        "set_cursor_visible",
        "set_dual_cursor_mode",
        "set_tick_density",
        "enable_span_selector",
        "get_statistics",
        "invalidate_envelope_cache",
        "invalidate_monotonicity_cache",
        # compatibility seam introduced/checked by this task
        "draw_idle",
        "draw",
        "_flush_pending_refresh",
    ]
    for name in required_methods:
        attr = getattr(canvas, name, None)
        assert callable(attr), (
            f"TimeDomainCanvas is missing callable method {name!r}"
        )

    required_attributes = [
        "axes_list",
        "channel_data",
        "_channel_lines",
        "_primary_xaxis_ax",
        "_ax",
        "_bx",
        "_placing",
        "_refresh",
    ]
    for name in required_attributes:
        assert hasattr(canvas, name), (
            f"TimeDomainCanvas is missing attribute {name!r}"
        )


# ---------------------------------------------------------------------------
# 4.2 — channel_data shape: (t, sig, color, unit), raw post-range-filter
# ---------------------------------------------------------------------------


def test_plot_channels_keeps_channel_data_as_raw_tuple(qapp):
    """Design §4.2: ``channel_data[name]`` must remain
    ``(t, sig, color, unit)`` — raw (post-range-filter), full-resolution,
    NOT envelope output."""
    canvas = TimeDomainCanvas()
    t = np.linspace(0.0, 1.0, 200, dtype=float)
    sig = np.sin(2 * np.pi * 5 * t).astype(float)
    color = "#ef4444"
    unit = "Nm"

    canvas.plot_channels(
        [("torque", True, t, sig, color, unit)], mode="overlay"
    )

    assert "torque" in canvas.channel_data
    stored = canvas.channel_data["torque"]
    assert isinstance(stored, tuple) and len(stored) == 4, (
        f"channel_data['torque'] must be a 4-tuple, got {stored!r}"
    )
    got_t, got_sig, got_color, got_unit = stored
    # Raw full-resolution arrays — not the downsampled/envelope output.
    np.testing.assert_array_equal(np.asarray(got_t), t)
    np.testing.assert_array_equal(np.asarray(got_sig), sig)
    assert got_color == color
    assert got_unit == unit


# ---------------------------------------------------------------------------
# 4.2 — get_statistics reads raw channel_data, not envelope cache output
# ---------------------------------------------------------------------------


def test_get_statistics_reads_raw_channel_data_not_envelope_cache(qapp):
    """Design §4.2 / §4.3: statistics must come from raw
    ``channel_data``. Poisoning the envelope cache with wildly different
    values must NOT change the returned stats, proving stats do not
    follow envelope output.
    """
    canvas = TimeDomainCanvas()
    t = np.linspace(0.0, 1.0, 256, dtype=float)
    sig = np.linspace(-1.0, 1.0, 256, dtype=float)
    canvas.plot_channels(
        [("speed", True, t, sig, "#00b894", "rpm")], mode="overlay"
    )

    # Baseline stats from raw data.
    stats_before = canvas.get_statistics(time_range=(0.0, 1.0))
    assert "speed" in stats_before
    assert stats_before["speed"]["min"] == pytest.approx(-1.0)
    assert stats_before["speed"]["max"] == pytest.approx(1.0)
    assert stats_before["speed"]["mean"] == pytest.approx(0.0, abs=1e-12)

    # Snapshot envelope cache state, then poison it with a bogus entry
    # whose values are nowhere near the raw signal range. If
    # get_statistics consulted the envelope output, this poisoned entry
    # would shift min/max/mean — but get_statistics reads channel_data
    # directly, so the stats must be identical.
    envelope_cache = canvas._envelope_cache
    assert hasattr(canvas, "_envelope_cache"), (
        "TimeDomainCanvas should expose _envelope_cache as a viewport seam"
    )
    snapshot_keys_before = list(envelope_cache.keys())
    # Inject a poisoned entry under a key that mimics the cache shape
    # (data_id, channel, quantized_xlim, pixel_width). Whatever the
    # exact shape, the key must not collide with the live channel name.
    poisoned_t = np.array([0.0, 1.0])
    poisoned_s = np.array([1e9, -1e9])  # absurd values
    envelope_cache[("__poison__", "speed", (0.0, 1.0), 100)] = (
        poisoned_t, poisoned_s
    )

    stats_after = canvas.get_statistics(time_range=(0.0, 1.0))
    # Stats must be identical to the raw-data baseline — envelope cache
    # poisoning must not have leaked into the result.
    assert stats_after["speed"]["min"] == pytest.approx(-1.0)
    assert stats_after["speed"]["max"] == pytest.approx(1.0)
    assert stats_after["speed"]["mean"] == pytest.approx(0.0, abs=1e-12)
    # Stats are computed from numpy ops on channel_data — no envelope
    # cache READ side effect should mutate the cache either.
    assert ("__poison__", "speed", (0.0, 1.0), 100) in envelope_cache
    # And the pre-existing keys (likely none for a fresh canvas) are
    # untouched.
    for k in snapshot_keys_before:
        assert k in envelope_cache


# ---------------------------------------------------------------------------
# 3.3 — plot_time does not enable always-on SpanSelector
# ---------------------------------------------------------------------------


def test_plot_time_does_not_enable_always_on_span_selector():
    """Design §3.3: the always-on drag-to-select SpanSelector was
    retired (main_window.py:993-996). ``MainWindow.plot_time`` must NOT
    call ``canvas_time.enable_span_selector``. Asserting this at the
    source level is more robust than running the whole window: any
    future regression that re-adds the call would be caught by grep.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    src = inspect.getsource(MainWindow.plot_time)
    assert "enable_span_selector" not in src, (
        "plot_time must not auto-enable SpanSelector; the always-on "
        "drag-to-select was retired 2026-05-27 (see comments at "
        "main_window.py:993-996)."
    )


# ---------------------------------------------------------------------------
# 3.2 — TimeChartCard button labels are exact literal Chinese strings
# ---------------------------------------------------------------------------


def test_time_chart_card_button_labels_are_exact_chinese_strings(qapp):
    """Design §3.2: TimeChartCard segmented-control buttons must carry
    the exact labels ``分屏``, ``叠加``, ``游标关``, ``单游标``, ``双游标``
    (chart_stack.py:554-580). Use ``.text()`` so we test what the user
    actually sees, not just the constructor literal."""
    canvas = TimeDomainCanvas()
    card = TimeChartCard(canvas)

    assert card.btn_subplot.text() == "分屏"
    assert card.btn_overlay.text() == "叠加"

    cursor_buttons = card._cursor_buttons
    assert cursor_buttons["off"].text() == "游标关"
    assert cursor_buttons["single"].text() == "单游标"
    assert cursor_buttons["dual"].text() == "双游标"


# ---------------------------------------------------------------------------
# 3.2 — Alt+1..Alt+5 shortcuts wired to the segmented controls
# ---------------------------------------------------------------------------


def test_time_chart_card_has_alt_1_through_5_shortcuts_wired(qapp):
    """Design §3.2 (revised): Alt+1..Alt+5 must be wired (chart_stack.py
    _TIME_CARD_SHORTCUTS). The app has no QMenuBar so Alt+digit is safe and
    leaves Ctrl+digit free. We check both the module-level mapping and the
    installed QShortcut sequences on the live card so a future refactor
    cannot drop one without the test noticing."""
    # Module-level constant pinned to the design.
    assert chart_stack_mod._TIME_CARD_SHORTCUTS == (
        ("btn_subplot", "分屏", "Alt+1"),
        ("btn_overlay", "叠加", "Alt+2"),
        ("cursor_off", "游标关", "Alt+3"),
        ("cursor_single", "单游标", "Alt+4"),
        ("cursor_dual", "双游标", "Alt+5"),
    )

    canvas = TimeDomainCanvas()
    card = TimeChartCard(canvas)

    # Five QShortcut instances installed on the card.
    shortcuts = card._time_button_shortcuts
    assert len(shortcuts) == 5, (
        f"expected 5 segmented-control shortcuts, got {len(shortcuts)}"
    )
    sequences = {sc.key().toString() for sc in shortcuts}
    assert sequences == {"Alt+1", "Alt+2", "Alt+3", "Alt+4", "Alt+5"}


# ---------------------------------------------------------------------------
# Task 2 Step 2/3 — reset_cursor_state contract
# ---------------------------------------------------------------------------


def test_reset_cursor_state_clears_dual_fields_and_marks_refresh(qapp):
    """Task 2 Step 2: ``TimeDomainCanvas.reset_cursor_state`` is the
    public seam ``MainWindow._reset_cursors`` calls instead of poking
    ``_ax`` / ``_bx`` / ``_placing`` / ``_refresh`` directly.
    Verify behavior: dual-cursor pair cleared, placing reset to 'A',
    refresh flag set."""
    canvas = TimeDomainCanvas()
    # Simulate dual cursor placed somewhere.
    canvas._ax = 0.3
    canvas._bx = 0.7
    canvas._placing = "B"
    canvas._refresh = False

    reset = getattr(canvas, "reset_cursor_state", None)
    assert callable(reset), (
        "TimeDomainCanvas should expose reset_cursor_state() so MainWindow "
        "does not have to mutate private cursor fields directly"
    )
    reset()

    assert canvas._ax is None
    assert canvas._bx is None
    assert canvas._placing == "A"
    assert canvas._refresh is True


def test_main_window_reset_cursors_uses_canvas_helper(qapp, qtbot):
    """Task 2 Step 3: ``MainWindow._reset_cursors`` should call the
    canvas's ``reset_cursor_state()`` (with a ``getattr`` fallback for
    the legacy direct-mutation path)."""
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    # Seed dual cursor state on the time canvas, then reset via
    # MainWindow's helper.
    w.canvas_time._ax = 0.2
    w.canvas_time._bx = 0.8
    w.canvas_time._placing = "B"
    w.canvas_time._refresh = False

    w._reset_cursors()

    assert w.canvas_time._ax is None
    assert w.canvas_time._bx is None
    assert w.canvas_time._placing == "A"
    assert w.canvas_time._refresh is True


# ---------------------------------------------------------------------------
# Task 7 — Toolbar action-key surface (design §5.4)
# ---------------------------------------------------------------------------
#
# These assertions pin the action-key set the chart-stack helpers
# (``_find_action``, ``_install_nav_shortcuts``, ``_apply_mdi_icons``,
# ``apply_chinese_toolbar_labels``) look up by ``act.data()`` /
# normalized english text. A future pyqtgraph-backed toolbar shim MUST
# expose the same six keys so the existing i18n / icon / shortcut
# wiring keeps working without further surgery in chart_stack.py.
#
# Pre-switch: these run against the matplotlib ``NavigationToolbar2QT``
# created in ``_ChartCard.__init__``. Post-switch: the same assertions
# run against whatever toolbar the TimeChartCard ends up holding.


_EXPECTED_TOOLBAR_ACTION_KEYS = ("home", "back", "forward", "pan", "zoom", "save")


def _action_keys(toolbar):
    """Return the normalized action-key set present on ``toolbar``.

    Mirrors ``chart_stack._find_action``: prefer ``act.data()`` (i18n-
    stable, set by ``apply_chinese_toolbar_labels``), fall back to
    lowercased ``act.text()``.
    """
    keys = []
    for act in toolbar.actions():
        if act.data():
            keys.append(str(act.data()).strip().lower())
        elif act.text():
            keys.append(act.text().strip().lower())
    return keys


def test_time_chart_card_toolbar_exposes_expected_action_keys(qapp):
    """Design §5.4: the time-chart card toolbar MUST expose the six
    navigation action keys ``home``/``back``/``forward``/``pan``/
    ``zoom``/``save`` so the Chinese i18n layer, MDI icon pass, and
    ``Alt+R/Z/Shift+Z/G/B`` shortcuts can locate each action by key.
    Pins the surface contract a future pyqtgraph-toolbar shim must
    honor.
    """
    canvas = TimeDomainCanvas()
    card = TimeChartCard(canvas)
    present = _action_keys(card.toolbar)
    for key in _EXPECTED_TOOLBAR_ACTION_KEYS:
        assert key in present, (
            f"toolbar action {key!r} missing from time-chart card; "
            f"found keys: {present!r}"
        )


def test_time_chart_card_toolbar_action_keys_ordering_pan_before_zoom(qapp):
    """Pan must come before Zoom in the toolbar so users reach the
    default (pan) tool first when scanning left-to-right. This pins the
    matplotlib default ordering (home, back, forward, pan, zoom, ...,
    save) — the shim must produce the same order so the visual chrome
    matches before/after the renderer swap.
    """
    canvas = TimeDomainCanvas()
    card = TimeChartCard(canvas)
    present = _action_keys(card.toolbar)
    expected_in_order = ["home", "back", "forward", "pan", "zoom", "save"]
    seen_positions = [
        present.index(k) for k in expected_in_order if k in present
    ]
    assert seen_positions == sorted(seen_positions), (
        f"toolbar action keys appear out of expected order: {present!r} "
        f"(positions for {expected_in_order!r}: {seen_positions!r})"
    )


# ---------------------------------------------------------------------------
# Task 7 — Copy-image action present + composites cursor pill
# ---------------------------------------------------------------------------


def test_time_chart_card_has_copy_image_button(qapp):
    """Design §5.4: the chart card's ``_copy_btn`` must exist as a
    QToolButton wired through ``copy_image_requested``. The button
    survives the renderer swap because it is a sibling widget inserted
    into ``self.toolbar``, not part of the matplotlib navigation
    actions.
    """
    from PyQt5.QtWidgets import QToolButton

    canvas = TimeDomainCanvas()
    card = TimeChartCard(canvas)
    btn = getattr(card, "_copy_btn", None)
    assert btn is not None, "TimeChartCard must expose _copy_btn"
    assert isinstance(btn, QToolButton)
    # Tooltip describes the cursor-pill composite behavior so users
    # know the screenshot includes the floating readout.
    assert "复制" in btn.toolTip()


def test_chart_stack_copy_card_image_composites_cursor_pill(qapp):
    """Behavior contract: ``ChartStack._copy_card_image`` composites the
    floating cursor pill onto the captured pixmap when the active card
    is the time card and the pill is visible. Pin the public hooks
    (signal name, method name) so the renderer swap can't silently
    break the clipboard contract.
    """
    cs = ChartStack()

    # The image-copied signal carries a status string for MainWindow's
    # status bar. Pin its signature so the bus stays compatible.
    bound = cs.image_copied
    raw = bound.signal.lstrip("0123456789")
    assert raw == "image_copied(QString)"

    # The method exists and is callable.
    assert callable(getattr(cs, "_copy_card_image", None))
    # The card path exposes the canvas as ``card.canvas`` — used by the
    # copy-image flow to call ``canvas.grab()``. Same attribute name on
    # the future PG card, since it inherits ``_ChartCard``.
    assert cs._time_card.canvas is cs.canvas_time

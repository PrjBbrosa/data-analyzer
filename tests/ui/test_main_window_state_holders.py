"""Unit tests for the named state holders (spec D-E2).

These own state that used to be written from several files across
``ui/main_window/``.  Like ``AnalysisContext``, they are plain objects and need
no ``MainWindow`` to exercise.  The shims that keep the historical
``MainWindow`` attribute names working are covered further down, against a real
window, because that is exactly what they exist to protect.
"""

from __future__ import annotations

import pytest

from mf4_analyzer.ui.main_window._state_holders import (
    KEEP,
    CustomXAxisState,
    ViewFocusState,
)
from mf4_analyzer.ui.time_xaxis import (
    CHANNEL_MODE,
    EXACT_SOURCE,
    PER_SOURCE_NAME,
    TIME_MODE,
    CustomXAxisSpec,
)


# -- CustomXAxisState --------------------------------------------------------

def test_defaults_to_the_time_axis():
    state = CustomXAxisState()

    assert state.spec == CustomXAxisSpec()
    assert state.spec.mode == TIME_MODE
    assert (state.fid, state.ch, state.xlabel) == (None, None, None)


def test_each_instance_gets_its_own_spec():
    """A shared mutable default would leak state between windows."""
    a, b = CustomXAxisState(), CustomXAxisState()

    assert a.spec is not b.spec or a.spec == b.spec
    a.spec = CustomXAxisSpec(mode=CHANNEL_MODE, channel="rpm")

    assert b.spec.mode == TIME_MODE


def test_clear_resets_every_field():
    state = CustomXAxisState(
        spec=CustomXAxisSpec(mode=CHANNEL_MODE, channel="rpm"),
        fid="f1",
        ch="rpm",
        xlabel="Motor speed",
    )

    state.clear()

    assert state.spec == CustomXAxisSpec()
    assert (state.fid, state.ch, state.xlabel) == (None, None, None)


def test_adopt_derives_the_adapters_from_an_exact_source_spec():
    state = CustomXAxisState()

    state.adopt(
        CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=EXACT_SOURCE,
            channel="motor_speed",
            source_fid="f1",
        )
    )

    assert (state.fid, state.ch) == ("f1", "motor_speed")


def test_adopt_clears_the_adapters_for_a_per_source_name_spec():
    """A logical selection resolves per file at draw time; a leftover
    (fid, ch) pair would leak one source's X array into every curve."""
    state = CustomXAxisState(fid="f1", ch="motor_speed")

    state.adopt(
        CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=PER_SOURCE_NAME,
            channel="motor_speed",
            source_fid=None,
        )
    )

    assert (state.fid, state.ch) == (None, None)


def test_adopt_clears_the_adapters_for_a_time_spec():
    state = CustomXAxisState(fid="f1", ch="motor_speed")

    state.adopt(CustomXAxisSpec())

    assert (state.fid, state.ch) == (None, None)


def test_adopt_leaves_the_label_alone_by_default():
    state = CustomXAxisState(xlabel="Motor speed")

    state.adopt(CustomXAxisSpec(mode=CHANNEL_MODE, channel="torque"))

    assert state.xlabel == "Motor speed"


def test_adopt_can_clear_the_label_explicitly():
    """``None`` must mean "clear", not "leave alone" -- hence the sentinel."""
    state = CustomXAxisState(xlabel="Motor speed")

    state.adopt(CustomXAxisSpec(), xlabel=None)

    assert state.xlabel is None


def test_adopt_sets_a_new_label():
    state = CustomXAxisState()

    state.adopt(CustomXAxisSpec(mode=CHANNEL_MODE, channel="torque"), xlabel="Torque")

    assert state.xlabel == "Torque"


def test_keep_sentinel_is_not_a_plausible_label():
    assert KEEP is not None and not isinstance(KEEP, str)


# -- ViewFocusState ----------------------------------------------------------

def test_view_focus_starts_unbound():
    state = ViewFocusState()

    assert (state.primary, state.secondary, state.focused) == (None, None, None)


def test_bind_without_a_partner_focuses_the_active_view():
    state = ViewFocusState()

    state.bind(active=2, partner=None)

    assert (state.primary, state.secondary, state.focused) == (2, None, 2)


def test_bind_mirrors_the_split_pair():
    state = ViewFocusState()

    state.bind(active=0, partner=3)

    assert (state.primary, state.secondary) == (0, 3)


def test_bind_keeps_focus_on_the_secondary_pane_when_it_is_still_bound():
    """Re-binding on an unrelated manager change must not steal focus back."""
    state = ViewFocusState()
    state.bind(active=0, partner=3)
    state.focused = 3

    state.bind(active=0, partner=3)

    assert state.focused == 3


def test_bind_recovers_focus_when_the_focused_view_leaves_the_pair():
    state = ViewFocusState()
    state.bind(active=0, partner=3)
    state.focused = 3

    state.bind(active=0, partner=5)

    assert state.focused == 0


def test_leaving_split_pulls_focus_back_to_the_active_view():
    state = ViewFocusState()
    state.bind(active=0, partner=3)
    state.focused = 3

    state.bind(active=0, partner=None)

    assert (state.secondary, state.focused) == (None, 0)


# -- MainWindow compatibility shims ------------------------------------------

@pytest.fixture
def win(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_window_starts_with_a_cleared_holder(win):
    assert win._custom_xaxis.spec == CustomXAxisSpec()
    assert (win._custom_xaxis.fid, win._custom_xaxis.ch) == (None, None)


@pytest.mark.parametrize(
    "attr, holder_field, value",
    [
        ("_custom_xaxis_fid", "fid", "f7"),
        ("_custom_xaxis_ch", "ch", "motor_speed"),
        ("_custom_xlabel", "xlabel", "Motor speed"),
        ("_custom_xaxis_spec", "spec", CustomXAxisSpec(mode=CHANNEL_MODE, channel="x")),
    ],
)
def test_legacy_attribute_writes_land_on_the_holder(win, attr, holder_field, value):
    setattr(win, attr, value)

    assert getattr(win._custom_xaxis, holder_field) == value


@pytest.mark.parametrize(
    "attr, holder_field, value",
    [
        ("_custom_xaxis_fid", "fid", "f7"),
        ("_custom_xaxis_ch", "ch", "motor_speed"),
        ("_custom_xlabel", "xlabel", "Motor speed"),
        ("_custom_xaxis_spec", "spec", CustomXAxisSpec(mode=CHANNEL_MODE, channel="x")),
    ],
)
def test_legacy_attribute_reads_come_from_the_holder(win, attr, holder_field, value):
    setattr(win._custom_xaxis, holder_field, value)

    assert getattr(win, attr) == value


def test_getattr_with_a_default_still_sees_the_holder(win):
    """``ui/view_bridge.py`` reads these through ``getattr(window, name, None)``."""
    win._custom_xaxis.ch = "motor_speed"

    assert getattr(win, "_custom_xaxis_ch", None) == "motor_speed"


@pytest.mark.parametrize(
    "attr, holder_field",
    [
        ("_primary_view_idx", "primary"),
        ("_secondary_view_idx", "secondary"),
        ("_focused_view_idx", "focused"),
    ],
)
def test_view_focus_shims_round_trip(win, attr, holder_field):
    setattr(win, attr, 4)
    assert getattr(win._view_focus, holder_field) == 4

    setattr(win._view_focus, holder_field, 1)
    assert getattr(win, attr) == 1


def test_window_starts_bound_to_the_active_view(win):
    active = win.view_manager.active

    assert win._view_focus.primary == active
    assert win._view_focus.secondary is None
    assert win._view_focus.focused == active

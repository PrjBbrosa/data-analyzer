"""Lifetime contracts for queued events from Inspector preset buttons."""
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.inspector_sections.presets import PresetBar


def test_preset_bar_ignores_a_late_button_event_after_teardown_state_is_gone(qtbot):
    """A queued Leave must not call a torn-down bar through an event filter."""
    bar = PresetBar("test", lambda: {}, lambda _params: None)
    qtbot.addWidget(bar)
    button = bar._load_btns[1]
    bar.show()

    # Qt can dispatch an already-queued Enter/Leave/Resize while the Python
    # wrapper is being torn down, after its instance attributes are gone.
    del bar._load_btns

    assert QApplication.sendEvent(button, QEvent(QEvent.Leave)) is True


def test_preset_load_button_preserves_hover_card_behavior(qtbot):
    bar = PresetBar("test", lambda: {"nfft": "2048"}, lambda _params: None)
    qtbot.addWidget(bar)
    button = bar._load_btns[1]
    bar._write(1, "预设", {"nfft": "2048"})
    bar._refresh_states()
    bar.resize(300, 32)
    bar.show()
    QApplication.processEvents()

    button.enterEvent(QEvent(QEvent.Enter))
    assert bar._hover_card.isVisible()

    button.leaveEvent(QEvent(QEvent.Leave))
    assert not bar._hover_card.isVisible()
    bar._delete(1)


def test_preset_bar_hide_ignores_a_destroyed_hover_card(qtbot):
    """Hiding the bar must not dereference a hover card Qt already deleted."""
    bar = PresetBar("test", lambda: {"nfft": "2048"}, lambda _params: None)
    qtbot.addWidget(bar)
    button = bar._load_btns[1]
    bar._write(1, "预设", {"nfft": "2048"})
    bar._refresh_states()
    bar.resize(300, 32)
    bar.show()
    QApplication.processEvents()

    button.enterEvent(QEvent(QEvent.Enter))
    card = bar._hover_card
    assert card.isVisible()

    sip.delete(card)
    assert sip.isdeleted(card)

    bar.hide()
    assert bar._hover_slot is None
    assert bar._hover_card is None
    bar._delete(1)


def test_contextual_segmented_choices_are_destroyed_with_their_owner(qapp):
    from mf4_analyzer.ui.inspector_sections import (
        FFTContextual,
        FFTTimeContextual,
        OrderContextual,
    )

    cases = (
        (FFTContextual, "_fft_section", ("choice_amp_y", "choice_weighting")),
        (FFTTimeContextual, "_tf_section", ("choice_weighting", "choice_amp_unit")),
        (
            OrderContextual,
            "_order_section",
            ("choice_rpm_mode", "choice_weighting", "choice_amp_unit"),
        ),
    )
    for context_type, section_name, choice_names in cases:
        context = context_type()
        choices = [getattr(context, name) for name in choice_names]
        combos = [choice.bound_combo() for choice in choices]
        groups = [choice._group for choice in choices]
        buttons = [button for choice in choices for button in choice.buttons()]

        getattr(context, section_name).set_expanded(True)
        context.resize(360, 760)
        context.show()
        qapp.processEvents()

        context.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()

        assert sip.isdeleted(context)
        assert all(sip.isdeleted(choice) for choice in choices)
        assert all(sip.isdeleted(combo) for combo in combos)
        assert all(sip.isdeleted(group) for group in groups)
        assert all(sip.isdeleted(button) for button in buttons)

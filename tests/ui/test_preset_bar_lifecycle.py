"""Lifetime contracts for queued events from Inspector preset buttons."""
import copy

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.inspector_sections import FFTContextual
from mf4_analyzer.ui.inspector_sections.preset_state import (
    PRESET_SOURCE_UNKNOWN_NOTE,
    PRESET_SOURCE_UPDATED_NOTE,
    PRESET_SOURCE_UNAVAILABLE_NOTE,
    build_preset_baseline,
)
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


def test_restored_baseline_detects_same_name_slot_rewrite(qtbot, monkeypatch):
    import copy
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    from mf4_analyzer.ui.inspector_sections.preset_state import (
        PRESET_SOURCE_UPDATED_NOTE,
    )

    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, "_confirm_axis_preservation", lambda *a, **kw: "preset")
    bar._load(1)
    old = bar.baseline()
    assert old["version"] == 2
    params = dict(bar._effective_payload(1), window="hamming")
    bar._write(1, old["display_name"], params)
    assert bar._slot_source_changed(1)
    assert bar._baseline_source_note(1) == PRESET_SOURCE_UPDATED_NOTE
    bar.set_baseline(copy.deepcopy(old))
    assert bar._slot_source_changed(1)
    assert bar._baseline_source_note(1) == PRESET_SOURCE_UPDATED_NOTE
    assert not bar._is_noop_reapply(1)


def test_v1_unknown_source_allows_reload_after_restore(qtbot, monkeypatch):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    from mf4_analyzer.ui.inspector_sections.preset_state import (
        PRESET_SOURCE_UNKNOWN_NOTE,
        build_preset_baseline,
    )

    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, "_confirm_axis_preservation", lambda *a, **kw: "preset")
    bar._load(1)
    current = ctx._collect_preset()
    v1 = build_preset_baseline("fft", 1, bar._slot_display_name(1), current)
    bar.set_baseline(v1)
    assert bar.baseline()["version"] == 1
    assert "source_payload" not in bar.baseline()
    assert bar._baseline_source_note(1) == PRESET_SOURCE_UNKNOWN_NOTE
    assert "来源版本未知" in bar._load_btns[1].accessibleDescription()
    assert not bar._is_noop_reapply(1)
    loads = []
    original_apply = bar._apply

    def wrapped(params):
        loads.append(dict(params))
        return original_apply(params)

    monkeypatch.setattr(bar, "_apply", wrapped)
    bar._on_left_click(1)
    assert loads


def test_rename_clear_and_restore_builtin_mark_source_change(qtbot, monkeypatch):
    from mf4_analyzer.ui.inspector_sections import FFTContextual
    from mf4_analyzer.ui.inspector_sections.preset_state import (
        PRESET_SOURCE_UNAVAILABLE_NOTE,
        PRESET_SOURCE_UPDATED_NOTE,
    )

    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, "_confirm_axis_preservation", lambda *a, **kw: "preset")
    bar._save(4)
    assert bar.baseline()["slot"] == 4
    bar._write(4, "改名后", bar._read(4)[1])
    bar.sync_match()
    assert bar._baseline_source_note(4) == PRESET_SOURCE_UPDATED_NOTE

    bar._delete(4)
    bar.sync_match()
    assert bar._baseline_source_note(4) == PRESET_SOURCE_UNAVAILABLE_NOTE
    assert bar._selected_slot is None

    bar._load(1)
    snapshot = dict(bar._effective_payload(1), overlap=11)
    bar._write(1, bar._slot_display_name(1), snapshot)
    bar.sync_match()
    assert bar._baseline_source_note(1) == PRESET_SOURCE_UPDATED_NOTE
    bar._reset_to_default(1)
    bar.sync_match()
    assert bar._baseline_source_note(1) == ""


def test_two_views_do_not_share_mutable_baseline(qtbot, monkeypatch):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    first = FFTContextual()
    second = FFTContextual()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    monkeypatch.setattr(
        first.preset_bar, "_confirm_axis_preservation", lambda *a, **kw: "preset",
    )
    first.preset_bar._load(2)
    second.preset_bar.set_baseline(first.preset_bar.baseline())
    assert second.preset_bar.baseline() == first.preset_bar.baseline()
    second.preset_bar.baseline()["params"]["window"] = "mutated"
    first.preset_bar._baseline["params"]["window"] = "changed-in-place"
    assert second.preset_bar._baseline["params"]["window"] != "changed-in-place"
    assert first.preset_bar.baseline()["params"]["window"] == "changed-in-place"


def test_empty_collect_is_not_a_successful_baseline(qtbot):
    from mf4_analyzer.ui.inspector_sections.presets import PresetBar

    bar = PresetBar("fft", lambda: {}, lambda _params: None)
    qtbot.addWidget(bar)
    committed = []
    bar.preset_committed.connect(committed.append)
    bar._save(4)
    assert bar.baseline() is None
    bar._commit_loaded_slot(4, {}, {"window": "hanning"})
    assert bar.baseline() is None
    assert committed == []


def _fft_bar(qtbot, monkeypatch):
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, "_confirm_axis_preservation", lambda *a, **kw: "preset")
    return ctx, bar


def test_successful_load_emits_one_preset_committed(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar_seen = []
    ctx_seen = []
    bar.preset_committed.connect(bar_seen.append)
    ctx.preset_committed.connect(ctx_seen.append)
    bar._load(1)
    assert len(bar_seen) == 1
    assert len(ctx_seen) == 1
    assert bar_seen[0]["slot"] == 1
    assert bar_seen[0]["version"] == 2
    assert ctx_seen[0]["slot"] == 1


def test_same_params_different_source_emits_preset_committed(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    current = ctx._collect_preset()
    bar._write(4, "identical", current)
    seen = []
    bar.preset_committed.connect(seen.append)
    bar._load(4)
    assert len(seen) == 1
    assert bar.baseline()["slot"] == 4
    assert bar.baseline()["display_name"] == "identical"


def test_different_params_load_emits_once(qtbot, monkeypatch):
    _ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    first = bar.baseline()
    seen = []
    bar.preset_committed.connect(seen.append)
    bar._load(2)
    assert len(seen) == 1
    assert bar.baseline()["slot"] == 2
    assert bar.baseline()["params"] != first["params"]


def test_updated_same_slot_is_not_noop_and_emits(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    payload = dict(bar._effective_payload(1), window="hamming")
    bar._write(1, bar._slot_display_name(1), payload)
    assert not bar._is_noop_reapply(1)
    seen = []
    bar.preset_committed.connect(seen.append)
    bar._on_left_click(1)
    assert len(seen) == 1
    assert ctx._collect_preset()["window"] == "hamming"


def test_identical_known_current_slot_is_noop(qtbot, monkeypatch):
    _ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    seen = []
    bar.preset_committed.connect(seen.append)
    bar._on_left_click(1)
    assert seen == []
    assert bar.baseline()["slot"] == 1


def test_save_as_new_baseline_emits_preset_committed(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    ctx.combo_win.setCurrentText("hamming")
    seen = []
    bar.preset_committed.connect(seen.append)
    bar._save(4)
    assert len(seen) == 1
    assert bar.baseline()["slot"] == 4
    assert bar.baseline()["params"]["window"] == "hamming"


def test_global_slot_write_without_load_does_not_emit(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    seen = []
    bar.preset_committed.connect(seen.append)
    bar._write(4, "idle", ctx._collect_preset())
    assert seen == []
    assert bar.baseline()["slot"] == 1


def test_set_baseline_and_cancel_do_not_emit(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    old = copy.deepcopy(bar.baseline())
    before = ctx._collect_preset()
    seen = []
    bar.preset_committed.connect(seen.append)
    bar.set_baseline(copy.deepcopy(old))
    assert seen == []

    ctx.chk_x_auto.setChecked(False)
    ctx.spin_x_min.setValue(1)
    ctx.spin_x_max.setValue(5)
    monkeypatch.setattr(bar, "_confirm_axis_preservation", lambda *a, **kw: "cancel")
    bar._load(2)
    assert seen == []
    assert bar.baseline() == old
    assert ctx.chk_x_auto.isChecked() is False
    assert ctx.spin_x_min.value() == 1
    assert ctx.spin_x_max.value() == 5
    assert before["window"] == ctx._collect_preset()["window"]


def test_apply_failure_rolls_back_and_does_not_emit(qtbot, monkeypatch):
    ctx, bar = _fft_bar(qtbot, monkeypatch)
    bar._load(1)
    before_baseline = copy.deepcopy(bar.baseline())
    before_params = ctx._collect_preset()
    seen = []
    errors = []
    bar.preset_committed.connect(seen.append)
    bar.acknowledged.connect(lambda level, msg: errors.append((level, msg)))

    def boom(_params):
        raise RuntimeError("injected apply failure")

    monkeypatch.setattr(bar, "_apply", boom)
    bar._load(2)
    assert seen == []
    assert bar.baseline() == before_baseline
    assert ctx._collect_preset() == before_params
    assert errors and errors[-1][0] == "error"
    assert "injected apply failure" in errors[-1][1]

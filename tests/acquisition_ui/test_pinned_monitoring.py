"""spec 2026-07-08 §G6: 采集通道 != 实时显示通道。"""

from can_logger.p0.a2l_probe import MeasurementSummary

from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import CockpitState


def _pool(n=12):
    return tuple(
        MeasurementSummary(
            name=f"Sig_{i:02d}",
            address=0x40000000 + 4 * i,
            datatype="UWORD",
            unit="",
            conversion="",
            available_events=("event_10ms",),
        )
        for i in range(n)
    )


class _SpyBackend(FakeRecorderBackend):
    def __init__(self):
        super().__init__()
        self.start_calls = 0

    def start(self, selected):
        self.start_calls += 1
        super().start(selected)


def _idle_window(qtbot, backend=None, n=12):
    window = CockpitMainWindow(
        backend=backend or FakeRecorderBackend(),
        initial_pool=_pool(n),
        allow_fake_backend=True,
    )
    qtbot.addWidget(window)
    for i in range(n):
        window.left_pane._set_measurement_selected(f"Sig_{i:02d}", True)
    window._begin_connection_attempt()
    qtbot.wait(20)
    window._poll_live()
    window._poll_health()
    assert window.state_machine.state == CockpitState.CONNECTED_IDLE
    return window


def test_default_pin_caps_cards_at_five(qtbot):
    window = _idle_window(qtbot)
    assert sorted(window._center.cards) == [f"Sig_{i:02d}" for i in range(5)]
    bar = window._center._summary_bar
    assert not bar.isHidden()
    assert bar.text() == "已选 12 · 实时显示 5 · 其余通道仍会录制"
    window.close()


def test_small_selection_keeps_legacy_behavior(qtbot):
    window = _idle_window(qtbot, n=3)
    assert len(window._center.cards) == 3
    assert window._center._summary_bar.isHidden()
    window.close()


def test_unpin_pin_reset_cycle(qtbot):
    window = _idle_window(qtbot)
    window.unpin_channel("Sig_02")
    assert "Sig_02" not in window._center.cards
    assert len(window._center.cards) == 4
    window.pin_channel("Sig_07")
    assert "Sig_07" in window._center.cards
    window.reset_pins()
    assert sorted(window._center.cards) == [f"Sig_{i:02d}" for i in range(5)]
    window.close()


def test_pin_ops_do_not_restart_stream(qtbot):
    backend = _SpyBackend()
    window = _idle_window(qtbot, backend=backend)
    calls_before = backend.start_calls
    window.unpin_channel("Sig_00")
    window.pin_channel("Sig_09")
    assert backend.start_calls == calls_before
    assert not window._idle_restart_timer.isActive()
    window.close()


def test_recording_config_uses_full_selection(qtbot):
    window = _idle_window(qtbot)
    config = window._build_session_config()
    assert len(config.selected) == 12
    assert len(window._center.cards) == 5
    window.close()


def test_card_menu_emits_unpin_and_reset(qtbot):
    window = _idle_window(qtbot)
    card = window._center.cards["Sig_00"]
    menu = window._center._build_card_menu(card)
    labels = [a.text() for a in menu.actions()]
    assert "取消固定实时显示" in labels
    assert "重置固定（默认前 5）" in labels

    next(a for a in menu.actions() if "取消固定" in a.text()).trigger()
    assert "Sig_00" not in window._center.cards

    remaining = next(iter(window._center.cards.values()))
    menu2 = window._center._build_card_menu(remaining)
    next(a for a in menu2.actions() if "重置固定" in a.text()).trigger()
    assert sorted(window._center.cards) == [f"Sig_{i:02d}" for i in range(5)]
    window.close()

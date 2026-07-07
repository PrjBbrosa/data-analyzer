"""T1-6 regression: Cockpit hydrates Transport from
``acquisition_config.yaml`` on startup and writes back on Settings save.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mf4_analyzer.acquisition_capture.config_store import (
    load_or_default,
    save_a2l_path,
    save_transport,
)
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def _custom_transport() -> TransportConfig:
    return TransportConfig(
        app_name="Python",
        channel=2,
        bitrate=1000000,
        can_fd=False,
        seed_and_key_dll=None,
    )


def test_no_config_path_leaves_transport_unset(qapp):
    """Default constructor: no auto-load, no crash."""

    window = CockpitMainWindow()
    try:
        assert window._transport_config is None
        assert window._config_path is None
    finally:
        window.deleteLater()


def test_config_path_without_file_leaves_transport_unset(qapp, tmp_path):
    """config_path supplied but no yaml on disk yet → no hydration,
    no crash. (Operator hasn't visited Settings yet.)"""

    config_path = tmp_path / "acquisition_config.yaml"
    window = CockpitMainWindow(config_path=config_path)
    try:
        assert window._config_path == config_path
        assert window._transport_config is None
    finally:
        window.deleteLater()


def test_config_path_with_saved_transport_hydrates_on_startup(
    qapp, tmp_path
):
    """Seed yaml with a non-default transport, construct cockpit
    pointing at it, transport must come back."""

    config_path = tmp_path / "acquisition_config.yaml"
    saved = _custom_transport()
    save_transport(saved, config_path=config_path)

    window = CockpitMainWindow(config_path=config_path)
    try:
        assert window._transport_config is not None
        assert window._transport_config.app_name == "Python"
        assert window._transport_config.channel == 2
        assert window._transport_config.bitrate == 1000000
    finally:
        window.deleteLater()


def test_persist_transport_writes_back(qapp, tmp_path):
    """Calling _persist_transport writes the value to disk; a fresh
    load_or_default returns the same transport."""

    config_path = tmp_path / "acquisition_config.yaml"
    window = CockpitMainWindow(config_path=config_path)
    try:
        new_transport = TransportConfig(
            app_name="CANoe",
            channel=3,
            bitrate=500000,
        )
        window.set_transport(new_transport)
        window._persist_transport(new_transport)

        store = load_or_default(
            project_root=config_path.parent,
            cli_config_path=config_path,
        )
        assert store.pinned is True
        assert store.transport == new_transport
    finally:
        window.deleteLater()


def test_round_trip_settings_then_restart(qapp, tmp_path):
    """End-to-end: write transport via cockpit, kill window, build a
    new one with the same config_path — value persists."""

    config_path = tmp_path / "acquisition_config.yaml"

    window1 = CockpitMainWindow(config_path=config_path)
    new_transport = TransportConfig(
        app_name="Python",
        channel=1,
        bitrate=500000,
        can_fd=True,
        data_bitrate=4000000,
    )
    window1.set_transport(new_transport)
    window1._persist_transport(new_transport)
    window1.deleteLater()

    window2 = CockpitMainWindow(config_path=config_path)
    try:
        assert window2._transport_config == new_transport
    finally:
        window2.deleteLater()


def test_corrupt_yaml_keeps_cockpit_alive(qapp, tmp_path):
    """A garbled config file must not crash the cockpit."""

    config_path = tmp_path / "acquisition_config.yaml"
    config_path.write_text("this: is: not: yaml: :::", encoding="utf-8")

    window = CockpitMainWindow(config_path=config_path)
    try:
        # No transport restored.
        assert window._transport_config is None
        # Status bar carries the failure reason.
        msg = window._status.currentMessage()
        assert "配置文件" in msg
    finally:
        window.deleteLater()


def _fake_summary(a2l_path):
    measurement = SimpleNamespace(
        name="EngSpd",
        unit="rpm",
        address=0x1000,
        available_events=("event_10ms",),
    )
    return SimpleNamespace(
        path=str(a2l_path),
        total_measurements=1,
        measurements=[measurement],
        event_capacity={"event_10ms": 1},
        measurement_events={},
        a2l_has_daq_events=True,
    )


def _stub_a2l_chain(window, monkeypatch, a2l_path):
    monkeypatch.setattr(
        "can_logger.p0.ifdata_xcp.parse_ifdata_xcp_file",
        lambda _path: (object(),),
    )
    window._load_measurement_summary = (
        lambda _path: (_fake_summary(a2l_path), None)
    )


def test_apply_a2l_persists_and_rehydrates(qtbot, tmp_path, monkeypatch):
    config_path = tmp_path / "acquisition_config.yaml"
    a2l = tmp_path / "demo.a2l"
    a2l.write_text("stubbed", encoding="utf-8")

    window1 = CockpitMainWindow(config_path=config_path, allow_fake_backend=True)
    qtbot.addWidget(window1)
    _stub_a2l_chain(window1, monkeypatch, a2l)
    window1.apply_a2l_path(a2l)
    assert str(a2l) in config_path.read_text(encoding="utf-8")

    seen = []
    window2 = CockpitMainWindow(config_path=config_path, allow_fake_backend=True)
    qtbot.addWidget(window2)
    window2.apply_a2l_path = lambda path: seen.append(Path(path))
    qtbot.wait(80)
    assert seen == [a2l]


def test_hydrate_skips_missing_a2l(qtbot, tmp_path):
    config_path = tmp_path / "acquisition_config.yaml"
    save_a2l_path(tmp_path / "gone.a2l", config_path=config_path)

    seen = []
    window = CockpitMainWindow(config_path=config_path, allow_fake_backend=True)
    qtbot.addWidget(window)
    window.apply_a2l_path = lambda path: seen.append(path)
    qtbot.wait(80)
    assert seen == []

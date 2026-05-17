"""Tests for acquisition_config.yaml v1 to v2 transport migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture.config_store import (
    CONFIG_VERSION,
    ConfigSchemaError,
    ConfigStore,
    _write_config_file,
    load_or_default,
)
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


def _load(path: Path) -> ConfigStore:
    return load_or_default(project_root=path.parent, cli_config_path=path)


def test_v1_config_loads_with_default_transport(tmp_path: Path) -> None:
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 1\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selected: []\n"
        "filter_state: {}\n"
        "threshold_overrides: {}\n",
        encoding="utf-8",
    )

    store = _load(cfg)

    assert store.version == CONFIG_VERSION
    assert store.transport == TransportConfig()


def test_v2_config_round_trip(tmp_path: Path) -> None:
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 2\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selected: []\n"
        "filter_state: {}\n"
        "threshold_overrides: {}\n"
        "transport:\n"
        '  app_name: "CANalyzer"\n'
        "  channel: 1\n"
        "  can_fd: true\n"
        "  bitrate: 1000000\n",
        encoding="utf-8",
    )

    store = _load(cfg)

    assert store.version == CONFIG_VERSION
    assert store.transport.app_name == "CANalyzer"
    assert store.transport.can_fd is True
    assert store.transport.bitrate == 1_000_000


def test_v2_transport_rejects_unknown_nested_key(tmp_path: Path) -> None:
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 2\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selected: []\n"
        "filter_state: {}\n"
        "threshold_overrides: {}\n"
        "transport:\n"
        '  appname: "CANalyzer"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigSchemaError, match="transport unknown key"):
        _load(cfg)


def test_v2_transport_rejects_invalid_channel_type(tmp_path: Path) -> None:
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 2\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selected: []\n"
        "filter_state: {}\n"
        "threshold_overrides: {}\n"
        "transport:\n"
        '  channel: "1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigSchemaError, match="transport channel must be an integer"):
        _load(cfg)


def test_save_then_load_preserves_transport(tmp_path: Path) -> None:
    cfg = tmp_path / "acquisition_config.yaml"
    store = ConfigStore(
        pinned=True,
        source_path=cfg.resolve(),
        a2l_path="x.a2l",
        favorites=[],
        selected=[],
        transport=TransportConfig(app_name="CANoe", channel=2, can_fd=True),
    )

    _write_config_file(cfg, store)
    reloaded = _load(cfg)

    assert reloaded.transport.app_name == "CANoe"
    assert reloaded.transport.channel == 2
    assert reloaded.transport.can_fd is True


def test_unknown_future_version_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 3\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selected: []\n"
        "filter_state: {}\n"
        "threshold_overrides: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigSchemaError, match="version"):
        _load(cfg)

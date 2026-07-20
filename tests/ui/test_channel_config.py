import json

import pytest
from PyQt5.QtCore import QSettings

from mf4_analyzer.ui.channel_config import (
    ChannelSelectionConfig,
    ChannelSelectionConfigStore,
    ConfigNameConflict,
    resolve_channel_config,
)


class FakeFd:
    def __init__(self, channels):
        self._channels = list(channels)

    def get_signal_channels(self):
        return list(self._channels)


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "channel-config.ini"), QSettings.IniFormat)


def test_store_creates_multiple_configs_and_casefold_detects_conflict(settings):
    store = ChannelSelectionConfigStore(
        settings,
        id_factory=iter(("a", "b")).__next__,
        now=lambda: "2026-07-20T10:00:00+00:00",
    )

    first = store.create("动力分析", ["Speed", "Torque", "Speed"])
    store.create("振动分析", ["Accel_X"])

    assert first.channel_names == ("Speed", "Torque")
    assert [config.config_id for config in store.list()] == ["a", "b"]
    with pytest.raises(ConfigNameConflict) as exc:
        store.create(" 动力分析 ", ["Temp"])
    assert exc.value.existing.config_id == "a"


def test_overwrite_preserves_identity_and_created_time(settings):
    times = iter(("created", "updated"))
    store = ChannelSelectionConfigStore(
        settings,
        id_factory=lambda: "stable-id",
        now=times.__next__,
    )
    original = store.create("动力分析", ["Speed"])

    replacement = store.overwrite(original.config_id, ["Torque", "Torque"])

    assert replacement.config_id == "stable-id"
    assert replacement.name == "动力分析"
    assert replacement.created_at == "created"
    assert replacement.updated_at == "updated"
    assert replacement.channel_names == ("Torque",)


def test_rename_and_delete_use_stable_id_and_casefold_validation(settings):
    ids = iter(("a", "b"))
    store = ChannelSelectionConfigStore(settings, id_factory=ids.__next__)
    first = store.create("动力", ["Speed"])
    store.create("振动", ["Accel"])

    renamed = store.rename(first.config_id, " 动力分析 ")
    assert renamed.config_id == "a"
    assert renamed.name == "动力分析"
    with pytest.raises(ConfigNameConflict):
        store.rename("a", "振动")

    deleted = store.delete("a")
    assert deleted.config_id == "a"
    assert store.get("a") is None


@pytest.mark.parametrize("name", ["", "   "])
def test_store_rejects_blank_names(settings, name):
    store = ChannelSelectionConfigStore(settings)

    with pytest.raises(ValueError, match="name"):
        store.create(name, ["Speed"])


def test_store_rejects_empty_channel_set(settings):
    store = ChannelSelectionConfigStore(settings)

    with pytest.raises(ValueError, match="channel"):
        store.create("空配置", [])


def test_store_ignores_corrupt_entries_but_preserves_valid_records(settings):
    valid = ChannelSelectionConfig.create(
        "valid-id",
        "有效配置",
        ["Speed"],
        now="2026-07-20T10:00:00+00:00",
    )
    settings.setValue(
        ChannelSelectionConfigStore.SETTINGS_KEY,
        json.dumps([valid.to_dict(), {"config_id": "broken"}, "not-a-record"]),
    )

    store = ChannelSelectionConfigStore(settings)

    assert store.had_corruption is True
    assert store.list() == [valid]


def test_store_mutations_roundtrip_through_qsettings(settings):
    store = ChannelSelectionConfigStore(
        settings,
        id_factory=lambda: "persisted-id",
        now=lambda: "2026-07-20T10:00:00+00:00",
    )
    store.create("动力分析", ["Speed", "Torque"])

    reopened = ChannelSelectionConfigStore(settings)

    assert reopened.had_corruption is False
    assert reopened.get("persisted-id").channel_names == ("Speed", "Torque")


def test_resolver_matches_every_attached_file_by_exact_raw_name():
    config = ChannelSelectionConfig.create(
        "cfg", "动力", ["Speed", "Torque"], now="now"
    )
    files = {
        "f0": FakeFd(["Speed", "Torque", "speed"]),
        "f1": FakeFd(["Speed", "Temp"]),
        "f2": FakeFd(["Torque"]),
    }

    result = resolve_channel_config(config, ["f0", "f1"], files)

    assert result.matched == (
        ("f0", "Speed"),
        ("f0", "Torque"),
        ("f1", "Speed"),
    )
    assert result.missing_names == ()
    assert result.target_file_count == 2


def test_resolver_reports_missing_names_and_skips_missing_or_unattached_files():
    config = ChannelSelectionConfig.create(
        "cfg", "动力", ["Speed", "Missing"], now="now"
    )
    files = {
        "f0": FakeFd(["Speed"]),
        "f1": FakeFd(["Missing"]),
    }

    result = resolve_channel_config(config, ["missing-fid", "f0"], files)

    assert result.matched == (("f0", "Speed"),)
    assert result.missing_names == ("Missing",)
    assert result.target_file_count == 1

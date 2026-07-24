import json

import pytest

from mf4_analyzer.ui.channel_config import ChannelSelectionConfig
from mf4_analyzer.ui.channel_config_transfer import (
    MAX_TRANSFER_BYTES,
    TRANSFER_FORMAT,
    TRANSFER_VERSION,
    merge_import,
    parse_transfer,
    serialize_transfer,
)


def _config(config_id, name, channels, units=None):
    return ChannelSelectionConfig.create(
        config_id, name, channels, now="now", channel_unit_hints=units or {}
    )


def test_transfer_round_trip_keeps_only_portable_unicode_facts():
    payload = serialize_transfer([_config("local-id", "转向基础", ["Torque"], {"Torque": "Nm"})], exported_at="now")
    raw = json.loads(payload)

    assert raw == {
        "format": TRANSFER_FORMAT,
        "version": TRANSFER_VERSION,
        "exported_at": "now",
        "configs": [{"name": "转向基础", "channels": [{"name": "Torque", "unit": "Nm"}]}],
    }
    parsed = parse_transfer(payload)
    assert parsed.configs[0].channel_names == ("Torque",)
    assert parsed.configs[0].unit_hint("Torque") == "Nm"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        json.dumps({"format": "wrong", "version": 1, "configs": [{}]}).encode(),
        json.dumps({"format": TRANSFER_FORMAT, "version": 2, "configs": [{}]}).encode(),
        json.dumps({"format": TRANSFER_FORMAT, "version": 1, "configs": []}).encode(),
    ],
)
def test_transfer_rejects_invalid_envelopes(payload):
    with pytest.raises(ValueError):
        parse_transfer(payload)


def test_transfer_rejects_oversized_payload():
    with pytest.raises(ValueError, match="2 MiB"):
        parse_transfer(b"x" * (MAX_TRANSFER_BYTES + 1))


def test_transfer_deduplicates_channels_by_first_seen_name():
    payload = json.dumps(
        {
            "format": TRANSFER_FORMAT,
            "version": TRANSFER_VERSION,
            "configs": [
                {
                    "name": "配置",
                    "channels": [
                        {"name": "A", "unit": "V"},
                        {"name": "A", "unit": "mV"},
                        {"name": "B", "unit": "A"},
                    ],
                }
            ],
        },
        ensure_ascii=False,
    ).encode()

    parsed = parse_transfer(payload)
    assert parsed.configs[0].channel_names == ("A", "B")
    assert parsed.configs[0].unit_hint("A") == "V"


@pytest.mark.parametrize(
    ("mode", "names", "ids"),
    [
        ("keep", ["动力", "动力（导入）"], ["old", "new"]),
        ("replace", ["动力"], ["old"]),
        ("skip", ["动力"], ["old"]),
    ],
)
def test_import_conflict_modes_have_stable_identity(mode, names, ids):
    current = _config("old", "动力", ["Speed"])
    incoming = parse_transfer(
        serialize_transfer([_config("outside", "动力", ["Torque"])])
    ).configs

    result = merge_import([current], incoming, conflict_mode=mode, id_factory=lambda: "new")

    assert [config.name for config in result.drafts] == names
    assert [config.config_id for config in result.drafts] == ids
    if mode == "replace":
        assert result.drafts[0].channel_names == ("Torque",)

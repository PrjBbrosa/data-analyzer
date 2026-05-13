import json

import pytest

from mf4_analyzer.acquisition.signals import (
    VehicleSignalMapping,
    load_vehicle_mapping,
    resolve_standard_signals,
)


def test_resolve_standard_signals_maps_available_raw_channels(tmp_path):
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "X04C.json").write_text(
        json.dumps(
            {
                "vehicle": "X04C",
                "aliases": {
                    "vehicle_speed": [
                        "Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16",
                        "VehSpdAvg",
                    ],
                    "torsion_bar_torque": ["Rte_TAS_mTorsionBarTorque_xds16"],
                },
            }
        ),
        encoding="utf-8",
    )

    mapping = load_vehicle_mapping(root, "X04C")
    assert isinstance(mapping, VehicleSignalMapping)
    resolved = resolve_standard_signals(
        ["Time", "Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16"],
        mapping,
    )

    assert resolved == {"vehicle_speed": "Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16"}


def test_resolve_standard_signals_uses_first_matching_alias(tmp_path):
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {
                "vehicle": "CAR",
                "aliases": {"vehicle_speed": ["CAR_PrimarySpeed", "CAR_BackupSpeed"]},
            }
        ),
        encoding="utf-8",
    )

    mapping = load_vehicle_mapping(root, "CAR")
    resolved = resolve_standard_signals(
        ["CAR_PrimarySpeed", "CAR_BackupSpeed"], mapping
    )

    assert resolved == {"vehicle_speed": "CAR_PrimarySpeed"}


def test_load_vehicle_mapping_rejects_non_list_alias(tmp_path):
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {"vehicle": "CAR", "aliases": {"vehicle_speed": "not-a-list"}}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="aliases.vehicle_speed must be a list"):
        load_vehicle_mapping(root, "CAR")


def test_load_vehicle_mapping_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_vehicle_mapping(tmp_path / "signals", "DOES_NOT_EXIST")

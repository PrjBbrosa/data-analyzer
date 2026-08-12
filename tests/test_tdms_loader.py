import numpy as np
import pytest
from nptdms import ChannelObject, TdmsWriter

from mf4_analyzer.io.loader import DataLoader


pytestmark = pytest.mark.filterwarnings(
    "ignore:Setting the dtype on a NumPy array has been deprecated:DeprecationWarning"
)


def _write_waveform_tdms(path):
    properties = {
        "wf_increment": 0.25,
        "wf_start_offset": 1.5,
    }
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject(
                "Powertrain", "Speed", np.array([1000.0, 1100.0, 1200.0]),
                {**properties, "unit_string": "rpm"},
            ),
            ChannelObject(
                "Chassis", "Speed", np.array([10.0, 11.0, 12.0]),
                {**properties, "unit_string": "km/h"},
            ),
            ChannelObject(
                "Powertrain", "Label", np.array(["idle", "run", "run"]),
                properties,
            ),
        ])


def test_load_tdms_uses_waveform_timing_and_qualifies_duplicate_channels(tmp_path):
    path = tmp_path / "waveform.tdms"
    _write_waveform_tdms(path)

    data, channels, units, fs, smeta = DataLoader.load_tdms(path)

    assert channels[0] == "Time"
    assert set(channels[1:]) == {"Powertrain.Speed", "Chassis.Speed"}
    np.testing.assert_allclose(data["Time"], [1.5, 1.75, 2.0])
    np.testing.assert_allclose(data["Powertrain.Speed"], [1000.0, 1100.0, 1200.0])
    np.testing.assert_allclose(data["Chassis.Speed"], [10.0, 11.0, 12.0])
    assert units == {"Powertrain.Speed": "rpm", "Chassis.Speed": "km/h"}
    assert fs is None
    assert smeta["source_kind"] == "tdms"
    assert any(
        isinstance(s, dict) and s.get("reason") == "non-numeric"
        for s in smeta["skipped_channels"]
    )
    assert smeta["renamed_channels"]
    assert all(
        r["original"] == "Speed" for r in smeta["renamed_channels"]
    )


def test_load_tdms_rejects_numeric_data_without_waveform_timing(tmp_path):
    path = tmp_path / "untimed.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject("Group", "Signal", np.array([1.0, 2.0, 3.0])),
        ])

    with pytest.raises(ValueError, match="timing metadata"):
        DataLoader.load_tdms(path)

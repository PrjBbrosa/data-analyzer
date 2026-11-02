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


@pytest.mark.parametrize("properties", [{}, {"wf_increment": 0.}, {"wf_increment": -1.},
                                       {"wf_increment": 1., "wf_start_offset": 1e308}])
def test_load_tdms_keeps_good_channel_when_other_time_is_unusable(tmp_path, properties):
    path = tmp_path / "mixed.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject("A", "Speed", np.array([1., 2., 3.]), {"wf_increment": .1}),
            ChannelObject("B", "Speed", np.arange(6.), properties),
        ])
    data, channels, _, _, metadata = DataLoader.load_tdms(path)
    assert channels == ["Time", "A.Speed"]
    np.testing.assert_allclose(data["Time"], [0., .1, .2])
    np.testing.assert_allclose(data["A.Speed"], [1., 2., 3.])
    assert metadata["import_diagnostics"]["state"] == "partial"
    issue = next(i for i in metadata["import_diagnostics"]["issues"] if i["code"] == "invalid_channel_time")
    assert issue["group"] == "B" and issue["channel"] == "Speed"


def test_load_tdms_does_not_extend_no_overlap_or_single_point_channels(tmp_path):
    path = tmp_path / "coverage.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject("G", "Good", np.array([1., 2., 3.]), {"wf_increment": .1}),
            ChannelObject("G", "Away", np.array([8., 9.]), {"wf_increment": .1, "wf_start_offset": 5.}),
            ChannelObject("G", "Single", np.array([7.]), {"wf_increment": .1}),
        ])
    data, channels, _, _, metadata = DataLoader.load_tdms(path)
    assert channels == ["Time", "Good"]
    assert len(data) == 3
    assert {i["code"] for i in metadata["import_diagnostics"]["issues"]} >= {"no_time_overlap", "single_sample"}


def test_load_tdms_reports_resampling_and_endpoint_fill(tmp_path):
    path = tmp_path / "aligned.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject("G", "Good", np.array([1., 2., 3., 4.]), {"wf_increment": .1}),
            ChannelObject("G", "Short", np.array([10., 20.]), {"wf_increment": .1, "wf_start_offset": .1}),
        ])
    data, _, _, _, metadata = DataLoader.load_tdms(path)
    np.testing.assert_allclose(data["Short"], [10., 10., 20., 20.])
    issue = next(i for i in metadata["import_diagnostics"]["issues"] if i["code"] == "resampled_channel")
    assert issue["endpoint_fill_count"] == 2


def test_load_tdms_single_sample_keeps_declared_sampling_rate(tmp_path):
    from mf4_analyzer.io.file_data import FileData

    path = tmp_path / "single.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([ChannelObject("G", "Value", np.array([7.]),
                                           {"wf_increment": .25, "wf_start_offset": 3.})])
    data, channels, units, fs, metadata = DataLoader.load_tdms(path)
    fd = FileData(str(path), data, channels, units, fs=fs, source_metadata=metadata)
    assert fd.fs == 4.
    assert fd.time_array.tolist() == [3.]


def test_tdms_reserved_time_rename_does_not_overwrite_an_existing_channel(tmp_path):
    path = tmp_path / "collision.tdms"
    with TdmsWriter(path) as writer:
        writer.write_segment([
            ChannelObject("G", "Time [2]", np.array([11., 12.]), {"wf_increment": 1.}),
            ChannelObject("G", "Time", np.array([21., 22.]), {"wf_increment": 1.}),
        ])
    data, channels, _, _, metadata = DataLoader.load_tdms(path)
    assert len(channels) == 3 and len(set(channels)) == 3
    np.testing.assert_allclose(data["Time [2]"], [11., 12.])
    assert any(np.array_equal(data[col], [21., 22.]) for col in channels[1:])
    assert metadata["import_diagnostics"]["counts"]["imported_channels"] == 2

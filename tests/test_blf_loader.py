"""DataLoader.load_blf — Vector BLF (raw CAN) import.

With a DBC, frames decode into named physical signals; without one, payload
bytes surface per CAN id. A2L is never involved (plain CAN → DBC).
"""
import numpy as np
import pytest
from types import SimpleNamespace

can = pytest.importorskip("can", reason="python-can not installed (win32-gated)")
cantools = pytest.importorskip("cantools", reason="cantools not installed")

from mf4_analyzer.io.loader import DataLoader  # noqa: E402
from tests._helpers.blf_factory import (  # noqa: E402
    write_engine_only_dbc,
    write_raw_blf,
    write_sample_blf,
    write_two_message_dbc,
)


def _fake_blf_reader(monkeypatch, *, frame_count=4097):
    tell_calls = []

    class FakeFile:
        def tell(self):
            tell_calls.append(None)
            return len(tell_calls) * 128

    class FakeReader:
        file_size = frame_count * 128

        def __init__(self, _path):
            self.file = FakeFile()

        def __iter__(self):
            for index in range(frame_count):
                yield SimpleNamespace(
                    is_error_frame=False,
                    is_remote_frame=False,
                    timestamp=float(index),
                    arbitration_id=0x123,
                    data=b"\x00",
                )

        def stop(self):
            pass

    monkeypatch.setattr(can.io, "BLFReader", FakeReader)
    return tell_calls


def test_read_blf_frames_without_progress_never_polls_reader_position(
    tmp_path, monkeypatch,
):
    tell_calls = _fake_blf_reader(monkeypatch)

    frames = DataLoader.read_blf_frames(tmp_path / "fake.blf")

    assert len(frames) == 4097
    assert tell_calls == []


def test_read_blf_frames_samples_position_before_tell_when_reporting_progress(
    tmp_path, monkeypatch,
):
    tell_calls = _fake_blf_reader(monkeypatch)
    progress = []

    frames = DataLoader.read_blf_frames(
        tmp_path / "fake.blf",
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    assert len(frames) == 4097
    assert 0 < len(tell_calls) < len(frames)
    assert progress[0][0] == 0
    assert progress[-1][0] == progress[-1][1]


def test_load_blf_with_dbc_decodes_named_signals(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    data, channels, units = DataLoader.load_blf(str(blf), dbc_paths=[str(dbc)])

    assert "EngineSpeed" in channels
    assert "Throttle" in channels
    assert "Speed" in channels
    assert "Time" in channels
    # physical scaling applied: EngineSpeed ramps 800,900,1000,1100,1200
    assert data["EngineSpeed"].iloc[0] == pytest.approx(800.0)
    assert data["EngineSpeed"].max() == pytest.approx(1200.0)
    # units carried from the DBC signals
    assert units["EngineSpeed"] == "rpm"
    assert units["Speed"] == "km/h"
    # shared time axis starts at zero (t0-shifted) and is non-decreasing
    t = data["Time"].to_numpy()
    assert t[0] == pytest.approx(0.0)
    assert np.all(np.diff(t) >= 0)


def test_probe_blf_dbc_reports_strong_match(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is True
    assert probe.strength == "strong"
    assert probe.matched_frame_id_count == 2
    assert probe.total_frame_id_count == 2
    assert probe.decoded_frame_count == 10
    assert set(probe.signal_names) == {"EngineSpeed", "Throttle", "Speed"}


def test_probe_blf_dbc_reports_partial_match_as_weak(tmp_path):
    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is True
    assert probe.strength == "weak"
    assert probe.matched_frame_id_count == 1
    assert probe.total_frame_id_count == 2
    assert probe.decoded_frame_count == 5


def test_probe_blf_dbc_reports_no_match_without_raising(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_raw_blf(tmp_path / "raw.blf")

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is False
    assert probe.strength == "none"
    assert probe.decoded_frame_count == 0


def test_load_blf_zoh_holds_between_can_frames(tmp_path):
    """A slower signal (VehicleSpeed) ZOH-holds its last value across the
    higher-rate reference timeline — never linearly ramps."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    data, _channels, _units = DataLoader.load_blf(str(blf), dbc_paths=[str(dbc)])

    speed = data["Speed"].to_numpy()
    # every resampled value must equal one of the transmitted Speed values
    transmitted = {20.0, 21.0, 22.0, 23.0, 24.0}
    assert set(np.unique(np.round(speed, 6))).issubset(transmitted)


def test_load_blf_without_dbc_exposes_raw_bytes(tmp_path):
    blf = write_raw_blf(tmp_path / "raw.blf")

    data, channels, units = DataLoader.load_blf(str(blf), dbc_paths=None)

    assert "0x1F3.byte0" in channels
    assert "0x1F3.byte2" in channels
    assert "0x200.byte1" in channels
    assert all(units[c] == "" for c in channels if c != "Time")
    # 0x1F3 byte0 transmitted 0x01 then 0x04
    b0 = data["0x1F3.byte0"].to_numpy()
    assert set(np.unique(b0[~np.isnan(b0)])).issubset({1.0, 4.0})


def test_load_raw_blf_frames_reports_frame_id_and_channel_assembly_progress(tmp_path):
    blf = write_raw_blf(tmp_path / "raw.blf")
    frames = DataLoader.read_blf_frames(str(blf))
    progress = []

    DataLoader.load_blf_frames(
        frames,
        dbc_paths=None,
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    assert progress[0] == (0, 1000)
    assert progress[-1] == (1000, 1000)
    assert all(total == 1000 for _current, total in progress)
    assert all(
        earlier <= later
        for (earlier, _), (later, _) in zip(progress, progress[1:])
    )

    # The raw fixture has three frames, two arbitration IDs and five byte
    # channels. Each real work unit must advance its corresponding phase.
    values = [current for current, _total in progress]
    assert len([value for value in values if 0 < value <= 500]) == len(frames)
    assert len([value for value in values if 500 < value <= 750]) == 2
    assert len([value for value in values if 750 < value <= 950]) == 5
    assert values.count(1000) == 1


def test_load_raw_blf_progress_continues_after_read_phase(tmp_path):
    blf = write_raw_blf(tmp_path / "raw.blf")
    progress = []

    DataLoader.load_blf(
        str(blf),
        dbc_paths=None,
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    values = [current for current, total in progress if total == 1000]
    assert values == sorted(values)
    assert values[-1] == 1000
    assert any(400 < value < 1000 for value in values)


def test_load_blf_dbc_mismatch_raises(tmp_path):
    """A DBC whose ids don't appear in the BLF decodes nothing -> clear error."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    # only ids 0x1F3 / 0x200 — neither is in the DBC (0x123 / 0x100)
    blf = write_raw_blf(tmp_path / "raw.blf")

    with pytest.raises(ValueError, match="没有任何帧被解码"):
        DataLoader.load_blf(str(blf), dbc_paths=[str(dbc)])


def test_load_blf_empty_raises(tmp_path):
    blf = write_raw_blf(tmp_path / "empty.blf", frames=())
    with pytest.raises(ValueError, match="没有可读的 CAN"):
        DataLoader.load_blf(str(blf), dbc_paths=None)

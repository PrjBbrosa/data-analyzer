"""DataLoader.load_blf — Vector BLF (raw CAN) import.

With a DBC, frames decode into named physical signals; without one, payload
bytes surface per CAN id. A2L is never involved (plain CAN → DBC).
"""
import numpy as np
import pytest
from types import SimpleNamespace

can = pytest.importorskip("can", reason="python-can not installed (win32-gated)")
cantools = pytest.importorskip("cantools", reason="cantools not installed")

from mf4_analyzer.io.loader import NO_CAN_FRAMES_MESSAGE, DataLoader  # noqa: E402
from mf4_analyzer.io import blf_format  # noqa: E402
from tests._helpers.blf_factory import (  # noqa: E402
    _sample_frame_payloads,
    engine_payload,
    make_can_frames,
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
    assert probe.decoded_sample_count == 10
    assert probe.decode_sample_count == 10
    assert probe.matched_frame_count == 10
    assert set(probe.signal_names) == {"EngineSpeed", "Throttle", "Speed"}


def test_probe_blf_dbc_reports_partial_match_as_weak(tmp_path):
    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is True
    assert probe.strength == "weak"
    assert probe.matched_frame_id_count == 1
    assert probe.total_frame_id_count == 2
    assert probe.decoded_sample_count == 5
    assert probe.decode_sample_count == 10
    assert probe.matched_frame_count == 5


def test_probe_blf_dbc_reports_no_match_without_raising(tmp_path):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_raw_blf(tmp_path / "raw.blf")

    probe = DataLoader.probe_blf_dbc(str(blf), [str(dbc)])

    assert probe.is_match is False
    assert probe.strength == "none"
    assert probe.decoded_sample_count == 0


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
    with pytest.raises(ValueError, match=NO_CAN_FRAMES_MESSAGE):
        DataLoader.load_blf(str(blf), dbc_paths=None)


def test_probe_large_frame_list_does_not_decode_every_frame(tmp_path, monkeypatch):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    eng, spd = _sample_frame_payloads(1)[0]
    frames = []
    for i in range(10_000):
        frames.append((i * 0.001, 0x123, eng))
        frames.append((i * 0.001 + 0.0005, 0x100, spd))
    calls = []
    real = blf_format._decode_can_payload

    def spy(msg, payload):
        calls.append(1)
        return real(msg, payload)

    monkeypatch.setattr(blf_format, "_decode_can_payload", spy)
    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    # Two independent budgets (P0-1): the statistical sample and the
    # discovery sample are each capped at _PROBE_DECODE_CAP.
    assert len(calls) <= 2 * blf_format._PROBE_DECODE_CAP
    assert len(calls) < len(frames)
    assert probe.discovery_decoded_count <= blf_format._PROBE_DECODE_CAP
    assert probe.strength == "strong"
    assert probe.total_frame_count == 20_000
    assert probe.matched_frame_id_count == 2
    assert probe.decode_sample_count <= blf_format._PROBE_DECODE_CAP
    assert probe.decoded_sample_count == probe.decode_sample_count
    assert probe.decoded_sample_count < probe.total_frame_count
    assert probe.sample_decode_success_ratio == pytest.approx(1.0)
    assert set(probe.signal_names) == {"EngineSpeed", "Throttle", "Speed"}


def test_probe_large_partial_match_stays_weak_without_full_decode(
    tmp_path, monkeypatch,
):
    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    eng, spd = _sample_frame_payloads(1)[0]
    frames = []
    for i in range(10_000):
        frames.append((i * 0.001, 0x123, eng))
        frames.append((i * 0.001 + 0.0005, 0x100, spd))
    calls = []
    real = blf_format._decode_can_payload

    def spy(msg, payload):
        calls.append(1)
        return real(msg, payload)

    monkeypatch.setattr(blf_format, "_decode_can_payload", spy)
    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    assert len(calls) <= blf_format._PROBE_DECODE_CAP
    assert probe.strength == "weak"
    assert probe.matched_frame_id_count == 1
    assert probe.matched_frame_count == 10_000
    assert probe.decode_sample_count <= blf_format._PROBE_DECODE_CAP
    assert 0.4 <= probe.sample_decode_success_ratio <= 0.6
    assert probe.decoded_sample_count <= probe.decode_sample_count


def test_load_blf_defers_zoh_until_column_access(tmp_path, monkeypatch):
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)
    calls = []
    real = blf_format._zoh_resample

    def spy(ref_t, t, v):
        calls.append(1)
        return real(ref_t, t, v)

    monkeypatch.setattr(blf_format, "_zoh_resample", spy)
    data, channels, _units = DataLoader.load_blf(str(blf), dbc_paths=[str(dbc)])

    assert isinstance(data, blf_format.LazyZohFrame)
    from mf4_analyzer.io.channel_frame import ChannelFrame
    assert isinstance(data, ChannelFrame)
    assert calls == []
    speed = data["Speed"].to_numpy()
    assert len(calls) == 1
    data["Speed"].to_numpy()
    assert len(calls) == 1
    transmitted = {20.0, 21.0, 22.0, 23.0, 24.0}
    assert set(np.unique(np.round(speed, 6))).issubset(transmitted)
    # Same-message Throttle shares EngineSpeed's axis (the longest / Time).
    throttle = data["Throttle"].to_numpy()
    assert len(calls) == 1
    assert throttle[0] == pytest.approx(10.0)
    assert "EngineSpeed" in channels


def test_assemble_sorts_unsorted_timestamps():
    t = np.array([3.0, 1.0, 2.0])
    v = np.array([30.0, 10.0, 20.0])
    data, channels, _units = blf_format._assemble_blf_channels(
        {"A": (t, v)}, {"A": "u"}, t0=1.0,
    )
    assert channels == ["Time", "A"]
    assert list(data["Time"]) == pytest.approx([0.0, 1.0, 2.0])
    assert list(data["A"]) == pytest.approx([10.0, 20.0, 30.0])


def test_probe_does_not_present_linear_scale_as_exact_decoded_count(tmp_path):
    """V8H-A01: front-all-hit / tail-all-miss must not look like an exact count."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    eng = engine_payload()
    front = blf_format._PROBE_DECODE_CAP
    tail = 8_192
    frames = make_can_frames([
        (front, 0x123, eng),
        (tail, 0x123, b""),
    ])

    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    assert probe.total_frame_count == front + tail
    assert probe.decode_sample_count <= blf_format._PROBE_DECODE_CAP
    assert probe.decoded_sample_count <= probe.decode_sample_count
    assert probe.decoded_sample_count < probe.total_frame_count
    # Sample stays in the sample domain; do not claim a file-wide exact decode.
    assert probe.decoded_sample_count != probe.total_frame_count
    if probe.estimated_decoded_frame_ratio is not None:
        assert 0.0 <= probe.estimated_decoded_frame_ratio <= 1.0
        assert probe.estimated_decoded_frame_ratio < 0.999


def test_statistical_sample_covers_front_mid_and_tail(tmp_path, monkeypatch):
    """V8H-A02: bursty hit rates must not be estimated from the front cap only."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    eng = engine_payload()
    unique_front = blf_format._PROBE_DECODE_CAP
    region = 6_000
    frames = make_can_frames(
        [(1, 0x1000 + i, b"\x00") for i in range(unique_front)]
        + [
            (region, 0x123, eng),
            (region, 0x999, b"\x00"),
            (region, 0x123, eng),
        ],
    )

    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])
    statistical = blf_format._statistical_probe_indices(frames)
    n = len(frames)
    front_end, mid_end = n // 3, 2 * n // 3

    assert statistical
    assert min(statistical) < front_end
    assert any(front_end <= index < mid_end for index in statistical)
    assert max(statistical) >= mid_end
    assert probe.decoded_sample_count > 0
    assert "front" in probe.sampling_strategy
    assert "mid" in probe.sampling_strategy
    assert "tail" in probe.sampling_strategy


def test_discovery_first_per_id_is_not_in_statistical_denominator(tmp_path):
    """V8H-A02: first-of-each-ID discovery frames are not the ratio denominator."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    unique = 200
    body = 12_000
    frames = make_can_frames(
        [(1, 0x2000 + i, b"\x00") for i in range(unique)]
        + [(body, 0x123, engine_payload())],
    )

    discovery = blf_format._discovery_probe_indices(frames)
    statistical = blf_format._statistical_probe_indices(frames)
    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    assert discovery != statistical
    assert probe.decode_sample_count == len(statistical)
    assert probe.decode_sample_count != len(discovery)


def test_rare_matched_id_keeps_its_signal_names_on_a_large_log(tmp_path):
    """P0-1: discovery owns its own budget, so a low-frequency ID still matches.

    30000 frames where the only DBC-defined ID (0x123) is transmitted once,
    at index 1 — outside the stratified statistical sample. Before the fix
    the discovery pass was funded from ``cap - len(statistical)`` (always 0
    on a log above the cap), so ``signal_names`` came back empty and the
    whole DBC was reported as a mismatch even though it decodes fine.
    """
    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    frames = make_can_frames([
        (1, 0x777, b"\x00"),
        (1, 0x123, engine_payload()),
        (29_998, 0x777, b"\x00"),
    ])
    statistical = blf_format._statistical_probe_indices(frames)
    assert 1 not in set(statistical), "fixture must keep 0x123 out of the sample"

    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    assert probe.total_frame_count == 30_000
    assert probe.is_match is True
    assert set(probe.signal_names) == {"EngineSpeed", "Throttle"}
    assert probe.discovery_decoded_count >= 1
    # Discovery feeds names only: it must stay out of the statistical ratio.
    assert probe.decoded_sample_count == 0
    assert probe.decode_sample_count == len(statistical)
    assert probe.sample_decode_success_ratio == 0.0
    assert probe.strength == "weak"


def test_discovery_scan_runs_only_when_the_sample_is_incomplete(
    tmp_path, monkeypatch,
):
    """P0-1: the O(n) discovery scan lives in the branch that consumes it."""
    dbc = write_engine_only_dbc(tmp_path / "engine.dbc")
    scans = []
    real = blf_format._discovery_probe_indices

    def spy(frames, *args, **kwargs):
        scans.append(len(frames))
        return real(frames, *args, **kwargs)

    monkeypatch.setattr(blf_format, "_discovery_probe_indices", spy)

    small = make_can_frames([(5, 0x123, engine_payload())])
    DataLoader.probe_blf_dbc_frames(small, [str(dbc)])
    assert scans == [], "a complete scan already decoded every frame"

    large = make_can_frames([
        (1, 0x123, engine_payload()),
        (blf_format._PROBE_DECODE_CAP + 1, 0x777, b"\x00"),
    ])
    DataLoader.probe_blf_dbc_frames(large, [str(dbc)])
    assert scans == [len(large)], "discovery must scan exactly once, when used"


def test_cancelled_probe_leaves_estimates_empty_with_reason(tmp_path):
    """V8H-A04: user cancel must not invent a scaled exact decode count."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    frames = make_can_frames([(20_000, 0x123, engine_payload())])

    probe = DataLoader.probe_blf_dbc_frames(
        frames, [str(dbc)], cancel_check=lambda: True,
    )

    assert probe.sampling_complete is False
    assert probe.estimated_decoded_frame_ratio is None
    assert probe.estimate_unavailable_reason
    assert "cancel" in probe.estimate_unavailable_reason.lower()


def test_truncated_probe_leaves_estimates_empty_with_reason(tmp_path):
    """V8H-A04: a truncated tail must not fill estimate fields."""

    class TruncatedFrames(list):
        def __getitem__(self, index):
            if isinstance(index, int) and index >= 12_000:
                raise IndexError("truncated BLF tail")
            return super().__getitem__(index)

    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    frames = TruncatedFrames(make_can_frames([(16_000, 0x123, engine_payload())]))

    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    assert probe.estimated_decoded_frame_ratio is None
    assert probe.sampling_complete is False
    assert probe.estimate_unavailable_reason
    assert "truncat" in probe.estimate_unavailable_reason.lower()


def test_corrupt_tail_leaves_estimates_empty_with_reason(tmp_path):
    """V8H-A04: corrupt statistical samples empty estimates with a reason."""
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")
    frames = make_can_frames([(12_000, 0x123, engine_payload())])
    start = 2 * len(frames) // 3
    for index in range(start, len(frames)):
        timestamp, arbitration_id, _payload = frames[index]
        frames[index] = (timestamp, arbitration_id, object())

    probe = DataLoader.probe_blf_dbc_frames(frames, [str(dbc)])

    assert probe.estimated_decoded_frame_ratio is None
    assert probe.sampling_complete is False
    assert probe.estimate_unavailable_reason
    assert "corrupt" in probe.estimate_unavailable_reason.lower()

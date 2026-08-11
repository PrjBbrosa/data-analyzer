"""CANoe ASC CAN-log sniffing, frame reading, and BLF-facade dispatch."""
from __future__ import annotations

import pytest

pytest.importorskip("can", reason="python-can not installed (win32-gated)")
pytest.importorskip("cantools", reason="cantools not installed")

from mf4_analyzer.io.asc_can_format import _read_asc_frames, sniff_canoe_asc
from mf4_analyzer.io.loader import NO_CAN_FRAMES_MESSAGE, DataLoader
from tests._helpers.blf_factory import (
    write_sample_asc,
    write_sample_blf,
    write_two_message_dbc,
)


def test_sniff_canoe_asc_true_for_sample(tmp_path):
    path = write_sample_asc(tmp_path / "log.asc", n=3)
    assert sniff_canoe_asc(path) is True


def test_sniff_canoe_asc_false_for_tabular_and_edge_cases(tmp_path):
    table = tmp_path / "table.asc"
    table.write_text("Time\tSpeed\n0.0\t10\n0.1\t11\n", encoding="utf-8")
    empty = tmp_path / "empty.asc"
    empty.write_text("", encoding="utf-8")

    assert sniff_canoe_asc(table) is False
    assert sniff_canoe_asc(empty) is False
    assert sniff_canoe_asc(tmp_path / "missing.asc") is False


def test_read_asc_frames_skips_sv_and_preserves_order(tmp_path):
    path = write_sample_asc(tmp_path / "log.asc", n=5, dt=0.1, t_start=1.0)
    frames = _read_asc_frames(path)

    assert len(frames) == 10
    assert frames[0][0] == pytest.approx(1.0)
    assert frames[0][1] == 0x123
    assert frames[1][0] == pytest.approx(1.05)
    assert frames[1][1] == 0x100
    assert len(frames[0][2]) == 8


def test_read_blf_frames_dispatches_asc_and_matches_blf_decode(tmp_path):
    n = 5
    asc = write_sample_asc(tmp_path / "log.asc", n=n, dt=0.1, t_start=1.0)
    blf = write_sample_blf(tmp_path / "log.blf", n=n, dt=0.1, t_start=1.0)
    dbc = write_two_message_dbc(tmp_path / "bus.dbc")

    asc_frames = DataLoader.read_blf_frames(asc)
    blf_frames = DataLoader.read_blf_frames(blf)
    assert len(asc_frames) == len(blf_frames) == n * 2
    # BLFReader normalizes container time to the first frame; ASCReader keeps
    # the written absolute measurement time. Compare relative deltas + payload.
    asc_t0 = asc_frames[0][0]
    blf_t0 = blf_frames[0][0]
    for (at, aid, adata), (bt, bid, bdata) in zip(asc_frames, blf_frames):
        assert (at - asc_t0) == pytest.approx(bt - blf_t0)
        assert aid == bid
        assert adata == bdata

    asc_data, asc_chs, _asc_units = DataLoader.load_blf_frames(
        asc_frames, dbc_paths=[str(dbc)],
    )
    blf_data, blf_chs, _blf_units = DataLoader.load_blf_frames(
        blf_frames, dbc_paths=[str(dbc)],
    )
    assert set(asc_chs) >= {"Time", "EngineSpeed", "Throttle", "Speed"}
    assert set(asc_chs) == set(blf_chs)
    assert float(asc_data["Time"].iloc[0]) == pytest.approx(0.0)
    for name in ("EngineSpeed", "Throttle", "Speed"):
        assert list(asc_data[name]) == pytest.approx(list(blf_data[name]))


def test_empty_canoe_asc_raises_shared_sentinel(tmp_path):
    path = tmp_path / "empty_log.asc"
    path.write_text(
        "date Mon Jan 01 12:00:00 PM 2024\n"
        "base hex timestamps absolute\n"
        "no internal events logged\n"
        "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024\n"
        "End TriggerBlock\n",
        encoding="ascii",
    )
    assert sniff_canoe_asc(path) is True
    with pytest.raises(ValueError, match=NO_CAN_FRAMES_MESSAGE):
        DataLoader.read_blf_frames(path)

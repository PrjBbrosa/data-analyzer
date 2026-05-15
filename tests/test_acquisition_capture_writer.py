"""Tests for ``Mf4Writer`` — including the channel-naming contract.

The load-bearing test is ``test_channel_names_match_a2l``: write a fake
recording with three measurements, reload via ``DataLoader.load_mf4``,
assert ``set(channels) - {'Time', 'time'} == set(selected_names)``
(exact equality, accounting for the loader-inserted ``Time`` column
and the asammdf master ``time`` exposed via ``MDF.channels_db``).
This is the spec §Recorder Backend contract that Stage 5
``expected_channels`` depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.writer import Mf4Writer, Mf4WriterError
from mf4_analyzer.io.loader import DataLoader


def _three_signals() -> tuple[SelectedMeasurement, ...]:
    return (
        SelectedMeasurement(name="EngSpdAvg", unit="rpm"),
        SelectedMeasurement(name="EngTrqAct", unit="Nm"),
        SelectedMeasurement(name="VehSpeedRaw", unit="km/h"),
    )


def test_channel_names_match_a2l(tmp_path: Path) -> None:
    """Writer channel names equal A2L measurement names verbatim.

    Spec §Recorder Backend: "every MF4 channel name MUST equal the
    A2L measurement ``name`` verbatim (no prefix, no suffix, no
    transliteration)." Stage 5 ``expected_channels`` relies on this.
    """
    selected = _three_signals()
    out_path = tmp_path / "out.mf4"
    writer = Mf4Writer(out_path, selected)
    for m in selected:
        writer.append(m.name, 0.0, 1.0)
        writer.append(m.name, 0.1, 2.0)
        writer.append(m.name, 0.2, 3.0)
    finalized = writer.finalize()
    assert finalized == out_path
    assert out_path.exists()

    df, channels, units = DataLoader.load_mf4(str(out_path))
    selected_names = {m.name for m in selected}
    # Set equality with loader/asammdf master columns accounted for:
    # ``DataLoader.load_mf4`` injects its own ``Time`` master, and
    # asammdf surfaces the per-channel master ``time`` via
    # ``MDF.channels_db`` iteration. These are the ONLY non-data
    # columns admitted — every other column MUST equal one of the
    # selected A2L measurement names (spec §Recorder Backend
    # channel-naming rule + §Persistence Contract). Subset-only would
    # let a stray duplicate group pass silently.
    _MASTER_COLUMNS = {"Time", "time"}
    assert set(channels) - _MASTER_COLUMNS == selected_names
    # And the units survive the round trip.
    assert units["EngSpdAvg"] == "rpm"
    assert units["EngTrqAct"] == "Nm"
    assert units["VehSpeedRaw"] == "km/h"


def test_writer_rejects_unknown_channel(tmp_path: Path) -> None:
    writer = Mf4Writer(tmp_path / "out.mf4", _three_signals())
    with pytest.raises(Mf4WriterError, match="not in selected set"):
        writer.append("UnknownChannel", 0.0, 1.0)


def test_writer_rejects_empty_selection(tmp_path: Path) -> None:
    with pytest.raises(Mf4WriterError, match="at least one"):
        Mf4Writer(tmp_path / "out.mf4", ())


def test_writer_handles_zero_samples_per_channel(tmp_path: Path) -> None:
    """A channel with no appended samples still appears in the MF4.

    Spec §Capture vs diagnostics: zero samples is a diagnostic
    warning, NOT a writer failure. Writer emits a placeholder sample
    so the channel name is still present.
    """
    selected = _three_signals()
    writer = Mf4Writer(tmp_path / "empty.mf4", selected)
    # Only append to one channel; leave the other two empty.
    writer.append(selected[0].name, 0.0, 1.0)
    writer.append(selected[0].name, 0.1, 2.0)
    out = writer.finalize()
    df, channels, _ = DataLoader.load_mf4(str(out))
    assert {m.name for m in selected} <= set(channels)


def test_writer_close_is_one_shot(tmp_path: Path) -> None:
    writer = Mf4Writer(tmp_path / "twice.mf4", _three_signals())
    writer.append("EngSpdAvg", 0.0, 1.0)
    writer.finalize()
    with pytest.raises(Mf4WriterError, match="already finalized"):
        writer.finalize()
    with pytest.raises(Mf4WriterError, match="closed"):
        writer.append("EngSpdAvg", 0.5, 5.0)


def test_writer_creates_parent_directories(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "out.mf4"
    writer = Mf4Writer(nested, _three_signals())
    writer.append("EngSpdAvg", 0.0, 1.0)
    writer.finalize()
    assert nested.exists()


def test_writer_append_batch_works(tmp_path: Path) -> None:
    writer = Mf4Writer(tmp_path / "batch.mf4", _three_signals())
    batch = [
        ("EngSpdAvg", 0.0, 1.0),
        ("EngTrqAct", 0.0, 2.0),
        ("VehSpeedRaw", 0.0, 3.0),
        ("EngSpdAvg", 0.1, 1.1),
    ]
    writer.append_batch(batch)
    assert writer.write_count == 4
    out = writer.finalize()
    assert out.exists()

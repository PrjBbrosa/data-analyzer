"""Shared Vector BLF + DBC builders for tests.

Both python-can and cantools are optional (python-can is win32-gated in
requirements). Tests using these helpers should ``pytest.importorskip`` both
modules first; the builders assume they are importable.
"""
from __future__ import annotations

import struct
from collections.abc import Sequence
from pathlib import Path


def write_two_message_dbc(path: Path) -> Path:
    """Write a small DBC with two messages / three signals.

    EngineData (0x123): EngineSpeed [rpm, scale 0.25], Throttle [%, scale 0.4]
    VehicleSpeed (0x100): Speed [km/h, scale 0.01]
    """
    import cantools
    from cantools.database.can import Database, Message, Signal
    from cantools.database.conversion import BaseConversion

    def sig(name: str, start: int, length: int, scale: float, unit: str) -> Signal:
        return Signal(
            name=name, start=start, length=length, byte_order="little_endian",
            is_signed=False, unit=unit,
            conversion=BaseConversion.factory(scale=scale, offset=0.0),
        )

    db = Database(messages=[
        Message(
            frame_id=0x123, name="EngineData", length=8, is_extended_frame=False,
            signals=[sig("EngineSpeed", 0, 16, 0.25, "rpm"),
                     sig("Throttle", 16, 8, 0.4, "%")],
        ),
        Message(
            frame_id=0x100, name="VehicleSpeed", length=8, is_extended_frame=False,
            signals=[sig("Speed", 0, 16, 0.01, "km/h")],
        ),
    ])
    cantools.database.dump_file(db, str(path))
    return path


def write_sample_blf(
    path: Path,
    *,
    n: int = 5,
    dt: float = 0.1,
    t_start: float = 1.0,
) -> Path:
    """Write a BLF with ``n`` EngineData (0x123) + ``n`` VehicleSpeed (0x100)
    frames, matching :func:`write_two_message_dbc`.

    EngineSpeed ramps 800,900,…; Throttle 10,15,…; Speed 20,21,….
    """
    import can
    from can.io import BLFWriter

    enc16 = lambda v: struct.pack("<H", int(v))  # noqa: E731
    writer = BLFWriter(str(path))
    try:
        for i in range(n):
            eng = enc16((800 + i * 100) / 0.25) + bytes([int((10 + i * 5) / 0.4)]) + b"\x00" * 5
            writer.on_message_received(can.Message(
                arbitration_id=0x123, is_extended_id=False, data=eng,
                timestamp=t_start + i * dt))
            spd = enc16((20 + i) / 0.01) + b"\x00" * 6
            writer.on_message_received(can.Message(
                arbitration_id=0x100, is_extended_id=False, data=spd,
                timestamp=t_start + 0.05 + i * dt))
    finally:
        writer.stop()
    return path


def write_raw_blf(
    path: Path,
    *,
    frames: Sequence[tuple[int, bytes, float]] = (
        (0x1F3, b"\x01\x02\x03", 0.0),
        (0x1F3, b"\x04\x05\x06", 0.1),
        (0x200, b"\xAA\xBB", 0.05),
    ),
) -> Path:
    """Write an arbitrary BLF from ``(arbitration_id, data, timestamp)`` tuples
    — for exercising the database-free raw-byte fallback."""
    import can
    from can.io import BLFWriter

    writer = BLFWriter(str(path))
    try:
        for arb_id, data, ts in frames:
            writer.on_message_received(can.Message(
                arbitration_id=arb_id, is_extended_id=False,
                data=data, timestamp=ts))
    finally:
        writer.stop()
    return path

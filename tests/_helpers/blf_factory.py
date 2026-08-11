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


def write_engine_only_dbc(path: Path) -> Path:
    """Write a DBC that matches only the EngineData frames from sample BLFs."""
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


def _sample_frame_payloads(n: int = 5):
    """EngineData / VehicleSpeed payloads matching :func:`write_sample_blf`."""
    enc16 = lambda v: struct.pack("<H", int(v))  # noqa: E731
    payloads = []
    for i in range(n):
        eng = (
            enc16((800 + i * 100) / 0.25)
            + bytes([int((10 + i * 5) / 0.4)])
            + b"\x00" * 5
        )
        spd = enc16((20 + i) / 0.01) + b"\x00" * 6
        payloads.append((eng, spd))
    return payloads


def write_sample_asc(
    path: Path,
    *,
    n: int = 5,
    dt: float = 0.1,
    t_start: float = 1.0,
) -> Path:
    """Write a CANoe ASC with the same frame sequence as :func:`write_sample_blf`.

    Inserts two ``SV:`` system-variable lines mid-file so readers must skip
    non-CAN rows. Self-checks with ``ASCReader`` before returning.
    """
    from can.io import ASCReader

    date_line = "date Mon Jan 01 12:00:00 PM 2024"
    lines = [
        date_line,
        "base hex timestamps absolute",
        "no internal events logged",
        f"Begin Triggerblock {date_line}",
    ]
    payloads = _sample_frame_payloads(n)
    mid = max(1, n // 2)
    for i, (eng, spd) in enumerate(payloads):
        if i == mid:
            lines.append("   SV: 1 0 1 ::Test::Var = [01 02]")
            lines.append("   SV: 2 0 1 ::Test::Other = [03 04]")
        t_eng = t_start + i * dt
        t_spd = t_start + 0.05 + i * dt
        eng_hex = " ".join(f"{b:02x}" for b in eng)
        spd_hex = " ".join(f"{b:02x}" for b in spd)
        lines.append(
            f"   {t_eng:.6f} 1  {0x123:03X}             Rx   d 8  {eng_hex}"
        )
        lines.append(
            f"   {t_spd:.6f} 1  {0x100:03X}             Rx   d 8  {spd_hex}"
        )
    lines.append("End TriggerBlock")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")

    reader = ASCReader(str(path))
    try:
        messages = list(reader)
    finally:
        stop = getattr(reader, "stop", None)
        if callable(stop):
            stop()
    assert len(messages) == n * 2, (
        f"write_sample_asc self-check expected {n * 2} frames, got {len(messages)}"
    )
    return path

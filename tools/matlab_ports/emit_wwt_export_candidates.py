#!/usr/bin/env python3
"""Emit WinWert open-trial candidates after the stub-trailer failure.

2026-08-11: ``candidate_body_only`` and ``candidate_trailer_stub`` both failed
to open in WinWert. Real files carry a ~30–100 KiB ``DatenFenste2`` display
block with per-channel label slots (~283 B). This script emits the next
ladder of candidates:

1. ``candidate_mutate_real.wwt`` — byte-copy of a known-good ``testdoc`` file
   with only the comment field retouched (control: WinWert must open this if
   the install can open originals at all).
2. ``candidate_graft_full_trailer.wwt`` — TraceLab body + full trailer grafted
   from that real file (count field patched).
3. ``candidate_graft_slot_labels.wwt`` — same graft, but the first channel
   label slots are rewritten to match the exported names.
4. Legacy stub/body-only files are regenerated for reference.

Usage:
    PYTHONPATH=. .venv/bin/python tools/matlab_ports/emit_wwt_export_candidates.py
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from mf4_analyzer.io.wwt_writer import (
    extract_wwt_trailer,
    patch_trailer_record_count,
    write_wwt,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "wwt_export_candidates"
TEMPLATE = ROOT / "testdoc" / "wwt" / "YP_SS_000089.wwt"

_SLOT_BASE = 514
_SLOT_STRIDE = 283
_LABEL_FIELD = 64  # enough for "Name [unit]" + NULs inside a slot


def _synth_series(n: int = 1000, dt: float = 0.001):
    time = np.arange(n, dtype=np.float64) * dt
    channels = {
        "Steering torque": 2.0 * np.sin(2 * np.pi * 5.0 * time),
        "Motor speed": 600.0 + 3000.0 * time / time[-1],
    }
    units = {"Steering torque": "Nm", "Motor speed": "rpm"}
    return time, channels, units


def _patch_slot_labels(trailer: bytes, labels: list[str]) -> bytes:
    """Rewrite leading ``Name [unit]`` strings in the 283-byte channel slots."""
    if not trailer.startswith(b"DatenFenste2"):
        return trailer
    out = bytearray(trailer)
    for i, label in enumerate(labels):
        off = _SLOT_BASE + i * _SLOT_STRIDE
        if off + _LABEL_FIELD > len(out):
            break
        raw = label.encode("latin-1", "replace")[: _LABEL_FIELD - 1]
        field = raw + b"\0" * (_LABEL_FIELD - len(raw))
        out[off:off + _LABEL_FIELD] = field
    return bytes(out)


def _emit_mutate_real() -> Path:
    raw = bytearray(TEMPLATE.read_bytes())
    # Retouch comment so the file is visually distinct in WinWert.
    comment = b"TraceLab mutate trial - open-control"
    raw[0x10F:0x20F] = comment.ljust(256, b"\0")
    out = OUT / "candidate_mutate_real.wwt"
    out.write_bytes(raw)
    return out


def main() -> None:
    if not TEMPLATE.is_file():
        raise SystemExit(f"missing trailer template: {TEMPLATE}")
    OUT.mkdir(parents=True, exist_ok=True)
    time, channels, units = _synth_series()
    trailer = extract_wwt_trailer(TEMPLATE)
    labels = [
        f"{name} [{units[name]}]" for name in channels
    ]

    write_wwt(
        OUT / "candidate_body_only.wwt",
        time,
        channels,
        units=units,
        title="TraceLab WWT export candidate",
        comment="body only — WinWert rejected 2026-08-11",
        source_filename="tracelab_export_candidate.wwt",
        include_trailer_stub=False,
    )
    write_wwt(
        OUT / "candidate_trailer_stub.wwt",
        time,
        channels,
        units=units,
        title="TraceLab WWT export candidate",
        comment="256B stub — WinWert rejected 2026-08-11",
        source_filename="tracelab_export_candidate.wwt",
        include_trailer_stub=True,
    )
    write_wwt(
        OUT / "candidate_graft_full_trailer.wwt",
        time,
        channels,
        units=units,
        title="TraceLab WWT export candidate",
        comment="grafted YP_SS trailer; count patched; WinWert rejected",
        source_filename="tracelab_export_candidate.wwt",
        include_trailer_stub=False,
        trailer=trailer,
    )
    write_wwt(
        OUT / "candidate_graft_slot_labels.wwt",
        time,
        channels,
        units=units,
        title="TraceLab WWT export candidate",
        comment="grafted trailer + slot labels; WinWert rejected",
        source_filename="tracelab_export_candidate.wwt",
        include_trailer_stub=False,
        trailer=_patch_slot_labels(
            patch_trailer_record_count(trailer, 1 + len(channels)),
            labels,
        ),
    )
    mutated = _emit_mutate_real()
    _emit_inplace_trials()

    print("Wrote candidates:")
    for p in sorted(OUT.glob("candidate_*.wwt")):
        print(f"  {p.name:40} {p.stat().st_size:8d} B")
    print()
    print("WinWert trial order (after graft failure):")
    print(f"  A) candidate_inplace_payload.wwt")
    print(f"  B) candidate_inplace_rename_header.wwt")
    print(f"  C) candidate_inplace_rename_both.wwt")
    print("Also confirm testdoc/wwt/YP_SS_000089.wwt still opens.")


def _emit_inplace_trials() -> None:
    """In-place mutations on the YP_SS skeleton (same layout/trailer)."""
    from mf4_analyzer.io.loader import DataLoader

    raw0 = TEMPLATE.read_bytes()
    idx = raw0.find(b"DatenFenste2")
    pos = 0x211
    payloads = {}
    while pos + 156 <= idx:
        tag = raw0[pos:pos + 5].split(b"\0")[0].decode()
        n = struct.unpack_from("<I", raw0, pos + 5)[0]
        name = raw0[pos + 0x1B:pos + 0x43].split(b"\0")[0]
        d = {"Zeit": 0, "Real": 8, "int1": 2, "Long": 4, "Floa": 4}[tag]
        payloads[name.decode("latin-1", "replace").strip()] = (
            tag, n, d, pos + 156, pos,
        )
        pos = pos + 156 + n * d

    def _write(name: str, data: bytes) -> None:
        path = OUT / name
        path.write_bytes(data)
        DataLoader.load_wwt(str(path))  # TraceLab sanity

    # A) replace Md-Lenkrad int16 payload with a sine
    data = bytearray(raw0)
    tag, n, d, data_off, rec_off = payloads["Md-Lenkrad"]
    a = struct.unpack_from("<d", data, rec_off + 0x84)[0]
    t = np.arange(n) * 0.001
    phys = 2.0 * np.sin(2 * np.pi * 3 * t)
    raw = np.clip(np.round(phys / a), -32768, 32767).astype("<i2")
    data[data_off:data_off + n * 2] = raw.tobytes()
    data[0x10F:0x20F] = b"trial A: in-place int1 payload replace".ljust(256, b"\0")
    _write("candidate_inplace_payload.wwt", data)

    # B) rename record header only
    data = bytearray(raw0)
    _tag, _n, _d, _data_off, rec_off = payloads["Md-Lenkrad"]
    data[rec_off + 0x1B:rec_off + 0x1B + 40] = b"Steering torque".ljust(40, b"\0")
    data[0x10F:0x20F] = b"trial B: rename record header only".ljust(256, b"\0")
    _write("candidate_inplace_rename_header.wwt", data)

    # C) rename header + trailer slot
    data = bytearray(raw0)
    _tag, _n, _d, _data_off, rec_off = payloads["Md-Lenkrad"]
    data[rec_off + 0x1B:rec_off + 0x1B + 40] = b"Steering torque".ljust(40, b"\0")
    t0 = idx + 1646  # Md-Lenkrad label slot in YP_SS trailer
    data[t0:t0 + 64] = b"Steering torque [Nm]".ljust(64, b"\0")
    data[0x10F:0x20F] = b"trial C: rename header+trailer slot".ljust(256, b"\0")
    _write("candidate_inplace_rename_both.wwt", data)


if __name__ == "__main__":
    main()

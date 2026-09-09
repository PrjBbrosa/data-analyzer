"""Official ZFGE2 fixture writers for tests.

Layout matches ``testdoc/zfd_import.m`` / Spec §4. This module must not
import the product parser or ``tools/matlab_ports``.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

HEADER_LINE_COUNT = 11
FAKE_MARKER = b"A99: fake\n"


def default_header_lines(*, version="TestRunPRO Data V1", title="Fixture"):
    lines = ["ZFGE2", str(version), str(title)]
    while len(lines) < HEADER_LINE_COUNT:
        lines.append("")
    return lines[:HEADER_LINE_COUNT]


def pack_header(lines):
    if len(lines) != HEADER_LINE_COUNT:
        raise ValueError(f"header must have exactly {HEADER_LINE_COUNT} lines")
    return b"".join(f"{line}\n".encode("latin-1") for line in lines)


def pack_annotation(
    text="",
    *,
    align_h=0,
    align_v=0,
    color=0,
    posx=0.0,
    posy=0.0,
    extra=0.0,
):
    return (
        struct.pack("<hhh", int(align_h), int(align_v), int(color))
        + struct.pack("<fff", float(posx), float(posy), float(extra))
        + f"{text}\n".encode("latin-1")
    )


def pack_time_record(
    *,
    count,
    name="t",
    unit="sec",
    t0=0.0,
    dt=0.001,
    declared_count=None,
):
    n = int(count if declared_count is None else declared_count)
    return (
        struct.pack("<h", 0)
        + b"\x00"
        + struct.pack("<i", n)
        + f"{name}\n".encode("latin-1")
        + f"{unit}\n".encode("latin-1")
        + struct.pack("<dd", float(t0), float(dt))
    )


def pack_float32_record(
    *,
    values,
    name="A2: temp",
    unit="C",
    x=0,
    declared_count=None,
    min_v=None,
    max_v=None,
    typ=4,
    data_bytes=None,
):
    arr = np.asarray(list(values), dtype="<f4")
    n = int(len(arr) if declared_count is None else declared_count)
    if arr.size:
        lo = float(arr.min()) if min_v is None else float(min_v)
        hi = float(arr.max()) if max_v is None else float(max_v)
    else:
        lo = 0.0 if min_v is None else float(min_v)
        hi = 0.0 if max_v is None else float(max_v)
    payload = arr.tobytes() if data_bytes is None else data_bytes
    return (
        struct.pack("<h", int(typ))
        + struct.pack("<i", n)
        + f"{name}\n".encode("latin-1")
        + f"{unit}\n".encode("latin-1")
        + struct.pack("<b", int(x))
        + b"\x00"
        + struct.pack("<dd", lo, hi)
        + payload
    )


def write_zfge2(
    path,
    *,
    header_lines=None,
    annotations=(),
    records,
    trailing=b"",
    declared_record_count=None,
    declared_annotation_count=None,
    annotation_count_bytes=None,
    record_count_bytes=None,
    omit_record_count=False,
    truncate=0,
):
    """Write a ZFGE2 file from packed record blobs.

    ``truncate`` drops that many trailing bytes after assembly (before write).
    """
    path = Path(path)
    header = pack_header(header_lines or default_header_lines())
    ann_blobs = [pack_annotation(item) if isinstance(item, str) else item
                 for item in annotations]
    if annotation_count_bytes is None:
        n_ann = (
            len(ann_blobs)
            if declared_annotation_count is None
            else int(declared_annotation_count)
        )
        annotation_count_bytes = struct.pack("<h", n_ann)
    if record_count_bytes is None and not omit_record_count:
        n_rec = (
            len(records)
            if declared_record_count is None
            else int(declared_record_count)
        )
        record_count_bytes = struct.pack("<b", n_rec)
    elif omit_record_count:
        record_count_bytes = b""
    blob = (
        header
        + annotation_count_bytes
        + b"".join(ann_blobs)
        + record_count_bytes
        + b"".join(records)
        + bytes(trailing or b"")
    )
    if truncate:
        blob = blob[: max(0, len(blob) - int(truncate))]
    path.write_bytes(blob)
    return path


def characteristic_values(count, *, head=11.0, mid=22.0, tail=33.0):
    """One measurement channel with checkable head / mid / tail samples."""
    values = np.arange(count, dtype=np.float64)
    values[0] = head
    values[count // 2] = mid
    values[-1] = tail
    return values


def write_minimal_zfd(
    path,
    *,
    dt,
    count=8,
    values=None,
    name="temp",
    unit="C",
    marker="E1",
    t0=0.0,
    time_name="t",
    time_unit="sec",
    title="Slow Sample",
    trailing=b"",
    x=0,
):
    """One type-0 time record plus one type-4 measurement (complete layout)."""
    samples = list(range(count)) if values is None else list(values)
    if len(samples) != count:
        raise ValueError("values length must equal count")
    display = f"{marker}: {name}" if marker else str(name)
    return write_zfge2(
        path,
        header_lines=default_header_lines(title=title),
        records=(
            pack_time_record(
                count=count, name=time_name, unit=time_unit, t0=t0, dt=dt,
            ),
            pack_float32_record(
                values=samples, name=display, unit=unit, x=x,
            ),
        ),
        trailing=trailing,
    )


def write_zfd_duplicate_names(path, *, dt=0.001, count=8, t0=0.0):
    """Two same-named channels so the second is renamed ``name [marker_id]``."""
    values_a = list(range(count))
    values_b = [v + 10.0 for v in values_a]
    return write_zfge2(
        path,
        header_lines=default_header_lines(title="Dup Names"),
        records=(
            pack_time_record(count=count, t0=t0, dt=dt),
            pack_float32_record(values=values_a, name="A2: Szyl 1", unit="mm"),
            pack_float32_record(values=values_b, name="E5: Szyl 1", unit="mm"),
        ),
    )


def write_truncated_last_channel(path, *, count=16, dt=0.001, drop_bytes=20):
    """Complete first records, then cut the last type-4 payload short."""
    values = characteristic_values(count)
    return write_zfge2(
        path,
        header_lines=default_header_lines(title="Truncated"),
        records=(
            pack_time_record(count=count, dt=dt),
            pack_float32_record(values=values, name="A2: keep", unit="C"),
            pack_float32_record(values=values, name="E3: cut", unit="C"),
        ),
        truncate=drop_bytes,
    )


# Public aliases used by older tests.
_write_minimal_zfd = write_minimal_zfd
_write_zfd_duplicate_names = write_zfd_duplicate_names

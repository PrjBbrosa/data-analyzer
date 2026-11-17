"""Shared MF4 builder for tests."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from asammdf import MDF, Signal
from asammdf.blocks.source_utils import Source


def write_single_channel_mf4(
    path: Path,
    *,
    name: str = "sig",
    unit: str = "V",
    timestamps: Sequence[float] | np.ndarray = (0.0, 0.01, 0.02, 0.03),
    samples: Sequence[float] | np.ndarray = (1.0, 2.0, 3.0, 4.0),
) -> Path:
    t = np.asarray(timestamps, dtype=float)
    y = np.asarray(samples, dtype=float)
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name=name, unit=unit)])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def write_single_channel_mdf(
    path: Path,
    *,
    name: str = "sig",
    unit: str = "V",
    timestamps: Sequence[float] | np.ndarray = (0.0, 0.01, 0.02, 0.03),
    samples: Sequence[float] | np.ndarray = (1.0, 2.0, 3.0, 4.0),
) -> Path:
    """Write a single-channel MDF v3 file (``.mdf`` extension is the caller's).

    MDF v3 is what most ``.mdf`` files in the wild are; asammdf reads it via
    the same ``MDF()`` entrypoint as v4 ``.mf4``. Used to prove the UI dispatch
    routes ``.mdf`` to ``load_mf4`` rather than the CSV fallback.
    """
    t = np.asarray(timestamps, dtype=float)
    y = np.asarray(samples, dtype=float)
    mdf = MDF(version="3.30")
    mdf.append([Signal(samples=y, timestamps=t, name=name, unit=unit)])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def write_source_path_mf4(
    path: Path,
    *,
    channels: Sequence[tuple[str, str, str, Sequence[float] | np.ndarray]],
    timestamps: Sequence[float] | np.ndarray = (0.0, 0.01, 0.02, 0.03),
) -> Path:
    """Write channels whose source path creates asammdf source-path aliases."""
    t = np.asarray(timestamps, dtype=float)
    signals = []
    for name, unit, source_path, samples in channels:
        signals.append(
            Signal(
                samples=np.asarray(samples, dtype=float),
                timestamps=t,
                name=name,
                unit=unit,
                source=Source(
                    name="",
                    path=source_path,
                    comment="",
                    source_type=Source.SOURCE_ECU,
                    bus_type=Source.BUS_TYPE_CAN,
                ),
            )
        )
    mdf = MDF(version="4.10")
    mdf.append(signals)
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def write_conversion_unit_mf4(
    path: Path,
    *,
    name: str = "trq",
    unit: str = "Nm",
    timestamps: Sequence[float] | np.ndarray = (0.0, 0.01, 0.02, 0.03),
    samples: Sequence[float] | np.ndarray = (1.0, 2.0, 3.0, 4.0),
) -> Path:
    """Write a channel whose unit lives only on the conversion block."""
    t = np.asarray(timestamps, dtype=float)
    y = np.asarray(samples, dtype=float)
    conversion = {"a": 1.0, "b": 0.0, "unit": unit}
    mdf = MDF(version="4.10")
    mdf.append([
        Signal(samples=y, timestamps=t, name=name, unit="", conversion=conversion)
    ])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def write_signal_groups_mf4(path: Path, groups: Sequence[Sequence]) -> Path:
    """Write one asammdf channel group per inner sequence.

    Each item is ``(name, samples, timestamps)`` or
    ``(name, samples, timestamps, unit)``. Separate groups keep independent
    clocks, which is how CANape stores rasters inside one MF4.
    """
    mdf = MDF(version="4.10")
    for group in groups:
        signals = []
        for item in group:
            name, samples, timestamps = item[:3]
            unit = item[3] if len(item) > 3 else ""
            samples = np.asarray(samples)
            timestamps = np.asarray(timestamps, dtype=float)
            encoding = "latin-1" if samples.dtype.kind in {"S", "V"} else None
            signals.append(
                Signal(
                    samples=samples,
                    timestamps=timestamps,
                    name=name,
                    unit=unit,
                    encoding=encoding,
                )
            )
        mdf.append(signals)
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def write_array_mf4(path, shape, *, dtype="<f4", cycles=3, inverse=False,
                    compression=0, fragment_size=None):
    """Array values follow an independent coordinate oracle, including F layout."""
    from asammdf.blocks import v4_constants as c

    size = int(np.prod(shape))
    expected = np.arange(cycles * size, dtype=dtype).reshape((cycles, *shape))
    samples = np.zeros(cycles, dtype=[("matrix", dtype, shape)])
    for i in range(cycles):
        samples["matrix"][i] = expected[i].ravel(order="F" if inverse else "C").reshape(shape)
    with MDF(version="4.10") as mdf:
        mdf.append([Signal(samples, timestamps=np.arange(cycles, dtype=float),
                           name="matrix", unit="V")])
        if inverse:
            mdf.groups[0].channel_dependencies[1][0].flags |= c.FLAG_CA_INVERSE_LAYOUT
        if fragment_size is not None:
            mdf.configure(write_fragment_size=fragment_size)
        mdf.save(path, overwrite=True, compression=compression)
    return Path(path), expected

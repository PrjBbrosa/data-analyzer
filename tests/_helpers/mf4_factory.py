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

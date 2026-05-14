"""Shared MF4 builder for tests."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from asammdf import MDF, Signal


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

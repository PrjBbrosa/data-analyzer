from pathlib import Path

import numpy as np
from asammdf import MDF, Signal


def write_single_signal_mf4(
    output_path: str | Path,
    *,
    signal_name: str,
    unit: str,
    timestamps: list[float],
    samples: list[float],
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ts = np.asarray(timestamps, dtype=float)
    vals = np.asarray(samples, dtype=float)
    if ts.shape != vals.shape:
        raise ValueError("timestamps and samples must have the same length")
    if ts.size == 0:
        raise ValueError("at least one sample is required")

    mdf = MDF(version="4.10")
    signal = Signal(samples=vals, timestamps=ts, name=signal_name, unit=unit)
    mdf.append([signal], comment="P0 acquisition probe")
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path

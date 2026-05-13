from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from mf4_analyzer.io.loader import DataLoader

from .manifest import sha256_file


@dataclass(frozen=True)
class PreflightResult:
    path: str
    ok: bool
    rows: int
    channels: tuple[str, ...]
    units: dict[str, str]
    duration_s: float
    estimated_fs_hz: float
    missing_channels: tuple[str, ...]
    problems: tuple[str, ...]
    sha256: str
    resolved_signals: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


def _time_stats(df) -> tuple[float, float, list[str]]:
    problems: list[str] = []
    if "Time" not in df.columns:
        return 0.0, 0.0, ["Time column missing"]
    t = np.asarray(df["Time"], dtype=float)
    if t.size < 2:
        return 0.0, 0.0, ["Time column has fewer than 2 samples"]
    if np.any(~np.isfinite(t)):
        problems.append("Time column contains non-finite values")
    dt = np.diff(t)
    if np.any(dt <= 0):
        problems.append("Time column is not strictly increasing")
    duration = float(t[-1] - t[0])
    positive = dt[dt > 0]
    fs = float(1.0 / np.median(positive)) if positive.size else 0.0
    return duration, fs, problems


def analyze_mf4(
    path: str | Path,
    *,
    expected_channels: tuple[str, ...] = (),
    expected_sha256: str | None = None,
    signal_config_root: str | Path | None = None,
    vehicle: str = "",
) -> PreflightResult:
    p = Path(path)
    problems: list[str] = []
    if not p.exists():
        return PreflightResult(
            path=str(p),
            ok=False,
            rows=0,
            channels=(),
            units={},
            duration_s=0.0,
            estimated_fs_hz=0.0,
            missing_channels=tuple(expected_channels),
            problems=("file does not exist",),
            sha256="",
            resolved_signals={},
        )

    actual_sha256 = sha256_file(p)
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        problems.append("sha256 mismatch")

    df, channels, units = DataLoader.load_mf4(str(p))
    channel_tuple = tuple(channels)

    resolved_signals: dict[str, str] = {}
    expected_raw = expected_channels
    if signal_config_root and vehicle:
        from .signals import load_vehicle_mapping, resolve_standard_signals

        mapping = load_vehicle_mapping(signal_config_root, vehicle)
        resolved_signals = resolve_standard_signals(channel_tuple, mapping)
        expected_raw = tuple(
            resolved_signals.get(ch, ch) for ch in expected_channels
        )
    missing = tuple(ch for ch in expected_raw if ch not in channel_tuple)
    if missing:
        problems.append("expected channels missing")

    duration, fs, time_problems = _time_stats(df)
    problems.extend(time_problems)

    numeric_cols = [col for col in df.columns if col != "Time"]
    if not numeric_cols:
        problems.append("no numeric signal channels")
    for col in numeric_cols:
        vals = np.asarray(df[col], dtype=float)
        if np.any(~np.isfinite(vals)):
            problems.append(f"{col} contains non-finite values")

    return PreflightResult(
        path=str(p),
        ok=not problems,
        rows=int(len(df)),
        channels=channel_tuple,
        units=dict(units),
        duration_s=duration,
        estimated_fs_hz=fs,
        missing_channels=missing,
        problems=tuple(problems),
        sha256=actual_sha256,
        resolved_signals=resolved_signals,
    )

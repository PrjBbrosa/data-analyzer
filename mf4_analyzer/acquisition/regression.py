from __future__ import annotations

import hashlib
import json
from math import isclose
from pathlib import Path

import numpy as np

from mf4_analyzer.io.loader import DataLoader


def _samples_sha256(values: np.ndarray) -> str:
    arr = np.ascontiguousarray(values, dtype=np.float64)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _metric_dict(values) -> dict[str, float | int | str]:
    arr = np.asarray(values, dtype=float)
    finite_mask = np.isfinite(arr)
    finite = arr[finite_mask]
    if finite.size == 0:
        mean = std = mn = mx = float("nan")
        first = last = float("nan")
    else:
        mean = float(np.mean(finite))
        std = float(np.std(finite))
        mn = float(np.min(finite))
        mx = float(np.max(finite))
        first = float(arr[0])
        last = float(arr[-1])
    return {
        "len": int(arr.size),
        "finite_count": int(finite.size),
        "mean": mean,
        "std": std,
        "min": mn,
        "max": mx,
        "first_sample": first,
        "last_sample": last,
        "samples_sha256": _samples_sha256(arr),
    }


def build_snapshot(path: str | Path, *, channels: tuple[str, ...] = ()) -> dict:
    df, loaded_channels, _units = DataLoader.load_mf4(str(path))
    if channels:
        target_channels = [ch for ch in channels if ch in df.columns]
    else:
        target_channels = [ch for ch in loaded_channels if ch != "Time"]

    duration = 0.0
    if "Time" in df.columns and len(df["Time"]) > 1:
        duration = float(df["Time"].iloc[-1] - df["Time"].iloc[0])

    return {
        "path": str(path),
        "rows": int(len(df)),
        "duration_s": duration,
        "channels": {ch: _metric_dict(df[ch].to_numpy()) for ch in target_channels},
    }


def _within_tol(a, b, *, rel_tol: float, abs_tol: float) -> bool:
    try:
        return isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except (TypeError, ValueError):
        return a == b


def compare_snapshot(
    baseline: dict,
    current: dict,
    *,
    rel_tol: float = 1e-4,
    abs_tol: float = 1e-6,
) -> list[str]:
    diffs: list[str] = []
    if baseline.get("rows") != current.get("rows"):
        diffs.append(
            f"rows drift: baseline={baseline.get('rows')} current={current.get('rows')}"
        )
    if not _within_tol(
        baseline.get("duration_s", 0.0),
        current.get("duration_s", 0.0),
        rel_tol=rel_tol,
        abs_tol=abs_tol,
    ):
        diffs.append(
            f"duration_s drift: baseline={baseline.get('duration_s')} current={current.get('duration_s')}"
        )

    baseline_channels = baseline.get("channels", {})
    current_channels = current.get("channels", {})
    for ch, metrics in baseline_channels.items():
        if ch not in current_channels:
            diffs.append(f"{ch} missing from current snapshot")
            continue
        for metric, baseline_value in metrics.items():
            current_value = current_channels[ch].get(metric)
            if current_value is None:
                diffs.append(f"{ch}.{metric} missing from current snapshot")
                continue
            if metric in ("samples_sha256", "len", "finite_count"):
                if baseline_value != current_value:
                    diffs.append(
                        f"{ch}.{metric} drift: baseline={baseline_value} current={current_value}"
                    )
                continue
            if not _within_tol(
                baseline_value, current_value, rel_tol=rel_tol, abs_tol=abs_tol
            ):
                diffs.append(
                    f"{ch}.{metric} drift: baseline={baseline_value} current={current_value}"
                )
    return diffs


def load_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

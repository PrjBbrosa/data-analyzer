"""Vector/CAN transport parameters for the Stage 8 backend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class TransportConfig:
    app_name: str = "Python"
    channel: int = 0
    can_fd: bool = False
    bitrate: int = 500_000
    data_bitrate: int = 2_000_000
    sample_point: float = 75.0
    fd_sample_point: float = 70.0
    timeout_s: float = 1.0
    seed_and_key_dll: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransportConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(
                f"unknown key(s) {sorted(unknown)!r}; allowed keys are {sorted(known)!r}"
            )
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key == "app_name":
                kwargs[key] = _require_non_empty_str(key, value)
            elif key == "channel":
                kwargs[key] = _require_int(key, value, minimum=0)
            elif key == "can_fd":
                kwargs[key] = _require_bool(key, value)
            elif key in {"bitrate", "data_bitrate"}:
                kwargs[key] = _require_int(key, value, minimum=1)
            elif key in {"sample_point", "fd_sample_point"}:
                kwargs[key] = _require_float(
                    key,
                    value,
                    minimum_exclusive=0.0,
                    maximum=100.0,
                )
            elif key == "timeout_s":
                kwargs[key] = _require_float(key, value, minimum_exclusive=0.0)
            elif key == "seed_and_key_dll":
                kwargs[key] = _require_optional_str(key, value)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_non_empty_str(key: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _require_optional_str(key: str, value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{key} must be a string or null")


def _require_bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _require_int(key: str, value: Any, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return value


def _require_float(
    key: str,
    value: Any,
    *,
    minimum_exclusive: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    result = float(value)
    if result <= minimum_exclusive:
        raise ValueError(f"{key} must be > {minimum_exclusive}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{key} must be <= {maximum}")
    return result

"""Pure built-in analysis preset catalog shared by UI and batch workflows.

The catalog owns only partial analysis-parameter patches.  Runtime scope,
signals, outputs, conflict policy, weighting and dB-reference state belong to
the live consumer and are intentionally absent here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .db_reference import normalize_unit


SUPPORTED_ANALYSIS_METHODS = ("fft", "fft_time", "order_time")
BUILTIN_PRESET_KEYS = ("torque", "vibration", "transient")
BUILTIN_PRESET_DISPLAY = MappingProxyType({
    "torque": "频率",
    "vibration": "均衡",
    "transient": "时间",
})
BUILTIN_PRESET_BLURB = MappingProxyType({
    "torque": "频率 / 幅值最准，时间偏粗 · 适合扭矩、压力等稳态量",
    "vibration": "时间-频率折中，宽动态 · 适合振动等通用诊断",
    "transient": "时间最细，频率偏粗 · 适合启停、冲击等瞬态",
})
PRESET_KEY_TO_SLOT = MappingProxyType(
    {"torque": 1, "vibration": 2, "transient": 3}
)


_TORQUE_UNITS = frozenset({
    "nm", "n·m", "n.m", "n*m", "mnm", "knm", "cnm",
    "bar", "mbar", "kpa", "mpa", "hpa", "pa", "psi",
    "°", "deg", "mm", "µm", "um", "%",
})
_VIBRATION_UNITS = frozenset({
    "g", "mg", "m/s2", "mm/s", "mm/s2", "µm/s", "um/s", "in/s",
})


# These are the sole built-in numeric literals.  Consumers may project a
# legacy/private shape from them, but must not keep a second literal catalog.
_PATCHES: dict[str, dict[str, dict[str, Any]]] = {
    "fft": {
        "torque": {
            "window": "flattop", "nfft": "自动", "t_win_s": 2.5,
            "overlap": 75, "amp_y": "dB", "avg_mode": "线性平均",
            "avg_overlap": 75,
        },
        "vibration": {
            "window": "hanning", "nfft": "自动", "t_win_s": 1.5,
            "overlap": 50, "amp_y": "dB", "avg_mode": "线性平均",
            "avg_overlap": 50,
        },
        "transient": {
            "window": "hanning", "nfft": "自动", "t_win_s": 0.6,
            "overlap": 75, "amp_y": "dB", "avg_mode": "峰值保持",
            "avg_overlap": 75,
        },
    },
    "fft_time": {
        "torque": {
            "window": "flattop", "nfft": "自动", "nfft_mode": "auto",
            "t_win_s": 2.5, "overlap": 75,
            "amplitude_mode": "Amplitude dB", "remove_mean": True,
            "freq_auto": True, "freq_min": 0.0, "freq_max": 0.0,
            "dynamic": "Auto", "cmap": "viridis",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -40.0, "z_ceiling": 0.0,
        },
        "vibration": {
            "window": "hanning", "nfft": "自动", "nfft_mode": "auto",
            "t_win_s": 1.5, "overlap": 50,
            "amplitude_mode": "Amplitude dB", "remove_mean": True,
            "freq_auto": True, "freq_min": 0.0, "freq_max": 0.0,
            "dynamic": "Auto", "cmap": "turbo",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -40.0, "z_ceiling": 0.0,
        },
        "transient": {
            "window": "hanning", "nfft": "自动", "nfft_mode": "auto",
            "t_win_s": 0.6, "overlap": 75,
            "amplitude_mode": "Amplitude dB", "remove_mean": True,
            "freq_auto": True, "freq_min": 0.0, "freq_max": 0.0,
            "dynamic": "Auto", "cmap": "turbo",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -30.0, "z_ceiling": 0.0,
        },
    },
    "order_time": {
        # Window is declared here on purpose, to stay aligned with the
        # "fft" / "fft_time" presets above (torque -> flattop, vibration /
        # transient -> hanning).  COT reads it via get_analysis_window, so
        # applying this patch changes the live order window too.
        "torque": {
            "max_order": 20, "order_res": 0.05, "time_res": 0.10,
            "nfft": "自动", "samples_per_rev": 256,
            "amplitude_mode": "Amplitude dB", "window": "flattop",
        },
        "vibration": {
            "max_order": 50, "order_res": 0.10, "time_res": 0.05,
            "nfft": "自动", "samples_per_rev": 512,
            "amplitude_mode": "Amplitude dB", "window": "hanning",
        },
        "transient": {
            "max_order": 30, "order_res": 0.25, "time_res": 0.02,
            "nfft": "自动", "samples_per_rev": 256,
            "amplitude_mode": "Amplitude dB", "window": "hanning",
        },
    },
}

_ENABLED: dict[str, dict[str, bool]] = {}
_ALIASES = {
    "fft_time": {
        "diagnostic": "vibration",
        "amplitude_accuracy": "torque",
        "high_frequency": "transient",
    },
}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    return value


@dataclass(frozen=True)
class BuiltinAnalysisPreset:
    """One immutable catalog record with an immutable partial patch."""

    method: str
    key: str
    display_name: str
    slot: int
    enabled: bool
    params: Mapping[str, Any]
    aliases: tuple[str, ...] = ()
    blurb: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _freeze(self.params))
        object.__setattr__(self, "aliases", tuple(self.aliases))

    def params_copy(self) -> dict[str, Any]:
        """Return a fresh mutable patch for a UI or batch consumer."""
        return _thaw(self.params)


def _check_method(method: str) -> str:
    token = str(method)
    if token not in SUPPORTED_ANALYSIS_METHODS:
        raise ValueError(f"unsupported analysis method: {method!r}")
    return token


def resolve_builtin_preset_alias(method: str, key: str) -> str:
    """Resolve a legacy key without changing canonical method semantics."""
    token = _check_method(method)
    return _ALIASES.get(token, {}).get(str(key), str(key))


def get_builtin_preset(method: str, key: str) -> BuiltinAnalysisPreset:
    """Return a fresh immutable preset record, resolving supported aliases."""
    token = _check_method(method)
    canonical_key = resolve_builtin_preset_alias(token, key)
    try:
        patch = _PATCHES[token][canonical_key]
    except KeyError:
        raise KeyError((token, key)) from None
    aliases = tuple(
        alias
        for alias, target in _ALIASES.get(token, {}).items()
        if target == canonical_key
    )
    return BuiltinAnalysisPreset(
        method=token,
        key=canonical_key,
        display_name=BUILTIN_PRESET_DISPLAY[canonical_key],
        slot=PRESET_KEY_TO_SLOT[canonical_key],
        enabled=_ENABLED.get(token, {}).get(canonical_key, True),
        params=patch,
        aliases=aliases,
        blurb=BUILTIN_PRESET_BLURB[canonical_key],
    )


def list_builtin_presets(method: str) -> tuple[BuiltinAnalysisPreset, ...]:
    """Return fresh records in the stable PresetBar slot order."""
    token = _check_method(method)
    return tuple(get_builtin_preset(token, key) for key in BUILTIN_PRESET_KEYS)


def recommend_builtin_preset(unit: object) -> str:
    """Recommend a signal-type key by exact normalized unit match."""
    norm = normalize_unit(unit)
    if norm in _TORQUE_UNITS:
        return "torque"
    if norm in _VIBRATION_UNITS:
        return "vibration"
    return "vibration"


__all__ = [
    "BUILTIN_PRESET_BLURB",
    "BUILTIN_PRESET_DISPLAY",
    "BUILTIN_PRESET_KEYS",
    "BuiltinAnalysisPreset",
    "PRESET_KEY_TO_SLOT",
    "SUPPORTED_ANALYSIS_METHODS",
    "get_builtin_preset",
    "list_builtin_presets",
    "recommend_builtin_preset",
    "resolve_builtin_preset_alias",
]

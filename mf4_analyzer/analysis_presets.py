"""Pure built-in analysis preset catalog shared by UI and batch workflows.

The catalog owns only partial analysis-parameter patches.  Runtime scope,
signals, outputs, conflict policy, weighting and dB-reference state belong to
the live consumer and are intentionally absent here.

``cmap`` 同样**不属于**这里，别再加回来：色图由图表选项实时决定，FFT-vs-Time
面板恒定发 ``_FIXED_CMAP``、应用预设时显式跳过预设里的 cmap，批处理的参数表单
根本没有色图控件。fft_time 三个预设过去各带一个 cmap（torque=viridis、
vibration/transient=turbo），全程无人消费，纯粹是会误导人的死数据。

``periodic_window`` 与 ``detrend`` 是同一性质的幽灵键，已从 frf 三条预设里删除，
别再加回来：FRF 面板没有对应控件，``FrfContextual.compute_params`` 把两者硬编码成
``True`` / ``"constant"``（面板的 ``apply_params`` 连读都不读），而三条预设的取值
本来就全同——换预设永远不可能改变它们。留在目录里只会让人以为「稳健/低频/快速」
在去趋势或周期窗上有区别。批处理侧的 ``periodic_window`` / ``detrend``
（``batch_recipe`` 白名单、``batch_compute``、``signal.frf.FrfParams``）是活的，
不受影响：那是配方自己声明的字段，不是内建预设的补丁。

坐标轴显示范围（``x_auto``/``x_min``/``x_max`` · ``y_auto``/``y_min``/``y_max`` ·
``z_auto``/``z_floor``/``z_ceiling``）反过来**属于**这里：它们有真实控件、被
Inspector 与批处理输出面板双向消费，预设不带就等于「换预设不还原坐标轴」。
fft / fft_time / order_time 三个方法都带全套；frf 不带，因为 FRF 面板没有轴 spin。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .db_reference import normalize_unit


SUPPORTED_ANALYSIS_METHODS = ("fft", "fft_time", "frf", "order_time")
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

# FRF uses method-specific business names.  Keep the established three-method
# constants above unchanged because existing consumers intentionally share
# their frequency/balanced/time vocabulary.
_FRF_PRESET_KEYS = ("robust", "low_frequency", "fast")
_FRF_PRESET_DISPLAY = MappingProxyType({
    "robust": "稳健",
    "low_frequency": "低频",
    "fast": "快速",
})
_FRF_PRESET_BLURB = MappingProxyType({
    "robust": "通用设置，适合输出侧噪声占主导的常规系统辨识",
    "low_frequency": "更长分段，提高低频分辨率并要求更长记录",
    "fast": "更短分段，适合短记录和快速检查",
})
_FRF_PRESET_KEY_TO_SLOT = MappingProxyType(
    {"robust": 1, "low_frequency": 2, "fast": 3}
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
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
        },
        "vibration": {
            "window": "hanning", "nfft": "自动", "t_win_s": 1.5,
            "overlap": 50, "amp_y": "dB", "avg_mode": "线性平均",
            "avg_overlap": 50,
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
        },
        "transient": {
            "window": "hanning", "nfft": "自动", "t_win_s": 0.6,
            "overlap": 75, "amp_y": "dB", "avg_mode": "峰值保持",
            "avg_overlap": 75,
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
        },
    },
    "fft_time": {
        "torque": {
            "window": "flattop", "nfft": "自动", "nfft_mode": "auto",
            "t_win_s": 2.5, "overlap": 75,
            "amplitude_mode": "Amplitude dB", "remove_mean": True,
            "freq_auto": True, "freq_min": 0.0, "freq_max": 0.0,
            "dynamic": "Auto",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -40.0, "z_ceiling": 0.0,
        },
        "vibration": {
            "window": "hanning", "nfft": "自动", "nfft_mode": "auto",
            "t_win_s": 1.5, "overlap": 50,
            "amplitude_mode": "Amplitude dB", "remove_mean": True,
            "freq_auto": True, "freq_min": 0.0, "freq_max": 0.0,
            "dynamic": "Auto",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -40.0, "z_ceiling": 0.0,
        },
        "transient": {
            "window": "hanning", "nfft": "自动", "nfft_mode": "auto",
            "t_win_s": 0.6, "overlap": 75,
            "amplitude_mode": "Amplitude dB", "remove_mean": True,
            "freq_auto": True, "freq_min": 0.0, "freq_max": 0.0,
            "dynamic": "Auto",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -30.0, "z_ceiling": 0.0,
        },
    },
    "frf": {
        "robust": {
            "estimator": "h1", "window": "hanning", "t_win_s": 2.0, "overlap": 0.5,
            "nfft_mode": "auto", "nfft": None,
            "magnitude_scale": "db", "frequency_scale": "log",
            "phase_mode": "unwrapped", "coherence_threshold": 0.8,
            "fade_low_coherence": True,
        },
        "low_frequency": {
            "estimator": "h1", "window": "hanning", "t_win_s": 8.0, "overlap": 0.75,
            "nfft_mode": "auto", "nfft": None,
            "magnitude_scale": "db", "frequency_scale": "log",
            "phase_mode": "unwrapped", "coherence_threshold": 0.8,
            "fade_low_coherence": True,
        },
        "fast": {
            "estimator": "h1", "window": "hanning", "t_win_s": 0.5, "overlap": 0.5,
            "nfft_mode": "auto", "nfft": None,
            "magnitude_scale": "db", "frequency_scale": "log",
            "phase_mode": "unwrapped", "coherence_threshold": 0.8,
            "fade_low_coherence": True,
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
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -50.0, "z_ceiling": -10.0,
        },
        "vibration": {
            "max_order": 50, "order_res": 0.10, "time_res": 0.05,
            "nfft": "自动", "samples_per_rev": 512,
            "amplitude_mode": "Amplitude dB", "window": "hanning",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -50.0, "z_ceiling": -10.0,
        },
        "transient": {
            "max_order": 30, "order_res": 0.25, "time_res": 0.02,
            "nfft": "自动", "samples_per_rev": 256,
            "amplitude_mode": "Amplitude dB", "window": "hanning",
            "x_auto": True, "x_min": 0.0, "x_max": 0.0,
            "y_auto": True, "y_min": 0.0, "y_max": 0.0,
            "z_auto": True, "z_floor": -50.0, "z_ceiling": -10.0,
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
    if token == "frf":
        display_name = _FRF_PRESET_DISPLAY[canonical_key]
        slot = _FRF_PRESET_KEY_TO_SLOT[canonical_key]
        blurb = _FRF_PRESET_BLURB[canonical_key]
    else:
        display_name = BUILTIN_PRESET_DISPLAY[canonical_key]
        slot = PRESET_KEY_TO_SLOT[canonical_key]
        blurb = BUILTIN_PRESET_BLURB[canonical_key]
    return BuiltinAnalysisPreset(
        method=token,
        key=canonical_key,
        display_name=display_name,
        slot=slot,
        enabled=_ENABLED.get(token, {}).get(canonical_key, True),
        params=patch,
        aliases=aliases,
        blurb=blurb,
    )


def list_builtin_presets(method: str) -> tuple[BuiltinAnalysisPreset, ...]:
    """Return fresh records in the stable PresetBar slot order."""
    token = _check_method(method)
    keys = _FRF_PRESET_KEYS if token == "frf" else BUILTIN_PRESET_KEYS
    return tuple(get_builtin_preset(token, key) for key in keys)


def recommend_builtin_preset(unit: object) -> str | None:
    """Recommend a signal-type key by exact normalized unit match.

    Returns ``"torque"`` or ``"vibration"`` when ``unit`` matches a known
    alias set. Missing and unrecognized units return ``None`` rather than
    guessing a default.
    """
    norm = normalize_unit(unit)
    if norm in _TORQUE_UNITS:
        return "torque"
    if norm in _VIBRATION_UNITS:
        return "vibration"
    return None


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

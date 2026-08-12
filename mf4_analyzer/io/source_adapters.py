"""Pure-Python source adapter registry shared by import and batch workflows.

The registry is deliberately free of Qt.  It is the single declaration of
which source extensions the Analyzer understands and normalizes the three
return shapes exposed by :class:`~mf4_analyzer.io.loader.DataLoader`:

``(data, channels, units)``
    Standard single-source tabular/measurement loaders.
``(data, channels, units, fs, source_metadata)``
    Single-source loaders that carry an explicit sample rate or source facts.
``list[dict]``
    Measurement containers with multiple logical groups.

``probe_cost`` is intentionally honest.  MDF has a metadata-only probe; the
other existing parsers need to read/decode their source and are labelled
``"full"`` until a format-specific lightweight probe exists.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
import pandas as pd

try:
    from asammdf.blocks.utils import MdfException as _AsamMdfException
except ImportError:  # pragma: no cover - optional dependency boundary
    _AsamMdfException = None

from .file_data import FileData, _TIME_NAMES
from . import loader as _loader
from .loader import AUDIO_VIDEO_EXTS, DataLoader, unique_mdf_channel_locations


_MDF_PROBE_IO_ERRORS = (
    (OSError, _AsamMdfException)
    if _AsamMdfException is not None
    else (OSError,)
)


class UnsupportedSourceFormatError(ValueError):
    """Raised when no registered adapter owns a path's extension."""


class SourceUnavailableError(RuntimeError):
    """Raised when dependencies or caller-supplied context are incomplete."""


class SourceIdentityError(RuntimeError):
    """Raised when a loader returns colliding logical group identities."""


@dataclass(frozen=True)
class AdapterAvailability:
    """Current readiness of one adapter for an optional execution context."""

    status: str
    reason: str = ""
    missing_packages: tuple[str, ...] = ()
    missing_context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"ready", "limited", "unavailable"}:
            raise ValueError(f"unknown adapter availability status: {self.status}")

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @property
    def is_available(self) -> bool:
        return self.status != "unavailable"


@dataclass(frozen=True)
class SourceDescriptor:
    """Lightweight logical-source facts; never owns samples or a DataFrame."""

    source_id: str
    source_path: str
    group_id: str
    display_name: str
    channel_names: tuple[str, ...]
    units: Mapping[str, str | None]
    fs: float | None
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class LoadedSource:
    """A fully loaded logical source plus the identity used during probe."""

    source_id: str
    source_path: str
    group_id: str
    display_name: str
    file_data: FileData
    metadata: Mapping[str, object]


def _package_available(package: str) -> bool:
    try:
        return importlib.util.find_spec(package) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def canonical_source_path(path: os.PathLike[str] | str) -> str:
    """Return the canonical physical-path identity used by every adapter."""
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def stable_source_id(adapter_key: str, source_path: str, group_id: str) -> str:
    """Build a stable, path-and-group-aware logical source identifier."""
    payload = json.dumps(
        {
            "adapter": str(adapter_key),
            "path": canonical_source_path(source_path),
            "group": str(group_id),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"{adapter_key}:{digest}"


def _signal_channels(channels) -> tuple[str, ...]:
    return tuple(
        str(name) for name in channels
        if str(name).strip() and str(name).lower() not in _TIME_NAMES
    )


def _finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _float_token(value) -> str:
    number = _finite_float(value)
    return "none" if number is None else number.hex()


def _axis_facts(data: pd.DataFrame) -> tuple[int, float | None, float | None]:
    n = int(len(data))
    time_column = next(
        (name for name in data.columns if str(name).lower() in _TIME_NAMES),
        None,
    )
    if time_column is None or n == 0:
        return n, None, None
    values = np.asarray(data[time_column], dtype=float)
    t0 = _finite_float(values[0]) if values.size else None
    dt = None
    if values.size >= 2:
        candidate = _finite_float(values[1] - values[0])
        if candidate is not None and candidate > 0:
            dt = candidate
    return n, dt, t0


def _group_identity(adapter_key: str, group: Mapping[str, object]) -> str:
    data = group.get("data")
    if not isinstance(data, pd.DataFrame):
        raise TypeError("group loader result requires a pandas DataFrame in 'data'")
    n, dt, t0 = _axis_facts(data)
    channel_metadata = group.get("channel_metadata")
    channel_metadata = channel_metadata if isinstance(channel_metadata, Mapping) else {}

    if adapter_key == "wwt":
        return f"wwt:n={n}:dt={_float_token(dt)}:t0={_float_token(t0)}"
    if adapter_key == "zfd":
        return f"zfd:count={n}:dt={_float_token(dt)}"
    if adapter_key == "mat":
        return f"mat:length={n}:dt={_float_token(dt)}"
    if adapter_key == "hdf":
        factors = sorted({
            str(facts.get("raster_factor"))
            for facts in channel_metadata.values()
            if isinstance(facts, Mapping) and facts.get("raster_factor") is not None
        })
        factor_token = ",".join(factors) if factors else "unknown"
        return (
            f"hdf:raster_factor={factor_token}:n={n}:"
            f"dt={_float_token(dt)}:t0={_float_token(t0)}"
        )
    return (
        f"{adapter_key}:n={n}:dt={_float_token(dt)}:"
        f"t0={_float_token(t0)}"
    )


def _safe_metadata(value):
    """Copy probe metadata without retaining samples or pandas containers."""
    if isinstance(value, Mapping):
        return {
            str(key): _safe_metadata(item)
            for key, item in value.items()
            if not isinstance(item, (pd.DataFrame, pd.Series))
        }
    if isinstance(value, (pd.DataFrame, pd.Series, np.ndarray)):
        return "<sample data omitted>"
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_safe_metadata(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _descriptor_from_loaded(
    loaded: LoadedSource,
    *,
    adapter_key: str,
    probe_cost: str,
) -> SourceDescriptor:
    fd = loaded.file_data
    channels = _signal_channels(fd.channels)
    units = {name: str(fd.channel_units.get(name, "") or "") for name in channels}
    metadata = _safe_metadata(dict(loaded.metadata))
    metadata.update({"adapter_key": adapter_key, "probe_cost": probe_cost})
    return SourceDescriptor(
        source_id=loaded.source_id,
        source_path=loaded.source_path,
        group_id=loaded.group_id,
        display_name=loaded.display_name,
        channel_names=channels,
        units=units,
        fs=_finite_float(fd.fs),
        metadata=metadata,
    )


def _mdf_channel_facts(mdf) -> tuple[tuple[str, ...], dict, dict]:
    locations = unique_mdf_channel_locations(mdf)
    channels = []
    units = {}
    channel_metadata = {}
    for display_name, (group_index, channel_index) in locations.items():
        name = str(display_name)
        if name.lower() in _TIME_NAMES:
            continue
        try:
            channel = mdf.groups[group_index].channels[channel_index]
        except Exception:
            channel = None
        if channel is None:
            unit = None
            source = None
        else:
            conversion = getattr(channel, "conversion", None)
            raw_unit = (
                getattr(conversion, "unit", None)
                if conversion is not None
                else None
            )
            if raw_unit in (None, ""):
                raw_unit = getattr(channel, "unit", None)
            # Lookup succeeded: empty/missing unit stays "" so it stays
            # distinguishable from a failed channel lookup (None).
            unit = "" if raw_unit in (None, "") else str(raw_unit)
            source = getattr(channel, "source", None)
        channels.append(name)
        units[name] = unit
        channel_metadata[name] = {
            "physical_occurrence": (int(group_index), int(channel_index)),
            "unit": unit,
            "source_path": str(getattr(source, "path", "") or ""),
        }
    return tuple(channels), units, channel_metadata


def _probe_mdf(path: str, adapter: "SourceAdapter") -> tuple[SourceDescriptor, ...]:
    MDF = getattr(_loader, "MDF", None)
    if MDF is None:  # pragma: no cover - guarded by availability
        raise SourceUnavailableError("asammdf is required for MDF sources")

    canonical = canonical_source_path(path)
    mdf = None
    try:
        mdf = MDF(path)
        channels, units, channel_metadata = _mdf_channel_facts(mdf)
    except _MDF_PROBE_IO_ERRORS as exc:
        raise SourceUnavailableError(
            f'MDF metadata unavailable for "{path}": {exc}'
        ) from exc
    finally:
        if mdf is not None:
            try:
                mdf.close()
            except Exception:
                pass
    if not channels:
        raise ValueError("MDF file has no numeric signal metadata")
    group_id = "root"
    return (SourceDescriptor(
        source_id=stable_source_id(adapter.key, canonical, group_id),
        source_path=canonical,
        group_id=group_id,
        display_name=Path(path).name,
        channel_names=channels,
        units=units,
        fs=None,
        metadata={
            "adapter_key": adapter.key,
            "probe_cost": adapter.probe_cost,
            "channel_metadata": channel_metadata,
            "channel_metadata_capability": "unit_and_physical_occurrence",
            "quantity_reference_metadata": False,
        },
    ),)


def _probe_blf(
    path: str,
    adapter: "SourceAdapter",
    context: Mapping[str, object],
) -> tuple[SourceDescriptor, ...]:
    dbc_paths = tuple(str(item) for item in context.get("dbc_paths", ()) if item)
    result = DataLoader.probe_blf_dbc(path, list(dbc_paths))
    if not getattr(result, "is_match", False):
        raise ValueError("CAN 日志与所选 DBC 不匹配，无法生成信号级来源")
    canonical = canonical_source_path(path)
    group_id = "root"
    names = tuple(str(name) for name in getattr(result, "signal_names", ()))
    source_kind = (
        "canoe_asc" if Path(path).suffix.lower() == ".asc" else "blf"
    )
    return (SourceDescriptor(
        source_id=stable_source_id(adapter.key, canonical, group_id),
        source_path=canonical,
        group_id=group_id,
        display_name=Path(path).name,
        channel_names=names,
        units={name: "" for name in names},
        fs=None,
        metadata={
            "adapter_key": adapter.key,
            "probe_cost": adapter.probe_cost,
            "source_kind": source_kind,
            "dbc_paths": dbc_paths,
            "dbc_strength": str(getattr(result, "strength", "")),
            "decoded_signal_count": int(
                getattr(result, "decoded_signal_count", len(names))
            ),
        },
    ),)


@dataclass(frozen=True)
class SourceAdapter:
    """One registered source family and its probe/load normalization rules."""

    key: str
    extensions: tuple[str, ...]
    display_name: str
    loader_name: str
    return_shape: str
    optional_packages: tuple[str, ...] = ()
    context_requirements: tuple[str, ...] = ()
    may_return_multiple: bool = False
    probe_cost: str = "full"
    capability_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.return_shape not in {"single3", "single5", "groups"}:
            raise ValueError(f"unknown loader return shape: {self.return_shape}")
        if self.probe_cost not in {"metadata", "full"}:
            raise ValueError(f"unknown probe cost: {self.probe_cost}")

    def availability(
        self, context: Mapping[str, object] | None = None,
    ) -> AdapterAvailability:
        context = dict(context or {})
        missing_packages = tuple(
            package for package in self.optional_packages
            if not _package_available(package)
        )
        if missing_packages:
            return AdapterAvailability(
                "unavailable",
                "缺少运行依赖: " + ", ".join(missing_packages),
                missing_packages=missing_packages,
            )
        missing_context = tuple(
            key for key in self.context_requirements if not context.get(key)
        )
        if missing_context:
            reason = (
                "CAN 日志（BLF/CANoe ASC）需要 DBC 解码上下文，raw CAN frame "
                "不作为批处理信号来源"
                if self.key == "blf"
                else "缺少来源上下文: " + ", ".join(missing_context)
            )
            return AdapterAvailability(
                "limited",
                reason,
                missing_context=missing_context,
            )
        return AdapterAvailability("ready")

    def _require_ready(self, context: Mapping[str, object] | None) -> dict:
        normalized = dict(context or {})
        availability = self.availability(normalized)
        if not availability.is_ready:
            raise SourceUnavailableError(availability.reason)
        return normalized

    def probe_sources(
        self,
        path: os.PathLike[str] | str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> tuple[SourceDescriptor, ...]:
        normalized = self._require_ready(context)
        text_path = os.fspath(path)
        if self.key == "mdf":
            return _probe_mdf(text_path, self)
        if self.key == "blf":
            return _probe_blf(text_path, self, normalized)
        return tuple(
            _descriptor_from_loaded(
                source,
                adapter_key=self.key,
                probe_cost=self.probe_cost,
            )
            for source in self.load_sources(text_path, context=normalized)
        )

    def load_sources(
        self,
        path: os.PathLike[str] | str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> tuple[LoadedSource, ...]:
        normalized = self._require_ready(context)
        text_path = os.fspath(path)
        loader: Callable = getattr(DataLoader, self.loader_name)
        if self.key == "blf":
            result = loader(
                text_path,
                dbc_paths=list(normalized.get("dbc_paths", ())),
            )
        else:
            result = loader(text_path)
        if self.return_shape == "groups":
            return self._loaded_groups(text_path, result)
        return (self._loaded_single(text_path, result),)

    def _loaded_single(self, path: str, result) -> LoadedSource:
        if not isinstance(result, tuple) or len(result) not in {3, 5}:
            raise TypeError(
                f"{self.loader_name} returned an invalid {self.return_shape} result"
            )
        data, channels, units = result[:3]
        if not isinstance(data, pd.DataFrame):
            raise TypeError(f"{self.loader_name} must return a pandas DataFrame")
        fs = result[3] if len(result) == 5 else None
        source_metadata = dict(result[4] or {}) if len(result) == 5 else {}
        source_metadata.update({
            "adapter_key": self.key,
            "capability_notes": self.capability_notes,
        })
        canonical = canonical_source_path(path)
        group_id = "root"
        channel_metadata = {}
        if self.key == "mdf":
            # Preserve the current loader's honest boundary.  Units and
            # physical occurrences are available from metadata; richer
            # quantity/reference facts are not inferred.
            source_metadata.update({
                "channel_metadata_capability": "unit_and_physical_occurrence",
                "quantity_reference_metadata": False,
            })
        fd = FileData(
            canonical,
            data,
            list(channels),
            dict(units),
            fs=fs,
            source_metadata=source_metadata,
            channel_metadata=channel_metadata,
        )
        return LoadedSource(
            source_id=stable_source_id(self.key, canonical, group_id),
            source_path=canonical,
            group_id=group_id,
            display_name=Path(path).name,
            file_data=fd,
            metadata=dict(source_metadata),
        )

    def _loaded_groups(self, path: str, groups) -> tuple[LoadedSource, ...]:
        if not isinstance(groups, (list, tuple)):
            raise TypeError(f"{self.loader_name} must return a group list")
        canonical = canonical_source_path(path)
        loaded = []
        seen_group_ids = set()
        for group in groups:
            if not isinstance(group, Mapping):
                raise TypeError(f"{self.loader_name} group entries must be mappings")
            group_id = _group_identity(self.key, group)
            if group_id in seen_group_ids:
                raise SourceIdentityError(
                    f"{Path(path).name} returned duplicate group identity {group_id}"
                )
            seen_group_ids.add(group_id)
            data = group.get("data")
            channels = list(group.get("channels") or ())
            units = dict(group.get("units") or {})
            source_metadata = dict(group.get("source_metadata") or {})
            channel_metadata = dict(group.get("channel_metadata") or {})
            label_suffix = str(group.get("label_suffix") or "")
            source_metadata.update({
                "adapter_key": self.key,
                "group_id": group_id,
                "capability_notes": self.capability_notes,
                "channel_metadata": channel_metadata,
            })
            fd = FileData(
                canonical,
                data,
                channels,
                units,
                source_metadata=source_metadata,
                channel_metadata=channel_metadata,
                label_suffix=label_suffix,
            )
            display_name = Path(path).name
            if label_suffix:
                display_name = f"{display_name} ·{label_suffix}"
            loaded.append(LoadedSource(
                source_id=stable_source_id(self.key, canonical, group_id),
                source_path=canonical,
                group_id=group_id,
                display_name=display_name,
                file_data=fd,
                metadata=dict(source_metadata),
            ))
        return tuple(loaded)


def _default_adapters() -> tuple[SourceAdapter, ...]:
    return (
        SourceAdapter(
            "mdf", (".mf4", ".mdf"), "ASAM MDF", "load_mf4", "single3",
            optional_packages=("asammdf",), probe_cost="metadata",
            capability_notes=(
                "physical occurrence dedupe preserved",
                "quantity/reference metadata not yet exposed by DataLoader",
            ),
        ),
        SourceAdapter(
            "blf", (".blf",), "Vector CAN 日志 (BLF/ASC) + DBC", "load_blf", "single3",
            optional_packages=("can", "cantools"),
            context_requirements=("dbc_paths",),
            capability_notes=("decoded signals require explicit DBC context",),
        ),
        SourceAdapter(
            "tdms", (".tdms",), "NI TDMS", "load_tdms", "single5",
            optional_packages=("nptdms",),
            capability_notes=("current DataLoader flattens TDMS groups",),
        ),
        SourceAdapter(
            "tabular", (".csv", ".fdc"), "CSV / FDC", "load_csv", "single3",
        ),
        SourceAdapter(
            "ascii", (".asc",), "ASCII table", "load_ascii", "single5",
        ),
        SourceAdapter(
            "excel_xlsx", (".xlsx",), "Excel workbook", "load_excel", "single3",
            optional_packages=("openpyxl",),
        ),
        SourceAdapter(
            "excel_xls", (".xls",), "Legacy Excel workbook", "load_excel", "single3",
            optional_packages=("xlrd",),
        ),
        SourceAdapter(
            "hdf", (".hdf",), "HEAD HDF", "load_hdf", "groups",
            may_return_multiple=True,
        ),
        SourceAdapter(
            "wwt", (".wwt",), "WinWert WWT", "load_wwt", "groups",
            may_return_multiple=True,
        ),
        SourceAdapter(
            "zfd", (".zfd",), "ZwickRoell ZFD", "load_zfd", "groups",
            may_return_multiple=True,
        ),
        SourceAdapter(
            "mat", (".mat",), "MATLAB MAT", "load_mat", "groups",
            optional_packages=("scipy", "h5py"), may_return_multiple=True,
        ),
        SourceAdapter(
            "media", tuple(sorted(AUDIO_VIDEO_EXTS)), "Audio / Video",
            "load_audio_video", "single5", optional_packages=("av",),
        ),
    )


class SourceAdapterRegistry:
    """Extension-indexed immutable registry of source adapters."""

    def __init__(self, adapters: tuple[SourceAdapter, ...]):
        self._adapters = tuple(adapters)
        by_extension = {}
        for adapter in self._adapters:
            for extension in adapter.extensions:
                normalized = str(extension).lower()
                if not normalized.startswith("."):
                    normalized = f".{normalized}"
                if normalized in by_extension:
                    raise ValueError(f"duplicate source extension: {normalized}")
                by_extension[normalized] = adapter
        self._by_extension = by_extension

    @classmethod
    def default(cls) -> "SourceAdapterRegistry":
        return cls(_default_adapters())

    @property
    def adapters(self) -> tuple[SourceAdapter, ...]:
        return self._adapters

    @property
    def supported_extensions(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_extension))

    @property
    def file_dialog_glob(self) -> str:
        return " ".join(f"*{extension}" for extension in self.supported_extensions)

    def adapter_for(self, path_or_extension: os.PathLike[str] | str) -> SourceAdapter:
        raw = os.fspath(path_or_extension)
        extension = raw.lower() if raw.startswith(".") else Path(raw).suffix.lower()
        if not extension:
            raise UnsupportedSourceFormatError(
                f"Unsupported source format: no extension ({raw})"
            )
        # Same extension, two formats: sniff real .asc paths for CANoe logs and
        # route them onto the BLF adapter. Bare ".asc" / missing files stay ascii.
        if extension == ".asc" and not raw.startswith("."):
            try:
                from .asc_can_format import sniff_canoe_asc
                if sniff_canoe_asc(raw):
                    return self._by_extension[".blf"]
            except ImportError as exc:
                raise ImportError(
                    "python-can 未安装，无法识别 CANoe ASC 文件。"
                    "请先 pip install python-can"
                ) from exc
            except Exception:
                pass
        try:
            return self._by_extension[extension]
        except KeyError as exc:
            raise UnsupportedSourceFormatError(
                f"Unsupported source format: {extension}"
            ) from exc

    def availability_for(
        self,
        path_or_extension: os.PathLike[str] | str,
        context: Mapping[str, object] | None = None,
    ) -> AdapterAvailability:
        return self.adapter_for(path_or_extension).availability(context)

    def probe_sources(
        self,
        path: os.PathLike[str] | str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> tuple[SourceDescriptor, ...]:
        return self.adapter_for(path).probe_sources(path, context=context)

    def load_sources(
        self,
        path: os.PathLike[str] | str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> tuple[LoadedSource, ...]:
        return self.adapter_for(path).load_sources(path, context=context)


DEFAULT_SOURCE_ADAPTER_REGISTRY = SourceAdapterRegistry.default()


__all__ = [
    "AdapterAvailability",
    "DEFAULT_SOURCE_ADAPTER_REGISTRY",
    "LoadedSource",
    "SourceAdapter",
    "SourceAdapterRegistry",
    "SourceDescriptor",
    "SourceIdentityError",
    "SourceUnavailableError",
    "UnsupportedSourceFormatError",
    "canonical_source_path",
    "stable_source_id",
]

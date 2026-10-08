"""Versioned, immutable heatmap palettes; standard library only.

The packaged catalog is the sole ordered list. RGB data are validated before
caching; presentation adapters must never change these versioned bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib import resources
import json
from pathlib import Path, PurePosixPath
import re

DEFAULT_HEATMAP_CMAP = "tracelab.head-style.v1"
FALLBACK_HEATMAP_CMAP = "gnuplot2"


class UnknownColormapError(ValueError):
    """A project or caller requested an unregistered palette ID."""


class ColormapResourceError(ValueError):
    """A registered palette violates the shipped resource contract."""


@dataclass(frozen=True)
class ColormapSpec:
    id: str
    label: str
    provider: str
    name: str | None = None
    file: str | None = None
    rgb_sha256: str | None = None


def _resource_root():
    return resources.files(__package__).joinpath("resources")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ColormapResourceError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ColormapResourceError(f"{path}: {exc}") from exc


def _fields(value, expected, context):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ColormapResourceError(f"{context}: expected fields {sorted(expected)}")


def _schema(value, context):
    if type(value) is not int or value != 1:
        raise ColormapResourceError(f"{context}: unsupported schema_version {value!r}")


def _resource_path(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ColormapResourceError("LUT file must be a nonempty relative JSON path")
    path = PurePosixPath(relative)
    if (
        path.is_absolute() or "\\" in relative or ":" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or path.suffix != ".json" or path.parts[0] != "luts"
    ):
        raise ColormapResourceError(f"unsafe LUT resource path: {relative!r}")
    target = root.joinpath(*path.parts)
    # Traversables also support zipped packages. Filesystem resources additionally
    # reject symlinks that escape the resource directory.
    if isinstance(root, Path) and not target.resolve().is_relative_to(root.resolve()):
        raise ColormapResourceError(f"LUT resource escapes package: {relative!r}")
    return target


def _read_specs(root):
    data = _read_json(root.joinpath("catalog.json"))
    _fields(data, {"schema_version", "entries"}, "catalog")
    _schema(data["schema_version"], "catalog")
    if not isinstance(data["entries"], list) or not data["entries"]:
        raise ColormapResourceError("catalog: entries must be a nonempty list")
    specs, ids, files = [], set(), set()
    providers = {
        "legacy_gnuplot2": set(), "pyqtgraph": {"name"},
        "rgb_lut": {"file", "rgb_sha256"},
    }
    for entry in data["entries"]:
        if (
            not isinstance(entry, dict) or not isinstance(entry.get("provider"), str)
            or entry["provider"] not in providers
        ):
            raise ColormapResourceError(f"catalog: unsupported provider in {entry!r}")
        provider = entry["provider"]
        _fields(entry, {"id", "label", "provider"} | providers[provider], "catalog entry")
        if any(not isinstance(v, str) or not v.strip() for v in entry.values()):
            raise ColormapResourceError("catalog entry: all values must be nonempty strings")
        ident = entry["id"]
        if ident in ids:
            raise ColormapResourceError(f"catalog: duplicate ID {ident!r}")
        ids.add(ident)
        if provider == "legacy_gnuplot2" and ident != "gnuplot2":
            raise ColormapResourceError("legacy_gnuplot2 provider is reserved for gnuplot2")
        if provider == "rgb_lut":
            if not re.fullmatch(r"tracelab\.[a-z0-9]+(?:-[a-z0-9]+)*\.v[1-9][0-9]*", ident):
                raise ColormapResourceError(f"invalid versioned RGB LUT ID: {ident!r}")
            _resource_path(root, entry["file"])
            if entry["file"] in files:
                raise ColormapResourceError(f"duplicate LUT file reference: {entry['file']}")
            files.add(entry["file"])
            if not re.fullmatch(r"[0-9a-f]{64}", entry["rgb_sha256"]):
                raise ColormapResourceError(f"invalid RGB SHA-256 for {ident}")
        specs.append(ColormapSpec(**entry))
    legacy = ("gnuplot2", "turbo", "viridis", "plasma", "inferno", "magma", "cividis")
    if tuple(spec.id for spec in specs[:7]) != legacy:
        raise ColormapResourceError("catalog must preserve the seven legacy IDs and their order")
    for spec in specs[:7]:
        expected = "legacy_gnuplot2" if spec.id == "gnuplot2" else "pyqtgraph"
        if spec.provider != expected or (expected == "pyqtgraph" and spec.name != spec.id):
            raise ColormapResourceError(f"legacy provider changed for {spec.id}")
    if DEFAULT_HEATMAP_CMAP not in ids:
        raise ColormapResourceError("catalog does not contain the default heatmap colormap")
    return tuple(specs)


@lru_cache(maxsize=1)
def list_colormap_specs() -> tuple[ColormapSpec, ...]:
    return _read_specs(_resource_root())


def get_colormap_spec(ident: str) -> ColormapSpec:
    for spec in list_colormap_specs():
        if spec.id == ident:
            return spec
    raise UnknownColormapError(f"unknown heatmap colormap: {ident!r}")


def _read_lut(root, spec):
    if spec.provider != "rgb_lut":
        raise ColormapResourceError(f"{spec.id}: provider {spec.provider} is not an RGB resource")
    target = _resource_path(root, spec.file)
    data = _read_json(target)
    context = str(target)
    _fields(data, {
        "schema_version", "id", "color_space", "encoding", "sample_count",
        "sampling", "evidence_level", "source_note", "rgb",
    }, context)
    _schema(data["schema_version"], context)
    fixed = {"id": spec.id, "color_space": "srgb", "encoding": "uint8-rgb", "sampling": "uniform-0-1"}
    if any(data[key] != expected for key, expected in fixed.items()):
        raise ColormapResourceError(f"{context}: incompatible identity/encoding/sampling")
    if type(data["sample_count"]) is not int or data["sample_count"] != 256:
        raise ColormapResourceError(f"{context}: sample_count must be 256")
    if not isinstance(data["evidence_level"], str) or data["evidence_level"] not in {
        "original_design", "screenshot_approximation", "reference_lut_verified", "reference_render_verified",
    }:
        raise ColormapResourceError(f"{context}: unknown evidence_level")
    if not isinstance(data["source_note"], str) or not data["source_note"].strip():
        raise ColormapResourceError(f"{context}: source_note must be nonempty")
    rgb = data["rgb"]
    if (
        not isinstance(rgb, list) or len(rgb) != 256
        or any(not isinstance(row, list) or len(row) != 3 for row in rgb)
        or any(type(v) is not int or not 0 <= v <= 255 for row in rgb for v in row)
    ):
        raise ColormapResourceError(f"{context}: expected 256 RGB triples of uint8 integers")
    digest = hashlib.sha256(bytes(v for row in rgb for v in row)).hexdigest()
    if digest != spec.rgb_sha256:
        raise ColormapResourceError(f"{context}: RGB SHA-256 mismatch ({digest})")
    return tuple(tuple(row) for row in rgb)


@lru_cache(maxsize=None)
def load_rgb_lut(ident: str) -> tuple[tuple[int, int, int], ...]:
    return _read_lut(_resource_root(), get_colormap_spec(ident))


def _json_resources(node, relative="luts"):
    for child in node.iterdir():
        name = f"{relative}/{child.name}"
        if child.is_dir():
            # Reject directory symlinks too: recursive validation must not escape
            # the package, nor follow a cycle inside it.
            if isinstance(child, Path) and child.is_symlink():
                raise ColormapResourceError(f"symlink LUT directory: {name}")
            yield from _json_resources(child, name)
        elif child.name.endswith(".json"):
            yield name


def validate_colormap_resources() -> tuple[ColormapSpec, ...]:
    """Validate fresh packaged data, including unregistered LUT files."""
    root = _resource_root()
    specs = _read_specs(root)
    expected = set()
    resolved = set()
    for spec in specs:
        if spec.provider == "rgb_lut":
            target = _resource_path(root, spec.file)
            identity = str(target.resolve()) if isinstance(target, Path) else spec.file
            if identity in resolved:
                raise ColormapResourceError(f"duplicate resolved LUT resource: {spec.file}")
            resolved.add(identity)
            expected.add(spec.file)
            _read_lut(root, spec)
    actual = set(_json_resources(root.joinpath("luts")))
    if actual != expected:
        raise ColormapResourceError(f"LUT registration mismatch: orphan={sorted(actual - expected)}, missing={sorted(expected - actual)}")
    return specs


SUPPORTED_HEATMAP_COLORMAPS = tuple(spec.id for spec in list_colormap_specs())

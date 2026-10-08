"""Resource integrity, reproducibility and neutral import contract."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from mf4_analyzer.colormaps import registry


@pytest.fixture
def resources_copy(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    shutil.copytree(registry._resource_root(), root)
    monkeypatch.setattr(registry, "_resource_root", lambda: root)
    registry.list_colormap_specs.cache_clear()
    registry.load_rgb_lut.cache_clear()
    yield root
    registry.list_colormap_specs.cache_clear()
    registry.load_rgb_lut.cache_clear()


def _edit(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_head_version_is_immutable_and_complete():
    specs = registry.validate_colormap_resources()
    assert registry.SUPPORTED_HEATMAP_COLORMAPS == tuple(s.id for s in specs)
    assert registry.DEFAULT_HEATMAP_CMAP == "tracelab.head-style.v1"
    assert registry.FALLBACK_HEATMAP_CMAP == "gnuplot2"
    spec = registry.get_colormap_spec(registry.DEFAULT_HEATMAP_CMAP)
    rgb = registry.load_rgb_lut(spec.id)
    assert isinstance(rgb, tuple) and all(isinstance(row, tuple) for row in rgb)
    assert len(rgb) == 256
    assert hashlib.sha256(bytes(v for row in rgb for v in row)).hexdigest() == "76035b39ed2f1223139896d983808146d89f21295f0db78a5c20e1057048d79d"
    with pytest.raises(FrozenInstanceError):
        spec.id = "changed"
    with pytest.raises(TypeError):
        rgb[0][0] = 1


def test_unknown_and_nonresource_provider_are_explicit():
    with pytest.raises(registry.UnknownColormapError):
        registry.load_rgb_lut("not-installed")
    with pytest.raises(registry.ColormapResourceError, match="not an RGB resource"):
        registry.load_rgb_lut("gnuplot2")


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("id", "wrong"),
    ("encoding", "float-rgb"), ("color_space", "linear"),
    ("sampling", "anchors"), ("sample_count", 255), ("sample_count", 256.0),
    ("evidence_level", "official"), ("evidence_level", []), ("source_note", ""),
    ("rgb", []), ("rgb", [[0, 0, 0]] * 255),
    ("rgb", [[0, 0]] * 256), ("rgb", [[0, 0, 0, 255]] * 256),
    ("rgb", [[True, 0, 0]] * 256), ("rgb", [[0.0, 0, 0]] * 256),
    ("rgb", [[-1, 0, 0]] * 256), ("rgb", [[256, 0, 0]] * 256),
    ("rgb", [[float("nan"), 0, 0]] * 256),
    ("rgb", [[float("inf"), 0, 0]] * 256),
])
def test_rejects_invalid_lut(resources_copy, field, value):
    _edit(resources_copy / "luts/head-style-v1.json", lambda data: data.update({field: value}))
    with pytest.raises(registry.ColormapResourceError):
        registry.load_rgb_lut(registry.DEFAULT_HEATMAP_CMAP)


@pytest.mark.parametrize("relative", ["/tmp/map.json", "../map.json", "luts/../map.json", "luts\\map.json", "C:/map.json", "luts//map.json", "luts/./map.json", "luts/map.txt"])
def test_rejects_unsafe_resource_paths(resources_copy, relative):
    _edit(resources_copy / "catalog.json", lambda data: data["entries"][-1].update(file=relative))
    with pytest.raises(registry.ColormapResourceError):
        registry.list_colormap_specs()


@pytest.mark.parametrize("relative", ["catalog.json", "luts/head-style-v1.json"])
def test_duplicate_json_keys_rejected(resources_copy, relative):
    path = resources_copy / relative
    path.write_text(path.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1))
    with pytest.raises(registry.ColormapResourceError, match="duplicate JSON key"):
        registry.validate_colormap_resources()


@pytest.mark.parametrize("change", [
    lambda data: data.update(scehma_version=1),
    lambda data: data["entries"].append(data["entries"][-1].copy()),
    lambda data: data["entries"][-1].update(provider="import-python"),
    lambda data: data["entries"][-1].update(provider=[]),
    lambda data: data["entries"][-1].update(id="gnuplot2"),
    lambda data: data["entries"][-1].update(id="tracelab.invalid.v0"),
    lambda data: data["entries"][-1].update(rgb_sha256="bad"),
    lambda data: data["entries"][1].update(name="viridis"),
    lambda data: data["entries"][-1].update(lable="typo"),
])
def test_rejects_catalog_contract_errors(resources_copy, change):
    _edit(resources_copy / "catalog.json", change)
    with pytest.raises(registry.ColormapResourceError):
        registry.validate_colormap_resources()


def test_hash_failure_is_not_a_fallback(resources_copy):
    _edit(resources_copy / "luts/head-style-v1.json", lambda data: data["rgb"][0].__setitem__(0, 1))
    with pytest.raises(registry.ColormapResourceError, match="SHA-256 mismatch"):
        registry.load_rgb_lut(registry.DEFAULT_HEATMAP_CMAP)


def test_missing_and_orphan_resource_fail_validation(resources_copy):
    lut = resources_copy / "luts/head-style-v1.json"
    orphan = resources_copy / "luts/orphan.json"
    orphan.write_text(lut.read_text())
    with pytest.raises(registry.ColormapResourceError, match="orphan"):
        registry.validate_colormap_resources()
    orphan.unlink()
    lut.unlink()
    with pytest.raises(registry.ColormapResourceError, match="head-style-v1.json"):
        registry.validate_colormap_resources()


def test_outside_symlink_is_rejected(resources_copy, tmp_path):
    lut = resources_copy / "luts/head-style-v1.json"
    outside = tmp_path / "outside.json"
    lut.replace(outside)
    lut.symlink_to(outside)
    with pytest.raises(registry.ColormapResourceError, match="escapes"):
        registry.validate_colormap_resources()


def test_stdlib_import_and_resource_loading_are_cwd_independent(tmp_path):
    code = '''
import sys
from mf4_analyzer.colormaps import validate_colormap_resources
validate_colormap_resources()
assert not any(k == 'numpy' or k.startswith(('PyQt5', 'pyqtgraph', 'mf4_analyzer.ui', 'mf4_analyzer.signal')) for k in sys.modules)
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_duplicate_file_reference_rejected(resources_copy):
    def change(data):
        entry = dict(data["entries"][-1], id="tracelab.other.v1")
        data["entries"].append(entry)
    _edit(resources_copy / "catalog.json", change)
    with pytest.raises(registry.ColormapResourceError, match="duplicate LUT file"):
        registry.validate_colormap_resources()


def test_lut_typos_and_malformed_json_include_resource_context(resources_copy):
    lut = resources_copy / "luts/head-style-v1.json"
    _edit(lut, lambda data: data.update(colour_space="srgb"))
    with pytest.raises(registry.ColormapResourceError, match="head-style-v1.json"):
        registry.validate_colormap_resources()
    lut.write_text("{ invalid JSON")
    with pytest.raises(registry.ColormapResourceError, match="head-style-v1.json"):
        registry.validate_colormap_resources()


def test_json_formatting_does_not_change_byte_identity(resources_copy):
    lut = resources_copy / "luts/head-style-v1.json"
    lut.write_text(json.dumps(json.loads(lut.read_text()), separators=(",", ":")))
    assert registry.validate_colormap_resources()[-1].id == registry.DEFAULT_HEATMAP_CMAP


def test_directory_symlink_cycle_rejected(resources_copy):
    (resources_copy / "luts/cycle").symlink_to(resources_copy / "luts", target_is_directory=True)
    with pytest.raises(registry.ColormapResourceError, match="symlink LUT directory"):
        registry.validate_colormap_resources()

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["build_windows_folder.ps1", "build_windows_folder_lite.ps1",
                                   "build_windows_folder_lite_modular.ps1"])
def test_native_reader_build_precedes_requirement_install_and_worker_is_collected(name):
    text = (ROOT / "tools" / name).read_text()
    assert "dependency_patches\\asammdf\\build_wheel.py" in text
    assert text.index('"--output", $MdfWheelDir') < text.index('"--find-links", $MdfWheelDir')
    assert "mf4_analyzer.io.import_worker" in text
    assert "mf4_analyzer.io.import_transport" in text
    assert "mf4_analyzer.ui.main_window.import_coordinator" in text
    assert "asammdf-8.8.32+tracelab.1-source.tar.gz" in text
    assert "_require_fixed_arrays" in text


def _asammdf_build_wheel():
    path = ROOT / "tools" / "dependency_patches" / "asammdf" / "build_wheel.py"
    spec = importlib.util.spec_from_file_location("asammdf_build_wheel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asammdf_patch_lock_accepts_crlf_working_copy(tmp_path):
    module = _asammdf_build_wheel()
    root = ROOT / "tools" / "dependency_patches" / "asammdf"
    lock = json.loads((root / "source.lock.json").read_text(encoding="utf-8"))
    for name, expected in lock["patches"].items():
        payload = module.patch_bytes(root / name)
        assert b"\r" not in payload
        assert hashlib.sha256(payload).hexdigest() == expected
        copied = tmp_path / name
        copied.write_bytes(payload.replace(b"\n", b"\r\n"))
        assert module.patch_bytes(copied) == payload

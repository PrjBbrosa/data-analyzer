import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["build_windows_folder.ps1", "build_windows_folder_lite.ps1",
                                   "build_windows_folder_lite_modular.ps1"])
def test_native_reader_build_precedes_requirement_install_and_worker_is_collected(name):
    text = (ROOT / "tools" / name).read_text(encoding="utf-8")
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell launch contract")
def test_lite_mdf_preflight_imports_from_repo_when_launched_elsewhere(tmp_path):
    text = (ROOT / "tools/build_windows_folder_lite.ps1").read_text(encoding="utf-8")
    invocation = next(line for line in text.splitlines() if "_require_fixed_arrays()" in line)
    helper = text[text.index("function Invoke-LoggedNative"):text.index("function ConvertTo-Win32ArgumentList")]
    repo = tmp_path / "project with spaces"
    package = repo / "mf4_analyzer/io"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "mdf_reader.py").write_text(
        "def _require_fixed_arrays():\n    print('MDF_PREFLIGHT_OK')\n", encoding="utf-8"
    )
    def literal(path):
        return "'" + str(path).replace("'", "''") + "'"
    probe = tmp_path / "probe.ps1"
    probe.write_text("\n".join([
        "$ErrorActionPreference = 'Stop'", helper,
        "$RepoRoot = " + literal(repo),
        "$VenvPython = " + literal(sys.executable), invocation,
    ]), encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"}
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MDF_PREFLIGHT_OK" in result.stdout

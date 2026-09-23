import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/build_windows_extension_installer.ps1"


def test_installer_validates_python_before_creating_environment():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "sysconfig.get_platform()" in text
    assert "function Initialize-ManagerEnvironment" in text
    assert 'if (-not $SkipInstall -or $EnvironmentCreated)' in text
    assert 'Write-Host "Command:' in text


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows Python and PowerShell")
@pytest.mark.parametrize("mode", ["repair", "reuse", "explicit_wrong_arch"])
def test_manager_environment_architecture(tmp_path, mode):
    """Use real ARM64/x64 interpreters; orchestration stubs cannot catch this bug."""
    x64 = os.environ.get("TRACELAB_TEST_X64_PYTHON")
    arm = os.environ.get("TRACELAB_TEST_ARM64_PYTHON")
    if not x64 or not arm:
        pytest.skip("set TRACELAB_TEST_X64_PYTHON and TRACELAB_TEST_ARM64_PYTHON")
    environment = tmp_path / "manager environment"
    original = x64 if mode == "reuse" else arm
    subprocess.run([original, "-m", "venv", "--without-pip", str(environment)], check=True, timeout=90)
    marker = environment / "preserve-me.txt"
    marker.write_text("original", encoding="utf-8")
    text = SCRIPT.read_text(encoding="utf-8")
    helpers = text[text.index("function Invoke-Checked"):text.index("Push-Location $RepoRoot")]
    probe = tmp_path / "probe.ps1"
    probe.write_text(
        '$ErrorActionPreference = "Stop"\nSet-StrictMode -Version Latest\n'
        + f'$RepoRoot = {_quote(ROOT)}\n$VenvDir = {_quote(environment)}\n'
        + '$VenvPython = Join-Path $VenvDir "Scripts/python.exe"\n'
        + f'$PythonExe = {_quote(arm if mode == "explicit_wrong_arch" else "")}\n'
        + helpers + '\n$created = Initialize-ManagerEnvironment\n'
        + f'Set-Content {_quote(tmp_path / "created.txt")} $created\n', encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
        capture_output=True, text=True, timeout=120,
    )
    if mode == "explicit_wrong_arch":
        assert result.returncode != 0
        assert marker.read_text() == "original"
        assert not list(tmp_path.glob("manager environment.incompatible-*"))
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "created.txt").read_text().strip() == str(mode == "repair")
    actual = subprocess.check_output(
        [str(environment / "Scripts/python.exe"), "-c", "import sysconfig; print(sysconfig.get_platform())"], text=True,
    ).strip()
    assert actual == "win-amd64"
    if mode == "repair":
        backups = list(tmp_path.glob("manager environment.incompatible-*"))
        assert len(backups) == 1
        assert (backups[0] / marker.name).read_text() == "original"
    else:
        assert marker.read_text() == "original"

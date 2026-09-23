"""Blank-startup import boundary: heavy IO libs must stay out of the first paint path.

Task 1 contract: before an interactive mark on a blank UI session,
``pandas`` / ``asammdf`` / ``openpyxl`` / ``xlrd`` must not enter ``sys.modules``.
A bare ``import mf4_analyzer.ui`` is not enough — the probe constructs and uses
MainWindow (offscreen) along the real ``app.main`` import closure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("pandas", "asammdf", "openpyxl", "xlrd")
_PROBE_TIMEOUT_SECONDS = 90


def _subprocess_env(config_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["TMPDIR"] = "/tmp"
    env["MPLCONFIGDIR"] = "/tmp"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = str(config_home)
    # Keep timing off so the probe does not require measurement tool sockets.
    env.pop("TRACELAB_STARTUP_TIMING", None)
    env.pop("TRACELAB_STARTUP_RUN_ID", None)
    env.pop("TRACELAB_STARTUP_PERF_DIR", None)
    env.pop("TRACELAB_STARTUP_PROBE_HOST", None)
    env.pop("TRACELAB_STARTUP_PROBE_PORT", None)
    return env


def test_blank_mainwindow_startup_does_not_import_heavy_io_libraries():
    """Construct MainWindow via the app bootstrap path; assert heavy libs absent."""
    script = r"""
import json
import os
import sys

HEAVY = ("pandas", "asammdf", "openpyxl", "xlrd")
assert not any(name in sys.modules for name in HEAVY), sorted(
    name for name in HEAVY if name in sys.modules
)

from mf4_analyzer.app import bootstrap_extension_runtime
bootstrap_extension_runtime()

from PyQt5.QtWidgets import QApplication
from mf4_analyzer.ui import MainWindow

app = QApplication.instance() or QApplication([])
window = MainWindow()
# Touch a few blank-session surfaces so this is not a no-op construct.
_ = window.windowTitle()
_ = window.isVisible()
window.show()
app.processEvents()

present = sorted(name for name in HEAVY if name in sys.modules)
print(json.dumps({"present": present, "title": window.windowTitle()}))
"""
    with tempfile.TemporaryDirectory(prefix="tracelab-startup-import-") as tmp:
        config_home = Path(tmp) / "xdg-config"
        config_home.mkdir()
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=_subprocess_env(config_home),
            text=True,
            capture_output=True,
            check=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["present"] == [], payload


def test_importing_io_package_exports_does_not_load_heavy_libraries():
    """Public ``mf4_analyzer.io`` names must resolve without creating DataFrames."""
    script = r"""
import json
import sys

HEAVY = ("pandas", "asammdf", "openpyxl", "xlrd")
from mf4_analyzer.io import (
    DataLoader,
    FileData,
    HAS_ASAMMDF,
    LoadedSource,
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
)
assert DataLoader is not None
assert FileData is not None
assert isinstance(HAS_ASAMMDF, bool)
assert LoadedSource is not None
assert DEFAULT_SOURCE_ADAPTER_REGISTRY is not None
present = sorted(name for name in HEAVY if name in sys.modules)
print(json.dumps({"present": present, "has_asammdf": HAS_ASAMMDF}))
"""
    with tempfile.TemporaryDirectory(prefix="tracelab-io-import-") as tmp:
        config_home = Path(tmp) / "xdg-config"
        config_home.mkdir()
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=_subprocess_env(config_home),
            text=True,
            capture_output=True,
            check=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["present"] == [], payload

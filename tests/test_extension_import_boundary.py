"""Guard: mf4_analyzer.extensions must not import GUI or optional native libs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


_IMPORT_PROBE_TIMEOUT_SECONDS = 30

CHILD_SCRIPT = r"""
import json
import sys

for name in (
    'PyQt5',
    'PyQt5.QtWidgets',
    'matplotlib',
    'matplotlib.pyplot',
    'av',
    'scipy',
    'h5py',
    'tuf',
):
    sys.modules[name] = None

try:
    import PyQt5  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print('POISON_INEFFECTIVE_PyQt5')
    sys.exit(2)

try:
    import av  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print('POISON_INEFFECTIVE_av')
    sys.exit(2)

import mf4_analyzer.extensions
import mf4_analyzer.extensions.contract
import mf4_analyzer.extensions.state
import mf4_analyzer.extensions.runtime_recipe
from mf4_analyzer.extensions import ReasonCode, parse_discovery_envelope  # noqa: F401

blocked = sorted(
    name for name in sys.modules
    if name in {
        'mf4_analyzer.ui',
        'mf4_analyzer.ui.main_window',
        'mf4_analyzer.ui.main_window.window',
        'av',
        'scipy',
        'h5py',
        'matplotlib.pyplot',
        'PyQt5',
        'tuf',
    } and sys.modules[name] is not None
)
print(json.dumps({'blocked': blocked, 'status': 'clean'}))
"""


def test_extensions_package_imports_without_qt_or_optional_native_libs():
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", CHILD_SCRIPT],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=_IMPORT_PROBE_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    assert "POISON_INEFFECTIVE" not in result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "clean"
    assert payload["blocked"] == []

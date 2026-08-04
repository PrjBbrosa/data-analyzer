"""Import-side-effect contract for the standalone batch Qt renderer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_batch_renderer_import_does_not_load_ui_package_or_main_window():
    repo_root = Path(__file__).resolve().parents[1]
    script = """
import json
import sys
import mf4_analyzer.batch_render
blocked = sorted(
    name for name in sys.modules
    if name == 'mf4_analyzer.ui'
    or name.startswith('mf4_analyzer.ui.')
)
print(json.dumps(blocked))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_slice_disabled_fft_time_export_does_not_import_pyqt5():
    """A data-only FFT-vs-Time export must not load the optional Qt renderer."""
    repo_root = Path(__file__).resolve().parents[1]
    script = """
import json
import sys

sys.modules['PyQt5'] = None

from mf4_analyzer.batch import BatchRunner

factory = BatchRunner({})._slice_workbook_factory(
    None,
    method='fft_time',
    params={},
    fact_params={},
    data_extension='xlsx',
    resolution=None,
    fd=None,
    signal_name='',
    unit='',
    warnings_out=[],
)
assert factory is None
print(json.dumps(sorted(
    name for name in sys.modules if name.startswith('PyQt5.')
)))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_renderer_probe_does_not_degrade_an_application_ui_import_error(
    monkeypatch,
):
    from mf4_analyzer.batch import BatchOutput, BatchRunner

    def _broken_probe():
        raise ImportError(
            "internal UI import failed", name="mf4_analyzer.ui.plot_helpers",
        )

    monkeypatch.setattr(
        BatchRunner, "_probe_image_backend", staticmethod(_broken_probe),
    )

    with pytest.raises(ImportError, match="internal UI import failed"):
        BatchRunner({})._resolve_effective_outputs(
            BatchOutput(export_data=True, export_image=True),
        )

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

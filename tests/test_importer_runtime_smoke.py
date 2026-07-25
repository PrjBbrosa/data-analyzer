import json

import numpy as np
import pytest
from scipy.io import savemat

from mf4_analyzer.io.importer_runtime_smoke import run


def test_runtime_smoke_writes_nonzero_channel_count_for_legacy_mat(tmp_path):
    """Catch a frozen importer probe that reports success without loading data."""
    sample = tmp_path / "legacy.mat"
    savemat(
        sample,
        {
            "time": np.array([0.0, 0.1, 0.2]),
            "signal": np.array([1.0, 2.0, 3.0]),
        },
    )
    output = tmp_path / "importer-smoke.json"

    assert run([sample], output) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result == {
        "files": [{"path": str(sample), "channels": 2}],
    }


def test_generated_fixtures_exercise_legacy_v73_and_audio_imports(tmp_path):
    """Catch a fixture generator that misses a MAT or PyAV import path."""
    pytest.importorskip("h5py")
    pytest.importorskip("av")
    from tools.verify_lite_importer_runtime import create_fixtures

    legacy_mat, hdf5_mat, wav, mp4 = create_fixtures(tmp_path)
    output = tmp_path / "importer-smoke.json"

    assert run([legacy_mat, hdf5_mat, wav, mp4], output) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert [record["channels"] for record in result["files"]] == [2, 2, 1, 1]

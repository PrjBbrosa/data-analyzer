# tests/integration/test_head_hdf_realfile.py
from __future__ import annotations
import os
import numpy as np
import pytest
from mf4_analyzer.io.loader import DataLoader

REAL = os.environ.get("HEAD_HDF_SAMPLE", "/tmp/head_sample.hdf")


@pytest.mark.skipif(not os.path.exists(REAL), reason="real HEAD sample absent")
def test_real_file_groups_and_counts():
    groups = DataLoader.load_hdf(REAL)
    suff = {g["label_suffix"] for g in groups}
    assert "24x" in suff and "1x" in suff      # 48x(全NaN ch28) 应被丢
    fast = next(g for g in groups if g["label_suffix"] == "24x")
    # 8 个 24x 通道 + 注入转速；样本数 1,188,000
    assert any(c == "L" for c in fast["channels"])
    assert len(fast["data"]) == 49500 * 24
    slow = next(g for g in groups if g["label_suffix"] == "1x")
    assert len(slow["data"]) == 49500
    # 标定后 L 量级合理（±几十 Pa 级，标定 104）
    assert np.nanmax(np.abs(fast["data"]["L"].to_numpy())) > 0

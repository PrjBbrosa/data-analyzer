from __future__ import annotations

import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput


def test_free_config_accepts_target_signals():
    p = AnalysisPreset.free_config(
        name="t",
        method="fft",
        target_signals=("sig_a", "sig_b"),
        params={"window": "hanning", "nfft": 1024},
    )
    assert p.target_signals == ("sig_a", "sig_b")
    assert p.source == "free_config"
    assert p.file_ids == ()
    assert p.file_paths == ()


def test_free_config_rejects_runtime_only_fields():
    with pytest.raises(ValueError, match="file_ids"):
        AnalysisPreset.free_config(
            name="t", method="fft", file_ids=(1, 2),
        )
    with pytest.raises(ValueError, match="file_paths"):
        AnalysisPreset.free_config(
            name="t", method="fft", file_paths=("/tmp/a.mf4",),
        )


def test_from_current_single_rejects_free_config_fields():
    with pytest.raises(ValueError, match="target_signals"):
        AnalysisPreset.from_current_single(
            name="t", method="fft", signal=(1, "sig"),
            target_signals=("sig",),
        )


def test_runtime_selection_via_replace():
    """UI 注入 file_ids / file_paths 走 dataclasses.replace 路径，而非工厂。"""
    from dataclasses import replace
    p = AnalysisPreset.free_config(
        name="t", method="fft", target_signals=("sig",),
    )
    p2 = replace(p, file_ids=(1, 2), file_paths=("/tmp/a.mf4",))
    assert p2.file_ids == (1, 2)
    assert p2.file_paths == ("/tmp/a.mf4",)
    assert p.file_ids == ()  # original untouched

from __future__ import annotations

import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput
from mf4_analyzer.batch_types import FrfPairRule


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


def test_frf_pair_rule_rejects_ambiguous_portable_pairs():
    with pytest.raises(ValueError, match="input_channel"):
        FrfPairRule("", ("out",))
    with pytest.raises(ValueError, match="output_channels"):
        FrfPairRule("input", ())
    with pytest.raises(ValueError, match="itself"):
        FrfPairRule("input", ("input",))
    with pytest.raises(ValueError, match="duplicate"):
        FrfPairRule("input", ("out", "out"))


def test_free_config_stores_only_portable_frf_pair_intent():
    rule = FrfPairRule("TorqueCmd", ("Torque", "Angle"))
    preset = AnalysisPreset.free_config(
        name="FRF",
        method="frf",
        frf_pair_rules=(rule,),
    )

    assert preset.frf_pair_rules == (rule,)
    assert preset.target_pairs == ()
    assert not hasattr(preset, "resolved_frf_tasks")


def test_frf_portable_rules_do_not_change_legacy_target_pairs_semantics():
    from dataclasses import replace

    preset = AnalysisPreset.free_config(
        name="FRF",
        method="frf",
        frf_pair_rules=(FrfPairRule("cmd", ("out",)),),
    )
    runtime = replace(preset, target_pairs=(("source-a", "legacy-signal"),))

    assert runtime.target_pairs == (("source-a", "legacy-signal"),)
    assert runtime.frf_pair_rules == preset.frf_pair_rules


def test_frf_pair_rules_are_method_gated():
    with pytest.raises(ValueError, match="method='frf'"):
        AnalysisPreset.free_config(
            name="wrong method",
            method="fft",
            frf_pair_rules=(FrfPairRule("cmd", ("out",)),),
        )

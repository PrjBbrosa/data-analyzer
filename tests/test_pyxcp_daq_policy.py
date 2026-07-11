"""Deterministic bounded DAQ policy tests."""

from __future__ import annotations

from mf4_analyzer.acquisition_capture.pyxcp_daq_policy import (
    BoundedDaqPolicy,
    DaqPolicyDiagnostics,
)


def test_policy_diagnostics_keeps_original_positional_constructor() -> None:
    diagnostics = DaqPolicyDiagnostics(0, 0, 0, None)

    assert diagnostics.dto_received_count == 0


def test_policy_accepts_only_daq_and_keeps_newest_frame_on_overflow() -> None:
    policy = BoundedDaqPolicy(frame_capacity=2)
    policy.feed("CMD", 0, 0, b"ignored")
    policy.feed("DAQ", 1, 10, b"one")
    policy.feed("DAQ", 2, 20, b"two")
    policy.feed("DAQ", 3, 30, b"three")

    full_diagnostics = policy.diagnostics()
    assert full_diagnostics.frame_depth == 2
    assert full_diagnostics.frame_high_water == 2
    assert full_diagnostics.frame_overflow_count == 1

    first = policy.get(timeout_s=0.01)
    second = policy.get(timeout_s=0.01)
    assert [first.payload, second.payload] == [b"two", b"three"]
    diagnostics = policy.diagnostics()
    assert diagnostics.dto_received_count == 3
    assert diagnostics.frame_depth == 0
    assert diagnostics.frame_overflow_count == 1
    assert diagnostics.frame_high_water == 2


def test_policy_is_nonblocking_after_finalize() -> None:
    policy = BoundedDaqPolicy(frame_capacity=1)
    policy.finalize()
    policy.feed("DAQ", 1, 1, b"ignored")
    assert policy.get(timeout_s=0.01) is None

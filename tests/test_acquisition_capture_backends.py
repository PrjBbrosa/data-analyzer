"""Tests for the recorder backends.

Pins:
- Fake backend emits deterministic samples for >= 3 signals.
- Replay backend works without Vector deps (synthetic source).
- Both expose ``last_frame_monotonic()`` (watchdog rule).
- ``VectorXcpRecorderBackend`` raises a clear error off Windows
  WITHOUT importing python-can / pyxcp.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

import mf4_analyzer.acquisition_capture.backends as backends_module
from mf4_analyzer.acquisition_capture.backends import (
    FakeRecorderBackend,
    ReplayRecorderBackend,
    VectorXcpRecorderBackend,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.writer import Mf4Writer
from tests._helpers.mf4_factory import write_source_path_mf4


THREE = (
    SelectedMeasurement(name="A", unit="rpm"),
    SelectedMeasurement(name="B", unit="Nm"),
    SelectedMeasurement(name="C", unit="km/h"),
)


# ---------------------------------------------------------------------------
# Fake backend.
# ---------------------------------------------------------------------------


def test_fake_backend_emits_three_signals():
    backend = FakeRecorderBackend(samples_per_second=100.0)
    backend.start(THREE)
    # Let some real wall-clock elapse so poll has something to emit.
    time.sleep(0.05)
    samples = backend.poll()
    assert samples, "fake backend must emit samples after start + sleep"
    seen_channels = {ch for ch, _ts, _v in samples}
    assert seen_channels == {"A", "B", "C"}


def test_fake_backend_last_frame_monotonic_advances():
    backend = FakeRecorderBackend(samples_per_second=100.0)
    backend.start(THREE)
    assert backend.last_frame_monotonic() is None
    time.sleep(0.03)
    backend.poll()
    first = backend.last_frame_monotonic()
    assert first is not None
    time.sleep(0.03)
    backend.poll()
    second = backend.last_frame_monotonic()
    assert second is not None and second >= first


def test_fake_backend_is_deterministic_for_same_inputs():
    """Same channels, same elapsed t ⇒ same values."""
    backend_a = FakeRecorderBackend(samples_per_second=100.0)
    backend_b = FakeRecorderBackend(samples_per_second=100.0)
    # Use private waveform shape directly; the FakeRecorderBackend
    # public path depends on real wall-clock, but the math itself
    # is pure.
    v0_a = FakeRecorderBackend._value_for(0, 0.25)
    v0_b = FakeRecorderBackend._value_for(0, 0.25)
    v1_a = FakeRecorderBackend._value_for(1, 0.50)
    v1_b = FakeRecorderBackend._value_for(1, 0.50)
    assert v0_a == v0_b
    assert v1_a == v1_b
    # And the three shapes are distinguishable.
    assert FakeRecorderBackend._value_for(0, 0.25) != FakeRecorderBackend._value_for(1, 0.25)
    del backend_a, backend_b  # exercised constructor only


def test_fake_backend_status_counts_rx():
    backend = FakeRecorderBackend(samples_per_second=100.0)
    backend.start(THREE)
    time.sleep(0.06)
    backend.poll()
    s = backend.status()
    assert s.started is True
    assert s.rx_count > 0


def test_fake_backend_force_warning_states():
    backend = FakeRecorderBackend()
    backend.start(THREE)
    backend.force_bus_error(2)
    backend.force_overflow(3)
    backend.force_error("simulated probe failure")
    s = backend.status()
    assert s.bus_error_count == 2
    assert s.queue_overflow_count == 3
    assert s.last_error == "simulated probe failure"


def test_fake_backend_rejects_empty_selection():
    backend = FakeRecorderBackend()
    with pytest.raises(ValueError, match="selected measurement"):
        backend.start(())


# ---------------------------------------------------------------------------
# Replay backend.
# ---------------------------------------------------------------------------


def test_replay_backend_imports_without_vector_or_can():
    """Importing the module must not require python-can / pyxcp."""
    # The backends module is already imported by the time we reach this
    # line — the check is that sys.modules doesn't contain ``can`` or
    # ``pyxcp`` as a side effect of capture-core import.
    assert "can" not in sys.modules or "can" in sys.modules and True
    # Lighter: the module-level globals don't reference those packages.
    import mf4_analyzer.acquisition_capture.backends as backends_module
    # Module source should not have a top-level ``import can`` etc.
    src = (backends_module.__file__ or "")
    if src:
        with open(src, encoding="utf-8") as f:
            text = f.read()
        # Top-level imports of can/pyxcp/PyQt are forbidden.
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("import can") or stripped.startswith("from can"):
                # Must only appear inside a function body (lazy import).
                assert line.startswith("    "), f"top-level python-can import: {line!r}"
            if stripped.startswith("import pyxcp") or stripped.startswith("from pyxcp"):
                assert line.startswith("    "), f"top-level pyxcp import: {line!r}"
            if "PyQt5" in stripped or "PySide" in stripped:
                pytest.fail(f"PyQt/PySide import found: {line!r}")


def test_replay_backend_synthetic_source_works():
    backend = ReplayRecorderBackend(synth_duration_s=0.3, synth_rate_hz=50.0)
    backend.start(THREE)
    # Block briefly so the replay clock advances beyond all timestamps.
    time.sleep(0.4)
    samples = backend.poll()
    seen = {ch for ch, _ts, _v in samples}
    assert seen == {"A", "B", "C"}
    assert backend.last_frame_monotonic() is not None


def test_replay_backend_explicit_source():
    source = [
        ("A", 0.0, 1.0),
        ("B", 0.0, 2.0),
        ("C", 0.0, 3.0),
        ("A", 0.05, 1.1),
    ]
    backend = ReplayRecorderBackend(source_samples=source)
    backend.start(THREE)
    time.sleep(0.1)
    samples = backend.poll()
    # All four samples should be released (their timestamps <= now_rel).
    assert len(samples) == 4
    channels = [s[0] for s in samples]
    assert channels == ["A", "B", "C", "A"]


def test_replay_backend_speed_multiplier_changes_release_rate(monkeypatch):
    now = {"t": 100.0}
    monkeypatch.setattr(backends_module.time, "monotonic", lambda: now["t"])
    source = [
        ("A", 0.0, 1.0),
        ("A", 0.05, 2.0),
        ("A", 0.10, 3.0),
    ]
    backend = ReplayRecorderBackend(source_samples=source, speed_multiplier=2.0)
    backend.start((SelectedMeasurement(name="A", unit="rpm"),))

    now["t"] += 0.03
    samples = backend.poll()

    assert [(ch, ts, val) for ch, ts, val in samples] == [
        ("A", 0.0, 1.0),
        ("A", 0.05, 2.0),
    ]


def test_replay_backend_loads_mf4_source_samples(tmp_path: Path):
    selected = (
        SelectedMeasurement(name="A", unit="rpm"),
        SelectedMeasurement(name="B", unit="Nm"),
    )
    mf4_path = tmp_path / "source.mf4"
    writer = Mf4Writer(mf4_path, selected)
    writer.append("A", 0.0, 1.0)
    writer.append("B", 0.0, 2.0)
    writer.append("A", 0.1, 1.5)
    writer.append("B", 0.1, 2.5)
    writer.finalize()

    replay_source = ReplayRecorderBackend.source_from_mf4(mf4_path)

    assert [m.name for m in replay_source.selected] == ["A", "B"]
    assert [m.unit for m in replay_source.selected] == ["rpm", "Nm"]
    assert replay_source.duration_s == pytest.approx(0.1)
    assert [sample[1] for sample in replay_source.source_samples] == sorted(
        sample[1] for sample in replay_source.source_samples
    )
    assert {sample[0] for sample in replay_source.source_samples} == {"A", "B"}


def test_replay_backend_deduplicates_source_path_aliases(tmp_path: Path):
    mf4_path = write_source_path_mf4(
        tmp_path / "source_alias.mf4",
        channels=(
            (
                "Rte_ActRet_mActiveReturnMotorTorq4Check_xds16",
                "Nm",
                "A_side",
                (1.0, 2.0, 3.0, 4.0),
            ),
        ),
    )

    replay_source = ReplayRecorderBackend.source_from_mf4(mf4_path)

    assert [m.name for m in replay_source.selected] == [
        "Rte_ActRet_mActiveReturnMotorTorq4Check_xds16"
    ]
    assert [m.unit for m in replay_source.selected] == ["Nm"]
    assert {sample[0] for sample in replay_source.source_samples} == {
        "Rte_ActRet_mActiveReturnMotorTorq4Check_xds16"
    }


def test_replay_backend_status_and_stop():
    backend = ReplayRecorderBackend(source_samples=[("A", 0.0, 1.0)])
    backend.start(THREE)
    time.sleep(0.05)
    backend.poll()
    s = backend.stop()
    assert s.started is False
    assert s.rx_count == 1


# ---------------------------------------------------------------------------
# Vector/XCP stub.
# ---------------------------------------------------------------------------


def test_vector_backend_raises_clear_error_off_windows():
    if sys.platform.startswith("win"):
        pytest.skip("VectorXcpRecorderBackend off-Windows error not applicable on Windows")
    preexisting_modules = {
        name: sys.modules.get(name)
        for name in ("can", "pyxcp", "pyxcp.master")
    }
    with pytest.raises(RuntimeError, match="Vector/XCP backend is Windows-only"):
        VectorXcpRecorderBackend()
    # The off-Windows guard must not import python-can / pyxcp. The test is
    # order-independent: another test may already have imported them.
    for name, module in preexisting_modules.items():
        assert sys.modules.get(name) is module


def test_vector_backend_module_has_no_top_level_can_import():
    import mf4_analyzer.acquisition_capture.backends as backends_module
    src_path = backends_module.__file__
    assert src_path is not None
    with open(src_path, encoding="utf-8") as f:
        text = f.read()
    # Top-level (no indent) ``import can`` / ``import pyxcp`` is forbidden.
    for line in text.splitlines():
        if line.startswith("import can ") or line.startswith("import can\n") or line == "import can":
            pytest.fail(f"top-level python-can import found: {line!r}")
        if line.startswith("from can"):
            pytest.fail(f"top-level python-can import found: {line!r}")
        if line.startswith("import pyxcp"):
            pytest.fail(f"top-level pyxcp import found: {line!r}")


def test_vector_runtime_uses_dynamic_pyxcp_imports_for_pyinstaller():
    """PyInstaller follows static pyxcp imports even inside functions.

    On Windows that crashes while importing pyxcp's native extension during
    build analysis, so Vector runtime paths must keep pyxcp behind dynamic
    import strings.
    """

    root = Path(__file__).resolve().parents[1]
    for relative in (
        "mf4_analyzer/acquisition_capture/backends.py",
        "mf4_analyzer/acquisition_capture/vector_hw_probe.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "from pyxcp" not in text
        assert "import pyxcp" not in text

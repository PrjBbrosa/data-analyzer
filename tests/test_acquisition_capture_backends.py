"""Tests for the recorder backends.

Pins:
- Fake backend emits deterministic samples for >= 3 signals.
- Replay backend works without Vector deps (synthetic source).
- Both expose ``last_frame_monotonic()`` (watchdog rule).
- ``VectorXcpRecorderBackend`` raises a clear error off Windows
  WITHOUT importing python-can / pyxcp.
"""

from __future__ import annotations

import subprocess
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
from tests._helpers.acq_owned_objects import isolated_user_env
from tests._helpers.mf4_factory import write_source_path_mf4

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _ControllableClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


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


def test_fake_backend_one_second_on_controlled_clock(monkeypatch):
    clock = _ControllableClock()
    monkeypatch.setattr(backends_module.time, "monotonic", clock)
    backend = FakeRecorderBackend(samples_per_second=20.0)
    backend.start(THREE)
    clock.advance(1.0)
    samples = backend.poll()
    by_channel: dict[str, list[tuple[float, float]]] = {"A": [], "B": [], "C": []}
    for ch, ts, val in samples:
        by_channel[ch].append((ts, val))
    status = backend.status()
    assert status.rx_count == len(samples)
    assert status.rx_count == 60
    for name, points in by_channel.items():
        assert points, f"{name} has no recorded samples"
        timestamps = [ts for ts, _ in points]
        assert min(timestamps) == pytest.approx(0.05)
        assert max(timestamps) == pytest.approx(1.0)
    backend.stop()


def test_fake_backend_empty_write_is_not_a_recorded_second(monkeypatch):
    clock = _ControllableClock()
    monkeypatch.setattr(backends_module.time, "monotonic", clock)
    backend = FakeRecorderBackend(samples_per_second=20.0)
    backend.start(THREE)
    samples = backend.poll()
    assert samples == []
    assert backend.status().rx_count == 0


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


_IMPORT_PROBE_CHILD = r"""
import importlib
import sys
import tempfile
from pathlib import Path

FORBIDDEN = ("can", "pyxcp", "pya2l")


class ForbiddenImportFinder:
    def __init__(self, subject_name):
        self.subject_name = subject_name
        self.hits = []

    def find_spec(self, fullname, path, target=None):
        root = fullname.split(".", 1)[0]
        if root not in FORBIDDEN:
            return None
        importer = _importing_module_name()
        kind = "direct" if importer == self.subject_name else "transitive"
        self.hits.append((kind, importer, fullname))
        raise ImportError(f"FORBIDDEN_{kind.upper()}:{fullname}:from:{importer}")


def _importing_module_name():
    frame = sys._getframe()
    while frame is not None:
        name = frame.f_globals.get("__name__", "")
        filename = frame.f_code.co_filename
        if (
            frame.f_code.co_name == "find_spec"
            or "importlib" in filename
            or name.startswith("importlib")
            or name.startswith("<frozen importlib")
            or name == "__main__"
        ):
            frame = frame.f_back
            continue
        return name or "<unknown>"
    return "<unknown>"


scratch = Path(tempfile.mkdtemp())
(scratch / "subject_direct.py").write_text("import can\n", encoding="utf-8")
(scratch / "helper_can.py").write_text("import can\n", encoding="utf-8")
(scratch / "subject_trans.py").write_text("import helper_can\n", encoding="utf-8")
sys.path.insert(0, str(scratch))

finder = ForbiddenImportFinder("subject_direct")
sys.meta_path.insert(0, finder)
try:
    importlib.import_module("subject_direct")
except ImportError as exc:
    if "FORBIDDEN_DIRECT:can:from:subject_direct" not in str(exc):
        print("PROBE_BROKEN_DIRECT " + str(exc))
        sys.exit(2)
else:
    print("PROBE_BROKEN_DIRECT_NOT_RAISED")
    sys.exit(2)

finder.subject_name = "subject_trans"
try:
    importlib.import_module("subject_trans")
except ImportError as exc:
    if "FORBIDDEN_TRANSITIVE:can:from:helper_can" not in str(exc):
        print("PROBE_BROKEN_TRANSITIVE " + str(exc))
        sys.exit(2)
else:
    print("PROBE_BROKEN_TRANSITIVE_NOT_RAISED")
    sys.exit(2)

finder.subject_name = "mf4_analyzer.acquisition_capture.backends"
finder.hits.clear()
importlib.import_module("mf4_analyzer.acquisition_capture.backends")
if finder.hits:
    print("FORBIDDEN_HIT " + repr(finder.hits))
    sys.exit(3)
print("CLEAN")
"""


def test_replay_backend_imports_without_vector_or_can(tmp_path):
    """Fresh process forbids can/pyxcp/pya2l; direct vs transitive are distinct."""
    env = isolated_user_env(tmp_path / "home")
    env["PYTHONPATH"] = str(_REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE_CHILD],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"import probe failed\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "CLEAN" in result.stdout
    assert "PROBE_BROKEN" not in result.stdout


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


@pytest.mark.parametrize("platform_name", ("darwin", "linux"))
def test_vector_backend_raises_clear_error_off_windows(monkeypatch, platform_name):
    monkeypatch.setattr(sys, "platform", platform_name)
    preexisting_modules = {
        name: sys.modules.get(name)
        for name in ("can", "pyxcp", "pyxcp.master")
    }
    from mf4_analyzer.acquisition_capture.backends import (
        RecorderBackendUnavailableError,
        VectorXcpRecorderBackend,
    )

    with pytest.raises(RecorderBackendUnavailableError, match="Windows-only"):
        VectorXcpRecorderBackend()
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

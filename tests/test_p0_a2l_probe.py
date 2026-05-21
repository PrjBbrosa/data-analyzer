import os
import pickle
import subprocess
import sys
from types import SimpleNamespace

import pytest

from can_logger.p0 import a2l_probe as a2l_probe_module
from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary, load_measurement_summary


def _summary(path: str) -> A2LSummary:
    return A2LSummary(
        path=path,
        total_measurements=1,
        measurements=[
            MeasurementSummary(
                name="VehicleSpeed",
                address=0x1234,
                datatype="UWORD",
                unit="km/h",
                conversion="SpeedConv",
            )
        ],
    )


@pytest.mark.skipif(
    not os.environ.get("P0_A2L_PATH"),
    reason="set P0_A2L_PATH to a real ECU A2L file for this probe",
)
def test_p0_real_a2l_has_measurements():
    summary = load_measurement_summary(os.environ["P0_A2L_PATH"], limit=5)

    assert summary.total_measurements > 0
    assert summary.measurements
    first = summary.measurements[0]
    assert first.name
    assert first.datatype
    assert isinstance(first.address, int)


def test_address_of_raises_when_attribute_missing():
    from can_logger.p0.a2l_probe import _address_of

    class FakeMeasurement:
        name = "BadMeasurement"
        # no ecu_address attribute

    with pytest.raises(ValueError, match="BadMeasurement.*ecu_address"):
        _address_of(FakeMeasurement())


def test_load_measurement_summary_unpickles_subprocess_result(monkeypatch, tmp_path):
    a2l = tmp_path / "ok.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    expected = _summary(str(a2l))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, pickle.dumps(expected), b"")

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    result = a2l_probe_module.load_measurement_summary(str(a2l), limit=None)

    assert result == expected
    cmd, kwargs = calls[0]
    assert cmd[:3] == [sys.executable, "-m", "can_logger.p0._a2l_subprocess"]
    assert str(a2l) in cmd
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 30
    assert "text" not in kwargs


def test_load_measurement_summary_subprocess_crash_becomes_runtime_error(
    monkeypatch, tmp_path
):
    a2l = tmp_path / "crash.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            -1073741819,
            b"",
            b"Windows fatal exception: access violation",
        )

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="0xC0000005.*access violation"):
        a2l_probe_module.load_measurement_summary(str(a2l), limit=1)


def test_load_measurement_summary_rejects_wrong_subprocess_payload(
    monkeypatch, tmp_path
):
    a2l = tmp_path / "wrong-type.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, pickle.dumps({"path": str(a2l)}), b"")

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="unexpected result type"):
        a2l_probe_module.load_measurement_summary(str(a2l), limit=1)


def test_load_measurement_summary_timeout_becomes_runtime_error(monkeypatch, tmp_path):
    a2l = tmp_path / "slow.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=30)

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out after 30s"):
        a2l_probe_module.load_measurement_summary(str(a2l), limit=1)


def _fake_measurement(name: str = "VehicleSpeed") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        ecu_address=SimpleNamespace(address=0x1234),
        datatype="UWORD",
        phys_unit="km/h",
        conversion="SpeedConv",
    )


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *_args):
        return self

    def count(self):
        return len(self._rows)

    def all(self):
        return self._rows

    def limit(self, limit):
        return _FakeQuery(self._rows[:limit])


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args):
        return _FakeQuery(self._rows)


def test_load_measurement_summary_import_removes_existing_sidecar(monkeypatch, tmp_path):
    a2l = tmp_path / "Bside.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    calls = []

    class FakeDB:
        def import_a2l(self, file_name, **kwargs):
            calls.append((file_name, kwargs))
            return _FakeSession([_fake_measurement()])

        def close(self):
            pass

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)

    summary = a2l_probe_module._load_measurement_summary_inprocess(str(a2l), limit=1)

    assert summary.total_measurements == 1
    assert calls == [
        (
            str(a2l),
            {
                "progress_bar": False,
                "loglevel": "ERROR",
                "remove_existing": True,
            },
        )
    ]


def test_load_measurement_summary_reimports_same_path_without_db_close(
    monkeypatch, tmp_path
):
    a2l = tmp_path / "Bside.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    calls = []

    class FakeDB:
        def import_a2l(self, file_name, **kwargs):
            calls.append((file_name, kwargs))
            return _FakeSession([_fake_measurement("RepeatedSignal")])

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)

    first = a2l_probe_module._load_measurement_summary_inprocess(str(a2l), limit=1)
    second = a2l_probe_module._load_measurement_summary_inprocess(str(a2l), limit=1)

    assert [item.name for item in first.measurements] == ["RepeatedSignal"]
    assert [item.name for item in second.measurements] == ["RepeatedSignal"]
    assert [kwargs["remove_existing"] for _file_name, kwargs in calls] == [True, True]

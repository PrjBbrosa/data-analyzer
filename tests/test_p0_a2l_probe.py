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


def test_load_measurement_summary_uses_hidden_child_when_frozen(monkeypatch, tmp_path):
    a2l = tmp_path / "frozen.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    expected = _summary(str(a2l))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, pickle.dumps(expected), b"")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    result = a2l_probe_module.load_measurement_summary(str(a2l), limit=7)

    assert result == expected
    assert calls[0][0] == [
        sys.executable,
        "--a2l-probe-child",
        "--a2l-path",
        str(a2l),
        "--a2l-limit",
        "7",
    ]


def test_a2l_hidden_child_preserves_pickle_stdout_and_exitcode(monkeypatch, tmp_path):
    from can_logger.p0 import _a2l_subprocess

    a2l = tmp_path / "child.a2l"
    expected = _summary(str(a2l))
    stdout: list[bytes] = []
    stderr: list[str] = []
    monkeypatch.setattr(
        _a2l_subprocess,
        "_load_measurement_summary_inprocess",
        lambda path, limit=None: expected,
    )
    monkeypatch.setattr(_a2l_subprocess, "_write_stdout", stdout.append)
    monkeypatch.setattr(_a2l_subprocess, "_write_stderr", stderr.append)

    assert _a2l_subprocess.main([str(a2l), "--limit", "3"]) == 0
    assert pickle.loads(stdout[0]) == expected
    assert stderr == []


def test_a2l_hidden_child_preserves_stderr_and_failure_exitcode(
    monkeypatch,
    tmp_path,
):
    from can_logger.p0 import _a2l_subprocess

    def fail(*_args, **_kwargs):
        raise RuntimeError("parser exploded")

    stderr: list[str] = []
    monkeypatch.setattr(_a2l_subprocess, "_load_measurement_summary_inprocess", fail)
    monkeypatch.setattr(_a2l_subprocess, "_write_stderr", stderr.append)

    assert _a2l_subprocess.main([str(tmp_path / "bad.a2l")]) == 1
    assert stderr == ["A2L parse failed: parser exploded\n"]


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


def _fake_linear_measurement() -> SimpleNamespace:
    return SimpleNamespace(
        name="BatteryVoltage",
        ecu_address=SimpleNamespace(address=0x40001000),
        ecu_address_extension=SimpleNamespace(extension=0x02),
        datatype="UWORD",
        # pya2l models PHYS_UNIT as a one-to-one relationship node.
        phys_unit=SimpleNamespace(unit="V"),
        conversion="BatteryVoltageConv",
    )


def _fake_compu_method(
    name: str,
    conversion_type: str,
    *,
    a: float | None = None,
    b: float | None = None,
    unit: str = "",
    coeffs: tuple[float, float, float, float, float, float] | None = None,
) -> SimpleNamespace:
    coeffs_linear = None
    if a is not None and b is not None:
        coeffs_linear = SimpleNamespace(a=a, b=b)
    return SimpleNamespace(
        name=name,
        conversionType=conversion_type,
        coeffs_linear=coeffs_linear,
        coeffs=(
            SimpleNamespace(**dict(zip("abcdef", coeffs, strict=True)))
            if coeffs is not None
            else None
        ),
        unit=unit,
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


class _TypedFakeSession:
    def __init__(self, measurement_model, compu_method_model, measurements, methods):
        self._measurement_model = measurement_model
        self._compu_method_model = compu_method_model
        self._measurements = measurements
        self._methods = methods

    def query(self, model):
        if model is self._measurement_model:
            return _FakeQuery(self._measurements)
        if model is self._compu_method_model:
            return _FakeQuery(self._methods)
        raise AssertionError(f"unexpected model query: {model!r}")


def test_inprocess_summary_parses_address_extension_and_linear_conversion(
    monkeypatch, tmp_path
):
    a2l = tmp_path / "linear.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    class MeasurementModel:
        name = "name"

    class CompuMethodModel:
        pass

    fake_model = SimpleNamespace(
        Measurement=MeasurementModel,
        CompuMethod=CompuMethodModel,
    )
    session = _TypedFakeSession(
        MeasurementModel,
        CompuMethodModel,
        [_fake_linear_measurement()],
        [
            _fake_compu_method(
                "BatteryVoltageConv",
                "LINEAR",
                a=0.015625,
                b=0.0,
                unit="V",
            )
        ],
    )

    class FakeDB:
        def import_a2l(self, _file_name, **_kwargs):
            return session

        def close(self):
            pass

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)
    monkeypatch.setattr(a2l_probe_module, "model", fake_model)

    summary = a2l_probe_module._load_measurement_summary_inprocess(str(a2l))

    assert summary.total_measurements == 1
    measurement = summary.measurements[0]
    assert measurement.address == 0x40001000
    assert measurement.address_extension == 0x02
    assert measurement.scale_a == pytest.approx(0.015625)
    assert measurement.scale_b == pytest.approx(0.0)
    assert measurement.conversion_supported is True
    assert measurement.unit == "V"


@pytest.mark.parametrize("conversion_type", ["TAB_INTP", "FORM", "TAB_VERB"])
def test_inprocess_summary_marks_nonlinear_conversion_unsupported(
    monkeypatch, tmp_path, conversion_type
):
    a2l = tmp_path / "nonlinear.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    class MeasurementModel:
        name = "name"

    class CompuMethodModel:
        pass

    fake_model = SimpleNamespace(
        Measurement=MeasurementModel,
        CompuMethod=CompuMethodModel,
    )
    session = _TypedFakeSession(
        MeasurementModel,
        CompuMethodModel,
        [_fake_linear_measurement()],
        [_fake_compu_method("BatteryVoltageConv", conversion_type)],
    )

    class FakeDB:
        def import_a2l(self, _file_name, **_kwargs):
            return session

        def close(self):
            pass

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)
    monkeypatch.setattr(a2l_probe_module, "model", fake_model)

    summary = a2l_probe_module._load_measurement_summary_inprocess(str(a2l))

    measurement = summary.measurements[0]
    assert measurement.conversion_supported is False
    assert measurement.scale_a == pytest.approx(1.0)
    assert measurement.scale_b == pytest.approx(0.0)


def test_inprocess_summary_accepts_affine_rat_func_conversion(monkeypatch, tmp_path):
    """Many production A2Ls encode INT=f(PHYS); accept its affine inverse."""

    a2l = tmp_path / "rat-linear.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    class MeasurementModel:
        name = "name"

    class CompuMethodModel:
        pass

    fake_model = SimpleNamespace(
        Measurement=MeasurementModel,
        CompuMethod=CompuMethodModel,
    )
    session = _TypedFakeSession(
        MeasurementModel,
        CompuMethodModel,
        [_fake_linear_measurement()],
        [
            _fake_compu_method(
                "BatteryVoltageConv",
                "RAT_FUNC",
                # INT = 64 * PHYS, so PHYS = INT / 64.
                coeffs=(0.0, 64.0, 0.0, 0.0, 0.0, 1.0),
                unit="V",
            )
        ],
    )

    class FakeDB:
        def import_a2l(self, _file_name, **_kwargs):
            return session

        def close(self):
            pass

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)
    monkeypatch.setattr(a2l_probe_module, "model", fake_model)

    measurement = a2l_probe_module._load_measurement_summary_inprocess(
        str(a2l)
    ).measurements[0]

    assert measurement.conversion_supported is True
    assert measurement.scale_a == pytest.approx(0.015625)
    assert measurement.scale_b == pytest.approx(0.0)


def test_inprocess_summary_rejects_nonlinear_rat_func(monkeypatch, tmp_path):
    a2l = tmp_path / "rat-nonlinear.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    class MeasurementModel:
        name = "name"

    class CompuMethodModel:
        pass

    fake_model = SimpleNamespace(
        Measurement=MeasurementModel,
        CompuMethod=CompuMethodModel,
    )
    session = _TypedFakeSession(
        MeasurementModel,
        CompuMethodModel,
        [_fake_linear_measurement()],
        [
            _fake_compu_method(
                "BatteryVoltageConv",
                "RAT_FUNC",
                coeffs=(1.0, 64.0, 0.0, 0.0, 0.0, 1.0),
            )
        ],
    )

    class FakeDB:
        def import_a2l(self, _file_name, **_kwargs):
            return session

        def close(self):
            pass

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)
    monkeypatch.setattr(a2l_probe_module, "model", fake_model)

    measurement = a2l_probe_module._load_measurement_summary_inprocess(
        str(a2l)
    ).measurements[0]

    assert measurement.conversion_supported is False


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


def test_compact_process_output_keeps_last_line_of_traceback():
    """B7: previously the helper kept lines[0] (= 'Traceback ...'), which
    hid the actual exception. The fix surfaces lines[-1] (the real error)."""
    traceback_text = (
        "Traceback (most recent call last):\n"
        "  File \"<string>\", line 1, in <module>\n"
        "  File \"pya2l/db.py\", line 42, in import_a2l\n"
        "ValueError: A2L grammar violation at line 17"
    ).encode("utf-8")
    detail = a2l_probe_module._compact_process_output(b"", traceback_text)
    assert "ValueError: A2L grammar violation at line 17" in detail
    # The 'Traceback' header should NOT be the leading text any more.
    assert not detail.startswith("Traceback")


def test_compact_process_output_dumps_long_log_to_temp_file(tmp_path, monkeypatch):
    """B7: when stderr > 800 chars, full text is written to %TEMP% and
    the returned detail string carries the log path."""
    long_text = ("err line abcdef " * 80).encode("utf-8")  # > 800 chars
    detail = a2l_probe_module._compact_process_output(b"", long_text)
    # Detail should mention a full-log path so the operator can pull
    # the full traceback out of disk.
    assert "full log:" in detail

from __future__ import annotations

import json
import pickle
import sys
from types import SimpleNamespace


def test_runtime_smoke_fails_closed_when_isolated_child_probe_crashes(
    monkeypatch,
    tmp_path,
) -> None:
    from mf4_analyzer.acquisition_capture import backends, runtime_smoke

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        backends,
        "_pyxcp_import_probe_command",
        lambda: [sys.executable, "--pyxcp-import-probe-child"],
        raising=False,
    )
    monkeypatch.setattr(
        backends,
        "_run_pyxcp_import_probe",
        lambda: (-1073741819, "", "access violation"),
    )
    output = tmp_path / "packaged-runtime-smoke.json"

    exit_code = runtime_smoke.run(output)

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["ok"] is False
    assert report["import_probe"]["command"] == [
        sys.executable,
        "--pyxcp-import-probe-child",
    ]
    assert report["import_probe"]["returncode"] == -1073741819
    assert "isolated" in report["error"]


def test_hidden_probe_child_loads_qt_before_pyxcp_without_opening_vector(
    monkeypatch,
) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    imports: list[str] = []

    class Master:
        pass

    def fake_import(name: str):
        imports.append(name)
        if name == "pyxcp.master":
            return type("MasterModule", (), {"Master": Master})
        return object()

    monkeypatch.setattr(runtime_smoke.importlib, "import_module", fake_import)

    assert runtime_smoke.run_import_probe_child() == 0
    assert imports == ["PyQt5.QtWidgets", "pyxcp.master"]


def test_hidden_probe_children_do_not_require_console_streams(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    modules = {
        "PyQt5.QtWidgets": object(),
        "pyxcp.master": SimpleNamespace(Master=type("Master", (), {})),
        "pya2l": object(),
        "pya2l.model": object(),
    }
    monkeypatch.setattr(
        runtime_smoke.importlib,
        "import_module",
        lambda name: modules[name],
    )
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    assert runtime_smoke.run_import_probe_child() == 0
    assert runtime_smoke.run_pya2l_import_probe_child() == 0


def test_frozen_pya2l_probe_uses_hidden_child_and_fails_closed(
    monkeypatch,
    tmp_path,
) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        runtime_smoke,
        "_production_import_probe",
        lambda: {
            "command": [sys.executable, "--pyxcp-import-probe-child"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        },
    )
    monkeypatch.setattr(
        runtime_smoke.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(
            args=command,
            returncode=-1073741819,
            stdout="",
            stderr="pya2l access violation",
        ),
    )
    output = tmp_path / "packaged-runtime-smoke.json"

    assert runtime_smoke.run(output) == 2

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["pya2l_import_probe"]["command"] == [
        sys.executable,
        "--pya2l-import-probe-child",
    ]
    assert report["pya2l_import_probe"]["returncode"] == -1073741819
    assert "pya2l" in report["error"]


def test_hidden_pya2l_probe_child_loads_qt_before_pya2l(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    imports: list[str] = []
    monkeypatch.setattr(
        runtime_smoke.importlib,
        "import_module",
        lambda name: imports.append(name) or object(),
    )

    assert runtime_smoke.run_pya2l_import_probe_child() == 0
    assert imports == ["PyQt5.QtWidgets", "pya2l", "pya2l.model"]


def test_frozen_a2l_parse_probe_drives_hidden_child_and_validates_pickle(
    monkeypatch,
) -> None:
    from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary
    from mf4_analyzer.acquisition_capture import runtime_smoke

    summary = A2LSummary(
        path="probe.a2l",
        total_measurements=1,
        measurements=[
            MeasurementSummary(
                name="RuntimeSmokeSignal",
                address=0x1000,
                datatype="UWORD",
                unit="",
                conversion="NO_COMPU_METHOD",
            )
        ],
    )
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=pickle.dumps(summary),
            stderr=b"",
        )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_smoke.subprocess, "run", fake_run)

    result = runtime_smoke._a2l_parse_probe()

    assert result["ok"] is True
    assert commands[0][0:2] == [sys.executable, "--a2l-probe-child"]
    assert "--a2l-path" in commands[0]
    assert result["measurement"] == {
        "address": 0x1000,
        "datatype": "UWORD",
        "name": "RuntimeSmokeSignal",
    }


def test_a2l_parse_probe_fails_closed_on_child_crash(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    monkeypatch.setattr(
        runtime_smoke.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(
            returncode=-1073741819,
            stdout=b"",
            stderr=b"access violation",
        ),
    )

    result = runtime_smoke._a2l_parse_probe()

    assert result["ok"] is False
    assert result["returncode"] == -1073741819
    assert "access violation" in result["error"]


def test_a2l_parse_probe_fails_closed_on_invalid_pickle(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    monkeypatch.setattr(
        runtime_smoke.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"not-a-pickle",
            stderr=b"",
        ),
    )

    result = runtime_smoke._a2l_parse_probe()

    assert result["ok"] is False
    assert result["returncode"] == 0
    assert "pickle" in result["error"]


def test_runtime_smoke_checks_metadata_master_policy_and_adapter_without_open(
    monkeypatch,
    tmp_path,
) -> None:
    from mf4_analyzer.acquisition_capture import runtime_smoke

    class Master:
        def getStatus(self):  # noqa: N802
            return None

        def getSeed(self, first, resource):  # noqa: N802
            return None

        def unlock(self, length, key):
            return None

        def cond_unlock(self, resources=None):
            return None

        def allocDaq(self, daq_count):  # noqa: N802
            return None

        def startStopDaqList(self, mode, daq_list_number):  # noqa: N802
            return None

    class FrameAcquisitionPolicy:
        def feed(self, category, counter, timestamp, payload):
            return None

    class NoOpPolicy:
        pass

    from mf4_analyzer.acquisition_capture import pyxcp_daq_policy, pyxcp_runtime

    config_inputs = []

    def create_application_from_config(config):
        config_inputs.append(config)
        return SimpleNamespace(
            general=SimpleNamespace(seed_n_key_dll=""),
            transport=SimpleNamespace(
                layer=None,
                timeout=None,
                can=SimpleNamespace(
                    interface=None,
                    channel=None,
                    bitrate=None,
                    fd=None,
                    data_bitrate=None,
                    can_id_master=None,
                    can_id_slave=None,
                    vector=SimpleNamespace(app_name=None),
                ),
            ),
        )

    modules = {
        "pyxcp.master": SimpleNamespace(Master=Master),
        "pyxcp.transport.transport_ext": SimpleNamespace(
            FrameAcquisitionPolicy=FrameAcquisitionPolicy,
            NoOpPolicy=NoOpPolicy,
        ),
        "pyxcp.config": SimpleNamespace(
            create_application_from_config=create_application_from_config
        ),
        "mf4_analyzer.acquisition_capture.pyxcp_runtime": pyxcp_runtime,
        "mf4_analyzer.acquisition_capture.pyxcp_daq_policy": pyxcp_daq_policy,
        "pya2l": SimpleNamespace(DB=type("DB", (), {})),
        "pya2l.model": SimpleNamespace(Measurement=type("Measurement", (), {})),
    }
    monkeypatch.setattr(
        runtime_smoke,
        "_production_import_probe",
        lambda: {
            "command": [sys.executable, "--pyxcp-import-probe-child"],
            "returncode": 0,
            "stdout": '{"ok": true}',
            "stderr": "",
        },
    )
    monkeypatch.setattr(
        runtime_smoke,
        "_production_pya2l_import_probe",
        lambda: {
            "command": [sys.executable, "--pya2l-import-probe-child"],
            "returncode": 0,
            "stdout": '{"ok": true}',
            "stderr": "",
        },
    )
    monkeypatch.setattr(
        runtime_smoke,
        "_a2l_parse_probe",
        lambda: {
            "ok": True,
            "command": [sys.executable, "--a2l-probe-child"],
            "returncode": 0,
            "stderr": "",
            "stdout_size": 256,
            "measurement": {
                "name": "RuntimeSmokeSignal",
                "address": 0x1000,
                "datatype": "UWORD",
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        runtime_smoke.importlib.metadata,
        "version",
        lambda name: {
            "python-can": "4.6.1",
            "pyxcp": "0.29.14",
            "pya2ldb": "1.0.332",
        }[name],
    )
    monkeypatch.setattr(
        runtime_smoke.importlib,
        "import_module",
        lambda name: modules[name],
    )
    output = tmp_path / "packaged-runtime-smoke.json"

    assert runtime_smoke.run(output) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["versions"] == {
        "python-can": "4.6.1",
        "pya2ldb": "1.0.332",
        "pyxcp": "0.29.14",
    }
    assert "FrameAcquisitionPolicy.feed/NoOpPolicy" in report["checked_surfaces"]
    assert "pyxcp config + DAQ policies constructed (no Master/Vector)" in report[
        "checked_surfaces"
    ]
    assert "pya2l.DB/model.Measurement (not invoked)" in report["checked_surfaces"]
    assert config_inputs[0]["General"]["seed_n_key_dll"] == ""
    assert report["a2l_parse_probe"]["measurement"]["name"] == "RuntimeSmokeSignal"

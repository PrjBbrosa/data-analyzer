"""Non-GUI frozen/source smoke for the pinned acquisition runtime."""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


EXPECTED_VERSIONS = {
    "python-can": "4.6.1",
    "pya2ldb": "1.0.332",
    "pyxcp": "0.29.10",
}
REQUIRED_MASTER_METHODS = {
    "getStatus": ("self",),
    "getSeed": ("self", "first", "resource"),
    "unlock": ("self", "length", "key"),
    "cond_unlock": ("self", "resources"),
    "allocDaq": ("self", "daq_count"),
    "startStopDaqList": ("self", "mode", "daq_list_number"),
}

_MINIMAL_A2L = """ASAP2_VERSION 1 71
/begin PROJECT P ""
  /begin MODULE M ""
    /begin MEASUREMENT RuntimeSmokeSignal "" UWORD NO_COMPU_METHOD 0 0 0 65535
      ECU_ADDRESS 0x1000
    /end MEASUREMENT
  /end MODULE
/end PROJECT
"""


def _write_text_line(stream: object | None, message: str) -> None:
    """Best-effort child diagnostics, including PyInstaller ``--windowed``.

    Windowed Windows executables intentionally expose ``sys.stdout`` and
    ``sys.stderr`` as ``None``.  Probe success is carried by the process exit
    code and smoke evidence is carried by the JSON file, so missing console
    streams must not turn a valid import into a false failure.
    """

    writer = getattr(stream, "write", None)
    if not callable(writer):
        return
    try:
        writer(message + "\n")
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()
    except (OSError, ValueError):
        return


def run_import_probe_child() -> int:
    """Hidden frozen-child entrypoint for the Qt-loaded pyxcp import probe."""

    try:
        importlib.import_module("PyQt5.QtWidgets")
        master_module = importlib.import_module("pyxcp.master")
        if not callable(getattr(master_module, "Master", None)):
            raise RuntimeError("pyxcp Master is unavailable")
        _write_text_line(
            sys.stdout,
            json.dumps({"ok": True, "probe": "PyQt5.QtWidgets->pyxcp.master"}),
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - child exit/output are evidence
        _write_text_line(
            sys.stderr,
            json.dumps(
                {
                    "ok": False,
                    "probe": "PyQt5.QtWidgets->pyxcp.master",
                    "error": str(exc),
                }
            ),
        )
        return 2


def run_pya2l_import_probe_child() -> int:
    """Hidden frozen-child entrypoint for the Qt-loaded pya2l import probe."""

    try:
        importlib.import_module("PyQt5.QtWidgets")
        importlib.import_module("pya2l")
        importlib.import_module("pya2l.model")
        _write_text_line(
            sys.stdout,
            json.dumps({"ok": True, "probe": "PyQt5.QtWidgets->pya2l"}),
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - child exit/output are evidence
        _write_text_line(
            sys.stderr,
            json.dumps(
                {
                    "ok": False,
                    "probe": "PyQt5.QtWidgets->pya2l",
                    "error": str(exc),
                }
            ),
        )
        return 2


def _production_import_probe() -> dict[str, Any]:
    from mf4_analyzer.acquisition_capture import backends

    command = backends._pyxcp_import_probe_command()
    returncode, stdout, stderr = backends._run_pyxcp_import_probe()
    return {
        "command": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _pya2l_import_probe_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pya2l-import-probe-child"]
    probe_code = (
        "import importlib\n"
        "importlib.import_module('PyQt5.QtWidgets')\n"
        "importlib.import_module('pya2l')\n"
        "importlib.import_module('pya2l.model')\n"
    )
    return [sys.executable, "-c", probe_code]


def _production_pya2l_import_probe() -> dict[str, Any]:
    command = _pya2l_import_probe_command()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "stdout": "",
            "stderr": f"pya2l import probe timed out after {exc.timeout}s",
        }
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _a2l_parse_probe() -> dict[str, Any]:
    """Drive the real source/frozen parser child and validate its pickle."""

    from can_logger.p0 import a2l_probe

    with tempfile.TemporaryDirectory(prefix="tracelab_a2l_smoke_") as temp_dir:
        path = Path(temp_dir) / "minimal.a2l"
        path.write_text(_MINIMAL_A2L, encoding="latin-1")
        command = a2l_probe._a2l_subprocess_command(path, limit=1)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=a2l_probe.DEFAULT_A2L_PARSE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "command": command,
                "returncode": 124,
                "stdout_size": 0,
                "stderr": f"A2L parse probe timed out after {exc.timeout}s",
                "measurement": None,
                "error": "A2L parser child timed out",
            }

        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        report: dict[str, Any] = {
            "ok": False,
            "command": command,
            "returncode": result.returncode,
            "stdout_size": len(result.stdout),
            "stderr": stderr,
            "measurement": None,
            "error": None,
        }
        if result.returncode != 0:
            report["error"] = (
                "A2L parser child failed "
                f"(returncode={result.returncode}): {stderr or 'no output'}"
            )
            return report
        try:
            summary = pickle.loads(result.stdout)
        except Exception as exc:  # noqa: BLE001 - evidence retains bad child data
            report["error"] = f"A2L parser child returned invalid pickle: {exc}"
            return report
        if not isinstance(summary, a2l_probe.A2LSummary):
            report["error"] = (
                "A2L parser child returned unexpected type: "
                f"{type(summary).__name__}"
            )
            return report
        if summary.total_measurements != 1 or len(summary.measurements) != 1:
            report["error"] = (
                "A2L parser child returned unexpected measurement count: "
                f"total={summary.total_measurements}, rows={len(summary.measurements)}"
            )
            return report
        measurement = summary.measurements[0]
        facts = {
            "name": measurement.name,
            "address": measurement.address,
            "datatype": measurement.datatype,
        }
        report["measurement"] = facts
        if facts != {
            "name": "RuntimeSmokeSignal",
            "address": 0x1000,
            "datatype": "UWORD",
        }:
            report["error"] = f"A2L parser child returned unexpected facts: {facts}"
            return report
        report["ok"] = True
        return report


def _verify_import_surfaces(report: dict[str, Any]) -> None:
    from can_logger.p0.ifdata_xcp import DaqProcessorInfo, IfDataXcp
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

    master_module = importlib.import_module("pyxcp.master")
    transport_ext = importlib.import_module("pyxcp.transport.transport_ext")
    config_module = importlib.import_module("pyxcp.config")
    adapter_module = importlib.import_module(
        "mf4_analyzer.acquisition_capture.pyxcp_runtime"
    )
    daq_policy_module = importlib.import_module(
        "mf4_analyzer.acquisition_capture.pyxcp_daq_policy"
    )

    master = getattr(master_module, "Master", None)
    if not callable(master):
        raise RuntimeError("pyxcp Master is unavailable")
    for name, expected in REQUIRED_MASTER_METHODS.items():
        method = getattr(master, name, None)
        if method is None:
            raise RuntimeError(f"Master.{name} is absent")
        actual = tuple(inspect.signature(method).parameters)
        if actual != expected:
            raise RuntimeError(
                f"Master.{name} signature mismatch: expected {expected}, got {actual}"
            )
        report["checked_surfaces"].append(f"Master.{name}{actual}")

    policy = getattr(transport_ext, "FrameAcquisitionPolicy", None)
    noop = getattr(transport_ext, "NoOpPolicy", None)
    if policy is None or noop is None or not callable(getattr(policy, "feed", None)):
        raise RuntimeError("FrameAcquisitionPolicy/NoOpPolicy surface is unavailable")
    report["checked_surfaces"].append("FrameAcquisitionPolicy.feed/NoOpPolicy")

    factory = getattr(config_module, "create_application_from_config", None)
    build_application = getattr(adapter_module, "_build_application", None)
    discard_policy = getattr(adapter_module, "DiscardDaqPolicy", None)
    bounded_policy = getattr(daq_policy_module, "BoundedDaqPolicy", None)
    if not all(callable(item) for item in (factory, build_application, discard_policy, bounded_policy)):
        raise RuntimeError("pyxcp config/runtime policy construction surface is unavailable")
    ifdata = IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(),
        daq_processor=DaqProcessorInfo(0, 0, 1, "EVENT"),
    )
    application = build_application(factory, TransportConfig(), ifdata)
    if application.general.seed_n_key_dll != "":
        raise RuntimeError("default pyxcp seed_n_key_dll trait is not an empty string")
    discard = discard_policy()
    bounded = bounded_policy(frame_capacity=1)
    if not callable(getattr(discard, "feed", None)) or not callable(
        getattr(bounded, "feed", None)
    ):
        raise RuntimeError("constructed DAQ policy callback surface is unavailable")
    # No Master is constructed and no Vector channel is opened here.
    report["checked_surfaces"].append(
        "pyxcp config + DAQ policies constructed (no Master/Vector)"
    )

    pya2l_module = importlib.import_module("pya2l")
    pya2l_model = importlib.import_module("pya2l.model")
    if not callable(getattr(pya2l_module, "DB", None)):
        raise RuntimeError("pya2l.DB surface is unavailable")
    if getattr(pya2l_model, "Measurement", None) is None:
        raise RuntimeError("pya2l.model.Measurement surface is unavailable")
    report["checked_surfaces"].append("pya2l.DB/model.Measurement (not invoked)")


def run(output: Path) -> int:
    report: dict[str, Any] = {
        "ok": False,
        "frozen": bool(getattr(sys, "frozen", False)),
        "versions": {},
        "import_probe": None,
        "pya2l_import_probe": None,
        "a2l_parse_probe": None,
        "checked_surfaces": [],
        "error": None,
    }
    try:
        report["import_probe"] = _production_import_probe()
        if report["import_probe"]["returncode"] != 0:
            raise RuntimeError(
                "production isolated PyQt-loaded pyxcp probe failed "
                f"(returncode={report['import_probe']['returncode']})"
            )
        report["pya2l_import_probe"] = _production_pya2l_import_probe()
        if report["pya2l_import_probe"]["returncode"] != 0:
            raise RuntimeError(
                "production isolated PyQt-loaded pya2l probe failed "
                f"(returncode={report['pya2l_import_probe']['returncode']})"
            )
        report["versions"] = {
            "python-can": importlib.metadata.version("python-can"),
            "pya2ldb": importlib.metadata.version("pya2ldb"),
            "pyxcp": importlib.metadata.version("pyxcp"),
        }
        if report["versions"] != EXPECTED_VERSIONS:
            raise RuntimeError(f"pinned acquisition versions differ: {report['versions']}")
        report["a2l_parse_probe"] = _a2l_parse_probe()
        if not report["a2l_parse_probe"]["ok"]:
            raise RuntimeError(report["a2l_parse_probe"]["error"])
        _verify_import_surfaces(report)
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001 - JSON captures exact frozen failure
        report["error"] = str(exc)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_text_line(sys.stdout, json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2

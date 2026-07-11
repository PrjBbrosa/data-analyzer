#!/usr/bin/env python3
"""Verify the exact pyxcp 0.29 Vector/XCP runtime before bench use.

This intentionally imports optional native dependencies only after reporting a
clear Windows-only gate.  It writes machine-readable evidence for the source
and frozen-runtime acceptance paths; it does not open a Vector channel.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import inspect
import json
import platform
import sys
from pathlib import Path
from typing import Any


# tools/build_windows_folder.ps1 runs this file as a standalone script by
# absolute path, so sys.path[0] is this file's directory (scripts/) and the
# project package ``mf4_analyzer`` at the repo root is NOT importable. Put the
# repo root on sys.path so the build-time contract gate can import the
# production backend. (Under pytest the repo root is already on sys.path, so
# this insert is a harmless no-op there.)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


EXPECTED = {
    "python-can": "4.6.1",
    "pya2ldb": "1.0.332",
    "pyxcp": "0.29.14",
}
REQUIRED_METHODS = {
    "getStatus": ("self",),
    "getSeed": ("self", "first", "resource"),
    "unlock": ("self", "length", "key"),
    "cond_unlock": ("self", "resources"),
    "allocDaq": ("self", "daq_count"),
    "allocOdt": ("self", "daq_list_number", "odt_count"),
    "allocOdtEntry": ("self", "daq_list_number", "odt_number", "odt_entries_count"),
    "writeDaq": ("self", "bit_offset", "entry_size", "address_ext", "address"),
    "setDaqListMode": (
        "self",
        "mode",
        "daq_list_number",
        "event_channel_number",
        "prescaler",
        "priority",
    ),
    "startStopDaqList": ("self", "mode", "daq_list_number"),
    "startStopSynch": ("self", "mode"),
}


def _report() -> dict[str, Any]:
    return {
        "ok": False,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "python_bitness": 64 if sys.maxsize > 2**32 else 32,
        "machine": platform.machine(),
        "expected_versions": EXPECTED,
        "installed_versions": {},
        "import_probe": None,
        "checked_surfaces": [],
        "error": None,
    }


def verify() -> dict[str, Any]:
    report = _report()
    if sys.platform != "win32":
        report["error"] = "Windows x64 is required for the live Vector/pyxcp contract"
        return report
    if report["python_bitness"] != 64:
        report["error"] = "Windows x64 Python is required"
        return report

    # Exercise the exact isolated probe used by the production backend.  This
    # must happen before importing pyxcp in this process: a native crash cannot
    # be caught by Python, so the child return code and output are evidence.
    from mf4_analyzer.acquisition_capture import backends

    probe_command = backends._pyxcp_import_probe_command()
    returncode, stdout, stderr = backends._run_pyxcp_import_probe()
    report["import_probe"] = {
        "command": probe_command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if returncode != 0:
        report["error"] = (
            "production isolated PyQt-loaded pyxcp probe failed "
            f"(returncode={returncode})"
        )
        return report

    try:
        installed = {name: importlib.metadata.version(name) for name in EXPECTED}
    except importlib.metadata.PackageNotFoundError as exc:
        report["error"] = f"required package is not installed: {exc}"
        return report
    report["installed_versions"] = installed
    mismatches = {
        name: {"expected": EXPECTED[name], "installed": version}
        for name, version in installed.items()
        if version != EXPECTED[name]
    }
    if mismatches:
        report["error"] = f"pinned runtime mismatch: {mismatches}"
        return report

    # Keep these dynamic and after the production subprocess probe.
    try:
        master_module = importlib.import_module("py" + "xcp.master")
        transport_ext = importlib.import_module("py" + "xcp.transport.transport_ext")
        config_module = importlib.import_module("py" + "xcp.config")
    except Exception as exc:  # noqa: BLE001 - evidence must retain native failure
        report["error"] = f"pinned pyxcp import failed: {exc}"
        return report

    Master = master_module.Master
    for name, expected in REQUIRED_METHODS.items():
        method = getattr(Master, name, None)
        if method is None:
            report["error"] = f"Master.{name} is absent"
            return report
        actual = tuple(inspect.signature(method).parameters)
        if actual != expected:
            report["error"] = (
                f"Master.{name} signature mismatch: expected {expected}, got {actual}"
            )
            return report
        report["checked_surfaces"].append(f"Master.{name}{actual}")

    policy = getattr(transport_ext, "FrameAcquisitionPolicy", None)
    noop = getattr(transport_ext, "NoOpPolicy", None)
    if policy is None or noop is None or not callable(getattr(policy, "feed", None)):
        report["error"] = "FrameAcquisitionPolicy/NoOpPolicy callback surface is absent"
        return report
    report["checked_surfaces"].append("FrameAcquisitionPolicy.feed")

    can_class = getattr(config_module, "Can", None)
    vector_class = getattr(config_module, "Vector", None)
    if can_class is None or vector_class is None:
        report["error"] = "pyxcp CAN/Vector configuration classes are absent"
        return report
    can_traits = can_class.class_traits()
    vector_traits = vector_class.class_traits()
    for name in ("interface", "channel", "bitrate", "data_bitrate", "fd", "can_id_master", "can_id_slave"):
        if name not in can_traits:
            report["error"] = f"pyxcp CAN config trait is absent: {name}"
            return report
    if "app_name" not in vector_traits:
        report["error"] = "pyxcp Vector config trait is absent: app_name"
        return report
    report["checked_surfaces"].append("Can/Vector trait paths")
    report["ok"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, required=True, help="evidence JSON output")
    args = parser.parse_args(argv)
    report = verify()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

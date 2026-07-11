from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    (
        (-1073741819, "", "access violation"),
        (124, "partial output", "pyxcp import probe timed out after 5s"),
    ),
)
def test_windows_verifier_fails_closed_and_records_production_import_probe(
    monkeypatch,
    returncode: int,
    stdout: str,
    stderr: str,
) -> None:
    from mf4_analyzer.acquisition_capture import backends
    from scripts import verify_windows_acquisition_runtime as verifier

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        backends,
        "_pyxcp_import_probe_command",
        lambda: [sys.executable, "-c", "<production-qt-pyxcp-probe>"],
        raising=False,
    )
    monkeypatch.setattr(
        backends,
        "_run_pyxcp_import_probe",
        lambda: (returncode, stdout, stderr),
    )

    report = verifier.verify()

    assert report["ok"] is False
    assert report["import_probe"] == {
        "command": [sys.executable, "-c", "<production-qt-pyxcp-probe>"],
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    assert "isolated" in report["error"]


def test_windows_verifier_passes_only_after_probe_metadata_and_api_contract(
    monkeypatch,
) -> None:
    from mf4_analyzer.acquisition_capture import backends
    from scripts import verify_windows_acquisition_runtime as verifier

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

        def allocOdt(self, daq_list_number, odt_count):  # noqa: N802
            return None

        def allocOdtEntry(  # noqa: N802
            self, daq_list_number, odt_number, odt_entries_count
        ):
            return None

        def writeDaq(self, bit_offset, entry_size, address_ext, address):  # noqa: N802
            return None

        def setDaqListMode(  # noqa: N802
            self,
            mode,
            daq_list_number,
            event_channel_number,
            prescaler,
            priority,
        ):
            return None

        def startStopDaqList(self, mode, daq_list_number):  # noqa: N802
            return None

        def startStopSynch(self, mode):  # noqa: N802
            return None

    class FrameAcquisitionPolicy:
        def feed(self, category, counter, timestamp, payload):
            return None

    class NoOpPolicy:
        pass

    can_traits = {
        name: object()
        for name in (
            "interface",
            "channel",
            "bitrate",
            "data_bitrate",
            "fd",
            "can_id_master",
            "can_id_slave",
        )
    }

    class Can:
        @classmethod
        def class_traits(cls):
            return can_traits

    class Vector:
        @classmethod
        def class_traits(cls):
            return {"app_name": object()}

    modules = {
        "pyxcp.master": SimpleNamespace(Master=Master),
        "pyxcp.transport.transport_ext": SimpleNamespace(
            FrameAcquisitionPolicy=FrameAcquisitionPolicy,
            NoOpPolicy=NoOpPolicy,
        ),
        "pyxcp.config": SimpleNamespace(Can=Can, Vector=Vector),
    }
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        backends,
        "_pyxcp_import_probe_command",
        lambda: [sys.executable, "-c", "<production-qt-pyxcp-probe>"],
    )
    monkeypatch.setattr(
        backends,
        "_run_pyxcp_import_probe",
        lambda: (0, "probe ok", ""),
    )
    monkeypatch.setattr(
        verifier.importlib.metadata,
        "version",
        lambda name: {
            "python-can": "4.6.1",
            "pya2ldb": "1.0.332",
            "pyxcp": "0.29.14",
        }[name],
    )
    monkeypatch.setattr(
        verifier.importlib,
        "import_module",
        lambda name: modules[name],
    )

    report = verifier.verify()

    assert report["ok"] is True
    assert report["installed_versions"] == {
        "python-can": "4.6.1",
        "pya2ldb": "1.0.332",
        "pyxcp": "0.29.14",
    }
    assert report["import_probe"]["stdout"] == "probe ok"
    assert "FrameAcquisitionPolicy.feed" in report["checked_surfaces"]
    assert "Can/Vector trait paths" in report["checked_surfaces"]

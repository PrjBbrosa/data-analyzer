"""Windows-only real package contract for the pinned pyxcp runtime."""

from __future__ import annotations

import importlib.metadata
import inspect
import sys

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the real pyxcp/Vector compatibility contract is a Windows gate",
)


def test_pyxcp_029_master_and_policy_contract() -> None:
    assert importlib.metadata.version("python-can") == "4.6.1"
    assert importlib.metadata.version("pyxcp") == "0.29.10"

    from pyxcp.master import Master
    from pyxcp.transport.transport_ext import FrameAcquisitionPolicy, NoOpPolicy

    assert tuple(inspect.signature(Master.getSeed).parameters) == (
        "self",
        "first",
        "resource",
    )
    assert tuple(inspect.signature(Master.unlock).parameters) == ("self", "length", "key")
    assert tuple(inspect.signature(Master.allocDaq).parameters) == ("self", "daq_count")
    assert tuple(inspect.signature(Master.startStopDaqList).parameters) == (
        "self",
        "mode",
        "daq_list_number",
    )
    assert callable(FrameAcquisitionPolicy.feed)
    assert callable(NoOpPolicy)

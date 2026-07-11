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
    assert importlib.metadata.version("pya2ldb") == "1.0.332"
    assert importlib.metadata.version("pyxcp") == "0.29.10"

    from pyxcp.master import Master
    from pyxcp.transport.transport_ext import FrameAcquisitionPolicy, NoOpPolicy

    assert tuple(inspect.signature(Master.getSeed).parameters) == (
        "self",
        "first",
        "resource",
    )
    assert tuple(inspect.signature(Master.unlock).parameters) == ("self", "length", "key")
    assert tuple(inspect.signature(Master.cond_unlock).parameters) == (
        "self",
        "resources",
    )
    assert tuple(inspect.signature(Master.allocDaq).parameters) == ("self", "daq_count")
    assert tuple(inspect.signature(Master.startStopDaqList).parameters) == (
        "self",
        "mode",
        "daq_list_number",
    )
    assert callable(FrameAcquisitionPolicy.feed)
    assert callable(NoOpPolicy)


def test_pyxcp_029_structured_resource_and_daq_category_contract() -> None:
    from pyxcp import types

    from mf4_analyzer.acquisition_capture.xcp_auth import RESOURCE_ID_DAQ

    resource = types.ResourceType.parse(bytes([0x05]))

    assert resource.calpag is True
    assert resource.daq is True
    assert resource.stim is False
    assert resource.pgm is False
    assert resource.dbg is False
    assert types.RESOURCE_VALUES["daq"] == RESOURCE_ID_DAQ == 0x04


def test_pyxcp_029_general_seed_key_trait_rejects_none() -> None:
    from traitlets import TraitError

    from pyxcp.config import General

    general = General()

    assert general.seed_n_key_dll == ""
    with pytest.raises(TraitError):
        general.seed_n_key_dll = None

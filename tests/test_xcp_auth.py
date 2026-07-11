"""DAQ-only Seed&Key tests for pinned pyxcp 0.29 positional calls."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mf4_analyzer.acquisition_capture.xcp_auth import XcpAuthError, unlock_resources_if_needed


class _Master:
    def __init__(self, *, protected: bool) -> None:
        self.protected = protected
        self.calls: list[tuple[object, ...]] = []

    def getStatus(self):  # noqa: N802 - pinned pyxcp spelling
        self.calls.append(("getStatus",))
        return SimpleNamespace(resourceProtectionStatus=SimpleNamespace(daq=self.protected))

    def getSeed(self, first, resource):  # noqa: N802
        self.calls.append(("getSeed", first, resource))
        return SimpleNamespace(seed=b"\x01\x02", length=2)

    def unlock(self, length, key):
        self.calls.append(("unlock", length, key))


def test_unprotected_daq_skips_seed_key_even_if_connect_resource_is_set() -> None:
    master = _Master(protected=False)
    unlock_resources_if_needed(master=master, connect_response=SimpleNamespace(resource=0xFF), seed_and_key_dll=None)
    assert master.calls == [("getStatus",)]


def test_protected_daq_without_provider_is_operator_error() -> None:
    with pytest.raises(XcpAuthError, match="DAQ is protected"):
        unlock_resources_if_needed(master=_Master(protected=True), connect_response=None, seed_and_key_dll=None)


def test_protected_daq_uses_pinned_positional_get_seed_and_unlock(tmp_path) -> None:
    provider = tmp_path / "seed64.dll"
    provider.write_bytes(b"placeholder")
    master = _Master(protected=True)
    with patch("mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll", return_value=object()), patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._compute_key_from_seed", return_value=b"\xDE\xAD"
    ):
        unlock_resources_if_needed(master=master, connect_response=None, seed_and_key_dll=str(provider))
    assert master.calls == [("getStatus",), ("getSeed", 0, 2), ("unlock", 2, b"\xDE\xAD")]


def test_missing_provider_and_ecu_rejection_remain_distinct(tmp_path) -> None:
    provider = tmp_path / "seed64.dll"
    provider.write_bytes(b"placeholder")
    master = _Master(protected=True)

    def reject(length, key):
        raise RuntimeError("ERR_ACCESS_DENIED")

    master.unlock = reject  # type: ignore[method-assign]
    with patch("mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll", return_value=object()), patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._compute_key_from_seed", return_value=b"\xDE"
    ), pytest.raises(XcpAuthError, match="ECU rejected unlock"):
        unlock_resources_if_needed(master=master, connect_response=None, seed_and_key_dll=str(provider))

"""DAQ-only Seed&Key tests for pinned pyxcp 0.29 positional calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mf4_analyzer.acquisition_capture.xcp_auth import (
    RESOURCE_ID_DAQ,
    XcpAuthError,
    unlock_resources_if_needed,
)


class _Master:
    def __init__(self, *, protected: bool) -> None:
        self.protected = protected
        self.calls: list[tuple[object, ...]] = []

    def getStatus(self):  # noqa: N802 - pinned pyxcp spelling
        self.calls.append(("getStatus",))
        return SimpleNamespace(resourceProtectionStatus=SimpleNamespace(daq=self.protected))

    def cond_unlock(self, resources=None):
        self.calls.append(("cond_unlock", resources))
        self.protected = False


def test_unprotected_daq_skips_seed_key_even_if_connect_resource_is_set() -> None:
    master = _Master(protected=False)
    state = unlock_resources_if_needed(
        master=master,
        connect_response=SimpleNamespace(resource=0xFF),
        seed_and_key_dll=None,
    )
    assert state == "unprotected"
    assert master.calls == [("getStatus",)]


def test_protected_daq_without_provider_is_operator_error() -> None:
    with pytest.raises(XcpAuthError, match="DAQ is protected") as caught:
        unlock_resources_if_needed(master=_Master(protected=True), connect_response=None, seed_and_key_dll=None)
    assert caught.value.daq_protection == "locked"


def test_protected_daq_delegates_to_official_pyxcp_cond_unlock(tmp_path) -> None:
    provider = tmp_path / "seed64.dll"
    provider.write_bytes(b"placeholder")
    master = _Master(protected=True)
    state = unlock_resources_if_needed(
        master=master,
        connect_response=None,
        seed_and_key_dll=str(provider),
    )
    assert RESOURCE_ID_DAQ == 0x04
    assert state == "unlocked"
    assert master.calls == [
        ("getStatus",),
        ("cond_unlock", "DAQ"),
        ("getStatus",),
    ]


def test_missing_provider_and_ecu_rejection_remain_distinct(tmp_path) -> None:
    provider = tmp_path / "seed64.dll"
    provider.write_bytes(b"placeholder")
    master = _Master(protected=True)

    def reject(resources=None):
        raise RuntimeError("ERR_ACCESS_DENIED")

    master.cond_unlock = reject  # type: ignore[method-assign]
    with pytest.raises(XcpAuthError, match="pyxcp cond_unlock") as caught:
        unlock_resources_if_needed(master=master, connect_response=None, seed_and_key_dll=str(provider))
    assert caught.value.daq_protection == "locked"


def test_missing_get_status_daq_fact_is_unknown() -> None:
    class MissingDaqMaster:
        def getStatus(self):  # noqa: N802 - pinned pyxcp spelling
            return SimpleNamespace(resourceProtectionStatus=SimpleNamespace(calpag=False))

    with pytest.raises(XcpAuthError, match="does not report DAQ") as caught:
        unlock_resources_if_needed(
            master=MissingDaqMaster(),
            connect_response=None,
            seed_and_key_dll=None,
        )
    assert caught.value.daq_protection == "unknown"


def test_unlock_that_leaves_daq_locked_is_not_reported_as_success(tmp_path) -> None:
    provider = tmp_path / "seed64.dll"
    provider.write_bytes(b"placeholder")
    master = _Master(protected=True)

    def keep_locked(resources=None):
        master.calls.append(("cond_unlock", resources))

    master.cond_unlock = keep_locked  # type: ignore[method-assign]
    with pytest.raises(XcpAuthError, match="remains protected") as caught:
        unlock_resources_if_needed(
            master=master,
            connect_response=None,
            seed_and_key_dll=str(provider),
        )
    assert caught.value.daq_protection == "locked"

"""Seed&Key auth flow for XCP DAQ resources."""

from __future__ import annotations

import os
from typing import Any, Literal

RESOURCE_ID_DAQ = 0x04
DaqProtectionState = Literal["unprotected", "locked", "unlocked", "unknown"]


class XcpAuthError(RuntimeError):
    """Raised when the XCP Seed&Key unlock flow fails."""

    def __init__(
        self,
        message: str,
        *,
        daq_protection: DaqProtectionState = "unknown",
    ) -> None:
        super().__init__(message)
        self.daq_protection = daq_protection


def unlock_resources_if_needed(
    *,
    master: Any,
    connect_response: Any,
    seed_and_key_dll: str | None,
) -> DaqProtectionState:
    """Read current protection state and unlock *only* DAQ when required.

    CONNECT's resource byte advertises resource availability; it is not a
    protection bitmap. The pinned pyxcp path queries GET_STATUS first and uses
    its ``resourceProtectionStatus.daq`` fact to decide whether an unlock is
    needed. Locked DAQ is delegated to pyxcp's official ``cond_unlock`` path;
    this module must not guess a vendor DLL ABI.
    """

    del connect_response  # kept at the public seam while callers migrate.
    protection = _daq_protection_status(master)
    if protection == "unprotected":
        return protection
    if seed_and_key_dll is None:
        raise XcpAuthError(
            "DAQ is protected but no seed&key DLL configured "
            "(set TransportConfig.seed_and_key_dll)",
            daq_protection="locked",
        )
    if not os.path.exists(seed_and_key_dll):
        raise XcpAuthError(
            f"seed&key DLL not found: {seed_and_key_dll}",
            daq_protection="locked",
        )

    try:
        master.cond_unlock("DAQ")
    except Exception as exc:
        raise XcpAuthError(
            f"pyxcp cond_unlock('DAQ') failed: {exc}",
            daq_protection="locked",
        ) from exc

    try:
        post_unlock = _daq_protection_status(master)
    except XcpAuthError as exc:
        raise XcpAuthError(
            f"unable to verify DAQ unlock: {exc}",
            daq_protection="unknown",
        ) from exc
    if post_unlock == "locked":
        raise XcpAuthError(
            "ECU accepted UNLOCK but DAQ remains protected",
            daq_protection="locked",
        )
    return "unlocked"


def _daq_protection_status(master: Any) -> Literal["unprotected", "locked"]:
    try:
        status = master.getStatus()
    except Exception as exc:
        raise XcpAuthError(
            f"GET_STATUS failed: {exc}",
            daq_protection="unknown",
        ) from exc
    protection = getattr(status, "resourceProtectionStatus", None)
    if protection is None:
        protection = getattr(status, "protection_status", None)
    if protection is None:
        raise XcpAuthError(
            "GET_STATUS returned no resource protection state",
            daq_protection="unknown",
        )
    if isinstance(protection, dict):
        value = protection.get("daq")
    elif isinstance(protection, int):
        value = bool(protection & RESOURCE_ID_DAQ)
    else:
        value = getattr(protection, "daq", None)
    if value is None:
        raise XcpAuthError(
            "GET_STATUS protection state does not report DAQ",
            daq_protection="unknown",
        )
    return "locked" if bool(value) else "unprotected"

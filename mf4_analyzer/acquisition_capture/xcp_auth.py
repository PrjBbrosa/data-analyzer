"""Seed&Key auth flow for XCP DAQ resources."""

from __future__ import annotations

import ctypes
import os
from typing import Any

RESOURCE_ID_DAQ = 0x02


class XcpAuthError(RuntimeError):
    """Raised when the XCP Seed&Key unlock flow fails."""


def _load_seed_key_dll(path: str) -> Any:
    return ctypes.WinDLL(path)  # type: ignore[attr-defined]


def _compute_key_from_seed(seed: bytes, dll: Any) -> bytes:
    fn = dll.ASAP1A_XCP_ComputeKeyFromSeed
    fn.restype = ctypes.c_int32
    fn.argtypes = [
        ctypes.c_uint8,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_uint8),
    ]
    seed_buf = (ctypes.c_uint8 * len(seed))(*seed)
    key_buf = (ctypes.c_uint8 * 256)()
    key_len = ctypes.c_uint8(256)
    rc = fn(len(seed), seed_buf, ctypes.byref(key_len), key_buf)
    if rc != 0:
        raise XcpAuthError(f"seed&key DLL rejected seed: code={rc}")
    return bytes(key_buf[: int(key_len.value)])


def unlock_resources_if_needed(
    *,
    master: Any,
    connect_response: Any,
    seed_and_key_dll: str | None,
) -> None:
    """Read current protection state and unlock *only* DAQ when required.

    CONNECT's resource byte advertises resource availability; it is not a
    protection bitmap.  The pinned pyxcp path queries GET_STATUS first and uses
    its ``resourceProtectionStatus.daq`` fact to decide whether an unlock is
    needed.
    """

    del connect_response  # kept at the public seam while callers migrate.
    protected = _daq_protection_status(master)
    if not protected:
        return
    if seed_and_key_dll is None:
        raise XcpAuthError(
            "DAQ is protected but no seed&key DLL configured "
            "(set TransportConfig.seed_and_key_dll)"
        )
    if not os.path.exists(seed_and_key_dll):
        raise XcpAuthError(f"seed&key DLL not found: {seed_and_key_dll}")

    try:
        dll = _load_seed_key_dll(seed_and_key_dll)
    except OSError as exc:
        message = str(exc)
        if "193" in message or "not a valid" in message.lower():
            raise XcpAuthError(
                "seed&key DLL bitness mismatch "
                f"(Python is {ctypes.sizeof(ctypes.c_void_p) * 8}-bit): {message}"
            ) from exc
        raise XcpAuthError(f"seed&key DLL load failed: {message}") from exc

    try:
        seed = _read_seed(master)
    except Exception as exc:
        raise XcpAuthError(f"getSeed failed: {exc}") from exc

    key = _compute_key_from_seed(seed, dll)
    try:
        master.unlock(len(key), key)
    except Exception as exc:
        raise XcpAuthError(f"ECU rejected unlock: {exc}") from exc


def _daq_protection_status(master: Any) -> bool:
    try:
        status = master.getStatus()
    except Exception as exc:
        raise XcpAuthError(f"GET_STATUS failed: {exc}") from exc
    protection = getattr(status, "resourceProtectionStatus", None)
    if protection is None:
        protection = getattr(status, "protection_status", None)
    if protection is None:
        raise XcpAuthError("GET_STATUS returned no resource protection state")
    if isinstance(protection, dict):
        value = protection.get("daq")
    elif isinstance(protection, int):
        value = bool(protection & RESOURCE_ID_DAQ)
    else:
        value = getattr(protection, "daq", None)
    if value is None:
        raise XcpAuthError("GET_STATUS protection state does not report DAQ")
    return bool(value)


def _read_seed(master: Any) -> bytes:
    """Read a possibly multi-part seed using pyxcp 0.29 positional calls."""

    try:
        response = master.getSeed(0, RESOURCE_ID_DAQ)
    except Exception as exc:
        raise XcpAuthError(f"getSeed failed: {exc}") from exc
    first = bytes(getattr(response, "seed", response))
    expected = getattr(response, "length", len(first))
    if not isinstance(expected, int) or expected < len(first):
        return first
    seed = bytearray(first)
    while len(seed) < expected:
        try:
            part_response = master.getSeed(1, 0)
        except Exception as exc:
            raise XcpAuthError(f"getSeed remaining-part failed: {exc}") from exc
        part = bytes(getattr(part_response, "seed", part_response))
        if not part:
            raise XcpAuthError("getSeed returned an empty remaining seed part")
        seed.extend(part)
    return bytes(seed[:expected])

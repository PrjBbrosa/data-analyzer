"""Seed&Key auth flow for XCP DAQ resources."""

from __future__ import annotations

import ctypes
import os
from typing import Any

RESOURCE_BIT_DAQ = 0x04
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
    """Unlock DAQ if the CONNECT RESOURCE byte says DAQ is protected."""

    resource = getattr(connect_response, "resource", 0) or 0
    if not resource & RESOURCE_BIT_DAQ:
        return
    if seed_and_key_dll is None:
        raise XcpAuthError(
            "RESOURCE.DAQ locked but no seed&key DLL configured "
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
        seed = master.getSeed(resource_id=RESOURCE_ID_DAQ)
    except Exception as exc:
        raise XcpAuthError(f"getSeed failed: {exc}") from exc

    key = _compute_key_from_seed(seed, dll)
    try:
        master.unlock(resource_id=RESOURCE_ID_DAQ, key=key)
    except Exception as exc:
        raise XcpAuthError(f"ECU rejected unlock: {exc}") from exc

"""Windows LockFileEx tests.

Native NTFS / LockFileEx acceptance is UNKNOWN on non-Windows.  A skip on
macOS is not product proof that locking passed.  Structured fakes cover the
call sequence; unrestricted MagicMock is not used.
"""
from __future__ import annotations

import sys

import pytest

from mf4_analyzer.extensions.contract import ExtensionError, ReasonCode
from mf4_analyzer.extensions.locking import (
    LOCKFILE_EXCLUSIVE_LOCK,
    MemoryLockBackend,
    WindowsAPI,
    WindowsLockBackend,
    acquire_exclusive_lock,
    acquire_shared_lease,
    is_unc_path,
    refuse_unsupported_filesystem,
)
from tests.test_extension_transaction import _write_core


NATIVE_SKIP_REASON = (
    "Not native LockFileEx/NTFS acceptance. Skipping here is not product proof "
    "that Windows locking passed; real NTFS / frozen EXE WAV/MP4 remain UNKNOWN."
)

requires_native_ntfs = pytest.mark.skipif(sys.platform != "win32", reason=NATIVE_SKIP_REASON)


@requires_native_ntfs
def test_deep_install_reads_and_uninstalls_long_store_paths(tmp_path):
    from mf4_analyzer.extensions.runtime import load_runtime, STATUS_READY
    from tests.test_extension_transaction import _engine, _make_verified_zip

    # A normal app path can produce >260-character content-addressed paths.
    app_root = tmp_path / ("deep-install-" + "x" * 70)
    _write_core(app_root)
    source = _make_verified_zip(tmp_path, "media")
    engine = _engine(app_root, MemoryLockBackend())
    engine.install([source])
    snapshot = load_runtime(app_root, frozen=True, acquire_lease=False)
    assert snapshot.availability("media").status == STATUS_READY
    package = snapshot.planned.module_roots[0] / "av" / "__init__.py"
    assert len(str(package)) > 260
    assert package.read_bytes() == b"__version__ = '1'\n"
    engine.uninstall(["media"])
    assert not load_runtime(app_root, frozen=True, acquire_lease=False).planned.module_roots


class FakeKernel32:
    """Explicit LockFileEx surface.  Not MagicMock."""

    def __init__(self) -> None:
        self.next_handle = 200
        self.handles: dict[int, str] = {}
        self.shared = 0
        self.exclusive = False
        self.last_error = 0
        self.drive_type = 3  # DRIVE_FIXED
        self.fs_name = "NTFS"
        self.volume_serial = 0x1111
        self.lock_calls: list[int] = []

    def CreateFileW(self, path, *args):
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = str(path)
        return handle

    def CloseHandle(self, handle):
        self.handles.pop(int(handle), None)
        return 1

    def LockFileEx(self, handle, flags, reserved, low, high, overlapped):
        del handle, reserved, low, high, overlapped
        self.lock_calls.append(int(flags))
        exclusive = bool(int(flags) & LOCKFILE_EXCLUSIVE_LOCK)
        if exclusive:
            if self.shared or self.exclusive:
                self.last_error = 33
                return 0
            self.exclusive = True
            return 1
        if self.exclusive:
            self.last_error = 33
            return 0
        self.shared += 1
        return 1

    def UnlockFileEx(self, handle, reserved, low, high, overlapped):
        del handle, reserved, low, high, overlapped
        if self.exclusive:
            self.exclusive = False
        elif self.shared:
            self.shared -= 1
        return 1

    def GetFinalPathNameByHandleW(self, handle, buf, length, flags):
        del flags
        path = self.handles.get(int(handle), "")
        buf.value = path[: max(0, int(length) - 1)]
        return len(path)

    def GetFileInformationByHandleEx(self, handle, klass, lpinfo, size):
        del handle, klass, size
        info = lpinfo._obj
        info.VolumeSerialNumber = self.volume_serial
        for index in range(len(info.FileId)):
            info.FileId[index] = 0
        info.FileId[0] = 9
        return 1

    def GetDriveTypeW(self, root):
        del root
        return self.drive_type

    def GetVolumeInformationW(self, drive, vol_buf, vol_n, serial, max_comp, flags, fs_buf, fs_n):
        del drive, vol_buf, vol_n, serial, max_comp, flags, fs_n
        fs_buf.value = self.fs_name
        return 1

    def GetLastError(self):
        return self.last_error

    def as_api(self) -> WindowsAPI:
        return WindowsAPI(
            CreateFileW=self.CreateFileW,
            LockFileEx=self.LockFileEx,
            UnlockFileEx=self.UnlockFileEx,
            CloseHandle=self.CloseHandle,
            GetFinalPathNameByHandleW=self.GetFinalPathNameByHandleW,
            GetFileInformationByHandleEx=self.GetFileInformationByHandleEx,
            GetDriveTypeW=self.GetDriveTypeW,
            GetVolumeInformationW=self.GetVolumeInformationW,
            GetLastError=self.GetLastError,
        )


def test_skip_reason_documents_unknown_native_acceptance():
    assert "UNKNOWN" in NATIVE_SKIP_REASON
    assert "not product proof" in NATIVE_SKIP_REASON.lower()
    assert "LockFileEx" in NATIVE_SKIP_REASON


def test_windows_structures_match_previously_bound_ctypes_pointer_types():
    import ctypes
    from mf4_analyzer.extensions.locking import _windows_structures

    # Binding argtypes and acquiring a lease ask for structures separately.
    # ctypes rejects pointers to an independently redefined, identical class.
    bound_types = _windows_structures()
    acquired_types = _windows_structures()
    for bound, acquired in zip(bound_types, acquired_types):
        ctypes.POINTER(bound).from_param(ctypes.byref(acquired()))


def test_unc_paths_are_refused_before_lock():
    assert is_unc_path(r"\\server\share\TraceLab")
    with pytest.raises(ExtensionError) as caught:
        refuse_unsupported_filesystem(r"\\server\share\TraceLab")
    assert caught.value.reason_code == ReasonCode.UNSUPPORTED_FILESYSTEM


def test_memory_backend_shared_then_exclusive_is_app_running(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    shared = acquire_shared_lease(app_root, backend=backend)
    with pytest.raises(ExtensionError) as caught:
        acquire_exclusive_lock(app_root, backend=backend)
    assert caught.value.reason_code == ReasonCode.APP_RUNNING
    shared.release()
    exclusive = acquire_exclusive_lock(app_root, backend=backend)
    with pytest.raises(ExtensionError) as caught_shared:
        acquire_shared_lease(app_root, backend=backend)
    assert caught_shared.value.reason_code == ReasonCode.APP_RUNNING
    exclusive.release()


def test_structured_fake_lockfileex_shared_blocks_exclusive(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    fake = FakeKernel32()
    backend = WindowsLockBackend(api=fake.as_api())
    shared = acquire_shared_lease(app_root, backend=backend)
    assert fake.lock_calls
    with pytest.raises(ExtensionError) as caught:
        acquire_exclusive_lock(app_root, backend=WindowsLockBackend(api=fake.as_api()))
    assert caught.value.reason_code == ReasonCode.APP_RUNNING
    shared.release()


def test_structured_fake_remote_drive_is_unsupported(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    fake = FakeKernel32()
    fake.drive_type = 4  # DRIVE_REMOTE
    backend = WindowsLockBackend(api=fake.as_api())
    with pytest.raises(ExtensionError) as caught:
        acquire_exclusive_lock(app_root, backend=backend)
    assert caught.value.reason_code == ReasonCode.UNSUPPORTED_FILESYSTEM


@requires_native_ntfs
def test_native_lockfileex_shared_then_exclusive(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    shared = acquire_shared_lease(app_root)
    try:
        with pytest.raises(ExtensionError) as caught:
            acquire_exclusive_lock(app_root)
        assert caught.value.reason_code == ReasonCode.APP_RUNNING
    finally:
        shared.release()
    exclusive = acquire_exclusive_lock(app_root)
    exclusive.release()

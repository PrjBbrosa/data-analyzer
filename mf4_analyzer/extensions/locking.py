"""Shared run lease and exclusive manager lock.

Neutral stdlib module: no Qt, UI, av, SciPy, h5py, or TUF.  Windows uses
``LockFileEx`` on a stable lease file keyed by NTFS file identity, not a PID
file.  POSIX ``fcntl`` and the in-memory backend exist so the state machine
can be tested off Windows; they are not NTFS / frozen-EXE acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Literal, Protocol

from mf4_analyzer.extensions.contract import ExtensionError, ReasonCode


LEASE_RELATIVE = Path(".locks") / "run.lease"
LOCK_BYTE_COUNT = 1
LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_ALWAYS = 4
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = -1
FILE_ID_INFO_CLASS = 18
ERROR_LOCK_VIOLATION = 33
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5

LockMode = Literal["shared", "exclusive"]
APP_RUNNING_MESSAGE = (
    "TraceLab is holding the run lease; close it from the app. "
    "The installer does not kill user processes."
)
UPDATING_MESSAGE = "extensions are updating; retry after the manager commits"


@dataclass(frozen=True)
class LockFileIdentity:
    """OS file identity for the lease.  Not a PID, window title, or exe name."""

    volume: str
    file_id: str
    normalized_path: str


@dataclass
class Lease:
    """Held OS (or test) lock.  Released by ``release()`` or process exit."""

    mode: LockMode
    identity: LockFileIdentity
    path: Path
    _release: Callable[[], None] = field(repr=False)
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self._release()

    def close(self) -> None:
        self.release()

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


class LockBackend(Protocol):
    def acquire(
        self,
        path: Path,
        mode: LockMode,
        *,
        app_root: Path,
        fail_immediately: bool = True,
    ) -> Lease:
        ...


def extensions_root(app_root: str | Path) -> Path:
    root = Path(app_root).expanduser().resolve()
    # Content-addressed store paths can exceed MAX_PATH even in a normal app
    # directory. Use the Win32 extended form for local extension I/O without
    # changing persisted relative pointers or weakening the UNC refusal.
    if sys.platform == "win32" and not is_unc_path(root) and not str(root).startswith("\\\\?\\"):
        root = Path("\\\\?\\" + str(root))
    return root / "extensions"


def lease_path(app_root: str | Path) -> Path:
    return extensions_root(app_root) / LEASE_RELATIVE


def is_unc_path(path: str | Path) -> bool:
    text = os.fspath(path).replace("/", "\\")
    if text.startswith("\\\\?\\UNC\\") or text.startswith("//?/UNC/"):
        return True
    if text.startswith("\\\\?\\"):
        rest = text[4:]
        return rest.startswith("UNC\\") or rest.startswith("\\\\")
    return text.startswith("\\\\") or text.startswith("//")


def refuse_unsupported_filesystem(
    path: str | Path,
    *,
    drive_type: int | None = None,
    filesystem_name: str | None = None,
) -> None:
    """Refuse UNC / remote / unknown volumes before creating a write lock."""

    if is_unc_path(path):
        raise ExtensionError(
            ReasonCode.UNSUPPORTED_FILESYSTEM,
            "install transactions require a local disk, not a UNC path",
        )
    if drive_type in {DRIVE_REMOTE, DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR, DRIVE_REMOVABLE, DRIVE_CDROM}:
        raise ExtensionError(
            ReasonCode.UNSUPPORTED_FILESYSTEM,
            "install transactions require a local NTFS volume",
        )
    if filesystem_name:
        fs_name = filesystem_name.upper()
        if sys.platform == "win32" and fs_name != "NTFS":
            raise ExtensionError(
                ReasonCode.UNSUPPORTED_FILESYSTEM,
                f"install transactions require NTFS, not {filesystem_name}",
            )


def same_volume(left: str | Path, right: str | Path) -> bool:
    left_path = Path(left)
    right_path = Path(right)
    left_stat = _existing_stat(left_path)
    right_stat = _existing_stat(right_path)
    return int(left_stat.st_dev) == int(right_stat.st_dev)


def _existing_stat(path: Path) -> os.stat_result:
    probe = Path(path)
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    return probe.stat()


def ensure_lease_file(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "ab") as handle:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
    return path


def default_backend() -> LockBackend:
    if sys.platform == "win32":
        return WindowsLockBackend()
    return PosixLockBackend()


def acquire_shared_lease(
    app_root: str | Path,
    *,
    backend: LockBackend | None = None,
    fail_immediately: bool = True,
) -> Lease:
    root = Path(app_root).expanduser().resolve()
    path = ensure_lease_file(lease_path(root))
    chosen = backend or default_backend()
    try:
        return chosen.acquire(
            path,
            "shared",
            app_root=root,
            fail_immediately=fail_immediately,
        )
    except ExtensionError:
        raise
    except LockBusyError as exc:
        raise ExtensionError(ReasonCode.APP_RUNNING, str(exc) or UPDATING_MESSAGE) from exc


def acquire_exclusive_lock(
    app_root: str | Path,
    *,
    backend: LockBackend | None = None,
    fail_immediately: bool = True,
) -> Lease:
    """Installer mutate lock.  Does not kill TraceLab; fails with APP_RUNNING."""

    root = Path(app_root).expanduser().resolve()
    refuse_unsupported_filesystem(root)
    path = ensure_lease_file(lease_path(root))
    if not same_volume(root, path):
        raise ExtensionError(
            ReasonCode.UNSUPPORTED_FILESYSTEM,
            "lock file is not on the same volume as the identified app root",
        )
    chosen = backend or default_backend()
    try:
        return chosen.acquire(
            path,
            "exclusive",
            app_root=root,
            fail_immediately=fail_immediately,
        )
    except ExtensionError:
        raise
    except LockBusyError as exc:
        raise ExtensionError(ReasonCode.APP_RUNNING, APP_RUNNING_MESSAGE) from exc


class LockBusyError(Exception):
    """Backend-level busy; mapped to APP_RUNNING by the public acquire helpers."""


class MemoryLockBackend:
    """In-process shared/exclusive lease for state-machine tests."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._shared: dict[str, int] = {}
        self._exclusive: dict[str, int] = {}
        self._identities: dict[str, LockFileIdentity] = {}
        self._next_id = 1

    def identity_for(self, path: Path) -> LockFileIdentity:
        key = str(Path(path).expanduser().resolve())
        found = self._identities.get(key)
        if found is not None:
            return found
        self._next_id += 1
        identity = LockFileIdentity(
            volume="mem-vol",
            file_id=str(self._next_id),
            normalized_path=key,
        )
        self._identities[key] = identity
        return identity

    def acquire(
        self,
        path: Path,
        mode: LockMode,
        *,
        app_root: Path,
        fail_immediately: bool = True,
    ) -> Lease:
        del fail_immediately
        refuse_unsupported_filesystem(path)
        ensure_lease_file(path)
        key = str(Path(path).expanduser().resolve())
        app_key = str(Path(app_root).expanduser().resolve())
        if Path(key) != lease_path(app_root).resolve() and not key.startswith(app_key):
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                "lease file is not under the identified app root",
            )
        with self._guard:
            shared = self._shared.get(key, 0)
            exclusive = self._exclusive.get(key, 0)
            if mode == "exclusive":
                if shared or exclusive:
                    raise LockBusyError(APP_RUNNING_MESSAGE)
                self._exclusive[key] = 1
            else:
                if exclusive:
                    raise LockBusyError(UPDATING_MESSAGE)
                self._shared[key] = shared + 1
            identity = self.identity_for(Path(path))

        def _release() -> None:
            with self._guard:
                if mode == "exclusive":
                    self._exclusive[key] = 0
                else:
                    current = self._shared.get(key, 0)
                    self._shared[key] = max(0, current - 1)

        return Lease(mode=mode, identity=identity, path=Path(path), _release=_release)


class PosixLockBackend:
    """``fcntl`` flock stand-in.  Advisory; not a Windows NTFS proof."""

    def acquire(
        self,
        path: Path,
        mode: LockMode,
        *,
        app_root: Path,
        fail_immediately: bool = True,
    ) -> Lease:
        import fcntl

        refuse_unsupported_filesystem(path)
        ensure_lease_file(path)
        resolved = Path(path).expanduser().resolve()
        root = Path(app_root).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                "lease file is not under the identified app root",
            ) from exc
        handle = open(resolved, "r+b")
        flags = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
        if fail_immediately:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError as exc:
            handle.close()
            raise LockBusyError(
                APP_RUNNING_MESSAGE if mode == "exclusive" else UPDATING_MESSAGE
            ) from exc
        stat_result = resolved.stat()
        identity = LockFileIdentity(
            volume=str(stat_result.st_dev),
            file_id=str(stat_result.st_ino),
            normalized_path=str(resolved),
        )

        def _release() -> None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

        return Lease(mode=mode, identity=identity, path=resolved, _release=_release)


@dataclass(frozen=True)
class WindowsAPI:
    """Structured kernel32 surface.  Tests pass explicit callables, not MagicMock."""

    CreateFileW: Callable[..., int]
    LockFileEx: Callable[..., int]
    UnlockFileEx: Callable[..., int]
    CloseHandle: Callable[..., int]
    GetFinalPathNameByHandleW: Callable[..., int]
    GetFileInformationByHandleEx: Callable[..., int]
    GetDriveTypeW: Callable[..., int]
    GetVolumeInformationW: Callable[..., int]
    GetLastError: Callable[[], int]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_ulonglong),
        ("InternalHigh", ctypes.c_ulonglong),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class _FILE_ID_INFO(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", ctypes.c_ubyte * 16),
    ]


def _windows_structures() -> tuple[Any, Any]:
    # ctypes argtypes require the exact same class, not just the same layout.
    # Defining these once also keeps concurrent backend creation consistent.
    return _OVERLAPPED, _FILE_ID_INFO


def load_real_windows_api() -> WindowsAPI:
    """Bind LockFileEx via ctypes.  Must not run at import on non-Windows."""

    if sys.platform != "win32":
        raise ExtensionError(
            ReasonCode.UNSUPPORTED_FILESYSTEM,
            "real LockFileEx API is Windows-only; this is not a native acceptance path",
        )
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    OVERLAPPED, _file_id_info = _windows_structures()
    kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    kernel32.LockFileEx.restype = wintypes.BOOL
    kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    kernel32.UnlockFileEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    kernel32.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetVolumeInformationW.restype = wintypes.BOOL

    def _last_error() -> int:
        return int(ctypes.get_last_error())

    return WindowsAPI(
        CreateFileW=kernel32.CreateFileW,
        LockFileEx=kernel32.LockFileEx,
        UnlockFileEx=kernel32.UnlockFileEx,
        CloseHandle=kernel32.CloseHandle,
        GetFinalPathNameByHandleW=kernel32.GetFinalPathNameByHandleW,
        GetFileInformationByHandleEx=kernel32.GetFileInformationByHandleEx,
        GetDriveTypeW=kernel32.GetDriveTypeW,
        GetVolumeInformationW=kernel32.GetVolumeInformationW,
        GetLastError=_last_error,
    )


class WindowsLockBackend:
    """LockFileEx exclusive/shared lease keyed by NTFS file id."""

    def __init__(self, api: WindowsAPI | None = None) -> None:
        self.api = api

    def _api(self) -> WindowsAPI:
        if self.api is None:
            self.api = load_real_windows_api()
        return self.api

    def acquire(
        self,
        path: Path,
        mode: LockMode,
        *,
        app_root: Path,
        fail_immediately: bool = True,
    ) -> Lease:
        import ctypes
        from ctypes import wintypes

        OVERLAPPED, FILE_ID_INFO = _windows_structures()
        api = self._api()
        root = Path(app_root).expanduser().resolve()
        self._refuse_remote_volume(api, root)
        ensure_lease_file(path)
        handle = int(
            api.CreateFileW(
                str(Path(path).expanduser().resolve()),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_ALWAYS,
                FILE_ATTRIBUTE_NORMAL,
                0,
            )
        )
        if handle in {INVALID_HANDLE_VALUE, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF}:
            raise ExtensionError(
                ReasonCode.UNSUPPORTED_FILESYSTEM,
                f"could not open lease file (GetLastError={api.GetLastError()})",
            )
        try:
            normalized = self._final_path(api, handle)
            identity = self._file_identity(api, handle, FILE_ID_INFO, normalized)
            self._assert_lock_identity(api, FILE_ID_INFO, root, identity)
            overlapped = OVERLAPPED()
            overlapped.Offset = 0
            overlapped.OffsetHigh = 0
            flags = LOCKFILE_FAIL_IMMEDIATELY if fail_immediately else 0
            if mode == "exclusive":
                flags |= LOCKFILE_EXCLUSIVE_LOCK
            ok = api.LockFileEx(
                handle,
                flags,
                0,
                LOCK_BYTE_COUNT,
                0,
                ctypes.byref(overlapped),
            )
            if not ok:
                error = api.GetLastError()
                if error in {ERROR_LOCK_VIOLATION, 0}:
                    raise LockBusyError(
                        APP_RUNNING_MESSAGE if mode == "exclusive" else UPDATING_MESSAGE
                    )
                raise ExtensionError(
                    ReasonCode.UNSUPPORTED_FILESYSTEM,
                    f"LockFileEx failed (GetLastError={error})",
                )
        except Exception:
            api.CloseHandle(handle)
            raise

        def _release() -> None:
            unlock = OVERLAPPED()
            unlock.Offset = 0
            unlock.OffsetHigh = 0
            try:
                api.UnlockFileEx(
                    handle,
                    0,
                    LOCK_BYTE_COUNT,
                    0,
                    ctypes.byref(unlock),
                )
            finally:
                api.CloseHandle(handle)

        return Lease(mode=mode, identity=identity, path=Path(path), _release=_release)

    def _refuse_remote_volume(self, api: WindowsAPI, root: Path) -> None:
        drive = _drive_root(root)
        drive_type = int(api.GetDriveTypeW(drive))
        fs_name = _volume_fs_name(api, drive)
        refuse_unsupported_filesystem(root, drive_type=drive_type, filesystem_name=fs_name)

    def _final_path(self, api: WindowsAPI, handle: int) -> str:
        import ctypes
        from ctypes import wintypes

        length = 1024
        buf = ctypes.create_unicode_buffer(length)
        written = int(api.GetFinalPathNameByHandleW(handle, buf, length, 0))
        if written == 0:
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                "GetFinalPathNameByHandleW failed for the lease file",
            )
        return buf.value

    def _file_identity(
        self,
        api: WindowsAPI,
        handle: int,
        file_id_info_cls: Any,
        normalized: str,
    ) -> LockFileIdentity:
        import ctypes

        info = file_id_info_cls()
        ok = api.GetFileInformationByHandleEx(
            handle,
            FILE_ID_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                "GetFileInformationByHandleEx(FileIdInfo) failed",
            )
        file_id = bytes(info.FileId).hex()
        return LockFileIdentity(
            volume=str(info.VolumeSerialNumber),
            file_id=file_id,
            normalized_path=normalized,
        )

    def _assert_lock_identity(
        self,
        api: WindowsAPI,
        file_id_info_cls: Any,
        app_root: Path,
        lease_identity: LockFileIdentity,
    ) -> None:
        import ctypes

        marker = Path(app_root) / "core.json"
        if not marker.is_file():
            marker = Path(app_root)
        handle = int(
            api.CreateFileW(
                str(marker),
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                3,  # OPEN_EXISTING
                FILE_ATTRIBUTE_NORMAL,
                0,
            )
        )
        if handle in {INVALID_HANDLE_VALUE, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF}:
            return
        try:
            root_identity = self._file_identity(
                api,
                handle,
                file_id_info_cls,
                self._final_path(api, handle),
            )
        finally:
            api.CloseHandle(handle)
        if root_identity.volume != lease_identity.volume:
            raise ExtensionError(
                ReasonCode.UNSUPPORTED_FILESYSTEM,
                "lease file volume does not match the identified app root",
            )


def _drive_root(path: Path) -> str:
    text = str(Path(path).expanduser().resolve())
    if len(text) >= 2 and text[1] == ":":
        return text[:2] + "\\"
    return str(path)


def _volume_fs_name(api: WindowsAPI, drive: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    fs_buf = ctypes.create_unicode_buffer(32)
    vol_buf = ctypes.create_unicode_buffer(32)
    serial = wintypes.DWORD()
    max_comp = wintypes.DWORD()
    flags = wintypes.DWORD()
    ok = api.GetVolumeInformationW(
        drive,
        vol_buf,
        32,
        ctypes.byref(serial),
        ctypes.byref(max_comp),
        ctypes.byref(flags),
        fs_buf,
        32,
    )
    if not ok:
        return None
    return fs_buf.value


def write_staging_auth(staging_dir: Path, nonce: str) -> Path:
    """Create the per-transaction read grant.  Not an environment skip."""

    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / "staging.auth"
    payload = nonce.strip().encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def verify_staging_auth(
    staging_dir: Path,
    nonce: str,
    *,
    extensions_root_path: Path,
    transaction_id: str,
) -> Path:
    """Child-side grant check: path must be this transaction's staging tree."""

    staging = Path(staging_dir).expanduser().resolve()
    root = Path(extensions_root_path).expanduser().resolve()
    expected = (root / ".staging" / transaction_id).resolve()
    # Normal and extended Win32 spellings may identify the same directory.
    if staging != expected and not (
        staging.is_dir() and expected.is_dir() and staging.samefile(expected)
    ):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "probe staging path is not the authorized transaction staging directory",
        )
    auth = staging / "staging.auth"
    if not auth.is_file():
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "probe staging auth file is missing; env skip is not allowed",
        )
    actual = auth.read_bytes().decode("utf-8").strip()
    if actual != nonce.strip():
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "probe staging nonce does not match the exclusive-holder grant",
        )
    return staging


__all__ = (
    "APP_RUNNING_MESSAGE",
    "LEASE_RELATIVE",
    "Lease",
    "LockBusyError",
    "LockFileIdentity",
    "LockMode",
    "MemoryLockBackend",
    "PosixLockBackend",
    "WindowsAPI",
    "WindowsLockBackend",
    "acquire_exclusive_lock",
    "acquire_shared_lease",
    "default_backend",
    "ensure_lease_file",
    "extensions_root",
    "is_unc_path",
    "lease_path",
    "load_real_windows_api",
    "refuse_unsupported_filesystem",
    "same_volume",
    "verify_staging_auth",
    "write_staging_auth",
)

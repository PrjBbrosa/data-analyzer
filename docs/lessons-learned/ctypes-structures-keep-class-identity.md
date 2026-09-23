---
id: ctypes-structures-keep-class-identity
status: active
owners: [codex]
keywords: [ctypes, windows, LockFileEx, OVERLAPPED, native, structure]
paths: [mf4_analyzer/extensions/locking.py]
checks: [Native Windows shared-exclusive lease test]
tests: [tests/test_extension_windows_locking.py]
---

# ctypes Structure Definitions Must Keep Class Identity

Trigger: A ctypes structure is shared between function argtypes and native call sites.

Past failure: A helper redefined OVERLAPPED every time it was called. Kernel32 binding and lease acquisition therefore used different class objects with identical layouts. Fake API tests passed, while real LockFileEx rejected the pointer before entering Windows.

Rule: Define shared ctypes structure types once. Identical names and field layouts do not make independently created Python classes pointer-compatible. Keep the Windows API binding lazy; stdlib structure definitions can remain import-safe on other platforms.

Verification: Convert an acquired structure pointer through the previously bound pointer type on every platform. Also run the real Windows shared-to-exclusive locking test and the frozen extension installation gate.

---
id: windows-extension-store-long-paths
status: active
owners: [codex]
keywords: [Windows, MAX_PATH, extensions, staging, content-addressed]
paths: [mf4_analyzer/extensions/locking.py, mf4_analyzer/extensions/probe.py]
checks: [Native Windows deep install and frozen combination gates]
tests: [tests/test_extension_windows_locking.py, tests/test_extension_transaction.py, tests/test_extension_probe.py]
---

# Windows Extension Stores Need Long Path Handling

Trigger: Installing or reading content-addressed extension packages on Windows.

Past failure: A normal local app directory grew beyond MAX_PATH after staging IDs, runtime IDs, package hashes and native DLL names were appended. Extraction raised FileNotFoundError/WinError 206 even though parent creation and available disk space were correct.

Rule: Route extension filesystem paths through the shared extensions_root owner, using the local Win32 extended path form. Keep persisted package references relative and retain UNC rejection. Authentication must recognize normal and extended spellings of the same authorized directory without accepting a different directory. Do not shorten only the smoke-test path or change the machine registry to conceal the product defect.

Verification: Reproduce installation, stored-file reads and uninstall with paths longer than 260 characters on Windows. Run native lock/transaction/probe checks and rebuild frozen binaries before repeating the real extension combination gate.

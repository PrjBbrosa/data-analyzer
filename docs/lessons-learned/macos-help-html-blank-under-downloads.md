---
id: macos-help-html-blank-under-downloads
status: active
owners: [codex]
keywords: [macos, help, downloads, browser, tcc]
paths: [mf4_analyzer/help/__init__.py]
checks:
  - On macOS, open a real temp copy of the help tree with /usr/bin/open.
  - Do not symlink that copy back into Downloads, Desktop, or Documents.
tests:
  - tests/test_help_browser_open.py
---

# Open macOS Help From a Browser-Readable Copy

Trigger: Opening bundled HTML help on macOS from a checkout under Downloads, Desktop, or Documents.

Past failure: `QDesktopServices.openUrl` gave Chrome a `file://` URL inside
`~/Downloads`. The browser process cannot read that folder, so the tab is
blank even though the same HTML renders when the reader has access.

Rule: Publish a real copy of the help directory under the user temp directory
and open that path with `/usr/bin/open`. Keep relative asset names. A symlink
still resolves into the protected directory.

Verification: `tests/test_help_browser_open.py`.

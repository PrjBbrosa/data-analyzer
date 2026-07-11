---
id: claude-native-wrapper-stub-recovery
status: active
owners: [codex]
keywords: [claude, npm, postinstall, native-binary, darwin-arm64]
paths: []
checks:
  - command -v claude
  - file /opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
  - claude --version
tests: []
---

# Claude Native Wrapper Stub Recovery

Trigger: `claude` resolves to the global npm install but prints `claude native binary not installed` on Apple Silicon.

Past failure: The platform-native optional package was downloaded and runnable,
but the global wrapper still pointed at a small placeholder script because
postinstall had not replaced it.

Rule: Inspect the wrapper target and the nested `darwin-arm64` binary before
reinstalling. If the native binary exists and runs, rerun the installed
`install.cjs`; reinstall with optional dependencies only when it is absent.

Verification: Confirm `ignore-scripts`, `omit`, and `optional` npm settings,
verify the wrapper is a Mach-O arm64 executable after repair, and run `claude
--version` successfully.

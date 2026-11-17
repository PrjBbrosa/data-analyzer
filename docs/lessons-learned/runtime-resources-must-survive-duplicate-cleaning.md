---
id: runtime-resources-must-survive-duplicate-cleaning
status: active
owners: [codex]
keywords: [CleanMyMac, duplicate, deleted, resources, qss, recovery]
paths: [mf4_analyzer/ui_kit/style.qss, mf4_analyzer/help/assets/, assets/]
checks: [git ls-files --deleted, git diff --check]
tests: [tests/ui_kit/test_stylesheet_parses.py]
---

# Runtime Resources Must Survive Duplicate Cleaning

Trigger: Runtime resources disappear, the app loses its global styling, or a cleanup proposes deleting duplicate files inside a working repository.

Past failure: CleanMyMac 5 DuplicateRemovalTask deleted nine tracked TraceLab
resources on 2026-10-02 at 20:43:35 Asia/Shanghai, including style.qss. Its log
records each removed path (lines 11912–11924 of the main log started on
2026-08-26). A similar task deleted help images and the logo on September 12.
The stylesheet loader silently returned when the file was missing.

Rule: Equal content does not make runtime paths interchangeable. Do not approve
repository resource deletion based on duplicate detection. Recommend excluding
working repositories from duplicate cleaning; change external app settings only
with authorization. Before authorized recovery, preserve Git status and parent
directory timestamps, then match paths against deletion logs. Restore only the
confirmed scope from a known revision and distinguish recovery of committed
content from recovery of possible uncommitted changes. Never attribute deletion
to an agent or person from timestamps alone.

Verification: Check git ls-files --deleted, compare restored blob hashes with
the chosen revision, run tests/ui_kit/test_stylesheet_parses.py, and probe the
production loader for nonempty QSS without parse errors. Keep foreground visual
acceptance separate. Local incident evidence is under
.state/resource-recovery-20261003/; it is not a committed artifact.

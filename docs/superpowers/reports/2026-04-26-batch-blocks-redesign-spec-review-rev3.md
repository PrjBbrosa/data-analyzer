# Spec Review: Batch-Blocks Redesign Rev 3

## 1. Verdict
needs revision before plan

## 2. Prior Findings Status
- **NF-1: resolved.** §4.4 now gives all `BatchProgressEvent` payload fields `None` defaults and a per-kind payload table, §6.2 includes `task_cancelled` and `run_finished(final_status='done'|'partial'|'cancelled'|'blocked')`, and §6.2 says the unlock trigger is "始终为 `QThread.finished` 信号".
- **NF-2: resolved.** §4.1 marks `signal_pattern` as "后端兜底（UI 不写入）" with serialization `✗`, §4.2's JSON schema omits it, and §8 says saved files must not contain `signal_pattern`.
- **NF-3: partial.** §4.3 and §6.2.1 now state all-missing target signals should produce 0 tasks and `BatchRunResult(status='blocked')`, but §4.3's shown loop still says missing channels execute `else: ... yield fid, fd, ch`, so the backend expansion rule remains contradictory.
- **NF-4: resolved.** §9 slice 2 now spells out the full runner signature: `run(preset, output_dir, progress_callback=None, *, on_event=None, cancel_token=None)`.
- **F-1: resolved.** §4.3 defines `BatchRunner.__init__(files, loader=...)`, `_loader = loader or _default_loader`, and per-instance `_disk_cache`, and §8 covers both `file_paths` lazy-load success and load failure.

## 3. New Findings (if any)
None beyond the unresolved NF-3 contradiction above.

## 4. Cross-Check Summary
- **§4.4 payload table vs §6.2 vs §8 — pass.** §4.4 defines required payload fields for all five kinds, §6.2 maps `task_started` / `task_done` / `task_failed` / `task_cancelled` / `run_finished` into UI flow, and §8 requires tests that all five event kinds can trigger.
- **§4.3 blocked behavior vs §6.2.1 vs §7 — fail.** §6.2.1 says 0 expanded tasks returns `BatchRunResult(status='blocked', blocked=['no matching batch tasks'])`, and §7 says all unavailable imported `target_signals` disables Run; however, §4.3's pseudo-code still yields a task in the missing-signal `else` branch.
- **§4.1 signal_pattern vs §4.2 vs §8 — pass.** §4.1 says `signal_pattern` is not serialized, §4.2's schema does not include it, and §8's whitelist test explicitly excludes it.
- **§4.3 loader injection vs §8 — pass.** §4.3 defines constructor injection plus `_default_loader` fallback and `_disk_cache`, and §8 requires tests for lazy-load success and load failure.

## 5. Short Summary
Rev 3 resolves NF-1, NF-2, NF-4, and the F-1 loader-injection leftover. The remaining must-fix issue is NF-3: the prose and tests now specify the all-missing case as blocked, but the §4.3 pseudo-code still yields missing-signal tasks. This blocks writing a reliable implementation plan because runner behavior would depend on which part of §4.3 an implementer follows. No additional NF-5+ inconsistencies were found in the requested cross-checks.

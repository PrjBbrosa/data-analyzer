# Stage 8 Bench Evidence

This directory holds **raw evidence from PR-4 bench runs** — every MF4,
session summary, screenshot, console excerpt that a future investigator
might need to reconstruct what happened on the bench / vehicle.

## Per-round subdirectory naming

```
docs/analyzer/acquisition/evidence/stage-8/
└── <YYYY-MM-DD>-<round>/
    ├── README.md            (one-paragraph round summary; pass/fail per step)
    ├── step1-failure.txt    (only if Test Connection went red)
    ├── step2-a2l-warning.txt (only if A2L pick popped a warning dialog)
    ├── step3-3sig-30s.mf4
    ├── step3-3sig-30s.session_summary.json
    ├── step4-12sig-60s.mf4
    ├── step4-12sig-60s.session_summary.json
    ├── step5-<vnmodel>-3sig-30s.mf4  (one per VN hardware tested)
    ├── step6-canfd-24sig-60s.mf4     (only if CAN-FD round)
    ├── settings-screenshot.png       (Settings → Transport showing app_name / channel / bitrate)
    ├── vector-hwconfig.png           (Vector Hardware Configurator with the bench HW)
    └── operator-notes.md             (free-form: anything unusual; ECU state; harness changes)
```

`<round>` is a short suffix to distinguish multiple sessions on the
same day: `round1`, `round2`, or `vn1610`, `vn1630`, etc. Keep it
under 8 characters so the directory name fits in `ls -l` cleanly.

## Why the convention is strict

The PR-4 acceptance gate (`runbooks/stage-8-pr4-bench.md`) hinges on
being able to point at concrete MF4s and prove the timestamps / sample
counts hit tolerance. If files land here ad-hoc, the next operator —
or the next bug investigation — has to guess which file was which
step, which round corrupted, which session was CAN-FD vs. classic.
That ambiguity has burned us before.

## What does NOT belong here

- Personal credentials, ECU Seed&Key DLLs, vehicle VINs.
- Anything generated from running tests on Mac side (those go under
  `docs/analyzer/acquisition/reports/`).
- Synthetic / fake-backend MF4s — only real ECU recordings.

## After a round

1. `README.md` in the round subdirectory (1–3 sentences):
   "Round 1 on VN1630 + ERD6 dev mule. Steps 1-3 green. Step 4 dropped
   2 samples at 50 s — see operator-notes.md. Step 5 deferred (no
   second VN model on site)."
2. Append the round to the parent action board's *变更日志* footer:
   date + outcome.
3. If anything code-related came up, file a follow-up task on the Mac
   side AND link it from the round's `README.md`.

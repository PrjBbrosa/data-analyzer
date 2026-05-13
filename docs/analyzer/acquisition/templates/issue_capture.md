# Issue Capture & Regression Procedure

Use this template every time a real vehicle / bench / customer report reveals
an analyzer or acquisition bug. The goal is a permanently-failing test that
goes green only when the bug is actually fixed.

## 0. Trigger

Describe the symptom in one paragraph:

- What you saw:
- What you expected:
- Where it was observed (vehicle ID, bench rig, customer ticket):

## 1. Capture the clip

- Trim the source MF4 to **10–60 seconds** that demonstrate the issue.
- Save to `data/local/issue/<short-slug>.mf4` (gitignored).
- Compute SHA256:

  ```bash
  python -c "from mf4_analyzer.acquisition.manifest import sha256_file; print(sha256_file('data/local/issue/<slug>.mf4'))"
  ```

## 2. Add a manifest entry

Append to `data/manifest.local.json` under `entries`:

```json
{
  "id": "<short-slug>",
  "path": "local/issue/<short-slug>.mf4",
  "path_kind": "local",
  "sets": ["issue"],
  "vehicle": "<vehicle id or 'unknown'>",
  "platform": "<platform>",
  "scenario": "<short scenario>",
  "issue_tags": ["<tag1>", "<tag2>"],
  "expected_channels": ["<channel-or-standard-signal>", "..."],
  "sha256": "<hash from step 1>",
  "required": false
}
```

Use `path_kind: "lfs"` instead if the clip will be checked in.

## 3. Write a failing test

Add a test under `tests/issue/test_<short-slug>.py` that asserts the **correct**
behavior. Run it first; it must FAIL before any code changes.

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/issue/test_<short-slug>.py -v
```

## 4. Fix the bug

Implement the smallest change that turns the test green. Do not weaken the
test. If the assertion shape is wrong, fix the assertion in a separate commit
with a written reason.

## 5. Promote the clip

If the clip is genuinely useful as a permanent fixture:

- If it can be checked in: move to `data/golden/issue/<slug>.mf4` (Git LFS),
  flip the manifest entry's `sets` to `["issue", "golden"]` and `path_kind` to `lfs`.
- If it cannot be checked in: leave under `data/local/`, update the team-shared
  NAS index per roadmap §4 with the SHA256.

## 6. Record the lesson

If the bug revealed a durable analyzer rule (e.g., "loader must keep raw names")
write it to `docs/lessons-learned/<area>/<date>-<slug>.md` and update
`LESSONS.md`.

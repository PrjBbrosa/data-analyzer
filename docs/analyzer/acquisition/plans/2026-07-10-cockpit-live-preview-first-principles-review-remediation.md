# Cockpit First-Principles Review Remediation — 5.6 Terra Execution Plan

> **Executor:** one GPT-5.6 Terra agent, sequential execution only. Read the
> source spec and this plan completely before editing. Tasks 1–5 are closed TDD
> slices: failing test → minimal implementation → focused green → commit. Task 6
> consolidates those already-proven behaviors into the final tour and gates.
> Do not combine tasks, skip the failing-test proof, or push from the worker.

Date: 2026-07-10

Source spec: `docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-preview-first-principles-spec.md`

Original implementation plan: `docs/analyzer/acquisition/plans/2026-07-10-cockpit-live-preview-first-principles-implementation.md`

Reviewed implementation head at plan time: `13334f07`

Target branch: `codex/cockpit-first-principles-review-remediation`

## Goal

Close the five actionable UI-contract gaps found after Claude completed the
first-principles implementation, while preserving the accepted two-column body,
Replay right-panel boundary, live-card performance work, health thresholds, and
recording core.

The final handoff must make the following statements literally true:

1. Healthy state is quiet; unknown/yellow/red state is concise Chinese and no
   escalation issue is silently discarded.
2. The status bar says what state the app is in and shows the promised idle /
   recording facts with whole-field width degradation.
3. A health popover cannot survive a mode-page switch.
4. The preflight popover contains the required trust note and does not leak it
   into ordinary chip details.
5. Clearing a live-card data lifecycle returns it to an honest no-data state.

## Why one sequential agent

Tasks 1, 3, and 4 all touch `HealthStrip` / `HealthPopover`; Tasks 2 and 6 both
touch status/tour assertions; Tasks 5 and 6 both touch live-card acceptance.
Parallel workers would create artificial merge conflicts and make it easy to
green one task with stale assertions from another. One Terra agent should keep
the contract chain coherent and produce one commit per task.

## Review Finding → Contract → Task Matrix

| Finding | Source contract | Primary code | Task |
| --- | --- | --- | --- |
| Health summary is always-visible English; third+ issues disappear | Spec B6, especially lines 228–248 | `health_strip.py:350-439,717-729`; `escalation_bar.py:241-266,321-324` | 1 |
| Idle/recording fact text lacks promised context | Spec B5 lines 211–224 | `_settings_mixin.py:251-344` | 2 |
| Mode switch leaves popover visible | Spec B1 lines 148–161 | `window.py:378-379`; `health_strip.py:543-590` | 3 |
| Preflight popover has five rows but no trust note | Spec B2 lines 163–174 | `health_popover.py`; `health_strip.py:492-505` | 4 |
| Reset leaves an empty card classified as live | Spec A3 lines 94–110 | `live_cards.py:1212-1245,1264-1292` | 5 |

## Global Constraints

- Use `.venv/bin/python`; run pytest/tours in the foreground. Never use
  `run_in_background`.
- Work in an isolated worktree. The source checkout currently has unrelated
  dirty files that must not be edited, staged, copied, or reverted:
  `docs/lessons-learned/.state.yml`,
  `mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py`,
  `mf4_analyzer/ui_kit/style.qss`, and
  `tests/acquisition_ui/test_visual_shell.py`, plus untracked
  `codex-review-report.html` / `output/`.
- The source spec is correct. Do not weaken or rewrite it to match the current
  implementation.
- Do not change acquisition thresholds, `HealthSnapshot`, controller, ring,
  writer, sample shape, or auto-stop authority.
- Do not reintroduce a capture `RightPanel`. `ReplayTab` remains its only
  consumer.
- Do not touch painter/downsampler/tick math unless a regression test proves the
  remediation broke them.
- Preserve current object names and dynamic properties unless a task explicitly
  adds a new introspection hook.
- No new dependency. Prefer a Qt signal over reaching across widgets through a
  private attribute.
- Tests must assert literal contract outcomes, not merely “text is non-empty”,
  “contains some Chinese”, or “row_count == 5”.
- Onscreen evidence is mandatory for final UI acceptance; offscreen green is
  structural evidence only.
- Worker commits locally and returns evidence. Parent reviewer owns the final
  review and `git push` decision.

---

## Task 0: Isolated worktree + exact baseline

**Purpose:** protect the user's current dirty checkout and prove the worker
starts from the completed implementation rather than from `origin/main`.

- [ ] **Step 1: Read before mutation**

Read, in full:

```text
docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-preview-first-principles-spec.md
docs/analyzer/acquisition/plans/2026-07-10-cockpit-live-preview-first-principles-review-remediation.md
docs/lessons-learned/codex-plan-spec-literal-evidence.md
docs/lessons-learned/codex-visual-parity-rendered-screenshot.md
docs/lessons-learned/codex-confirmed-issue-list-means-remaining-scope.md
```

- [ ] **Step 2: Verify source state and create/reuse the worktree**

From the source checkout:

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 13334f07 HEAD
```

Expected: the implementation head `13334f07` is an ancestor. The remediation
branch starts from that exact reviewed implementation commit; the worker reads
this plan from the source checkout before entering the sibling worktree.

Create a clean sibling worktree (choose another unused sibling path if this one
already exists):

```bash
BASE=13334f07
git worktree add ../data-analyzer-cockpit-remediation \
  -b codex/cockpit-first-principles-review-remediation "$BASE"
cd ../data-analyzer-cockpit-remediation
if [ ! -e .venv ]; then
  ln -s "/Users/donghang/Downloads/data analyzer/.venv" .venv
fi
test -x .venv/bin/python
git status --short --branch
```

`.venv/` is gitignored; the symlink only lets the clean worktree reuse the
project's existing runtime and must never be staged.

If the branch/worktree already exists, reuse it only when it is clean and still
contains `13334f07`; otherwise stop and report the conflict. Do not delete or
reset an existing worktree.

- [ ] **Step 3: Baseline gates**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py \
  tests/acquisition_ui/test_live_downsampler.py \
  tests/acquisition_ui/test_health_strip.py \
  tests/acquisition_ui/test_escalation.py \
  tests/acquisition_ui/test_pinned_monitoring.py \
  tests/acquisition_ui/test_status_bar_text.py \
  tests/acquisition_ui/test_right_panel.py \
  tests/acquisition_ui/test_replay_tab.py \
  tests/acquisition_ui/test_state_machine.py -q
```

Expected baseline at plan time: `173 passed`. A different count is acceptable
only if every listed test passes and the agent records why the count changed.

No commit for Task 0.

---

## Task 1: Complete B6 health summary + overflow/detail path

**Files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
- Modify: `mf4_analyzer/acquisition_ui/widgets/escalation_bar.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`
- Test: `tests/acquisition_ui/test_health_strip.py`
- Test: `tests/acquisition_ui/test_escalation.py`

**Interfaces:**

- Production must consume the existing
  `effective_chip_levels(snapshot, state)` helper; it must not remain a
  test-only function.
- Add `EscalationBar.details_requested = pyqtSignal(str)` carrying the most
  severe issue's `source_chip`.
- Give the detail control objectName `escalationBarDetails` and expose either a
  read-only `details_button` property or find it by objectName in tests.
- Add a public `HealthStrip.open_chip_detail(name: str) -> None` entrypoint that
  reuses the single existing popover. `CockpitMainWindow` wires the signal to
  that entrypoint.

- [ ] **Step 1: Write literal failing tests**

Add tests that prove all of the following:

```python
def test_all_green_hides_summary(...):
    ...
    assert summary.isHidden()

def test_unknown_summary_is_chinese_evidence_count(...):
    ...
    assert not summary.isHidden()
    assert summary.text() == "1 项无证据"

def test_yellow_summary_is_chinese_attention_count(...):
    ...
    assert summary.text() == "2 项需注意"

def test_escalation_overflow_is_not_silently_dropped(...):
    # Build at least three simultaneous issues.
    ...
    assert "另 1 项" in bar.message_text()
    assert bar.details_button.isVisible()

def test_view_details_opens_worst_chip_single_popover(...):
    ...
    assert strip.active_chip() == state.top_issues(1)[0].source_chip
    assert strip.detail_popover.isVisible()
```

Also strengthen recovery/ack tests:

- green recovery hides the banner and the all-green summary;
- ack hides only the banner while red chip + red summary remain;
- red/unknown counts are Chinese and deterministic;
- a third/fourth issue is represented by `另 N 项`, never silently truncated.

Update or replace the currently incorrect
`test_strip_all_green` assertion that only checks `summary.text().strip()`.

- [ ] **Step 2: Confirm red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_health_strip.py \
  tests/acquisition_ui/test_escalation.py -q
```

Expected: the new literal summary, overflow, and detail-routing tests fail for
the current implementation.

- [ ] **Step 3: Implement the smallest coherent state renderer**

Required behavior:

- `apply_snapshot` stores/renders base levels and updates open detail rows.
- `apply_escalation` derives effective levels through
  `effective_chip_levels`; every chip renders the effective value.
- All green: summary label hidden and cleared.
- One or more `off`: summary visible as `N 项无证据`, but no banner.
- Yellow: summary visible as `N 项需注意`; banner shows at most two issue
  messages plus `另 N 项` when needed.
- Red: summary visible as `N 项严重`; entering/changing reason still pulses only
  three loops. Ack retains red chip + summary.
- Green recovery restores base chip levels, stops pulses, hides summary/banner
  when all base levels are green, and clears the ack latch.
- “查看” emits the worst issue's chip and opens that chip in the existing
  single popover; it must not create a second floating widget.

Do not add threshold literals. Keep issue ordering in `EscalationState` as the
single severity/priority authority. Here `N` means affected issues at the
current worst escalation tier; for `off`, `N` means chips without evidence.

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_health_strip.py \
  tests/acquisition_ui/test_escalation.py \
  tests/acquisition_ui/test_status_bar_text.py -q
```

- [ ] **Step 5: Commit**

```bash
git add \
  mf4_analyzer/acquisition_ui/widgets/health_strip.py \
  mf4_analyzer/acquisition_ui/widgets/escalation_bar.py \
  mf4_analyzer/acquisition_ui/main_window/window.py \
  tests/acquisition_ui/test_health_strip.py \
  tests/acquisition_ui/test_escalation.py
git commit -m "fix(acq): complete health escalation summary and detail path"
```

---

## Task 2: Make B5 idle/recording facts self-explanatory

**Files:**

- Modify: `mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py`
- Test: `tests/acquisition_ui/test_status_bar_text.py`

**Interface decisions:**

- The permanent `cockpitBackendBadge` remains the backend fact; do not duplicate
  its full text in the transient message.
- Connected-idle message becomes
  `已连接 · 已选 {N} · 实时显示 {P}`. Together with the permanent badge this
  satisfies `后端 · 已选 N · 实时显示 P` without wasting width twice.
- The first recording field is one indivisible priority field:
  `录制中 · {mm:ss}`.
- Disk-time field is `磁盘剩 {_humanize_duration_s(...)}`.
- The five priority fields remain: recording state+elapsed, disk time, samples,
  file size, write rate. Whole-field degradation order stays unchanged.

- [ ] **Step 1: Write failing tests**

Tests must assert exact semantic tokens:

```python
def test_connected_idle_status_bar_has_selection_and_monitor_counts(...):
    ...
    assert message == "已连接 · 已选 12 · 实时显示 5"

def test_recording_status_bar_names_state_and_disk_context(...):
    ...
    assert message.startswith("录制中 · 00:00 · 磁盘剩 ")
    assert "样本" in message and "样本/s" in message

def test_recording_facts_degrade_whole_fields_at_960(...):
    ...
    assert parts[0].startswith("录制中 · ")
    assert parts[1].startswith("磁盘剩 ")
    assert measured_width <= available_width
```

Derive `P` from effective pins intersected with current selection, not from the
temporarily focused card count. Keep the existing proof that
`rec.write_rate_bps` is samples/s and never byte throughput.

- [ ] **Step 2: Confirm red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_status_bar_text.py -q
```

- [ ] **Step 3: Implement**

Add a small private count helper if needed; do not make status rendering parse
the center summary string. Reuse `current_selection()` and
`_effective_pinned_names()` as structured sources.

Keep disconnected `未连接 · A2L: ...` because it is useful state context; the
permanent backend badge already satisfies the backend fact there.

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_status_bar_text.py \
  tests/acquisition_ui/test_pinned_monitoring.py \
  tests/acquisition_ui/test_state_machine.py -q
```

- [ ] **Step 5: Commit**

```bash
git add \
  mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py \
  tests/acquisition_ui/test_status_bar_text.py
git commit -m "fix(acq): make idle and recording fact streams explicit"
```

---

## Task 3: Close B1 popover on every mode-page switch

**Files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`
- Test: `tests/acquisition_ui/test_health_strip.py`

**Interface:** expose `HealthStrip.dismiss_popover() -> None` as an idempotent
public lifecycle method; it may delegate to the existing private cleanup but
must also remove the application event filter and clear the anchor.

- [ ] **Step 1: Write failing integration tests**

Use a real `CockpitMainWindow`, not a direct call to `eventFilter`:

```python
def test_mode_page_switch_dismisses_health_popover(qtbot):
    window = CockpitMainWindow()
    ...
    window.health_strip.chip("HW").clicked.emit("HW")
    assert window.health_strip.detail_popover.isVisible()
    window._mode_tabs.setCurrentIndex(1)  # Replay
    assert window.health_strip.active_chip() is None
    assert not window.health_strip.detail_popover.isVisible()
    assert not window.health_strip._filter_installed
```

Repeat Replay → History after reopening a chip detail so the rule is about any
page switch, not only the first transition.

- [ ] **Step 2: Confirm red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_health_strip.py -q -k "mode_page_switch"
```

- [ ] **Step 3: Implement**

`CockpitMainWindow._on_mode_tab_changed` first dismisses the strip popover, then
syncs the mode segment. Do not rely on a mouse outside-click: programmatic and
keyboard-driven tab changes must close it too.

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_health_strip.py \
  tests/acquisition_ui/test_replay_tab.py \
  tests/acquisition_ui/test_visual_shell.py -q
```

If the source checkout's unrelated `test_visual_shell.py` edits are not part of
the worktree base, do not copy them in; run the committed test file as-is.

- [ ] **Step 5: Commit**

```bash
git add \
  mf4_analyzer/acquisition_ui/widgets/health_strip.py \
  mf4_analyzer/acquisition_ui/main_window/window.py \
  tests/acquisition_ui/test_health_strip.py
git commit -m "fix(acq): dismiss health popovers on mode changes"
```

---

## Task 4: Add B2 preflight trust note without content leakage

**Files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/health_popover.py`
- Modify: `mf4_analyzer/acquisition_ui/widgets/health_strip.py`
- Test: `tests/acquisition_ui/test_health_strip.py`

**Interfaces:**

- Add `HealthPopover.set_note(text: str | None) -> None` and a test accessor such
  as `note_text() -> str`.
- Extend `HealthStrip.open_popover(..., note: str | None = None)`; every open
  call must set/clear the note explicitly.
- Define one UI constant:
  `PREFLIGHT_NOTE = "数字仅供参考·实际录制按真实样本累计"`.

- [ ] **Step 1: Write failing tests**

```python
def test_preflight_popover_shows_required_trust_note(...):
    ...
    assert pop.note_text() == PREFLIGHT_NOTE
    assert pop.note_label.isVisible()

def test_switching_preflight_to_chip_clears_note(...):
    ...
    assert pop.note_text() == ""
    assert not pop.note_label.isVisible()
```

Also assert that the note adds enough minimum height to avoid overlapping the
fifth row after a synchronous reused-popover resize.

- [ ] **Step 2: Confirm red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_health_strip.py -q -k "trust_note or clears_note"
```

- [ ] **Step 3: Implement**

Place the note below the grid in `HealthPopover`'s existing outer layout. Use a
small, low-contrast label (`#64748b` or the current muted token), no backing
rectangle, no focus, and no modal behavior. Include note height only when it is
visible. Keep the existing self-painted rounded/translucent background.

Do **not** edit `mf4_analyzer/ui_kit/style.qss` for this task because that file
has unrelated user changes in the source checkout; the popover already owns its
local floating-surface styling.

- [ ] **Step 4: Run green + rendered probe**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_health_strip.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert --shots /tmp/terra-preflight-note-offscreen
```

Inspect the rendered `03e-preflight-popover` image: five rows + note are fully
visible, text is not overlaid, and the rounded surface has no gray backing.

- [ ] **Step 5: Commit**

```bash
git add \
  mf4_analyzer/acquisition_ui/widgets/health_popover.py \
  mf4_analyzer/acquisition_ui/widgets/health_strip.py \
  tests/acquisition_ui/test_health_strip.py
git commit -m "fix(acq): add the preflight estimate trust note"
```

---

## Task 5: Reset live cards to an honest A3 no-data lifecycle

**Files:**

- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Test: `tests/acquisition_ui/test_live_cards.py`
- Regression: `tests/acquisition_ui/test_replay_tab.py`

**Interface decision:** `LiveSignalCard.reset_buffer()` starts a new display
data lifecycle. It clears samples, arrival cadence, current value, and stats.
`set_recording(True, ...)` must call this single reset path instead of keeping a
second partial reset implementation.

- [ ] **Step 1: Write failing tests**

```python
def test_reset_buffer_returns_card_to_no_data(qtbot):
    clock = [5.0]
    card = LiveSignalCard("MotSpd", raster="event_1ms", clock=lambda: clock[0])
    qtbot.addWidget(card)
    card.push_sample(1.0, 2.0)
    card.reset_buffer()
    card.refresh()
    assert card._spark.sample_count == 0
    assert card.sample_state() == "no-data"
    assert card._spark._sample_state == "no-data"
    assert card._value_label.text() == "—"
    assert card._stats_full_text == "μ — · σ — · max —"

def test_recording_reset_uses_same_no_data_lifecycle(...):
    ...
    card.set_recording(True, 0.0)
    assert card.sample_state() == "no-data"
    card.push_sample(0.001, 3.0)
    assert card.sample_state() == "live"
```

Keep the existing invariant that `set_recording(False)` does not clear a
populated buffer.

- [ ] **Step 2: Confirm red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py -q \
  -k "reset_buffer_returns or recording_reset_uses"
```

- [ ] **Step 3: Implement**

The single reset path must:

- reset spark raw/display buckets;
- set `_last_arrival = None`;
- immediately set the spark state to `("no-data", None)`;
- show current value `—`;
- restore `μ — · σ — · max —` and invalidate the 2 Hz stats gate;
- request a repaint without sleeping or reading wall time.

Do not conflate this with stale: stale means a visible prior trace stopped
arriving; reset means the new display lifecycle has no sample yet.

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py \
  tests/acquisition_ui/test_live_downsampler.py \
  tests/acquisition_ui/test_replay_tab.py -q
```

- [ ] **Step 5: Commit**

```bash
git add \
  mf4_analyzer/acquisition_ui/widgets/live_cards.py \
  tests/acquisition_ui/test_live_cards.py
git commit -m "fix(live-cards): reset the complete no-data display lifecycle"
```

---

## Task 6: Strengthen acceptance so green means the spec is green

**Files:**

- Modify: `scripts/cockpit_ui_tour.py`
- Modify only if needed for exact integration assertions:
  `tests/acquisition_ui/test_health_strip.py`,
  `tests/acquisition_ui/test_status_bar_text.py`,
  `tests/acquisition_ui/test_live_cards.py`

- [ ] **Step 1: Replace weak tour assertions**

The tour must no longer accept these weak forms:

- `bool(summary_text())` for B6;
- “contains some Chinese” for B5;
- `row_count() == 5` as the whole B2 contract.

Add literal checks for:

- all-green summary hidden; unknown summary `N 项无证据`;
- yellow summary `N 项需注意`;
- a three-issue injection shows `另 1 项` and “查看” opens the most severe
  chip's existing popover;
- preflight has five rows **and** the exact trust note;
- programmatic Capture → Replay page switch closes the popover, then the tour
  returns to Capture before recording;
- recording status contains `录制中`, `磁盘剩`, samples, size, and samples/s;
- reset/start-recording no-data state is honest before the first new sample;
- every escalation transition still leaves center geometry unchanged.

- [ ] **Step 2: Run the complete focused suite**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py \
  tests/acquisition_ui/test_live_downsampler.py \
  tests/acquisition_ui/test_health_strip.py \
  tests/acquisition_ui/test_escalation.py \
  tests/acquisition_ui/test_pinned_monitoring.py \
  tests/acquisition_ui/test_status_bar_text.py \
  tests/acquisition_ui/test_right_panel.py \
  tests/acquisition_ui/test_replay_tab.py \
  tests/acquisition_ui/test_state_machine.py -q

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui_kit/test_ticks_math.py tests/ui/ -q -k "tick or canvas or axis"
```

Expected: all pass. At plan time the comparison baselines were `173 passed`
and `828 passed, 1241 deselected`; record the new counts rather than forcing
these exact numbers.

- [ ] **Step 3: Offscreen structural tour**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert \
  --shots /tmp/terra-cockpit-remediation-offscreen
```

Expected: every strengthened invariant passes. This is not final visual proof.

- [ ] **Step 4: macOS onscreen acceptance**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert --onscreen \
  --shots /tmp/terra-cockpit-remediation-onscreen
```

Inspect at native DPR:

- green strip is quiet; off/yellow/red summaries are readable Chinese;
- preflight note is sharp, fully visible, and has no extra gray rectangle;
- yellow overflow/detail route and red ack/recovery are understandable;
- idle and recording body geometry is unchanged;
- status facts remain one line at 1280px and degrade by whole fields at 960px;
- Capture has two columns and Replay still owns its right panel.

- [ ] **Step 5: Performance regression gate**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/benchmark_live_cards.py
```

Required on the target Mac: normal p95 `<33ms`, degraded p95 `<100ms`. The
comparison review measured `23.32ms` and `24.43ms`; use the contract thresholds,
not those exact machine samples, as pass/fail.

- [ ] **Step 6: Hygiene + final commit**

```bash
git diff --check
```

```bash
git add scripts/cockpit_ui_tour.py
git commit -m "test(acq): make review-remediation UI contracts literal"
```

If Task 6 needed a small test-only adjustment, stage only those named test
files with the tour. Do not amend prior implementation commits.

Then run the committed-range checks with an explicit base (do not depend on a
shell variable surviving from Task 0):

```bash
BASE=13334f07
git diff --check "$BASE"..HEAD
git status --short --branch
git diff --name-only "$BASE"..HEAD
```

The changed-file list must cover all five findings and must not contain the
source checkout's unrelated dirty files or generated screenshots/output.

---

## Terra Handoff Contract

The worker stops after local commits and returns:

1. branch name and ordered commit SHAs mapped to Tasks 1–6;
2. exact focused pytest counts;
3. offscreen and onscreen tour result summaries and screenshot directories;
4. normal/degraded live-card p95 measurements;
5. `git diff --check` result and exact changed-file list;
6. any deviation from this plan, explicitly labeled rather than silently
   absorbed.

The worker must **not** push. The parent reviewer then compares
`13334f07..HEAD` against A3/B1/B2/B5/B6, checks the rendered screenshots, verifies
the source checkout's unrelated dirty files are untouched, and only then may
fast-forward/cherry-pick and `git push`.

## Final Coverage Checklist

- [ ] Finding 1: green/off/yellow/red summary semantics + overflow/detail path.
- [ ] Finding 2: idle selection/pin facts + explicit recording/disk facts.
- [ ] Finding 3: page switch closes popover and removes event filter.
- [ ] Finding 4: preflight trust note visible; chip popovers clear it.
- [ ] Finding 5: reset and recording start return to no-data until first sample.
- [ ] Capture remains two-column; Replay right panel still works.
- [ ] No threshold/core/painter scope creep.
- [ ] Focused, tick/canvas, offscreen, onscreen, performance, and diff hygiene
  gates all pass.

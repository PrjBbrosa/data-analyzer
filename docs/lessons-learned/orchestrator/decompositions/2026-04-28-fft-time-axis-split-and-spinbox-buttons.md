# Decomposition — FFTTimeContextual axis split + global spinbox button removal

Date: 2026-04-28
Source request: split FFTTimeContextual "坐标轴设置" group into two
QGroupBoxes (彩图 / 频谱), and globally remove QSpinBox / QDoubleSpinBox
up/down stepper buttons + slim padding-right; plus optional spinbox
max-width relaxation.

User has pre-specified a 3-wave structure with codex review gates
between waves (per `feedback_squad_wave_review.md` memory). Each wave
is a separate dispatch; main Claude must run codex review (using
`feedback_module_review.md` defaults) at wave boundaries before
advancing to the next wave.

## Subtasks

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W1 — split FFTTimeContextual axis group into 彩图 + 频谱 QGroupBoxes, preserve `chk_freq_auto` / `spin_freq_min` / `spin_freq_max` aliases, update tests + offscreen screenshot | pyqt-ui-engineer | (none) | UI-surface change to inspector layout; QFormLayout + QGroupBox splitting is `pyqt-ui` territory. No computation change. |
| W1-review — codex review of W1 patch | (codex via `feedback_module_review.md`) | W1 | Wave gate per `feedback_squad_wave_review.md` |
| W2a — globally remove QSpinBox/QDoubleSpinBox stepper buttons in `style.qss` (zero out `::up-button` / `::down-button` / `::up-arrow` / `::down-arrow`), restore `padding-right` to match `padding-left`, and add `setButtonSymbols(QAbstractSpinBox.NoButtons)` belt-and-braces in widget construction sites (Inspector, axis-edit dialogs, anywhere QSpinBox/QDoubleSpinBox is created) | pyqt-ui-engineer | W1-review | QSS + widget-side double protection. UI/styling. Must keep `QComboBox::drop-down` arrow rules intact. |
| W2b — clean up dead `ICON_SPIN_UP_*` / `ICON_SPIN_DOWN_*` keys in `mf4_analyzer/ui/icons.py` and any references in `render_qss_template`, only after W2a confirms no QSS template still substitutes those placeholders | refactor-architect | W2a | Pure dead-code cleanup once QSS no longer references them. Module/import surface change is `refactor` territory. Conditional on W2a's actual deletions. |
| W2-review — codex review of W2a + W2b combined | (codex via `feedback_module_review.md`) | W2a, W2b | Wave gate. |
| W3 (optional) — relax `_build_axis_row` spinbox max-width from 72 px to 110 px so axis-group spinboxes can show "20000.00 Hz" without truncation; verify column-width unification still works under both single-group (OrderContextual) and dual-group (FFTTimeContextual) cases | pyqt-ui-engineer | W2-review | Layout-tuning follow-up; only kicks in if user confirms after W2. UI sizing is `pyqt-ui`. |
| W3-review — codex review of W3 patch (only if W3 ran) | (codex via `feedback_module_review.md`) | W3 | Wave gate. |

## Lessons consulted

- `docs/lessons-learned/README.md` (reflection protocol)
- `docs/lessons-learned/LESSONS.md` (master index)
- `docs/lessons-learned/.state.yml` (top_level_completions=34, last_prune_at=21 — no prune)
- `docs/lessons-learned/pyqt-ui/2026-04-28-qss-subcontrol-needs-explicit-arrow-glyph.md` — context for the spinbox/combo subcontrol QSS that we're partially undoing; note that the same lesson explains why spinbox arrows currently render via `image:url(...)`. Removing spinbox stepper buttons means we can drop the corresponding subcontrol rules (and PNG cache placeholders) entirely; combo `::drop-down` + `::down-arrow` rules MUST stay.
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` — when splitting the axis group, the freq (X) row's auto/min/max paired-field children visibility logic must seed at __init__ end on each new group; alias attributes (`chk_freq_auto`, `spin_freq_min`, `spin_freq_max`) inherit visibility from the X row's wrapper, so verify per-widget `isHidden()` honesty if the freq-auto checkbox's enable-children logic survives.
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md` — global QSS `padding` rules win over per-instance margin tweaks; when removing the 24 px right padding gutter for spinboxes, do it at the QSS level (long-form `padding-right: 8px` matching `padding-left`), not via inline Python overrides.
- `docs/lessons-learned/pyqt-ui/2026-04-26-action-button-on-group-title-needs-qframe-header.md` — heads-up: if either of the two new QGroupBoxes ever needs a title-right action button later, switch to QFrame header pattern (not relevant for W1 itself, just keep in mind).
- Plan: `docs/superpowers/plans/2026-04-28-axis-settings-and-cot-migration.md` (Wave 4 narrative + the `_make_axis_settings_group` helper signature).

## Notes for main Claude

- The escape hatch (`skip squad:` / `直接改：`) is NOT used; the user
  explicitly requested squad routing (via 3-wave structure + codex
  review gates).
- `_make_axis_settings_group` (currently at `inspector_sections.py`
  line 629) is the SINGLE-group helper. W1 must either (a) introduce a
  new helper variant (e.g. `_make_axis_settings_groups_split` returning
  two QGroupBoxes) used only by FFTTimeContextual while OrderContextual
  keeps using the single-group form, or (b) parameterize the existing
  helper with a `split: bool` argument. (a) is preferred to avoid
  forcing OrderContextual through a code path it does not need. Brief
  must call this out so pyqt-ui-engineer doesn't accidentally regress
  OrderContextual.
- W1's brief must emphasize that `_enforce_label_widths(self,
  unify_columns=True)` was added per the 2026-04-27 padding lesson so
  sig_card form + axis-group form share label columns; with two axis
  groups, `unify_columns=True` will now span FOUR forms (sig_card +
  谱参数 + 彩图 + 频谱). Verify that label columns still align
  consistently and that the 频谱 group's "频率(X)" / "幅值(Y)" labels
  don't push the unified column wider than today's "时间(X)" /
  "阶次(Y)" max — if they do, expect a slight horizontal shift in
  unrelated forms and screenshot it.
- W1's offscreen screenshot must be at the default main-window size,
  with FFTTimeContextual mode active, scrolled to the axis groups, and
  saved to a temp path the brief specifies (e.g. under
  `.pytest-tmp/inspector-fft-time-after-split.png`); pyqt-ui-engineer
  should report the rendered total height of the inspector content
  column and confirm whether a scrollbar appears at default window
  size.
- W2a explicitly preserves `QComboBox::drop-down` and its arrow rules
  — ONLY spinbox subcontrols are stripped. Brief must enumerate which
  QSS selectors to keep vs. remove to avoid an unintended combo
  regression (rework risk against the 2026-04-28 arrow-glyph lesson).
- W2b is conditional: if W2a confirms it removed every
  `{{ICON_SPIN_UP_*}}` / `{{ICON_SPIN_DOWN_*}}` placeholder from
  `style.qss`, then `icons.py` keys + render_qss_template substitution
  rows for those 8 placeholders are dead and refactor-architect can
  delete them. W2b brief must include "grep the entire repo for any
  remaining `ICON_SPIN_UP_` / `ICON_SPIN_DOWN_` reference (qss, py,
  test fixtures) before deleting" to avoid breaking startup.
- Rework-detection caveat: W2a (pyqt-ui) and W2b (refactor) both touch
  `mf4_analyzer/ui/icons.py` only if W2a needs to remove the QSS
  template placeholders that `icons.py` substitutes. To minimize
  cross-specialist file overlap, instruct W2a to leave the icons.py
  list alone (just blank out QSS rules) and let W2b own the icons.py
  delete; this keeps `files_changed` disjoint (W2a: style.qss +
  inspector_sections.py if any setButtonSymbols sites; W2b: icons.py).
- Skill: `superpowers:writing-plans` is already satisfied by the
  user's existing plan-doc reference (3 waves explicitly listed) +
  this audit; main Claude does not need to invoke a separate plans
  skill before dispatch.

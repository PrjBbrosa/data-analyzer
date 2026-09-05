# QMessageBox migration ledger (T0)

Date: 2026-09-05. Status: **T0 inventory complete; T3 demo code ready for `unsaved_project`; G3/G4 UNVERIFIED. Do not start T5.** Remaining message-box rows stay `pending`.

This ledger is the C11 source of truth for current production call sites. Historical audit count 77 is a baseline, not a quota. Identifiers are `module + owner symbol + prompt_id`. Line numbers are navigation only.

## 0. Snapshot

| Field | Value |
|---|---|
| HEAD | `e5ec1fa9a52f6316fe14f0c1af24dc2e9d1e7c0e` |
| Historical audit HEAD | `a60da923b864f53cade16d97de2dd17e49cf7a33` |
| Dirty worktree (unrelated to this inventory) | `AGENTS.md` modified; deleted assets under `assets/` and `docs/reports/`; untracked Spec/Plan/audit docs, `code_stats_report.html`, `ssh-keygen` |
| `mf4_analyzer/**` QMessageBox sources | clean vs HEAD (no product edits in this T0) |
| Scan | `mf4_analyzer/**/*.py` `QMessageBox` / `QMessageBox(` / static helpers / `_QMessageBox(` |
| Production call-site count | **77** (27 instance constructors + 50 static helpers) |
| vs historical 77 | same count; `_fft_mixin.py` owners/lines moved (`do_fft` L645, `_do_fft_single` L817; audit had 428/583 and swapped labels) |

## 1. Counts by plan appendix A

M0 is the unsaved-project subset of M1, not an extra 78th site.

| Batch | Module (relative to `mf4_analyzer/`) | Count | Wave |
|---|---|---|---|
| M0 ⊂ M1 | `ui/main_window/_project_io_mixin.py` unsaved project | 1 | **T3** |
| M1 | `ui/main_window/_project_io_mixin.py` | 15 | T3 (1) + T5 (14) |
| M1 | `ui/main_window/_channel_scope_mixin.py` | 3 | T5 |
| M1 | `ui/main_window/_view_mixin.py` | 3 | T5 |
| M1 | `ui/main_window/window.py` | 9 | T5 |
| M1 | `ui/main_window/wwt_import_coordinator.py` | 1 | T5 |
| M2 | `ui/dialogs/channel_editor.py` | 18 | T5 |
| M2 | `ui/dialogs/chart_options.py` | 1 | T5 |
| M2 | `ui/drawers/batch/sheet.py` | 6 | T5 |
| M2 | `ui/widgets/channel_tree.py` | 3 | T5 |
| M2 | `ui/inspector_sections/presets.py` | 1 | T5 |
| M3 | `ui/chart_stack/cards.py` | 1 | T5 |
| M3 | `ui/chart_stack/toolbar.py` | 1 | T5 |
| M3 | `ui/chart_stack/ultraview/board_switcher.py` | 1 | T5 |
| M3 | `ui/chart_stack/ultraview/board_toolbar.py` | 1 | T5 |
| M3 | `ui/chart_stack/ultraview/page.py` | 2 | T5 |
| M3 | `ui/view_tabbar.py` | 1 | T5 |
| M4 | `ui/main_window/_analysis_mixin.py` | 1 | T5 |
| M4 | `ui/main_window/_fft_mixin.py` | 2 | T5 |
| M4 | `ui/main_window/_order_mixin.py` | 1 | T5 |
| M5 | `acquisition_ui/main_window/_connection_mixin.py` | 1 | **T6** |
| M5 | `acquisition_ui/main_window/_settings_mixin.py` | 2 | T6 |
| M5 | `acquisition_ui/review_modal.py` | 2 | T6 |
| M5 | `acquisition_ui/settings_dialog.py` | 1 | T6 |
| **Total** | | **77** | |

S14 (not message-box migration): **5** `QInputDialog` sites, **20** `QFileDialog` sites. See §6.

## 2. Scan exclusions (not call sites)

These mention `QMessageBox` but are not production prompts:

- Imports / re-exports / type annotations: `ui/main_window/__init__.py`, `ui/dialogs/__init__.py`, `ui/widgets/__init__.py`, `ui/chart_stack/__init__.py` (QFileDialog only), `acquisition_ui/main_window/__init__.py`, `acquisition_ui/main_window/window.py` (`_connection_warning_box: QMessageBox \| None`)
- Helper, not a prompt: `ui_kit/message_box_buttons.py` (`fit_message_box_buttons_to_text`, role tagging)
- Stylesheet hook: `ui_kit/stylesheet.py` `install_message_box_button_roles`
- Comments: `ui/main_window/project_dirty.py`, `_order_mixin.py` L844, `_view_mixin.py` L947, `batch/sheet.py` L2170
- `_ask_open_blf_dbc_dialog` default arg `icon=QMessageBox.Information` is a signature default, not a second call site

## 3. Shared seams (keep or migrate all consumers together)

| Seam | Where | Who uses it |
|---|---|---|
| Class static methods | `QMessageBox.warning/question/information/critical` | All 50 static helpers. Patching the Qt class via any alias (`PyQt5.QtWidgets.QMessageBox`, `mf4_analyzer.ui.dialogs.QMessageBox`, `mf4_analyzer.ui.widgets.QMessageBox`, mixin module `QMessageBox`) replaces the class method globally. |
| `QMessageBox.exec_` | class method | All 27 instance boxes that call `exec_()`. Tests often stub `exec_` and inspect the live box. |
| Package + runtime lookup | `mf4_analyzer.acquisition_ui.main_window.QMessageBox` then `sys.modules.get(...).QMessageBox` | M5 constructors in `_connection_mixin` / `_settings_mixin`. Tests patch `.open` here. |
| Package re-export (no runtime lookup for boxes) | `mf4_analyzer.ui.main_window.QMessageBox` | Documented “static-warning anchor”. Analyzer mixins bind `QMessageBox` at import; class-method patches still hit them. `QFileDialog` *does* use runtime lookup. |
| Package re-export | `mf4_analyzer.ui.dialogs.QMessageBox` | `tests/ui/test_dialogs.py`, `test_dialog_with_handle.py` |
| Package re-export | `mf4_analyzer.ui.widgets.QMessageBox` | `tests/ui/test_file_navigator.py` (`question`); production `channel_tree.py` imports PyQt5 directly — class-method patch still applies. |
| Chart-stack package | `mf4_analyzer.ui.chart_stack.QFileDialog` runtime lookup | toolbar save-as, not a message box. Toolbar warning uses local `QMessageBox`. |
| Method stubs | `window._prompt_unsaved_project`, `_confirm_*`, `_ask_*` | Preferred owner seam. `tests/ui/conftest.py` autouse stubs `ProjectIOMixin._prompt_unsaved_project` → `"discard"` so shown MainWindow teardown never blocks. |
| Button-fit helper | `fit_message_box_buttons_to_text` | Custom instance boxes (not static helpers). `tests/ui/test_message_box_buttons.py`, `tests/acquisition_ui/test_message_box_button_fit.py`. |
| Result mapping | custom `clickedButton() is btn` vs `QMessageBox.Yes/No/Cancel/Ok` | Must not collapse to `QDialog.Accepted`. |

New `AppMessageDialog` Action/Help/Apply default is **non-closing**. Current QMessageBox **closes on ActionRole**. BLF multi-action boxes must set `closes=true` on ActionRole during T5.

## 4. Default / Escape / Close rules used below

- **Explicit** means `setDefaultButton` / `setEscapeButton` / static `defaultButton=` argument.
- **Sole-button Qt** means one Ok (or one custom) button; Qt `detectEscapeButton` uses that button. Callers usually ignore the return.
- **Not explicit — do not guess** means no `setEscapeButton` (all sites except `unsaved_project`) and/or no `setDefaultButton`. Spec C03: do not infer the first AcceptRole, and do not invent a safe cancel if Reject currently means a real action.
- Title-bar close / Alt+F4 follow the escape button when Qt has one; if Qt has none, close may emit neither action. Unproven without a key/close probe.

**Only production `setEscapeButton`:** `ProjectIOMixin._unsaved_project_prompt_buttons` → Cancel.

## 5. Call-site ledger

Column order for every site: module | owner | prompt_id | mode | buttons/roles | default | escape/close | return mapping | checkbox/details | test seam | test anchors | wave | status | notes.

### 5.1 T3 — unsaved project demo (M0)

#### `unsaved_project`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L177) |
| owner | `ProjectIOMixin._unsaved_project_prompt_buttons` (shown by `_prompt_unsaved_project` L189) |
| prompt_id | `unsaved_project` |
| mode | **sync** `exec_()` (builder does not exec; prompt method does) |
| buttons/roles | 保存 `AcceptRole`; 不保存 `DestructiveRole`; 取消 `RejectRole` |
| default | **explicit** 保存 |
| escape/close | **explicit** 取消 (`setEscapeButton`). Title-bar close / Escape / Alt+F4 must stay `cancel`. |
| return mapping | custom `'save' \| 'discard' \| 'cancel'` via `clickedButton()`. Guard maps save-fail / Save-As cancel → `DirtyGuardResult.CANCELLED`, not proceed. |
| checkbox/details | none |
| test seam | builder + `_prompt_unsaved_project` + `confirm_leave_unsaved_project`. Autouse `tests/ui/conftest.py::_auto_discard_unsaved_project_on_close` stubs prompt to `"discard"`. |
| test anchors | `tests/ui/test_project_dirty_guard.py::test_unsaved_prompt_defaults_to_save_not_discard`; `test_failed_or_cancelled_save_keeps_dirty_and_current_project`; `test_open_replacement_uses_same_save_discard_cancel_guard`; `test_close_cancel_happens_before_workers_or_tool_windows_stop`; `test_reentrant_close_shows_one_prompt_and_tears_down_once`; `test_real_main_window_close_cancel_stops_before_teardown`; `test_real_main_window_close_discard_uses_production_teardown`; `test_real_main_window_reentrant_close_prompts_once`; `tests/ui/test_open_and_save_entry.py::test_open_replace_confirm_cancel_aborts` |
| wave | **T3** |
| status | pending — **demo code ready; G3/G4 UNVERIFIED**. Display path now uses `AppMessageDialog` / `build_unsaved_project_dialog`; dirty/save functions unchanged. Do not start T5 until Cocoa + Windows 100% native demo pass. |
| notes | Spec §3.3 demo. Do not change dirty/save functions. Cocoa/Windows native G3/G4 required before T5 bulk migration. |

---

### 5.2 T5 M1 — project IO (remaining 14)

#### `open_multiple_projects_rejected`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L251) |
| owner | `ProjectIOMixin._open_paths` |
| prompt_id | `open_multiple_projects_rejected` |
| mode | sync static `QMessageBox.warning` |
| buttons/roles | Ok |
| default | Ok (static) |
| escape/close | Ok (sole button) |
| return mapping | Ok ignored; method `return`s |
| checkbox/details | none |
| test seam | class `QMessageBox.warning` |
| test anchors | `tests/ui/test_open_and_save_entry.py::test_open_multiple_projects_rejected` |
| wave | T5 M1 |
| status | pending |
| notes | Notification only. |

#### `heavy_load_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L316) |
| owner | `ProjectIOMixin._confirm_heavy_load` |
| prompt_id | `heavy_load_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 继续加载 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 继续加载 (not a safety-first default) |
| escape/close | **not explicit**. Sole RejectRole is 取消; close currently returns False because `clickedButton() is cont` fails. Do not change default to Cancel without a product decision. |
| return mapping | `bool`: True iff 继续加载 |
| checkbox/details | `setInformativeText` duration estimate |
| test seam | method `_confirm_heavy_load` / `_should_confirm_heavy_load` |
| test anchors | `tests/ui/test_load_progress_and_heavy_confirm.py::test_should_confirm_heavy_load_thresholds`; `test_open_data_paths_cancels_when_heavy_load_declined` (method stub, no live keys) |
| wave | T5 M1 |
| status | pending |
| notes | Escape unproven by keyboard test. Default is Continue. |

#### `degraded_project_save_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L534) |
| owner | `ProjectIOMixin._confirm_degraded_project_save` |
| prompt_id | `degraded_project_save_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 仍要保存 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit**; close currently False (`clickedButton() is save_btn`) |
| return mapping | `bool` True iff 仍要保存. Comment: tests monkeypatch this seam. |
| checkbox/details | `setInformativeText` missing/dropped counts |
| test seam | method `_confirm_degraded_project_save` |
| test anchors | `tests/ui/test_project_session.py::test_degraded_project_save_clears_health_after_confirm` |
| wave | T5 M1 |
| status | pending |
| notes | Safety default Cancel is explicit. Escape still unproven. |

#### `load_mf4_missing_asammdf`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L819) |
| owner | `ProjectIOMixin._load_one_impl` |
| prompt_id | `load_mf4_missing_asammdf` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; `return` |
| checkbox/details | none |
| test seam | `_project_io_mixin.QMessageBox.critical` |
| test anchors | none found that force `HAS_ASAMMDF` false |
| wave | T5 M1 |
| status | pending |
| notes | Same owner as the two generic load errors; keep prompt_id distinct. |

#### `load_one_import_error`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1052) |
| owner | `ProjectIOMixin._load_one_impl` |
| prompt_id | `load_one_import_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | text from `_format_load_import_error` (python-can naming) |
| test seam | `_project_io_mixin.QMessageBox.critical` |
| test anchors | `tests/ui/test_file_scope_follow.py::test_format_load_import_error_names_python_can`; `test_asc_sniff_importerror_shows_python_can_dialog` |
| wave | T5 M1 |
| status | pending |
| notes | User-visible error; do not dump traceback. |

#### `load_one_generic_error`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1054) |
| owner | `ProjectIOMixin._load_one_impl` |
| prompt_id | `load_one_generic_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | `str(e)` as text |
| test seam | `_project_io_mixin.QMessageBox.critical` |
| test anchors | `tests/ui/test_wwt_import_flow.py::test_open_batch_middle_failure_keeps_remembered_choice` |
| wave | T5 M1 |
| status | pending |
| notes | Same except-block as import error; two call sites. |

#### `blf_batch_read_error`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1583) |
| owner | `ProjectIOMixin._load_blf_batch` |
| prompt_id | `blf_batch_read_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; file skipped |
| checkbox/details | `{path.name}\n{exc}` |
| test seam | class `critical` |
| test anchors | no dedicated node id found |
| wave | T5 M1 |
| status | pending |
| notes | Notification; batch continues. |

#### `blf_batch_dbc_action`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1661) |
| owner | `ProjectIOMixin._ask_blf_batch_dbc_action` |
| prompt_id | `blf_batch_dbc_action` |
| mode | sync `exec_()` |
| buttons/roles | 统一选择 DBC `AcceptRole`; 逐个选择 `ActionRole`; 取消 `RejectRole` |
| default | **explicit** 统一选择 DBC |
| escape/close | **not explicit**. Close/unknown click → `"cancel"`. ActionRole **closes** current QMessageBox. |
| return mapping | `"batch" \| "individual" \| "cancel"` |
| checkbox/details | `setInformativeText` |
| test seam | method + `QMessageBox.exec_` |
| test anchors | `tests/ui/test_blf_batch_import.py::test_batch_dbc_is_confirmed_once_and_each_blf_is_read_once`; `test_batch_dbc_dialog_actions_fit_without_text_elision`; `test_batch_dbc_mismatch_can_skip_without_decoding_wrong_file` |
| wave | T5 M1 |
| status | pending |
| notes | Multi Accept/Action. New component must close on ActionRole. Escape unproven. |

#### `blf_batch_mismatch_action`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1684) |
| owner | `ProjectIOMixin._ask_blf_batch_mismatch_action` |
| prompt_id | `blf_batch_mismatch_action` |
| mode | sync `exec_()` |
| buttons/roles | 重选… `AcceptRole`; 跳过此文件 `ActionRole`; 停止剩余导入 `RejectRole` |
| default | **explicit** 重选 |
| escape/close | **not explicit**; unknown → `"cancel"` (stop remaining) |
| return mapping | `"choose" \| "skip" \| "cancel"` |
| checkbox/details | informative + optional `detail` |
| test seam | method + `exec_` |
| test anchors | `tests/ui/test_blf_batch_import.py::test_batch_dbc_mismatch_actions_fit_without_text_elision`; `test_last_batch_mismatch_mentions_only_current_file`; `test_batch_dbc_mismatch_can_skip_without_decoding_wrong_file` |
| wave | T5 M1 |
| status | pending |
| notes | RejectRole is “stop remaining”, a real batch action. Do not remap Escape to a no-op without a probe. |

#### `blf_open_choose_dbc`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1748) |
| owner | `ProjectIOMixin._ask_open_blf_dbc_dialog` |
| prompt_id | `blf_open_choose_dbc` |
| mode | sync `exec_()` |
| buttons/roles | 选择 DBC `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 选择 DBC |
| escape/close | **not explicit**; False if not 选择 DBC |
| return mapping | `bool` |
| checkbox/details | none; icon argument Information (default) or caller-supplied |
| test seam | method `_ask_open_blf_dbc_dialog` |
| test anchors | `tests/ui/test_blf_open.py::test_load_one_cancelled_dbc_selection_leaves_blf_unopened`; `test_dbc_picker_title_says_cancel_does_not_open_file`; `tests/ui/test_asc_can_open.py` (several method stubs); `tests/ui/test_project_session.py` BLF restore stubs |
| wave | T5 M1 |
| status | pending |
| notes | Helper used by BLF/ASC open. Cancel means do not open the file. |

#### `blf_dbc_candidate_action`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1763) |
| owner | `ProjectIOMixin._ask_blf_dbc_candidate_action` |
| prompt_id | `blf_dbc_candidate_action` |
| mode | sync `exec_()` |
| buttons/roles | 使用/仍然使用/校验并使用 `AcceptRole`; 选择其他 DBC `ActionRole`; 取消 `RejectRole` |
| default | **explicit** use |
| escape/close | **not explicit**; unknown → `"cancel"` |
| return mapping | `"use" \| "choose" \| "cancel"` |
| checkbox/details | informative candidate summary; icon Warning if weak/unverified else Information |
| test seam | method `_ask_blf_dbc_candidate_action` |
| test anchors | `tests/ui/test_blf_open.py::test_load_one_reuses_matching_session_dbc_after_confirmation`; `test_load_one_reuses_persisted_recent_dbc_after_restart` |
| wave | T5 M1 |
| status | pending |
| notes | Labels depend on candidate status. ActionRole must close. |

#### `blf_dbc_mismatch_retry`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L1828) |
| owner | `ProjectIOMixin._ask_blf_dbc_mismatch_action` |
| prompt_id | `blf_dbc_mismatch_retry` |
| mode | sync `exec_()` |
| buttons/roles | 重新选择 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 重新选择 |
| escape/close | **not explicit**; not retry → `"cancel"` |
| return mapping | `"retry" \| "cancel"` |
| checkbox/details | optional informative `detail` |
| test seam | method |
| test anchors | no live exec node id found (covered via `_choose_blf_dbc_with_retry` stubs) |
| wave | T5 M1 |
| status | pending |
| notes | Distinct from batch mismatch. |

#### `project_restore_degraded`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L2443) |
| owner | `ProjectIOMixin._open_project_restoring` |
| prompt_id | `project_restore_degraded` |
| mode | sync static `warning` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | missing paths + dropped analysis/time counts in text |
| test seam | class `QMessageBox.warning` |
| test anchors | `tests/ui/test_project_session.py::test_open_project_skips_missing`; `test_degraded_project_save_clears_health_after_confirm`; `test_project_restore_unremapable_record_has_no_ghost_row`; `tests/ui/test_ultraview_project_session.py::test_open_project_keeps_page_hooks_and_toasts_ultraview_warnings` |
| wave | T5 M1 |
| status | pending |
| notes | Health-holder branch. Local `from PyQt5.QtWidgets import QMessageBox` inside method. |

#### `project_restore_missing_files`

| Field | Value |
|---|---|
| module | `ui/main_window/_project_io_mixin.py` (nav L2449) |
| owner | `ProjectIOMixin._open_project_restoring` |
| prompt_id | `project_restore_missing_files` |
| mode | sync static `warning` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | missing path list in text |
| test seam | class `QMessageBox.warning` |
| test anchors | same files as `project_restore_degraded` (elif missing without health) |
| wave | T5 M1 |
| status | pending |
| notes | Defensive branch; keep separate from degraded. |

---

### 5.3 T5 M1 — channel scope (3)

#### `analysis_view_detach_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_channel_scope_mixin.py` (nav L240) |
| owner | `ChannelScopeMixin._confirm_analysis_detach` |
| prompt_id | `analysis_view_detach_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 从当前 View 移除 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit**; False if not remove |
| return mapping | `bool` |
| checkbox/details | none |
| test seam | method `_confirm_analysis_detach` |
| test anchors | `tests/ui/test_analysis_source_scope.py` (method stubs, e.g. around detach tests); `tests/ui/test_analysis_scope_and_xframe.py`; `tests/ui/test_message_box_buttons.py::test_long_chinese_accept_button_fits_view_remove_label` (geometry, not keys) |
| wave | T5 M1 |
| status | pending |
| notes | Nested `from PyQt5.QtWidgets import QMessageBox`. No live Escape test. |

#### `channel_config_overwrite_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_channel_scope_mixin.py` (nav L396) |
| owner | `ChannelScopeMixin._confirm_channel_config_overwrite` |
| prompt_id | `channel_config_overwrite_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 覆盖配置 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit**; False if not overwrite |
| return mapping | `bool` |
| checkbox/details | informative old→new counts |
| test seam | method |
| test anchors | `tests/ui/test_view_channel_scope.py::test_save_existing_name_requires_confirmation_before_overwrite` |
| wave | T5 M1 |
| status | pending |
| notes | Destructive overwrite; Cancel default explicit. |

#### `time_view_detach_files_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_channel_scope_mixin.py` (nav L515) |
| owner | `ChannelScopeMixin._confirm_detach_files` |
| prompt_id | `time_view_detach_files_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 从当前 View 移除 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit** |
| return mapping | `bool` |
| checkbox/details | none |
| test seam | method `_confirm_detach_files` |
| test anchors | `tests/ui/test_view_channel_scope.py::test_detach_cancel_preserves_attachment_and_checked_state`; `test_confirmed_detach_filters_view_state_and_replots_once`; `tests/ui/test_analysis_source_scope.py` |
| wave | T5 M1 |
| status | pending |
| notes | Same button labels as analysis detach; different owner/text. |

---

### 5.4 T5 M1 — view mixin (3)

#### `view_delete_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_view_mixin.py` (nav L958) |
| owner | `ViewMixin._confirm_view_delete` |
| prompt_id | `view_delete_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 删除 `DestructiveRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit**; False if not 删除 |
| return mapping | `bool` |
| checkbox/details | informative irreversible copy |
| test seam | method + `QMessageBox.exec_` |
| test anchors | `tests/ui/test_view_switch_integration.py::test_delete_view_confirm_copy_defaults_to_cancel`; `test_delete_view_cancel_keeps_view`; `test_overflow_view_delete_skips_confirm_and_tab_delete_still_prompts` |
| wave | T5 M1 |
| status | pending |
| notes | Overflow × skips this prompt by design. |

#### `view_close_others_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_view_mixin.py` (nav L971) |
| owner | `ViewMixin._confirm_close_other_views` |
| prompt_id | `view_close_others_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 关闭其他 `DestructiveRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit** |
| return mapping | `bool` |
| checkbox/details | informative |
| test seam | method + `exec_` |
| test anchors | `tests/ui/test_view_switch_integration.py::test_close_others_keeps_current_view_id_after_one_confirm`; `test_close_others_cancel_is_zero_mutation`; `test_bulk_close_dialog_copy_matches_spec`; `tests/ui/test_analysis_view_cache_residency.py` |
| wave | T5 M1 |
| status | pending |
| notes | Default Cancel asserted via exec_ spy. Escape unproven. |

#### `view_close_all_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_view_mixin.py` (nav L986) |
| owner | `ViewMixin._confirm_close_all_views` |
| prompt_id | `view_close_all_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 关闭全部 `DestructiveRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit** |
| return mapping | `bool` |
| checkbox/details | informative |
| test seam | method + `exec_` |
| test anchors | `tests/ui/test_view_switch_integration.py::test_close_all_resets_to_a_blank_view`; `test_bulk_close_dialog_copy_matches_spec` |
| wave | T5 M1 |
| status | pending |
| notes | Leaves one blank View. |

---

### 5.5 T5 M1 — MainWindow (9)

#### `cockpit_lite_unavailable`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L3298) |
| owner | `MainWindow.open_acquisition_cockpit` |
| prompt_id | `cockpit_lite_unavailable` |
| mode | sync static `information` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; `return` |
| checkbox/details | none |
| test seam | class `information` |
| test anchors | `tests/ui/test_analyzer_opens_cockpit.py` covers import/open when acquisition_ui exists; **no Lite ModuleNotFoundError dialog node id found** |
| wave | T5 M1 |
| status | pending |
| notes | Analyzer-only / Lite fallback. Low-UI but still an application prompt — not a start-up exception exemption unless separately evidenced. |

#### `global_file_close_all_empty`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L3457) |
| owner | `MainWindow._confirm_global_file_close` (no-uses + `close_all`) |
| prompt_id | `global_file_close_all_empty` |
| mode | sync `exec_()` |
| buttons/roles | 关闭并从所有 View 移除 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit**; False if not close |
| return mapping | `bool` |
| checkbox/details | none |
| test seam | method `_confirm_global_file_close` (both boxes) |
| test anchors | `tests/ui/test_analysis_source_scope.py::test_global_close_with_dependencies_defaults_to_cancel`; `tests/ui/test_view_channel_scope.py::test_global_file_close_cleans_every_time_view` (`force=True` skips dialog); `tests/ui/test_message_box_buttons.py::test_close_and_remove_from_all_views_label_fits_after_helper` |
| wave | T5 M1 |
| status | pending |
| notes | Same owner as in-use box; two constructors. |

#### `global_file_close_in_use`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L3495) |
| owner | `MainWindow._confirm_global_file_close` (uses present) |
| prompt_id | `global_file_close_in_use` |
| mode | sync `exec_()` |
| buttons/roles | 关闭并从所有 View 移除 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit** |
| return mapping | `bool` |
| checkbox/details | informative summary + up to 12 use lines + “另有 N 处” |
| test seam | method |
| test anchors | same as empty close-all; analysis dependency tests stub the method |
| wave | T5 M1 |
| status | pending |
| notes | Long informative text; C08 keep full refs accessible. |

#### `global_channel_delete_in_use`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L3526) |
| owner | `MainWindow._confirm_global_channel_delete` |
| prompt_id | `global_channel_delete_in_use` |
| mode | sync `exec_()` |
| buttons/roles | 关闭并从所有 View 移除 `AcceptRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit** |
| return mapping | `bool` |
| checkbox/details | none |
| test seam | method |
| test anchors | `tests/ui/test_view_channel_scope.py::test_channel_editor_removal_cleans_deleted_channel_from_every_view` (stubs True) |
| wave | T5 M1 |
| status | pending |
| notes | Label reused from file-close; identity is channel delete. |

#### `overlay_mode_risk_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L3786) |
| owner | `MainWindow._confirm_overlay_risk` |
| prompt_id | `overlay_mode_risk_confirm` |
| mode | sync static `question` |
| buttons/roles | Yes \| No |
| default | **explicit** No |
| escape/close | **not explicit**. Qt typically maps No when Cancel absent — **unverified**. |
| return mapping | `bool` `result == QMessageBox.Yes` |
| checkbox/details | extra sentence if filter enabled |
| test seam | `window_mod.QMessageBox.question` |
| test anchors | `tests/ui/test_main_window_overlay_risk.py::test_danger_cancel_prompts_and_skips_expensive_plot`; `test_danger_confirm_allows_plotting`; `test_danger_cancel_reverts_overlay_segment_to_previous_mode`; `tests/ui/test_view_channel_scope.py` apply-risk cancel |
| wave | T5 M1 |
| status | pending |
| notes | Do not treat `QDialog.Rejected` as No. Escape pending. |

#### `export_excel_error`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L4756) |
| owner | `MainWindow._do_export_excel` |
| prompt_id | `export_excel_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | `str(e)` |
| test seam | local import `QMessageBox.critical` |
| test anchors | `tests/ui/test_channel_editor_export.py` happy-path export; no dedicated failure dialog node |
| wave | T5 M1 |
| status | pending |
| notes | Local import inside method. |

#### `export_wwt_range_too_short`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L4794) |
| owner | `MainWindow._do_export_wwt` |
| prompt_id | `export_wwt_range_too_short` |
| mode | sync static `warning` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; `return` |
| checkbox/details | none |
| test seam | class `warning` |
| test anchors | `tests/ui/test_channel_editor_export.py::test_do_export_wwt_refuses_too_short_source` |
| wave | T5 M1 |
| status | pending |
| notes | Distinct from `WwtExportError`. |

#### `export_wwt_error`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L4839) |
| owner | `MainWindow._do_export_wwt` |
| prompt_id | `export_wwt_error` |
| mode | sync static `warning` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | `str(e)` (`WwtExportError`) |
| test seam | class `warning` |
| test anchors | no dedicated node id found |
| wave | T5 M1 |
| status | pending |
| notes | Same owner, different except. |

#### `export_wwt_unexpected_error`

| Field | Value |
|---|---|
| module | `ui/main_window/window.py` (nav L4841) |
| owner | `MainWindow._do_export_wwt` |
| prompt_id | `export_wwt_unexpected_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | `str(e)` |
| test seam | class `critical` |
| test anchors | no dedicated node id found |
| wave | T5 M1 |
| status | pending |
| notes | Generic except after `WwtExportError`. |

---

### 5.6 T5 M1 — WWT layout (1)

#### `wwt_layout_prompt`

| Field | Value |
|---|---|
| module | `ui/main_window/wwt_import_coordinator.py` (nav L313) |
| owner | `WwtImportCoordinator._ask_layout` |
| prompt_id | `wwt_layout_prompt` |
| mode | sync `exec_()` |
| buttons/roles | `ACCEPT_TEXT` “创建时域 View 并绘图” `AcceptRole`; `REJECT_TEXT` “仅加载数据” `RejectRole` |
| default | **explicit** accept |
| escape/close | **not explicit**. Reject is **load data only**, not abort-import. If Escape/close maps to RejectRole or `clickedButton() is not accept`, current code treats it as load-data-only. **Do not invent a third cancel.** |
| return mapping | `WwtLayoutPromptResult(accepted, apply_to_remaining)`. Tests may monkeypatch bool (`apply_to_remaining=False`) via `coerce_layout_prompt`. |
| checkbox/details | `QCheckBox("对本次剩余 WWT 使用此选择")` default unchecked; `setInformativeText` |
| test seam | method `_ask_layout` / `_resolve_layout_prompt`; `QMessageBox.exec_` |
| test anchors | `tests/ui/test_wwt_import_flow.py::test_ask_layout_checkbox_default_unchecked_and_wires_result`; `tests/ui/test_wwt_open_batch_choice.py::test_remember_layout_asks_once_for_three_display_wwts`; `test_remember_data_only_asks_once_and_creates_no_winwert_views`; `test_raw_bool_true_does_not_remember_for_remaining` |
| wave | T5 M1 |
| status | pending |
| notes | **Ambiguous escape semantics.** Checkbox is the only production QMessageBox checkbox. |

---

### 5.7 T5 M2 — channel editor (18)

All static except `channel_remove_confirm`. Seam: `mf4_analyzer.ui.dialogs.QMessageBox` / class methods. Owner module `ui/dialogs/channel_editor.py`.

Shared test files: `tests/ui/test_dialogs.py`, `tests/ui/test_channel_editor_expression.py`, `tests/ui/test_channel_editor_export.py`, `tests/ui/test_channel_editor_create_labels.py`, `tests/ui/test_standard_desktop_interactions.py::test_destructive_dialog_default_is_safe`.

| module | owner | prompt_id | mode | buttons/roles | default | escape/close | return mapping | checkbox/details | test seam | test anchors | wave | status | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ui/dialogs/channel_editor.py` L563 | `ChannelEditorDialog._on_export_clicked` | `channel_export_no_selection` | sync `information` | Ok | Ok | Ok | ignored | none | class `information` | `tests/ui/test_channel_editor_export.py::test_editor_export_no_selection_does_not_emit` | T5 M2 | pending | |
| same L626 | `_create_single` | `channel_create_single_missing_source` | sync `warning` | Ok | Ok | Ok | ignored | none | `dialogs.QMessageBox.warning` | `tests/ui/test_dialogs.py::test_single_channel_missing_source_warns` | T5 M2 | pending | |
| same L647 | `_create_single` | `channel_create_single_unsupported_op` | sync `warning` | Ok | Ok | Ok | ignored | none | `dialogs.QMessageBox.warning` | `tests/ui/test_dialogs.py::test_single_channel_unknown_op_warns` | T5 M2 | pending | |
| same L653 | `_create_single` | `channel_create_single_error` | sync `critical` | Ok | Ok | Ok | ignored | `str(e)` | class `critical` | none found | T5 M2 | pending | |
| same L725 | `_create_expression` | `channel_create_expr_empty` | sync `warning` | Ok | Ok | Ok | ignored | none | class `warning` | `tests/ui/test_channel_editor_expression.py::test_bad_expression_warns_and_creates_nothing` (parametrized; empty may be this or parse) | T5 M2 | pending | |
| same L730 | `_create_expression` | `channel_create_expr_parse_error` | sync `warning` | Ok | Ok | Ok | ignored | `str(e)` title 表达式错误 | class `warning` | `test_bad_expression_warns_and_creates_nothing` | T5 M2 | pending | |
| same L742 | `_create_expression` | `channel_create_expr_missing_channel` | sync `warning` | Ok | Ok | Ok | ignored | channel key in text | class `warning` | expression tests | T5 M2 | pending | |
| same L746 | `_create_expression` | `channel_create_expr_length_mismatch` | sync `warning` | Ok | Ok | Ok | ignored | lengths in text | class `warning` | `test_expression_only_needing_A_ignores_B_length` (negative: must not fire) | T5 M2 | pending | |
| same L754 | `_create_expression` | `channel_create_expr_eval_error` | sync `warning` | Ok | Ok | Ok | ignored | ExpressionError | class `warning` | `test_bad_expression_warns_and_creates_nothing` | T5 M2 | pending | |
| same L757 | `_create_expression` | `channel_create_expr_eval_crash` | sync `critical` | Ok | Ok | Ok | ignored | `表达式计算失败：{e}` | class `critical` | none found | T5 M2 | pending | |
| same L760 | `_create_expression` | `channel_create_expr_all_nan` | sync `warning` | Ok | Ok | Ok | ignored | none | class `warning` | `tests/ui/test_channel_editor_expression.py::test_all_nan_result_is_refused` | T5 M2 | pending | |
| same L781 | `_create_dual` | `channel_create_dual_missing_a` | sync `warning` | Ok | Ok | Ok | ignored | none | `dialogs.QMessageBox.warning` | `tests/ui/test_dialogs.py::test_dual_channel_missing_channel_warns` | T5 M2 | pending | same title as missing B |
| same L784 | `_create_dual` | `channel_create_dual_missing_b` | sync `warning` | Ok | Ok | Ok | ignored | none | same | same parametrized test | T5 M2 | pending | keep distinct prompt_id |
| same L792 | `_create_dual` | `channel_create_dual_length_mismatch` | sync `warning` | Ok | Ok | Ok | ignored | lengths | class `warning` | none found | T5 M2 | pending | |
| same L811 | `_create_dual` | `channel_create_dual_unsupported_op` | sync `warning` | Ok | Ok | Ok | ignored | none | `dialogs.QMessageBox.warning` | `tests/ui/test_dialogs.py::test_dual_channel_unknown_op_warns` | T5 M2 | pending | |
| same L827 | `_create_dual` | `channel_create_dual_error` | sync `critical` | Ok | Ok | Ok | ignored | `str(e)` | class `critical` | none found | T5 M2 | pending | |
| same L836 | `_remove` | `channel_remove_no_selection` | sync `information` | Ok | Ok | Ok | ignored | none | class `information` | `tests/ui/test_channel_editor_export.py::test_editor_delete_no_selection_does_not_remove` | T5 M2 | pending | |
| same L838 | `_remove` | `channel_remove_confirm` | sync `question` | Yes \| No | **explicit No** | **not explicit**; Qt typically No — unverified | `!= QMessageBox.Yes` aborts | none | `channel_editor_mod.QMessageBox.question` | `tests/ui/test_channel_editor_export.py::test_editor_delete_uses_checked_export_items`; `tests/ui/test_dialogs.py::test_dangerous_confirmation_escape_and_return_are_safe`; `tests/ui/test_standard_desktop_interactions.py::test_destructive_dialog_default_is_safe` | T5 M2 | pending | Escape/Enter asserted in desktop-interaction spy, not a real AppMessageDialog yet |

---

### 5.8 T5 M2 — chart options (1)

#### `chart_options_log_range_invalid`

| Field | Value |
|---|---|
| module | `ui/dialogs/chart_options.py` (nav L482) |
| owner | `ChartOptionsDialog.apply_changes` |
| prompt_id | `chart_options_log_range_invalid` |
| mode | sync static `warning` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; `_applied = False` and stay on form |
| checkbox/details | none |
| test seam | `mf4_analyzer.ui.dialogs.QMessageBox.warning` |
| test anchors | `tests/ui/test_dialog_with_handle.py::test_dialog_log_scale_with_non_positive_range_falls_back_to_autoscale`; `tests/ui/test_dialogs.py::test_chart_options_log_axis_warning_blocks_close`; `test_validation_failure_keeps_dialog_open_and_focuses_first_error` |
| wave | T5 M2 |
| status | pending |
| notes | Must not close the options dialog. |

---

### 5.9 T5 M2 — batch sheet (6)

Owner file `ui/drawers/batch/sheet.py`. Toast owner `_show_result_toast`; stop owner `_confirm_stop_running_dialog`.

| module | owner | prompt_id | mode | buttons/roles | default | escape/close | return mapping | checkbox/details | test seam | test anchors | wave | status | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ui/drawers/batch/sheet.py` L2133 | `BatchSheet._show_result_toast` | `batch_run_done` | sync `information` | Ok | Ok | Ok | ignored | warnings folded into text via `_with_warnings` | `sheet_module.QMessageBox` | `tests/ui/test_batch_smoke.py::test_batch_sheet_result_toast_renders_and_folds_warnings` | T5 M2 | pending | skipped if sheet not visible |
| same L2142 | same | `batch_run_partial_degraded` | sync `information` | Ok | Ok | Ok | ignored | warnings + degraded count | same | same | T5 M2 | pending | `partial` + degraded_count and not blocked |
| same L2150 | same | `batch_run_partial_blocked` | sync `warning` | Ok | Ok | Ok | ignored | warnings + blocked count | same | same | T5 M2 | pending | `partial` else branch |
| same L2155 | same | `batch_run_cancelled` | sync `information` | Ok | Ok | Ok | ignored | warnings | same | same | T5 M2 | pending | |
| same L2162 | same | `batch_run_blocked` | sync `warning` | Ok | Ok | Ok | ignored | warnings + reason | same | same | T5 M2 | pending | |
| same L2245 | `BatchSheet._confirm_stop_running_dialog` | `batch_stop_on_close_confirm` | sync `question` | Yes \| No | **explicit No** | **not explicit** | `choice == Yes` | none; title `_STOP_ON_CLOSE_TITLE` “确认关闭”; text running-cancel copy | `sheet_module.QMessageBox.question` | `tests/ui/test_batch_smoke.py::test_confirm_stop_and_wait_no_leaves_runner_untouched`; `test_confirm_stop_and_wait_yes_waits_until_running_clears`; `test_stop_confirmation_copy_is_single_sourced`; `tests/ui/test_batch_compact_contract.py::test_mainwindow_close_ignored_when_user_declines_batch_stop`; `tests/ui/test_batch_close_guard_subprocess.py::test_mainwindow_close_after_confirmed_batch_stop_exits_clean` | T5 M2 | pending | parent may be MainWindow |

---

### 5.10 T5 M2 — channel tree (3)

#### `channel_file_node_check_all_confirm`

| Field | Value |
|---|---|
| module | `ui/widgets/channel_tree.py` (nav L2250) |
| owner | `MultiFileChannelWidget._on_item_changed` |
| prompt_id | `channel_file_node_check_all_confirm` |
| mode | sync `question` |
| buttons/roles | Yes \| No |
| default | **explicit No** |
| escape/close | **not explicit** |
| return mapping | `!= Yes` unchecks the node |
| checkbox/details | none; fires when descendant count > `MAX_CHANNELS_WARNING` (8) |
| test seam | `mf4_analyzer.ui.widgets.QMessageBox.question` (class method) |
| test anchors | `tests/ui/test_file_navigator.py::test_channel_over_threshold_warns` (this test calls `_all()`, so it is a stronger anchor for `channel_select_all_confirm`; node-check path has no dedicated live node id) |
| wave | T5 M2 |
| status | pending |
| notes | Parent is `self.tree`. |

#### `channel_selected_batch_check_confirm`

| Field | Value |
|---|---|
| module | `ui/widgets/channel_tree.py` (nav L2845) |
| owner | `MultiFileChannelWidget._confirm_selected_channel_checks` |
| prompt_id | `channel_selected_batch_check_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 全部勾选并显示 **or** 全部取消勾选 `AcceptRole`; 取消操作 `RejectRole` |
| default | **explicit** 取消操作 |
| escape/close | **not explicit**; False if not confirm |
| return mapping | `bool` |
| checkbox/details | none; copy depends on checking vs unchecking |
| test seam | method + `QMessageBox.exec_` |
| test anchors | `tests/ui/test_channel_widget.py::test_batch_confirmation_copy_and_default_cancel`; `test_checkbox_click_batches_selected_channel_rows_after_confirmation`; `test_checkbox_batch_cancel_keeps_states_and_emits_nothing` |
| wave | T5 M2 |
| status | pending |
| notes | One constructor, two label variants. Default Cancel asserted. |

#### `channel_select_all_confirm`

| Field | Value |
|---|---|
| module | `ui/widgets/channel_tree.py` (nav L3137) |
| owner | `MultiFileChannelWidget._all` |
| prompt_id | `channel_select_all_confirm` |
| mode | sync `question` |
| buttons/roles | Yes \| No |
| default | **explicit No** |
| escape/close | **not explicit** |
| return mapping | `!= Yes` returns without checking |
| checkbox/details | none |
| test seam | `mf4_analyzer.ui.widgets.QMessageBox.question` |
| test anchors | `tests/ui/test_file_navigator.py::test_channel_over_threshold_warns` |
| wave | T5 M2 |
| status | pending |
| notes | Threshold 8. Escape unverified. |

---

### 5.11 T5 M2 — presets (1)

#### `preset_clear_confirm`

| Field | Value |
|---|---|
| module | `ui/inspector_sections/presets.py` (nav L1018) |
| owner | `PresetBar._clear` |
| prompt_id | `preset_clear_confirm` |
| mode | sync `question` |
| buttons/roles | Yes \| No |
| default | **explicit No** |
| escape/close | **not explicit** |
| return mapping | `!= Yes` abort |
| checkbox/details | none |
| test seam | class `question` |
| test anchors | `tests/ui/test_preset_bar_lifecycle.py` does **not** exercise `_clear`; **no live confirm node id found** |
| wave | T5 M2 |
| status | pending |
| notes | Plan: keep cancel. Need a focused owner test at T5. |

---

### 5.12 T5 M3 — chart stack / views (7)

#### `chart_clear_annotations_confirm`

| Field | Value |
|---|---|
| module | `ui/chart_stack/cards.py` (nav L797) |
| owner | `_ChartCard._confirm_clear_annotations` |
| prompt_id | `chart_clear_annotations_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 清除标注 `DestructiveRole`; 取消 `RejectRole` |
| default | **explicit** 取消 |
| escape/close | **not explicit** |
| return mapping | `bool` |
| checkbox/details | informative 无法撤销 |
| test seam | method `_confirm_clear_annotations` |
| test anchors | `tests/ui/test_chart_stack.py::test_clear_annotation_skips_confirm_when_no_remarks`; `test_clear_annotation_confirms_when_remarks_present` |
| wave | T5 M3 |
| status | pending |
| notes | Empty chart skips dialog. |

#### `chart_save_image_failed`

| Field | Value |
|---|---|
| module | `ui/chart_stack/toolbar.py` (nav L961) |
| owner | `PgNavigationToolbar.save_figure` |
| prompt_id | `chart_save_image_failed` |
| mode | sync static `warning` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | path in text |
| test seam | `toolbar_mod.QMessageBox.warning` (module name) |
| test anchors | `tests/ui/test_chart_stack.py::test_save_image_failure_warns` |
| wave | T5 M3 |
| status | pending |
| notes | QFileDialog for save-as is S14. |

#### `ultraview_board_delete_from_switcher`

| Field | Value |
|---|---|
| module | `ui/chart_stack/ultraview/board_switcher.py` (nav L188) |
| owner | `BoardSwitcher._on_context_menu` |
| prompt_id | `ultraview_board_delete_from_switcher` |
| mode | sync `question` |
| buttons/roles | Cancel \| Yes |
| default | **explicit Cancel** |
| escape/close | Cancel is a standard Cancel button — likely escape, **unverified by keys** |
| return mapping | `== Yes` emits `delete_requested` |
| checkbox/details | none |
| test seam | class `question` |
| test anchors | no switcher-specific node id found; page-level delete tests cover similar copy |
| wave | T5 M3 |
| status | pending |
| notes | Same copy as page delete; keep distinct owner. |

#### `ultraview_leave_free_grid_from_toolbar`

| Field | Value |
|---|---|
| module | `ui/chart_stack/ultraview/board_toolbar.py` (nav L211) |
| owner | `BoardToolbar._on_free_grid_toggled` |
| prompt_id | `ultraview_leave_free_grid_from_toolbar` |
| mode | sync `question` |
| buttons/roles | Cancel \| Yes |
| default | **explicit Cancel** |
| escape/close | likely Cancel; unverified |
| return mapping | `!= Yes` rechecks free-grid toggle |
| checkbox/details | none |
| test seam | class `question` |
| test anchors | `tests/ui/test_ultraview_project_session.py` / `test_ultraview_export.py` call `_on_free_grid_toggled` but do not assert this dialog |
| wave | T5 M3 |
| status | pending |
| notes | Only when disabling visible free-grid. |

#### `ultraview_leave_free_grid_from_page`

| Field | Value |
|---|---|
| module | `ui/chart_stack/ultraview/page.py` (nav L1308) |
| owner | `UltraViewPage._confirm_leave_free_grid` |
| prompt_id | `ultraview_leave_free_grid_from_page` |
| mode | sync `question` |
| buttons/roles | Cancel \| Yes |
| default | **explicit Cancel** |
| escape/close | likely Cancel; unverified |
| return mapping | `== Yes` |
| checkbox/details | none; skipped when count ≤ capacity |
| test seam | class `question` |
| test anchors | `tests/ui/test_ultraview_page.py::test_free_grid_overlap_drop_moves_blocker_without_modal` (asserts question is **not** used on overlap); no overflow-leave node id found |
| wave | T5 M3 |
| status | pending |
| notes | Different copy from toolbar (capacity/overflow). |

#### `ultraview_board_delete_from_page`

| Field | Value |
|---|---|
| module | `ui/chart_stack/ultraview/page.py` (nav L1708) |
| owner | `UltraViewPage._confirm_delete_board` |
| prompt_id | `ultraview_board_delete_from_page` |
| mode | sync `question` |
| buttons/roles | Cancel \| Yes |
| default | **explicit Cancel** |
| escape/close | likely Cancel; unverified |
| return mapping | `== Yes` emits `delete_board_requested` |
| checkbox/details | none |
| test seam | class `QMessageBox.question` |
| test anchors | `tests/ui/test_ultraview_page.py::test_board_popover_click_switches_and_row_actions_copy_delete`; `test_board_popover_create_disables_at_cap_and_delete_cancel_keeps_board`; `tests/ui/test_ultraview_project_session.py` (related session, not this prompt) |
| wave | T5 M3 |
| status | pending |
| notes | Views are not deleted. |

#### `view_tab_replace_split_confirm`

| Field | Value |
|---|---|
| module | `ui/view_tabbar.py` (nav L1426) |
| owner | `ViewTabBar._on_context_menu` |
| prompt_id | `view_tab_replace_split_confirm` |
| mode | sync `question` |
| buttons/roles | Yes \| No |
| default | **explicit No** |
| escape/close | **not explicit** |
| return mapping | `!= Yes` abort split |
| checkbox/details | none |
| test seam | `mf4_analyzer.ui.view_tabbar.QMessageBox.question` |
| test anchors | `tests/ui/test_view_tabbar.py::test_context_menu_replacing_active_split_requires_confirmation`; `test_context_menu_replacing_active_split_cancel_keeps_current_pair` |
| wave | T5 M3 |
| status | pending |
| notes | View identity in copy; do not use display name as a data key. |

---

### 5.13 T5 M4 — analysis / FFT / Order (4)

#### `analysis_local_time_range_confirm`

| Field | Value |
|---|---|
| module | `ui/main_window/_analysis_mixin.py` (nav L866) |
| owner | `AnalysisMixin._ask_use_local_time_range` |
| prompt_id | `analysis_local_time_range_confirm` |
| mode | sync `exec_()` |
| buttons/roles | 用局部范围 `AcceptRole`; 用全时段 `DestructiveRole`; 取消 `RejectRole` |
| default | **explicit** 用局部范围 |
| escape/close | **not explicit**. Unknown click → `'cancel'`. Do not assume Escape is 全时段. |
| return mapping | `'local' \| 'full' \| 'cancel'` |
| checkbox/details | none |
| test seam | method `_ask_use_local_time_range` (comment: tests monkeypatch this) |
| test anchors | `tests/ui/test_analysis_time_range_confirm.py::test_offer_local_arms_checkbox`; `test_offer_full_keeps_unchecked`; `test_offer_cancel_aborts`; `test_do_fft_cancel_skips_capture`; `test_do_fft_local_choice_captures_pane_time_range`; `test_do_frf_cancel_returns_false` |
| wave | T5 M4 |
| status | pending |
| notes | Three-way result. Escape unproven. Do not change analysis range math. |

#### `fft_multi_source_compute_error`

| Field | Value |
|---|---|
| module | `ui/main_window/_fft_mixin.py` (nav L645) |
| owner | `FFTMixin.do_fft` |
| prompt_id | `fft_multi_source_compute_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; source marked failed, loop continues |
| checkbox/details | `str(e)` title `FFT错误` |
| test seam | `fft_mod.QMessageBox.critical` |
| test anchors | no dedicated multi-source critical node; `tests/ui/test_compute_progress_integration.py` covers `_do_fft_single` |
| wave | T5 M4 |
| status | pending |
| notes | Audit line 428/583 stale. AutoNFFT blocked does **not** use this box (toast). |

#### `fft_single_compute_error`

| Field | Value |
|---|---|
| module | `ui/main_window/_fft_mixin.py` (nav L817) |
| owner | `FFTMixin._do_fft_single` |
| prompt_id | `fft_single_compute_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored |
| checkbox/details | `str(error)` |
| test seam | `fft_mod.QMessageBox.critical` |
| test anchors | `tests/ui/test_compute_progress_integration.py::test_fft_single_progress_finishes_when_compute_raises` |
| wave | T5 M4 |
| status | pending |
| notes | Do not change FFT compute. |

#### `order_job_build_error`

| Field | Value |
|---|---|
| module | `ui/main_window/_order_mixin.py` (nav L506) |
| owner | `OrderMixin._build_order_job` |
| prompt_id | `order_job_build_error` |
| mode | sync static `critical` |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | ignored; returns None. Shown only if `warn` and no `_order_outcome`. |
| checkbox/details | `str(e)` |
| test seam | class `critical` |
| test anchors | `tests/ui/test_compute_progress_integration.py` / `tests/ui/test_main_window_smoke.py` call `_build_order_job` but do not assert this dialog |
| wave | T5 M4 |
| status | pending |
| notes | Outcome path increments `failed` instead of the box. Do not change Order DSP. |

---

### 5.14 T6 M5 — Cockpit async (6)

All window-modal `open()`, not `exec_()`. Hold a live reference. Visible-only paint (hidden tests must not open). Runtime class lookup on `mf4_analyzer.acquisition_ui.main_window.QMessageBox` for mixin constructors.

#### `cockpit_connection_preconditions`

| Field | Value |
|---|---|
| module | `acquisition_ui/main_window/_connection_mixin.py` (nav L248) |
| owner | `ConnectionMixin._warn_connection_preconditions` |
| prompt_id | `cockpit_connection_preconditions` |
| mode | **async** `open()` if `isVisible()` |
| buttons/roles | Ok (if empty) |
| default | Ok (standard) |
| escape/close | Ok (sole button); **unverified** while recording/connect |
| return mapping | none (no `exec_` result). Caller does not wait. |
| checkbox/details | none |
| test seam | `mf4_analyzer.acquisition_ui.main_window.QMessageBox` + `.open`; stored `_connection_warning_box` |
| test anchors | `tests/acquisition_ui/test_record_backend_swap.py::test_connection_precondition_warning_uses_nonblocking_message_box`; `test_missing_vehicle_preconditions_warn_in_production`; `tests/acquisition_ui/test_connection_messages.py::test_no_double_encoded_text_in_connection_mixin` (source encoding, not runtime) |
| wave | **T6** |
| status | pending |
| notes | Replaces prior box via attribute. |

#### `cockpit_a2l_load_warning`

| Field | Value |
|---|---|
| module | `acquisition_ui/main_window/_settings_mixin.py` (nav L561) |
| owner | `SettingsMixin._warn_a2l_load_problems` |
| prompt_id | `cockpit_a2l_load_warning` |
| mode | **async** `open()` if visible |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | none |
| checkbox/details | filename + bullet problems |
| test seam | package `QMessageBox.open`; method may also be stubbed; `_a2l_warning_box` |
| test anchors | `tests/acquisition_ui/test_pick_a2l_warnings.py::test_a2l_warning_hidden_window_does_not_open_message_box`; `test_ifdata_parse_failure_warns_and_clears_cache`; `test_measurement_failure_clears_new_ifdata_and_old_pool` |
| wave | T6 |
| status | pending |
| notes | Replaces prior A2L warning. Tests stub method or `.open`. |

#### `cockpit_dropped_frames_prompt`

| Field | Value |
|---|---|
| module | `acquisition_ui/main_window/_settings_mixin.py` (nav L630) |
| owner | `SettingsMixin._show_dropped_frames_prompt` |
| prompt_id | `cockpit_dropped_frames_prompt` |
| mode | **async** `open()` if visible |
| buttons/roles | 继续录制 `AcceptRole`; 停止并复盘 `DestructiveRole`. **No RejectRole.** |
| default | **not set** |
| escape/close | **not set; no RejectRole.** Title-bar / Escape / parent destroy **must not be guessed** (continue vs stop vs neither). |
| return mapping | no `exec_` value. `buttonClicked`: stop → `request_stop_and_review()` once; continue dismiss-only. |
| checkbox/details | none; title/text `DROPPED_FRAMES_PROMPT_*` |
| test seam | package `QMessageBox.open`; `_dropped_prompt` / continue/stop btn attrs |
| test anchors | `tests/acquisition_ui/test_dropped_frame_prompt.py::test_prompt_text_matches_spec`; `test_prompt_hidden_window_does_not_open_message_box`; `test_continue_button_dismisses_and_keeps_recording`; `test_stop_button_runs_stop_flush_finalize_flow`; `test_dropped_prompt_re_arms_after_time_and_delta`; `tests/acquisition_ui/test_message_box_button_fit.py::test_dropped_frames_prompt_fits_action_buttons` |
| wave | T6 |
| status | pending |
| notes | **Highest-ambiguity default/escape.** `finished` and `clicked` must not both run stop. |

#### `cockpit_review_discard_confirm`

| Field | Value |
|---|---|
| module | `acquisition_ui/review_modal.py` (nav L407) |
| owner | `ReviewModal._show_discard_confirm` |
| prompt_id | `cockpit_review_discard_confirm` |
| mode | **async** `open()` if visible |
| buttons/roles | 确认删除 `DestructiveRole`; 取消 `RejectRole` |
| default | **not set**. First added is destructive. **Do not assume Enter = delete.** |
| escape/close | **not explicit**. If Qt maps RejectRole, cancel is safe; **unproven**. Click-delete may close parent review — one-shot result. |
| return mapping | no `exec_`. `buttonClicked` confirm → `do_discard(confirmed=True)` |
| checkbox/details | none |
| test seam | `QMessageBox.open` / `exec_` forbidden in tests; `_discard_confirm_box` |
| test anchors | `tests/acquisition_ui/test_review_handoff.py::test_discard_requires_confirmation`; `test_discard_removes_mf4_and_sidecars`; `tests/acquisition_ui/test_message_box_button_fit.py::test_discard_confirm_fits_delete_button` |
| wave | T6 |
| status | pending |
| notes | **Ambiguous default.** Parent destroy during open is a T6 gate. |

#### `cockpit_review_archive_failure`

| Field | Value |
|---|---|
| module | `acquisition_ui/review_modal.py` (nav L597) |
| owner | `ReviewModal._show_archive_failure` |
| prompt_id | `cockpit_review_archive_failure` |
| mode | **async** `open()` (after `isVisible()` guard) |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | none; save is not aborted |
| checkbox/details | exception + mf4 path in text |
| test seam | `QMessageBox.open`; `_archive_failure_box` |
| test anchors | `tests/acquisition_ui/test_review_handoff.py::test_archive_failure_does_not_corrupt_mf4`; `test_archive_failure_visible_modal_uses_nonblocking_message_box` |
| wave | T6 |
| status | pending |
| notes | Must not `exec_` on QThread.finished. |

#### `cockpit_test_connection_result`

| Field | Value |
|---|---|
| module | `acquisition_ui/settings_dialog.py` (nav L523) |
| owner | `SettingsDialog._show_test_connection_result` |
| prompt_id | `cockpit_test_connection_result` |
| mode | **async** `open()` if visible |
| buttons/roles | Ok |
| default / escape/close | Ok |
| return mapping | none |
| checkbox/details | none; icon Information if ok else Warning |
| test seam | `QMessageBox.open`; static helpers must not be used; `_test_connection_box` |
| test anchors | `tests/acquisition_ui/test_settings_transport_tab.py::test_test_connection_result_uses_managed_nonblocking_box`; `tests/acquisition_ui/test_message_box_button_fit.py::test_every_message_box_constructor_fits_buttons`; `tests/acquisition_ui/test_settings_dialog.py` (save/cancel, not this box) |
| wave | T6 |
| status | pending |
| notes | Direct `QMessageBox(self)`, not package lookup. |

---

## 6. S14 — QInputDialog and QFileDialog (not message-box migration)

Retain Qt components. Record for T4/T7 compatibility. Disposition starts `pending` (retained_verified only after font/small-screen/multi-screen check).

### 6.1 QInputDialog — 5 sites

| module | owner | kind | notes | related tests |
|---|---|---|---|---|
| `acquisition_ui/main_window/_settings_mixin.py` L273 | `SettingsMixin._on_mark_segment` | `getText` | optional segment label | acquisition settings/record tests |
| `ui/inspector_sections/presets.py` L994 | `PresetBar._rename` | `getText` | max length truncated after OK | `tests/ui/test_preset_bar_lifecycle.py` (no live getText found) |
| `ui/main_window/_channel_scope_mixin.py` L387 | `ChannelScopeMixin._prompt_channel_config_name` | `getText` | returns `(text, ok)` | `tests/ui/test_view_channel_scope.py` stubs method |
| `ui/chart_stack/ultraview/board_switcher.py` L183 | `BoardSwitcher._on_context_menu` | `getText` | rename Board | ultraview page/switcher |
| `ui/main_window/_project_io_mixin.py` L1807 | `ProjectIOMixin._ask_multiple_blf_dbc_candidates` | `getItem` | extra “选择其他 DBC...” row | BLF open tests |

### 6.2 QFileDialog — 20 sites

Docstring mention in `ui/drawers/batch/output_panel.py` L5 is not a call.

| module | owner | API | notes / seam |
|---|---|---|---|
| `acquisition_ui/history_tab.py` L624 | `HistoryTab._choose_manifest` | `getOpenFileName` | JSON manifest |
| `acquisition_ui/replay_tab.py` L161 | `ReplayTab._pick_file` | `getOpenFileName` | MF4 replay |
| `acquisition_ui/settings_dialog.py` L396 | `TransportTabWidget._browse_seed_key` | `getOpenFileName` | Seed&Key DLL |
| `acquisition_ui/main_window/_settings_mixin.py` L447 | `SettingsMixin._on_pick_a2l` | `getOpenFileName` | tests prefer `apply_a2l_path` |
| `acquisition_ui/main_window/_settings_mixin.py` L601 | `SettingsMixin._on_pick_output_dir` | `getExistingDirectory` | |
| `ui/chart_stack/toolbar.py` L939 | `PgNavigationToolbar.save_figure` | `getSaveFileName` via `mf4_analyzer.ui.chart_stack.QFileDialog` | |
| `ui/widgets/channel_config_manager.py` L1372 | `ChannelConfigManagerDialog._open_import_file` | `getOpenFileName` | |
| `ui/widgets/channel_config_manager.py` L1378 | `ChannelConfigManagerDialog._save_export_file` | `getSaveFileName` | |
| `ui/markup/editor.py` L406 | `MarkupEditor._get_save_path` | `getSaveFileName` | |
| `ui/drawers/batch/output_panel.py` L928 | `OutputPanel._choose_dir` | `getExistingDirectory` | |
| `ui/drawers/batch/input_panel.py` L766 | `FileListWidget._open_disk_dialog` | `getOpenFileNames` | |
| `ui/drawers/batch/sheet.py` L1504 | `BatchSheet._on_import_preset` | `getOpenFileName` | |
| `ui/drawers/batch/sheet.py` L1531 | `BatchSheet._on_export_preset` | `getSaveFileName` | |
| `ui/main_window/_project_io_mixin.py` L236 | `ProjectIOMixin.open_files_or_project` | `getOpenFileNames` via `main_window.QFileDialog` | |
| `ui/main_window/_project_io_mixin.py` L511 | `ProjectIOMixin.save_project_as_via_dialog` | `getSaveFileName` | local import |
| `ui/main_window/_project_io_mixin.py` L559 | `ProjectIOMixin.load_files` | `getOpenFileNames` via package lookup | |
| `ui/main_window/_project_io_mixin.py` L1855 | `ProjectIOMixin._prompt_blf_dbc` | `getOpenFileNames` via package lookup | |
| `ui/main_window/ultraview_coordinator.py` L385 | `UltraViewCoordinator.choose_and_export_png` | `getSaveFileName` | |
| `ui/main_window/window.py` L4734 | `MainWindow._do_export_excel` | `getSaveFileName` | |
| `ui/main_window/window.py` L4801 | `MainWindow._do_export_wwt` | `getSaveFileName` | |

## 7. Adjacent non-QMessageBox (plan T4 / S10)

| Item | Path | Ledger note |
|---|---|---|
| `_PlaceholderReviewModal` | `acquisition_ui/main_window/window.py` L99 | Placeholder QDialog, not a message box. Do not rewrite from class name alone. Not in the 77. |
| Real `ReviewModal` | `acquisition_ui/review_modal.py` | Owns two T6 boxes above. |

## 8. Ambiguous default / escape — must stay pending

Do not fill these with AcceptRole/first-button guesses. Need a key/close probe or an explicit product freeze before T5/T6 mapping.

| prompt_id | Why pending |
|---|---|
| `unsaved_project` | Default/escape **are** explicit (Save / Cancel). Keep that freeze; still pending until T3 visual+keyboard evidence. |
| `heavy_load_confirm` | Default is Continue (explicit, not safety-first). Escape not set. |
| `blf_batch_dbc_action` | ActionRole currently closes. Escape not set; unknown click is `"cancel"`. |
| `blf_batch_mismatch_action` | RejectRole = stop remaining import, not a no-op. |
| `blf_dbc_candidate_action` | ActionRole closes; escape not set. |
| `wwt_layout_prompt` | Reject/Escape/close currently means **load data only**, not abort. Checkbox. |
| `analysis_local_time_range_confirm` | Three results; default local; Escape not set — must not become `full`. |
| `overlay_mode_risk_confirm` and all `question(Yes\|No, No)` | Escape not passed; Qt-likely No is **unverified** (`channel_remove_confirm`, `batch_stop_on_close_confirm`, `preset_clear_confirm`, `channel_file_node_check_all_confirm`, `channel_select_all_confirm`, `view_tab_replace_split_confirm`). |
| `ultraview_*` `question(Cancel\|Yes, Cancel)` | Cancel default explicit; Escape likely Cancel via standard Cancel button, no key test. |
| Every custom `exec_()` box except `unsaved_project` | No `setEscapeButton`. Close currently follows `clickedButton() is confirm` → False, but Escape identity is unproven. |
| `cockpit_dropped_frames_prompt` | No default, no escape, no RejectRole. Stop vs continue vs neither on X/Escape/parent destroy is unknown. |
| `cockpit_review_discard_confirm` | No default; Destructive is first. Enter must not be assumed to delete. |
| `cockpit_connection_preconditions` / `cockpit_a2l_load_warning` / `cockpit_review_archive_failure` / `cockpit_test_connection_result` | Sole Ok async; close mapping unused by callers but must stay non-blocking and single-shot. |

## 9. prompt_id index (77)

T3: `unsaved_project`

T5 M1: `open_multiple_projects_rejected`, `heavy_load_confirm`, `degraded_project_save_confirm`, `load_mf4_missing_asammdf`, `load_one_import_error`, `load_one_generic_error`, `blf_batch_read_error`, `blf_batch_dbc_action`, `blf_batch_mismatch_action`, `blf_open_choose_dbc`, `blf_dbc_candidate_action`, `blf_dbc_mismatch_retry`, `project_restore_degraded`, `project_restore_missing_files`, `analysis_view_detach_confirm`, `channel_config_overwrite_confirm`, `time_view_detach_files_confirm`, `view_delete_confirm`, `view_close_others_confirm`, `view_close_all_confirm`, `cockpit_lite_unavailable`, `global_file_close_all_empty`, `global_file_close_in_use`, `global_channel_delete_in_use`, `overlay_mode_risk_confirm`, `export_excel_error`, `export_wwt_range_too_short`, `export_wwt_error`, `export_wwt_unexpected_error`, `wwt_layout_prompt`

T5 M2: `channel_export_no_selection`, `channel_create_single_missing_source`, `channel_create_single_unsupported_op`, `channel_create_single_error`, `channel_create_expr_empty`, `channel_create_expr_parse_error`, `channel_create_expr_missing_channel`, `channel_create_expr_length_mismatch`, `channel_create_expr_eval_error`, `channel_create_expr_eval_crash`, `channel_create_expr_all_nan`, `channel_create_dual_missing_a`, `channel_create_dual_missing_b`, `channel_create_dual_length_mismatch`, `channel_create_dual_unsupported_op`, `channel_create_dual_error`, `channel_remove_no_selection`, `channel_remove_confirm`, `chart_options_log_range_invalid`, `batch_run_done`, `batch_run_partial_degraded`, `batch_run_partial_blocked`, `batch_run_cancelled`, `batch_run_blocked`, `batch_stop_on_close_confirm`, `channel_file_node_check_all_confirm`, `channel_selected_batch_check_confirm`, `channel_select_all_confirm`, `preset_clear_confirm`

T5 M3: `chart_clear_annotations_confirm`, `chart_save_image_failed`, `ultraview_board_delete_from_switcher`, `ultraview_leave_free_grid_from_toolbar`, `ultraview_leave_free_grid_from_page`, `ultraview_board_delete_from_page`, `view_tab_replace_split_confirm`

T5 M4: `analysis_local_time_range_confirm`, `fft_multi_source_compute_error`, `fft_single_compute_error`, `order_job_build_error`

T6 M5: `cockpit_connection_preconditions`, `cockpit_a2l_load_warning`, `cockpit_dropped_frames_prompt`, `cockpit_review_discard_confirm`, `cockpit_review_archive_failure`, `cockpit_test_connection_result`

Index count: 1 + 30 + 29 + 7 + 4 + 6 = **77**.

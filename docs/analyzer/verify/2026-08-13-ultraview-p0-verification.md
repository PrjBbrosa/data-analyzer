# UltraView P0 补完验收报告

- 日期：2026-08-13
- 分支：`feat/ultraview-p0`
- 文档基线提交：`c4b8fb479f99e2825d9afc091ab67d2838d594d0`（`docs(ui): add UltraView P0 completion spec and plan`）
- 实现：该提交之上的未提交工作区（Task 1–7 代码与测试尚未按建议序列提交）
- 平台：Windows 10 26200，offscreen Qt，仓库 `.venv\Scripts\python.exe`
- 关联：`docs/analyzer/specs/2026-08-13-ultraview-p0-completion-hardening-spec.md`
- 视觉证据（默认不入库）：`.state/ultraview-p0/`

本报告把自动化、offscreen、Cocoa、Windows frozen 分成不同证据层。未跑的层写
`UNVERIFIED`，不把部分通过的用例推断成全套通过。

## 1. 命令与结果

| Contract | Evidence class | Command/action | Result | Evidence | Notes |
|---|---|---|---|---|---|
| 静态 | source-only | `git diff --check`；`rg except Exception` on ultraview owner files | PASS | 无 whitespace error；coordinator / `chart_stack/ultraview` 无宽泛 `except Exception` | Task 7 纪律 |
| UV-R14 | unit | `pytest` state ownership / import boundaries / signal no-gui / batch-render boundary / native imports / packaging / pg backref | PASS | 24 passed / 1 skipped | skipped 为既有 packaging spec 缺席，非 UltraView |
| UV-R01 | subprocess | `tests/ui/test_ultraview_lifecycle_subprocess.py` 连续 3 轮 | PASS | 每轮 4 passed（约 10–11 s） | 子进程 exit code，不用 `pytest.raises` |
| UV-R02/R03 | unit | `test_ultraview_mode_integration.py` reset / close-all / shutdown | PASS | 13 passed | Task 7 给 `export_png_requested` 补了 `QFileDialog` mock，避免 reset 后真弹保存框 |
| UV-R04 | unit | `tests/test_project_io.py` + `tests/ui/test_ultraview_project_session.py` | PASS | project_io 含 schema=2 / last source mode / 旧读者丢字段；session 含重开不进总览 | |
| UV-R05/R07/R08 | unit + offscreen | `tests/ui/test_ultraview_export.py` | PASS | compositor 1600×900 / 3200×1800、原子 PNG、clipboard SHA、LRU touch | 不用 `QWidget.grab` 做整板导出 |
| UV-R06 | unit | `tests/ui/test_ultraview_capture.py` inactive digest / ledger | PASS | 含 payload 不读 active page、时域不 fallback canvas | |
| UV-R09 | unit | page Esc / board name；mode integration | PASS | `test_board_name_is_keyboard_editable`、Esc 优先级三条 | |
| UV-R10 | unit | hints / quickref / help / screenshot / packaging | PASS | Task 6 套件 94 passed / 1 skipped（packaging spec） | screenshot CSV 在 Windows 补了 `encoding="utf-8"` |
| UV-R11/R12 | unit | `test_full_ultraview_export_sequence_stays_zero_compute` | PASS | compute/job/store-write = 0；演示、复制、PNG 1×/2×、保存 | |
| UV-R13 | unit | `tests/ui/test_ultraview_*.py` 聚焦全量 | PASS | capture+export+job+layouts+page+store+state+probes+session **98 passed**；mode 13；lifecycle 4；合计 **115** | 交错顺序 101 passed（state / project_io / page / help / export） |
| UV-R15 主体 | two-process | `pytest -q --ignore=tests/acquisition_ui` | **UNVERIFIED** | 约 46% 处 `Windows fatal exception: access violation`（`0xC0000005`） | 崩在 `tests/ui/test_blf_batch_import.py::test_batch_dbc_dialog_actions_fit_without_text_elision` → `_ask_blf_batch_dbc_action` `QMessageBox.exec_`。无汇总。不能把崩溃前的点阵当通过。 |
| UV-R15 acquisition | two-process | `pytest -q tests/acquisition_ui` | FAIL（环境） | **4 failed / 354 passed / 1 skipped**，进程正常结束 | 失败均为 Cockpit 路径显示 / Vector 本机可用 / YAML 转义，与 UltraView 无调用关系 |
| UV-R16 | Cocoa | 真机主窗口进入/退出总览、拖放、Esc、clipboard、PNG | **UNVERIFIED** | 无 macOS 前景机 | offscreen contact sheet 不能代替 |
| UV-R18 | Windows frozen | Full/Lite 冻结包 | **UNVERIFIED** | 未跑 `tools/build_windows_folder*.ps1` | 不阻塞源码合入，阻塞 Windows 发布签字 |
| UV-R33 视觉 | offscreen | `python tools/verify_ultraview_visuals.py --platform offscreen` | PASS | `.state/ultraview-p0/manifest.json` + `contact-sheet.png` + 10 张 named shots | 截图默认不提交 Git（`.state/`） |

Qt 前缀（本机）：

```text
PYTHONPATH=.
QT_QPA_PLATFORM=offscreen
TMPDIR/TMP/TEMP/MPLCONFIGDIR = <repo>/.tmp-pytest
.venv\Scripts\python.exe -m pytest ...
```

## 2. UV-R01～R18

| ID | Result | Evidence |
|---|---|---|
| UV-R01 | PASS | lifecycle subprocess ×3 |
| UV-R02 | PASS | `test_reset_project_state_keeps_page_hooks_and_stays_interactive`；shutdown 后 receivers 为 0 |
| UV-R03 | PASS | close-all 取消/确认/无文件三条 |
| UV-R04 | PASS | schema 仍为 2；`ultraview` 增量；未知 mode → time |
| UV-R05 | PASS | copy board/card + PNG 1×/2×；失败走 `ComposeError` |
| UV-R06 | PASS | inactive A 不随 active B；自身变化 stale |
| UV-R07 | PASS | 屏上 footer=0 与 compositor show flags；项目 payload 含开关 |
| UV-R08 | PASS | placed/focus/copy/compose touch；library `get()` 不 touch |
| UV-R09 | PASS | 板名 `QLineEdit`；Esc = focus → replacement → presentation → popup |
| UV-R10 | PASS | hints/quickref/guide/`PANEL_MODES`/packaging datas |
| UV-R11 | PASS | 完整零计算序列含演示/复制/导出/保存 |
| UV-R12 | PASS | 同一序列断言 restore pending、identity snapshot、cache write=0 |
| UV-R13 | PASS | 既有 capture/DPR/布局/托盘/四态测试仍绿 |
| UV-R14 | PASS | 架构门禁未放宽白名单 |
| UV-R15 | **UNVERIFIED** | 主体进程异常退出；见上表 |
| UV-R16 | **UNVERIFIED** | 本机不是 macOS Cocoa 前景 |
| UV-R17 | PASS | 下文 UV-A01～A34 全映射 |
| UV-R18 | **UNVERIFIED** | 未做 Windows Full/Lite frozen |

## 3. 原 UV-A01～A34 映射

| ID | 映射 R | 自动化/证据入口 | Result |
|---|---|---|---|
| UV-A01 | R13 | `test_ultraview_state.py::test_ref_accepts_only_gui_sections_and_stable_id` | PASS |
| UV-A02 | R13 | `test_capacity_operations_preserve_every_ref_in_tray` | PASS |
| UV-A03 | R04/R13 | `test_orphan_rebind_uses_replace_flow` + project normalize | PASS |
| UV-A04 | R13 | `test_status_is_derived_and_never_optimistically_fresh` | PASS |
| UV-A05 | R06/R13 | `test_presentation_digest_pixel_affecting_field_matrix` | PASS |
| UV-A06 | R13 | `test_all_templates_fit_without_overlap_at_supported_sizes` | PASS |
| UV-A07 | R02/R13 | library 搜索/添加；`test_main_window_ultraview_mode_hides_nav_and_ignores_alt_shortcuts` | PASS |
| UV-A08 | R13 | `test_overflow_tray_is_visible_and_persisted` | PASS |
| UV-A09 | R09/R13 | `test_menu_double_click_and_keyboard_share_intents` + focus 打开原 View | PASS |
| UV-A10 | R13 | `test_compare_filter_and_axis_warnings_do_not_mutate_board` | PASS |
| UV-A11 | R09 | Esc 三条 + `test_reset_during_presentation_restores_inspector` | PASS |
| UV-A12 | R13 | `test_main_window_ultraview_mode_hides_nav_and_ignores_alt_shortcuts`（Alt no-op） | PASS |
| UV-A13 | R06 | `test_time_switch_captures_old_binding_before_deferred_render` | PASS |
| UV-A14 | R13 | `test_each_capture_trigger_obeys_canvas_stability_contract` | PASS |
| UV-A15 | R13 | `test_time_split_is_two_refs_and_analysis_split_is_one_composite` | PASS |
| UV-A16 | R13 | `test_dpr_normalization_and_minimum_valid_dimensions` | PASS |
| UV-A17 | R13 | `test_transient_overlays_hidden_but_markup_revision_is_captured` | PASS |
| UV-A18 | R13 | `test_capture_dedupes_and_rejects_late_binding_or_digest` | PASS |
| UV-A19 | R11 | `test_full_ultraview_export_sequence_stays_zero_compute`（`compute_total==0`） | PASS |
| UV-A20 | R11 | 同上 `job_total==0` 且 `store_new_key_writes==0` | PASS |
| UV-A21 | R12 | 同上 identity snapshot + restore pending | PASS |
| UV-A22 | R11 | `test_preview_path_never_calls_restore_or_source_replot` | PASS |
| UV-A23 | R10/R13 | toolbar 六 mode、Inspector `ultraview` guide、hint bar `?` | PASS |
| UV-A24 | R10/R13 | `test_toolbar_six_modes_go_icon_only_at_1100_and_restore_labels_at_1600` + harness `toolbar_1100` | PASS offscreen |
| UV-A25 | R04 | `test_ultraview_field_is_last_and_positional_construction_unchanged`（SCHEMA=2） | PASS |
| UV-A26 | R04 | `test_save_from_ultraview_writes_last_source_mode_and_board`；未知 mode → time | PASS |
| UV-A27 | R04 | `test_normalize_keeps_legal_missing_refs_and_warns_on_illegal` | PASS |
| UV-A28 | R04 | `test_old_reader_drops_ultraview_on_resave` | PASS |
| UV-A29 | R08/R13 | `test_raw_pixel_budget_lru_stats_and_symmetric_clear` | PASS |
| UV-A30 | R05 | `test_clipboard_matches_compositor_and_card_copy_touches` | PASS |
| UV-A31 | R05 | compositor 2× contain-fit；job isolation 2× PNG 零计算 | PASS |
| UV-A32 | R10 | hints/quickref/`ultraview-guide.html`/`PANEL_MODES`/packaging | PASS |
| UV-A33 | R10 | `tests/test_verify_ultraview_visuals.py` + `.state/ultraview-p0/` | PASS offscreen |
| UV-A34 | R16 | Cocoa 前景清单 | **UNVERIFIED** |

## 4. Task 7 仅修的回归

`test_reset_project_state_keeps_page_hooks_and_stays_interactive` 在 Task 5 接上
`export_png_requested` 后会弹出 `QFileDialog`，offscreen 下挂死。测试改为 mock
`getSaveFileName`，产品代码未改导出行为。

`tools/gen_help_screenshots.py` 的合成 CSV 在 Windows cp1252 下无法写入中文表头，
补 `encoding="utf-8"`，否则 `--only ultraview` 截图工具不可用。

## 5. 未验与合入判断

- **macOS Cocoa 前景**：未做。需要真机核对侧栏恢复、Retina、拖放、clipboard/PNG 观感。contact sheet 只作对照清单。
- **Windows frozen Full/Lite**：未做。
- **主体全套**：异常退出，`UV-R15` 不能签 PASS。崩溃点是 BLF 批量 DBC 对话框，不是 UltraView 测试。
- **acquisition_ui**：进程正常结束，4 条失败是 Windows 路径压缩与本机 Vector 可用性，不是总览代码。

**结论**：UltraView P0 的生命周期、项目往返、digest 隔离、导出、帮助与 offscreen 视觉在本工作区有自动化证据（UV-R01～R14、R17）。按 spec Done 定义，在 Cocoa 前景、主体两进程正常结束、以及（若要 Windows 发布）frozen 包之前，**不能从 NO-GO 改为可合入**。未 force push `main`，未自动 merge。

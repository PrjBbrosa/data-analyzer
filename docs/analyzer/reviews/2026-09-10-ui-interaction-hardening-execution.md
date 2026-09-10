# UI 交互收口执行报告

日期：2026-09-10。基线 HEAD：`29ab049c5932a5fb17b4478cb8fa8b0fb3cd6043`。
配套：[Review](2026-09-10-ui-interaction-two-day-review.md) ·
[Spec](../specs/2026-09-10-ui-interaction-hardening-spec.md) ·
[Plan](../plans/2026-09-10-ui-interaction-hardening-plan.md)。

结论：**F01–F11 产品侧已关闭**，对应 R01–R11 有 owner 测试。R12 / A23 / A24
按平台分层记录：offscreen 与本机 Cocoa 禁用像素已跑；完整五方法前台
walkthrough、长客户 ZFD、Windows native/frozen 为 **UNKNOWN**。未跑全量。

## 1. 快照

| 项 | 值 |
| --- | --- |
| 实施前 HEAD | `29ab049c5932a5fb17b4478cb8fa8b0fb3cd6043` |
| 实施后（本报告写入时） | 同 HEAD，工作区脏；本提交只含收口范围 |
| 实施期间他人提交 | 无（HEAD 未移动） |
| 主机 | macOS 27 arm64，Apple M5，PingFang SC 可用 |

用户实施前已有、**不纳入本提交**的改动：`compute_progress.py` 与其测试、
`channel_config_bar.py`、`searchable_combo.py`、lessons INDEX、
`progress-label-implicit-indent-clips-ink.md`、未跟踪 `ssh-keygen`。
`.state/` 任务报告留本机。`presets.py` 自绘圆点、`style.qss` 删除
`QLabel#presetDiffDot`、以及 hints/quickref 里已有的可搜索下拉文案与收口
缠在一起，随本提交走。

## 2. 任务结果

| Task | 关闭 | 结果 |
| --- | --- | --- |
| T0 | 范围/指纹 | HEAD=`29ab049c`；F01–F11 当时全开 |
| T1 | F01 文本/勾选、F02、F06 | `RangeEditQuery`；flush 不再先 `interpretText()`；非法勾选不写全时段；无编辑不回写显示精度。151 passed |
| T2 | F01 coverage/多 pane、F07 | `validate_requested_span`；冻结 candidate 再一次写入；`FileData.time_array` property + 六元组签名。126 + 16 passed |
| T3 | F04、F05 | `resolve_preset_target`；`baseline.params=target`；v2 `source_payload`；v1 来源未知。131 passed / 1 skipped |
| T4 | F03 | 成功加载/保存发一次 `preset_committed` → 完整 params+baseline → 一次 `mark_user_mutation`。145 passed |
| T5 | F09、F11 | `GroupingCountSnapshot` + `plan_render_tasks`；默认仍 time；程序 apply 走 `_suspend_user_configuration`。279 passed / 2 几何红交 T6/T8 |
| T6 | F10 | 自绘读 `isEnabled()`×checked；QSS 长写 `border-color`。Cocoa 选中预设卡 `#0b73e7` **258→0**。278 passed |
| T7 | F08 | `tests/zfd_corpus.py`；无 corpus skip，`TRACELAB_REQUIRE_ZFD_CORPUS=1` fail。普通 105 passed / 3 skipped；本机六样本 8 passed |
| T8 | R12、A24、文案、集成 | hints/quickref；几何前提；本报告 |

T8 对窄列做了两处前提修正，**没有缩小生产字号，没有关掉 `fit_window`**：

- 1080×760 / FRF 窄列：注入 1920×1080 可用屏；800×600 夹取与底栏可达仍独立看守。
- 288 列预设卡：紧凑模式卡间距 6→5，避免 246/4=61.5 把「自定义」卡在 61 px
  刀口上。度量用 `resolve_cjk_font()`，不用缺失的 `Microsoft YaHei` 别名。
- 目标策略分段条：不再钉死 QFormLayout 的 71 px 起点；断言字段列仍铺满到
  右缘 275，起点允许 70–76。

## 3. 需求 / 验收 / Finding

| ID | 状态 | 证据 |
| --- | --- | --- |
| R01 / F01 / A01 / A02 | 关闭 | T1：非法文本与倒序勾选不回退、不写 `(0,10)`；T2：越界草稿不可作局部 |
| R02 / A03 / A04 | 关闭 | T2：全部 candidate 先验证；取消/失败零写入 |
| R03 / F02 / A05 | 关闭 | T1：`_capture_analysis_time_range` 不把 `spin.value()` 写回已启用模型 |
| R04 / F06 / F07 / A06–A08 | 关闭 | T1 投影最终 intent；T2 签名 `(t0,t1,n,source_token,axis_revision,axis_token)` |
| R05 / F04 / A09 / A10 | 关闭 | T3：黄点相对 **target**，不是保留后的 applied |
| R06 / F05 / A11 / A12 | 关闭 | T3：v2 存 `source_payload`；v1 未知，不拿当前槽反填 |
| R07 / F03 / A13 / A14 | 关闭 | T4：等参数跨槽加载 dirty；取消/失败/程序恢复不发事件 |
| R08 / F09 / A15 / A16 | 关闭 | T5：稀疏来源 2≠4；pending/FRF 半配对写「待确定」 |
| R09 / F10 / A17 / A18 | 关闭 | T6：祖先锁零信号；Cocoa 选中预设卡 258→0 |
| R10 / F08 / A21 / A22 | 关闭（长客户 UNKNOWN） | T7 + T8 复跑：普通 skip 可选样本；必需缺根 **fail** |
| R11 / F11 / A19 / A20 | 关闭 | T5：默认 time；handoff 保留方法；lock 比 before 快照 |
| R12 / A23 / A24 | 分层 | 见 §5；hints/quickref 已同步，无 schema/revision 用户词 |

`_collect_safe()` 仍有展示用 `except Exception: return {}`。空 `{}` 不能当成功
commit（T3/T4 已钉）。apply/commit 失败回滚并 `acknowledged`。未把该 catch
改成提交成功路径。

## 4. 待证横展（不可默默消失）

| 项 | 结论 | 检查边界 |
| --- | --- | --- |
| Batch probe 完成误计用户配置 | **未复现** | pending 行 `QTimer.singleShot(0, _on_probe_finished)` 不发 `userSourceAdded`；无已选信号时无 `selectionChanged` |
| 偏好恢复误计用户配置 | **未复现** | `_restore_panel_prefs` 在引导接线之前完成，打开后仍是 start hint |
| 程序 `apply_params` / `apply_signals` / `apply_files` / `apply_sources` | **复现并修复** | 通用 `changed` 会进 `_on_user_configuration`；用已有 `_applying_preset` 短事务 `_suspend_user_configuration` 包住 |
| 成功导入方案 | 仍计用户配置 | `apply_preset` 成功后 `_guidance_engaged = True` |
| 取消/失败导入 | 不计 | 空路径、缺文件 JSON 后仍是 start hint |
| 自绘禁用漏网 | **复现并修复** | T6：effective enabled + 共享 token；祖先锁 |
| 投影当意图（时间） | **复现并修复** | T1：无编辑不回写；非法不 interpret |
| 新持久化状态未入 dirty | **复现并修复** | T4：`preset_committed` |
| 不完整身份（槽来源 / 时间轴） | **复现并修复** | T3 `source_payload`；T2 轴修订 |

## 5. 平台与集成门禁

| Gate | 状态 | 命令/说明 |
| --- | --- | --- |
| 时间/预设/dirty/hints/help/边界/FileData | **PASS** | `462 passed, 1 skipped`（约 79 s）。含 `test_frf_time_range_surface.py`、`test_hints.py`、`test_help_content.py`、state-ownership / lambda / QSS / QSettings |
| Batch + 几何 + 中性规划 + 普通 ZFD | **PASS**（修前提后） | 初跑 `591 passed, 3 skipped, 2 failed`：288 列 1 px 字宽 / 71 px 列起点。前提修正后 `test_batch_method_buttons.py` + compact + 目标策略 **110 passed**；其余 Batch 文件未再改产品，复用同快照绿 |
| ZFD 必需缺根 | **PASS（fail 不是 skip）** | `TRACELAB_REQUIRE_ZFD_CORPUS=1` 且未设 ROOT：`test_zfd_corpus_*` 两条 `pytest.fail` |
| Cocoa 禁用像素 | **PASS（复用 T6）** | `QT_QPA_PLATFORM=cocoa`，DPR 2.0；选中预设卡启用 258 个 `#0b73e7`，祖先禁用后 0 |
| 完整五方法前台 walkthrough | **UNKNOWN** | 未做用户级 TraceLab 连算/切 View/保存重开整段 |
| 长轴/ColorBar/hover 边缘 | **未为本轮重开** | 本轮未改轴 gutter / hover owner；沿用 review 窗口既有绿，不作新视觉验收 |
| Windows native / Fusion / frozen | **UNKNOWN** | 无 Windows 机、未打冻结包 |
| 长客户 ZFD | **UNKNOWN** | testdoc 仅六份短样本；合成小时级不能代替现场文件 |
| 全量 pytest | **未跑** | 本轮是有范围的逻辑修复，不满足全量例外四条件 |

`git diff --check`：通过。无新增 `.connect(lambda`。未扩大
`test_main_window_state_ownership.py` 白名单。未改 root `conftest.py`。
未改 `APP_VERSION`。

### T8 发现性文案

| 面 | 内容 |
| --- | --- |
| hints | `analysis.range_invalid_keep`、`preset.target_axis_dot`、`preset.slot_source_note`、`batch.count_pending`、`batch.disabled_keeps_value`；宽均 ≤18 |
| quickref | 分析页「全部」、黄点/目标基准/槽位再加载、有效目标数量、禁用保值 |
| 帮助 HTML | 四份分析指南与使用说明已有「全部」/草稿表述，本轮未改版本扇出 |

## 6. Lesson

`scripts/lessons/check.py --status`：`lesson_required=False`。
未 promote 新条目。已有规则覆盖投影/禁用自绘/合成 fixture 供应。
用户 lessons INDEX 已脏，本次不当记忆更新，未改 INDEX。

## 7. 剩余门禁

发布或合并验收前仍需：Windows Full/Lite 冻结包上的时间范围、预设跨槽、
Batch 首显与禁用；本机前台五方法 walkthrough；若拿到原始长客户 ZFD，单独
跑 corpus 并记录。那些通过之前，不能把本报告写成发布完成。

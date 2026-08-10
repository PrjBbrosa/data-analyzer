# 近两日交付评审：来源隔离 · FRF · 批处理 UI（2026-08-09 ~ 08-11）

- 评审日期：2026-08-11
- 评审 HEAD：`777135c8`（分支 `codex/analysis-view-source-isolation-pilot`，领先 `main` 9 个提交）
- 评审范围：2026-08-09 以来的全部 38 个提交，分三条工作线；含用户指定的
  `2026-08-11-analysis-view-source-isolation-final-acceptance.html` 最终验收文档复核
- 评审方法：逐 Finding 代码核实（非复述文档）、几何回归二分定位（临时 worktree 实测
  5 个提交点）、本机两进程测试复跑、既有三份 Grok/Codex 评审文档交叉对照
- 性质：独立复审。除本报告与既有文档外未修改任何产品代码

## 1. 结论先行

**三条线的工程质量整体是高的**：每条线都有 spec/plan、RED→GREEN 测试纪律、lesson
沉淀和真机验证意识；Grok 评审指出的 6 项 Finding 全部被 Codex 真实修复（我逐项到代码
核实，不是对文档打勾）；FRF 数值核心此前已被逐行独立复验且后续打磨未破坏它。

**同意最终验收文档的核心结论**：允许受限试运行，暂不宣布 Stage 1 正式全量验收。
其证据边界（A17 拖拽手势未验真、Batch 既有红项）陈述诚实，未发现夸大。

需要压下去的三个真实问题（详见 §5 清单）：

1. **Batch 两条几何契约测试漏同步 + BatchSheet teardown 崩溃簇**——注意：相对
   2026-08-08 的全绿基线（`3fd691a8`），这些是**本周期 UI 打磨引入的回归**，不是
   历史债。本次评审已把两条几何红项二分定位到具体引入提交（§4.2）。
2. **v7.9.7 在 FRF 发布 gate（O6）未闭合的情况下完成了版本发布动作**——Windows
   frozen 冒烟仍是 UNKNOWN/UNVERIFIED，macOS 长任务取消/计算中关窗未补测（§3.3）。
3. 仓库全量套件已连续多日**不是全绿**，CLAUDE.md 记载的基线（v7.9.5 全绿）已失效，
   继续放着会让后续改动无法用"动手前记失败数"的纪律自证清白。

## 2. 线 A：分析 View 来源隔离试点（当前分支）

### 2.1 链路

```
74f00a3b spec/plan + schema 7 + 纯 helper
29e5e2fa 主 wiring（Tasks 3–6）
6f431ed0 degraded save guard + 复制语义
9fec2ec2/a08afe3e 测试迁移（其中 9fec2ec2 夹带了生产改动 → Grok F2 根因）
   ↓ Grok 评审：NO-GO（3×P1 + 2×P2 + Task10/前台/性能 gate 未执行）
ca5cf843 修复 F1–F5
9ed578df 模式进入合同测试改为 state+live 双断言
   ↓ Task 10 状态矩阵 + 性能门禁 + macOS Cocoa 前台
777135c8 收尾 R1/R2 + 最终验收报告
```

### 2.2 Grok Finding 逐项代码核实（本次评审独立确认）

| Finding | 修复核实 | 落点 |
| --- | --- | --- |
| F1 detach 后画布 stale（P1） | ✅ 已修。detach 与通道删除两条路径都补了 `_render_analysis_view_from_cache`，空 Pane 走共享清图路径，不触发全局 cache 失效 | `_channel_scope_mixin.py:245-252`、`window.py:3662-3669` |
| F2 FFT 模式进入覆盖目标参数（P1） | ✅ 已修。`_on_mode_changed('fft')` 改回 `apply_params=True`；`_enter_fft_mode` 从 `_capture_active_analysis_view`（全量反写）收窄为 `_capture_analysis_sources`（只同步导航勾选→焦点 pane 来源）。测试补齐 state serialization + live 控件双断言 | `window.py:1516-1529`、`window.py:1252-1262` |
| F3 exact-X/overlay 依赖漏索引（P1） | ✅ 已修。`_append_time_persisted_uses` 把 exact-X 轴来源、overlay primary、时域 FRF signature input/output 全部纳入依赖索引，与 cleanup 遍历同一套 persisted refs | `analysis_source_scope.py:54-113` |
| F5 候选树可点击外观（P2） | ✅ 已修。第三列 header 按角色切换（显示/来源/移出），`analysis_candidates` 剥离 `ItemIsUserCheckable`，rebuild 后重放 chrome 防止回退 | `channel_tree.py:1225-1247`、`:752-757` |
| F6 物理组关闭非原子（P2） | ✅ 已修。`file_group_close_requested` 单信号聚合整组 fids，`_close_files` 一次依赖汇总 + 单次确认，确认后逐 fid `force=True` 关闭（不可能部分成功），取消则全保留 | `file_navigator.py:502-521`、`window.py:2172-2205` |
| F4 gate 未执行（P1） | ✅ 已补。Task 10 矩阵（250 次切换零漂移零提交）、性能门禁两条 p95 全过、macOS Cocoa 前台 8 张截图 + 隔离 QSettings，A1–A18 台账成文 | 验收报告 §3–§7 |

本轮验收新增的 R1（dB reference 程序化 apply 冒充用户编辑 → 冷缓存提交计算）与
R2（项目重开后隐藏时域恢复覆盖分析 owner）两处修复也已核实：

- R1：`_on_db_reference_value_edited` 增加 `_applying_analysis_view` 早退
  （`window.py:2098-2107`）；Auto 解析路径本就 `blockSignals`（`_analysis_mixin.py:886-890`），
  两条程序化路径现在都有护栏。配套测试 `test_order_view_switch_with_cold_cache_does_not_submit_worker`。
- R2：`_apply_active_view` 只在可见模式为 `time` 时投影时域控件（`_view_mixin.py:220-238`），
  非时域模式下时域恢复完全不碰共享 navigator。配套测试
  `test_open_project_keeps_analysis_empty_owner_after_time_view_restore`。

### 2.3 验收文档本身的复核

- Task 10 矩阵、性能对比（candidate p95 +2.27%、projection p95 8.53ms < 53.2ms 门槛）、
  Batch 红项在 `1617b2d0` 干净 worktree 复现的归因过程——方法论成立，证据可追溯
  （`.state/analysis-source-isolation-pilot/`）。
- "保存动作捕获 live 派生展示参数，先锁路由状态、再以保存后状态为重开 oracle"的处理
  是对的，不构成放宽断言。
- A17 标 PARTIAL（前台拖拽手势因 Qt `QDrag` 嵌套事件循环无法用系统级工具自动化）
  是诚实的边界声明；对应状态合同已有 Task-10 矩阵与 focused tests 双重自动化覆盖。

### 2.4 线 A 剩余点

1. `tests/ui/test_main_window_smoke.py::test_entering_fft_mode_resolves_auto_db_reference_for_checked_channel`
   仍手动调用 `w._enter_fft_mode()` 模拟二次进入——Grok 修复顺序第 6 条（"恢复真正的
   自动 FFT entry 测试"）未完全落实。Stage 1 语义下勾选发生在进入之后，正确的合同应是
   "勾选变化本身触发 dB reference 解析"，而不是手动重放模式进入内部方法。
2. `set_projection_role` 无早退：角色未变时每次仍全树 `setFlags` + 刷新图标
   （`channel_tree.py:1179-1196`）。这是 projection p95 从 2.98→8.19ms（×2.75）的
   主要嫌疑。绝对值远低于门槛，但一行 `(role, editable)` 变更检查即可拿回大半。
3. Stage 2（unresolved/relink）未实现——全局明确关闭即清引用，验收文档已如实声明。

## 3. 线 B：FRF 系统辨识（c1bea5fa → 36f79938，已随 v7.9.7 发布）

### 3.1 已有基础（此前独立复验，本次交叉确认仍有效）

`2026-08-09-frf-post-implementation-review-and-optimization.md` 已对数值核心逐行
复验：H1/H2/相干定义、density scale、单边倍增边界（DC/Nyquist）、periodic 窗语义、
flattop 系数、`nperseg<2` 阻断、溢出 fail-closed、分段 unwrap 不跨 NaN——SciPy parity
23 条真实执行全绿。O0–O5 六项优化已全部提交落地（log 轴 1-2-5 降级刻度、Inspector
有效事实区 + warnings、同 pane 条件抢占、spec as-built、游标单位）。

### 3.2 后评审之后的提交（本次评审新覆盖）

- `b6874e30` 交互/轴打磨：H1/H2 语义化下拉 + 集中 tooltip 映射、FRF/频谱统一
  时域同款三态游标、minor grid、网格透明度对齐——有完整 plan 文档与决策记录（D1），
  实现与文档一致。
- `36f79938` 注释功能：复用 FFT/heatmap 的共享 `RemarkArtist`/`RemarkInteraction`
  契约，FRF 特有部分只有最近物理频率采样选择 + log 轴 Hz 标签；新结果与显示参数
  变化时正确清除旧注释；命中测试有像素容差。实现干净，没有第二套注释系统。
- `49fc0b04` Batch FRF 通道选择统一、`0b705f98` 条件抢占（`_pending` 空 + `is_running`
  双判据，含真线程用例）——均已核实。
- **阶跃/FRF 边界守住**：FRF 代码中无阶跃指标混入（约束：阶跃响应指标不并入频响，
  两者只共享指令分段器）。

### 3.3 ⚠️ 主要发现：发布 gate 未闭合即发版

`36f79938`（08-10 00:03）执行了 v7.9.7 的完整版本扇出（app_meta / README ×2 /
help / user-guide / 两个 build 脚本 / 三个测试契约——扇出面本身同步无遗漏），**但
后评审 O6 定义的两个发布 gate 至今开放**：

- Windows Full/Lite frozen EXE 冒烟：**UNKNOWN/UNVERIFIED**（仅 source-level 测试；
  实施计划 V3 自记 `未在 fresh Windows frozen EXE 上执行`）；
- macOS 前台补测清单未完成：长任务取消（低频预设 + 大数据）、计算中直接关窗的线程
  残留检查两项无记录。（项目保存/重开含 FRF View 恢复这一项已被线 A 的最终验收前台
  走查间接覆盖。）

后评审明确写了"执行前发布状态保持 NO-GO/UNKNOWN"。**版本号可以先行，但对外不应
声称 v7.9.7 已通过发布验收**；两项 gate 应尽快补齐并在原实施计划 Completion Record
追记。O7（`grab_pixmap` 放大质量）为可选项，未动，维持不做亦可。

## 4. 线 C：批处理与全局 UI 打磨（08-09 ~ 08-10）

### 4.1 总体

这条线纪律良好：全局控件视觉系统、参数面精简（有量化论证的三控件移除 + FRF 范围
收敛）、SegmentedChoice、drop-import、chart-statistics、QMenu 密度（option A 原型
HTML + guard test）、BLF/DBC 主窗对话复用（duck-typed resolver + 可注入测试缝，
无越层 import）——每项都有 spec/原型/守卫测试/lesson 至少其二。

### 4.2 ⚠️ 两条几何契约测试漏同步（本次评审二分定位到引入提交）

| 红项 | 现象 | 引入提交 | 定性 |
| --- | --- | --- | --- |
| `test_batch_signal_picker.py::test_picker_display_stays_single_line_and_inside_narrow_host` | 期望 height 38，实际 32 | `d677718d`（08-09 20:57 unify frf and batch control layout） | 产品侧**有意**把折叠 picker 并入共享 32px 基准轨（`_DISPLAY_HEIGHT = CONTROL_HEIGHTS["base"]`，注释明确），漏改本测试 |
| `test_batch_input_panel.py::test_target_policy_uses_a_full_width_segmented_choice_at_288px` | 期望 x=72，实际 71 | `9683ac2e`（08-10 00:23 filter 字段共享表单列） | 共享表单列改变标签列宽，漏改本测试 |

二分证据：`79588591` 双绿 → `b6874e30` picker 绿 → `d677718d` picker 红；
`36f79938` input 绿 → `9683ac2e` input 红（临时 worktree 实测）。

修复时的补充核实（§7 Agent 1）：x=72 一项的演进比二分结论更曲折——`9683ac2e`
自己把断言从 71 改到 72 配合当时的共享列改动，其后 `f625cb17` 等提交再次改动同一
`QFormLayout` 的标签度量使实际值回落 71。71 是 QFormLayout 按标签字体度量自动
算出的列宽，无具名产品常量可派生。

**归因修正**：验收文档称这些"在原始基线 `1617b2d0` 已存在，非来源隔离回归"——对
线 A 而言归因正确；但相对 2026-08-08 的全绿基线 `3fd691a8`，它们就是本周期引入的
回归，不能当历史债搁置。修法：确认新几何是刻意定版（两处都有注释/lesson 佐证）后，
更新两条测试期望值，独立小提交。

### 4.3 ⚠️ BatchSheet teardown 崩溃簇

BatchSheet 用例 test body 通过、pytest-qt teardown 访问已删除的 C++ wrapper 报
error，并连锁污染后续用例 setup，共 8 errors（本次全量实测名单）：

- `test_batch_toolbar.py`：`test_sheet_toast_paints_on_the_sheet_not_behind_it` /
  `test_sheet_toast_clears_the_footer_button_row` /
  `test_sheet_toast_falls_back_to_the_host_once_closed`（toast 三连，疑似根因组）
- `test_batch_runner_thread.py`：`test_sheet_run_passes_db_reference_catalog_snapshot_from_parent` /
  `test_sheet_preview_and_result_share_channel_metadata_reference`
- `test_batch_smoke.py`：`test_batch_db_reference_manage_uses_mainwindow_shared_route` /
  `test_pipeline_strip_set_stage_updates_summary`
- `test_blf_batch_import.py`：`test_batch_dbc_is_confirmed_once_and_each_blf_is_read_once`

**定性修正（§7 Agent 2 复现结论）**：验收文档"单独进程运行通过"只对级联的 4 条
setup `AssertionError` 成立；其余 4-5 条 teardown `RuntimeError` **单测单独跑也
确定性复现**（如 `test_sheet_toast_paints_on_the_sheet_not_behind_it` 单跑即
`1 passed, 1 error`）。根因与交错无关：`BatchSheet.__init__` 里 3 处闭包捕获
`self` 的 lambda 信号连接 + 1 处以普通属性存进子控件的 bound method
（`set_disk_paths_handler`），让子控件强引用 sheet 的 Python wrapper；测试的
无 parent `host` 被引用计数同步析构并级联删除整棵 C++ 子树后，wrapper 成僵尸，
pytest-qt teardown 对它 `.close()` 即 `RuntimeError: wrapped C/C++ object of type
BatchSheet has been deleted`。PyQt 对直接连接的 bound method 会绑定 receiver
生命周期、及时释放；lambda 与属性存储则没有这层绑定。已按此修复（§7）。

## 5. 待优化点清单（按优先级）

### P1（应在扩大试运行/下次发版前完成）

1. **Batch 两条几何测试同步**：引入点已定位（§4.2），确认视觉定版后更新期望值，
   两条独立小提交；顺手在提交信息里引用引入提交，恢复全量绿基线的可证性。
2. **BatchSheet teardown 崩溃簇**：定位 3 个用例的 wrapper 悬挂（建议
   `pytest tests/ui -k batch_sheet` + 全量同序最小重放），修 widget 生命周期而非
   给测试加 xfail。8 errors 里 5 条是连锁，修 3 条根因即全消。
3. **FRF O6 发布 gate 补齐**：Windows frozen Full/Lite 冒烟（启动、FRF guide、单次
   FRF、Batch FRF CSV+PNG+manifest、Unicode、取消/关闭）+ macOS 长任务取消与
   计算中关窗两项；完成前对外口径维持"v7.9.7 发布验收未闭环"。
4. **CLAUDE.md 基线段落更新**：版本号 v7.9.5 → v7.9.7；"两边全绿"基线改为当前
   实况（主体 2 failed + 8 errors 及其归因链接），否则"动手前记失败数"纪律失效。

### P2（试运行期间并行）

5. **A17 拖拽手势前台证据**：受限试运行期间重点人工观察拖入→角色选择→局部
   detach→明确级联四步文案与行为，出现一例错误立即收缩范围（验收文档建议，维持）。
6. **`set_projection_role` 无变化早退**：角色与可编辑性未变时跳过全树 flags 重放，
   预期拿回 projection p95 的大部分增幅（2.98→8.19ms）；改动一行判据 + 保留
   rebuild 后显式重放路径。
7. **FFT 模式进入 smoke 合同保真**：去掉手动 `_enter_fft_mode()` 重放，改为断言
   "attach + 勾选事件链自然触发 dB reference 解析"，防止真实事件链回归被遮蔽。
8. **参数面精简 A11 视觉验收**：spec 自记"macOS 前台视觉验收待单独执行"；若线 A
   最终验收的五模式走查未覆盖 Inspector 简化后的布局细节，补一次截图证据。

### P3（排期即可）

9. **Stage 2 unresolved/relink**：全局关闭现在即清引用；按 spec 计划推进，推进前
   保持"不承诺自动重连"的文案现状。
10. **组关闭的重复反馈**：`_close_files` 逐 fid `_close` 会连发多个 toast 与多次
    `_reset_plot_state`；聚合为单条"已关闭 N 个来源"提升观感（纯外观，不影响原子性）。
11. **FRF O7**（`grab_pixmap` 放大质量）：维持后评审判断——先核对其他 canvas 约定，
    不值得单独引入新渲染路径。
12. **合入 main 决策**：分支领先 main 9 提交、无落后。按验收建议先跑受限试运行，
    GO 后合入；期间 main 上若有并行改动，合入前重放一次聚焦切片。

## 6. 本次评审执行的验证

| 项目 | 结果 |
| --- | --- |
| 两条 Batch 几何红项 @ HEAD | 复现（2 failed / 103 passed） |
| 几何回归二分（5 个提交点，临时 worktree） | 引入点锁定 `d677718d` / `9683ac2e` |
| `test_batch_blf_dbc_context.py` 单独进程 | 5 passed（teardown 簇不复现，符合交错定性） |
| `tests/acquisition_ui` 单独进程 | 355 passed, 4 warnings, 7.97s |
| 主套件全量 `--ignore=tests/acquisition_ui` @ `777135c8` | **5914 passed, 9 skipped, 3 deselected, 2 failed, 8 errors**（486.19s）——与验收报告数字一致，红项即 §4.2/§4.3 清单 |

## 7. 优化执行记录（2026-08-11 当日追记）

§5 清单中可自动化的 5 项已由并行 agent 实施完毕（改动均在工作树、未提交），
本人逐 diff 复核通过：

| 项 | 对应 §5 | 改动 | 聚焦验证 |
| --- | --- | --- | --- |
| 几何测试同步 | P1-1 | height 断言改从 `SignalPickerPopup._DISPLAY_HEIGHT` 派生；x=71 保留字面量 + 来源注释（无具名常量可派生），断言语义未放宽 | 105 passed |
| BatchSheet teardown 根因修复 | P1-2 | `sheet.py`：3 处 lambda 连接改直接 bound method；`set_disk_paths_handler` 改 `weakref.WeakMethod` 闭包（新增 `_weak_bound`）。纯产品侧，零测试改动，未用 xfail/skip | 4 文件组合 99 passed（0 error）；逐文件单跑均绿 |
| projection chrome 早退 | P2-6 | `set_projection_role` 按 `(role, checks_editable, visibility_available)` 签名早退；`add_file` 重建路径不经缓存不受影响；兼容 shim `set_time_visibility_available` 同步缓存防陈旧态。+3 条防回归测试 | 76 passed |
| FFT smoke 合同保真 | P2-7 | 确认自然链存在（`channels_changed → _ch_changed` fft_sources 分支同步调 `_resolve_and_apply_db_reference`，window.py:2737），删除手动 `_enter_fft_mode()` 重放 | smoke 全文件 123 passed |
| 组关闭反馈聚合 | P3-10 | `_close` 增 `notify` 仅关键字参数（默认 True，既有调用点零变化）；`_close_files` 单成员组保留带文件名 toast（普通单文件关闭也走此路径），多来源组聚合为 1 toast + 1 statusBar + 1 次 `_reset_plot_state`（读实现确认幂等，与 `close_all()` 先例一致）。+2 条测试 | 75 passed（含状态所有权棘轮） |

未自动化处理（维持 §5 原状）：P1-3（O6 需真机 Windows frozen + macOS 前台手工）、
P2-5（A17 拖拽手势人工观察）、P2-8（A11 视觉验收）、P3-8/9/11/12。

修复后两进程全量（实测）：主体 **5925 passed, 9 skipped, 3 deselected, 0 failed,
0 errors**（434.65s）；`tests/acquisition_ui` 单独 **355 passed**（7.87s）。
全量重回两边全绿。CLAUDE.md 基线段落已同步更新（v7.9.7 / 新数字 / teardown
定性修正）。§5 清单中 P1-1、P1-2、P2-6、P2-7、P3-10 就此关闭；P1-4（CLAUDE.md）
亦已完成；其余各项维持开放。
| 阶跃/FRF 边界 grep | 干净 |
| v7.9.7 版本扇出一致性 | app_meta/README×2/build 脚本×2 全部 7.9.7，无漏 |

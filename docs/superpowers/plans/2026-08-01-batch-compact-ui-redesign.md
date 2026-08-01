# 批处理紧凑 UI 与单次分析接线 —— 分批执行计划

> **当前状态：仅计划，未执行。** 本计划的产品与视觉契约见
> `docs/superpowers/specs/2026-08-01-batch-compact-ui-redesign-design.md`（下称 Spec），
> 最终 UI 对标
> `docs/analyzer/ui-prototypes/2026-08-01-batch-compact-ui-redesign.html`（下称 HTML）。

**Goal：** 将现有批处理三栏对话框重构为 HTML 所示紧凑布局，消除重复/无效设置，
共享单次分析预设，修正各方法的区间与 dB 接线，并以真实 Qt 离屏矩阵完成最终确认。

---

## Global Constraints

- 未获得新的执行授权前，不修改产品代码、测试或运行实现命令。
- 正式开工前从包含本 Spec/Plan/HTML 的干净 commit 或独立 worktree 开始；当前 checkout
  的无关未提交文件不得被纳入实现提交。
- TDD-first：每个行为先落红测并保存 RED nodeid/原因，再做最小实现。
- HTML 是可见 UI/操作基准，Python model/runner/validation 是逻辑事实；两者冲突时按 Spec
  的明确决策解决，不能照搬 HTML 假数据。
- 不并行修改同一个文件；每个 Task 结束先跑其目标测试，再进入下一个 Task。
- `BatchRunner` 保持 GUI-free；不得把 QSettings、QWidget 或文件对话框下沉到 `batch.py`。
- `validate_outputs()` 继续是 output 合法性唯一权威；`normalize_batch_params()` 继续是
  method 字段归属权威。
- 最终离屏截图矩阵是最后一个硬 Gate：执行者必须亲自打开图片检查，不能只转述测试。
- HTML 对标允许的微调仅限 Qt 字体度量、scrollbar、焦点/可访问性和真实参数数量；偏差
  必须在 evidence 中逐条说明。

## 实施依赖图

```text
Batch 0 契约红测
       └──> Batch 1 共享预设
              └──> Batch 2 Input/分组
                     └──> Batch 3 区间/Output
                            └──> Batch 4 Sheet/状态栏
                                   └──> Batch 5 集成迁移
                                          └──> Batch 6 离屏终验
```

Batch 1–4 会交叉修改 `analysis_panel.py`、`method_buttons.py`、`output_panel.py` 和
`sheet.py`，必须按编号串行实施；不得为追求并行而拆出两套临时状态或制造红态中间提交。

## Batch 0：冻结现状与红测入口

### T0.1 固定 HTML 对标事实

**Files：**

- `docs/analyzer/ui-prototypes/2026-08-01-batch-compact-ui-redesign.html`（只读基准）
- `tests/ui/test_batch_compact_contract.py`（新建）

**步骤：**

- [ ] 用测试锁定 BatchSheet 可支持 1080×760、1440×900，主骨架存在 toolbar、pipeline、
  三个独立 scroll pane、footer。
- [ ] 先写红测：三栏 stretch=29:39:32；默认可见树不含 `BatchTaskList`；Input 主区不
  出现大文件列表和时间范围；Output 不出现高级格式/恢复控件。
- [ ] 先写红测：时域无 dB/源区间，FFT 有源区间+dB，FFT vs Time/阶次无源区间但有 dB。
- [ ] 先写红测：BatchSheet `get_preset()` 在四种方法下满足 Spec §4.5 与 §5.2。

**RED Gate：** 新测试应因当前等宽三栏、大文件列表、Input 时间范围、advanced output、
TaskList、硬编码预设或错误 `time_range` 语义而失败；记录准确 nodeid，不接受“测试没找到
控件”导致的假红。

### T0.2 锁定现有逻辑基线

**只读检查范围：**

- `mf4_analyzer/ui/drawers/batch/{sheet,input_panel,analysis_panel,method_buttons,output_panel,task_list}.py`
- `mf4_analyzer/ui/inspector_sections/{presets,contextual_fft,contextual_fft_time,contextual_order}.py`
- `mf4_analyzer/{analysis_presets,batch,batch_recipe,batch_validation,batch_preprocess,batch_preset_io}.py`

**步骤：**

- [ ] 记录 `BatchSheet` 的 method/params/output/progress/run/cancel 信号图。
- [ ] 记录单次预设三个 kind 的 QSettings key、内建回退、custom slot 和旧格式兼容。
- [ ] 记录当前 `time_range` 在 `batch_preprocess` 对所有方法生效的 RED 证据。
- [ ] 记录 CSV/XLSX、PNG、auto_number、manifest/resume 的后端能力边界。

**产出：** `docs/superpowers/reports/2026-08-01-batch-compact-ui-baseline.md`，只写当前事实、
目标测试 nodeid 和实现前截图路径，不宣称修复。

## Batch 1：共享单次分析预设与 dirty 状态

### T1.1 抽取共享预设槽仓库

**Files：**

- `mf4_analyzer/ui/analysis_preset_slots.py`（新建，名称可按现有 UI 包规范微调）
- `mf4_analyzer/ui/inspector_sections/presets.py`
- `mf4_analyzer/analysis_presets.py`（仅在需要共享常量时）
- `tests/ui/test_analysis_preset_slots.py`（新建）
- `tests/ui/test_inspector.py`
- `tests/ui/test_task6_preset_guard.py`

**红测：**

- [ ] `fft` / `fft_time` / `order` 槽 1–3 的 builtin fallback、override name+params、rename、
  reset 与当前 `PresetBar` 完全一致。
- [ ] slot 4 custom 的 empty/save/rename/clear 兼容。
- [ ] legacy flat dict 仍可读，下一次写回升级为 envelope。
- [ ] 仓库写入后发出 kind/slot 变更信号，两个 consumer 无需重新构造即可刷新。

**实现：**

- [ ] 把 `_key/_read/_write/_delete/default/builtin` 的持久化职责移到共享仓库。
- [ ] `PresetBar` 通过仓库消费并发变更信号，保持现有单次分析 UI 和 QSettings key 不变。
- [ ] 仓库只依赖 QtCore/QSettings 与纯 preset catalog，不依赖 QWidget 或 BatchRunner。

**Gate 1A：** 单次分析现有 preset 测试全绿，新仓库 round-trip 全绿；真实 QSettings key
没有迁移或复制。

### T1.2 Batch AnalysisPanel 改用真实槽

**Files：**

- `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `tests/ui/test_batch_method_buttons.py`
- `tests/ui/test_batch_preset_sync.py`（新建）

**红测：**

- [ ] 把单次 FFT 槽 1 重命名为“测试”并修改参数，批处理不重开应用即可显示“测试”，
  点击后应用相同 patch。
- [ ] `fft→fft_time→order_time` 分别读取 `fft/fft_time/order`，不得串槽。
- [ ] `time` 隐藏预设区。
- [ ] 推荐和 applied 分离；仅推荐时不显示“已应用”。
- [ ] 应用槽后修改其拥有字段，所有 card 清除 active，状态变为“已修改·未匹配预设”；
  改回原值也不自动重选。
- [ ] 应用 guard 不产生一次伪 dirty，也不漏最终 `paramsChanged`/pipeline recompute。

**实现：**

- [ ] 删除批处理硬编码 `频率/均衡/时间` 名称和第二份 builtin 查找逻辑。
- [ ] 建立 `method -> kind` 显式映射，四张卡读取共享仓库；空 custom 按 Spec 处理。
- [ ] 以“槽实际拥有的规范化 patch”建立 applied snapshot 和 dirty 比较。
- [ ] BatchSheet show/方法切换/`从当前单次同步`/仓库 signal 均触发刷新。

**Gate 1B：** preset sync/dirty 全绿；单次分析 preset tests 不回归；批处理与单次同一槽的
name、params 深比较相等。

## Batch 2：Input 紧凑化与分组波形卡

### T2.1 文件管理器与紧凑摘要

**Files：**

- `mf4_analyzer/ui/drawers/batch/input_panel.py`
- `mf4_analyzer/ui/drawers/batch/file_manager_dialog.py`（新建，或按现有模块拆分规范命名）
- `tests/ui/test_batch_input_panel.py`
- `tests/ui/test_batch_file_manager.py`（新建）

**红测：**

- [ ] Input 主区只呈现一行文件摘要和管理按钮，不直接显示大列表。
- [ ] 管理器打开后使用同一文件模型；增删文件后主摘要、common/partial channel、异常数、
  preflight 立即同步。
- [ ] 已探测行打开/关闭管理器不重复 loader/probe。
- [ ] 1080×760 下 Input 的目标策略、信号和滤波仍可到达。

**实现：**

- [ ] 将现有 `FileListWidget` 迁入/挂接模态管理器，InputPanel 暴露稳定模型级 API，
  不让 BatchSheet 直接穿透新的 dialog widget。
- [ ] 删除主 Input 的时间范围行和文本解析 UI；兼容 preset 迁移留给 Batch 3。
- [ ] 错误/空状态用摘要 badge + 管理器详情表达。

**Gate 2A：** file loader 调用次数、file_ids/paths/source_ids/paths、signal universe 与改造前
一致；主界面文件块高度符合 compact contract。

### T2.2 波形分组卡

**Files：**

- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_method_buttons.py`
- `tests/ui/test_batch_grouping_cards.py`（新建）

**红测：**

- [ ] 三卡互斥，内部值分别是 `none/source/channel`；可见标签是“按信号”而非“按通道”。
- [ ] 卡片 mini-waveform 的结构快照能区分 F×S 单项、固定 F 多 S、固定 S 多 F。
- [ ] none 禁用 layout，source/channel 启用 overlay/subplot。
- [ ] 4 源×3 信号摘要分别为 12/4/3 张；变更文件或信号后实时重算。
- [ ] `get_params/apply_params` 与旧 recipe `render_group_by/render_layout` 双向兼容。

**实现：**

- [ ] 用小型绘制 widget 或固定 SVG/icon path 绘制波形；不得启动 pyqtgraph canvas 或
  用真实数据造成额外开销。
- [ ] F/S 标签、颜色、图框和张数说明按 HTML/QSS 对标。
- [ ] 只替换 UI selector，不改 `group_render_tasks()` 或 runner schema。

**Gate 2B：** grouping widget tests 绿色；三种真实 scope 的 `BatchRunner.preview_outputs()`
与卡片摘要使用同一任务事实，不出现 UI 计算和 runner 计算分叉。

## Batch 3：区间、dB 与固定 Output 接线

### T3.1 建立方法拥有的区间规范

**Files：**

- `mf4_analyzer/batch_recipe.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/batch_preset_io.py`
- `tests/test_batch_recipe.py`
- `tests/test_batch_preset_io.py`
- `tests/ui/test_batch_source_interval.py`（新建）

**红测：**

- [ ] time：X auto 时无 `time_range`；手动 X=[a,b] 时 canonical preset 只有一个
  `time_range=[a,b]`，显示范围同值。
- [ ] fft：Analysis 源区间写 `time_range`；Output X 频率范围不覆盖它。
- [ ] fft_time/order_time：UI 无源区间，导入旧 `time_range` 后 canonical recipe 移除它。
- [ ] 方法切换后不兼容旧范围不能通过 `_base_params` 或 snapshot merge 复活。
- [ ] preflight 与 runner 获取的是同一个 canonical preset。

**实现：**

- [ ] 用一个 method-aware adapter 负责 `time_range` 的 UI 投影和 recipe 归属；删除
  `InputPanel.time_range()` 作为 BatchSheet 权威入口。
- [ ] `normalize_batch_params()` 对 `fft_time/order_time` 明确移除已知 `time_range`；对 time
  和 fft 保留。
- [ ] preset import 按 Spec §7.2 迁移并生成一次性提示。
- [ ] 保持 `batch_preprocess` 通用裁剪能力；通过 canonical recipe 保证不适用方法传入
  `None`，避免在数值层硬编码 GUI 方法例外。

**数值行为 Gate：** 用同一长时域输入证明 FFT vs Time/阶次即使导入旧 range 也消费全部
有效样本；time/FFT 指定 range 则只消费范围内样本。此处需验证 preprocess effective facts，
不能只断言控件隐藏。

### T3.2 时域移除 dB

**Files：**

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/batch_recipe.py`（如 method 清理需要）
- `tests/ui/test_batch_output_panel.py`
- `tests/test_batch_recipe.py`

**红测/实现：**

- [ ] time 下 dB 整行（label、editor、来源说明、菜单按钮）都不可见且不占 geometry。
- [ ] time `get_preset()` 不含 `db_reference/db_reference_mode`；导入旧值后丢弃。
- [ ] 三种谱方法显示并正确 round-trip dB；方法来回切换不丢谱方法当前值。
- [ ] dB catalog/store 仍由现有 shared resolver 解析，不另写单位逻辑。

**Gate 3B：** UI geometry + recipe 两层均通过；不得只 `hide()` editor 留下空 label/行高。

### T3.3 收缩 OutputPanel 可见面并固定交互式输出

**Files：**

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/batch_preset_io.py`
- `mf4_analyzer/batch.py`（仅 XLSX 大表写入必要变更）
- `tests/ui/test_batch_output_panel.py`
- `tests/test_batch_output.py`
- `tests/test_batch_preset_io.py`
- `tests/test_batch_validation.py`

**红测：**

- [ ] 可见 UI 只有目录、两复选框、固定事实、坐标和适用 dB；不存在高级设置/恢复 section。
- [ ] `get_outputs()` 明确产生 xlsx/png/1920×1080/auto_number/write_manifest=true/
  resume=none；两复选框只改变 export_data/export_image。
- [ ] 导入 csv/svg/pdf/其他尺寸/overwrite 等旧方案后 UI 和导出的新方案都是固定值，并只
  出现一次转换提示。
- [ ] 两复选框全关由 `validate_outputs()` 阻止。
- [ ] >1,048,575 数据行（加一行表头）的 XLSX 原子写拆为稳定多 sheet，回读行数/顺序/
  列名无损；中途异常不发布半个 workbook。

**实现：**

- [ ] 删除/不构造 output settings 展开区、resume/retry 按钮及相关 GUI signals。
- [ ] 非可见 DPI/background/line_width 读取 canonical `BatchOutput`/renderer default，不在
  OutputPanel 复制常量。
- [ ] 后端 CSV/validation/resume 兼容 API 保留；只固定 BatchSheet UI 边界。
- [ ] XLSX writer 使用 openpyxl/pandas writer 在同一 atomic temp 文件内分 sheet。

**Gate 3C：** output/preset/validation/atomic write 目标测试全绿；一个真实小任务只产生
`.xlsx`/`.png`/manifest，无 `.csv/.svg/.pdf`。

## Batch 4：三栏组合、状态栏与运行生命周期

### T4.1 按 HTML 重组 BatchSheet

**Files：**

- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/ui/drawers/batch/pipeline_strip.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_smoke.py`
- `tests/ui/test_batch_compact_contract.py`

**红测/实现：**

- [ ] toolbar 50 px、pipeline 62 px、footer 54 px；内容三栏 29:39:32。
- [ ] 三个 pane 独立纵向滚动，固定区域不随滚动移动。
- [ ] toolbar 文案更新为 `从当前单次同步/导入方案…/导出方案…`。
- [ ] pipeline 只投影 file/signal、method/group-or-preset、XLSX/PNG facts。
- [ ] 1080×760 和 1440×900 sizeHint/minimumSize/scrollbar 行为稳定。

### T4.2 移除可见 TaskList，接入紧凑状态栏

**Files：**

- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/ui/drawers/batch/batch_status_bar.py`（新建或内聚到 sheet）
- `mf4_analyzer/ui/drawers/batch/task_list.py`（默认不再实例化；删除前先扫引用）
- `tests/ui/test_batch_runner_thread.py`
- `tests/ui/test_batch_smoke.py`
- `tests/ui/test_batch_status_bar.py`（新建）

**红测：**

- [ ] idle-valid/idle-invalid/running/cancelling/completed/blocked 六种状态的文本、进度、按钮
  enabled 状态符合 Spec §6。
- [ ] progress event 的 task_index/total/stage 投影正确；重复/乱序终态不让进度倒退。
- [ ] running 请求 cancel 后只请求一次，线程 finished 前不解锁。
- [ ] completed/failed 计数来自 `BatchRunResult`，不由 UI 猜测。
- [ ] 默认 widget tree 无可见 TaskList/输出明细；manifest/log 写入不受影响。

**实现：**

- [ ] 将现有 TaskList 消费的必要进度汇总迁到小型状态 presenter，不复制 runner 状态机。
- [ ] 未运行时 `取消` 关闭；运行中变为请求取消；cancelling 禁用。
- [ ] 移除 Sheet 对 `artifactOpenRequested`、resumeRequested、retryFailedRequested 的默认接线；
  后端能力不删除。
- [ ] `lock_editing/unlock_editing/closeEvent` 统一由 runner thread 生命周期驱动。

**Gate 4：** runner/cancel/smoke/status tests 全绿；运行过程中无 UI 锁死、双启动或提前解锁。

## Batch 5：集成、导入迁移与逻辑一致性

### T5.1 从当前单次同步全链路

**Files：**

- `mf4_analyzer/ui/drawers/batch/sheet.py`
- 单次状态采集实际所在模块（先 `rg "from_current_single|fill_from_current"` 确认）
- `tests/ui/test_batch_toolbar.py`
- `tests/ui/test_batch_preset_sync.py`

**场景：**

- [ ] FFT 单次槽重命名+参数修改→Batch 打开→名称/参数相同→同步当前源/信号→输出仍固定。
- [ ] 时域同步→无 dB、单次当前 X 范围成为唯一 time_range。
- [ ] FFT vs Time/阶次同步带旧 time_range→Batch canonical recipe 丢弃 range。
- [ ] 同步过程只 recompute 一次稳定终态，不留 stale pipeline/preview。
- [ ] 同步后手动改槽拥有参数→applied 清除；改 output directory 不清除。

### T5.2 方案导入/导出兼容矩阵

**Files：**

- `mf4_analyzer/batch_preset_io.py`
- `mf4_analyzer/batch_recipe.py`
- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `tests/test_batch_preset_io.py`
- `tests/ui/test_batch_toolbar.py`

**矩阵：** current canonical、旧 CSV+PNG、旧 PDF/SVG、旧 Input time_range、旧时域 dB、
旧 fft_time/order range、runtime resume fields、未知未来字段。

- [ ] 已知废弃 UI 字段按 Spec 明确迁移/丢弃并提示。
- [ ] 未知未来字段继续遵循现有 conservative normalization，不被无关 UI round-trip 毁掉。
- [ ] export→import→export 的 canonical payload 稳定。

### T5.3 全量逻辑回归

运行目标（实施时按真实文件名补齐，不在本轮执行）：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -p no:randomly \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_toolbar.py \
  tests/ui/test_batch_runner_thread.py \
  tests/test_batch_recipe.py \
  tests/test_batch_preset_io.py \
  tests/test_batch_validation.py \
  tests/test_batch_runner.py \
  tests/test_batch_output.py -q
```

- [ ] 再跑既有 batch 全集合并记录准确 passed/skipped/failed/nodeid。
- [ ] 如默认裸全量仍触发现有 Qt SIGSEGV，单独写 `UNVERIFIED`，不能用目标集合绿色掩盖。
- [ ] `git diff --check`；检查只修改本计划范围文件。

**Gate 5：** 所有目标行为绿色；preflight、pipeline、export preset、runner 四处拿到的 method/
params/outputs 一致。

## Batch 6：最终 Qt 离屏对标（最后硬 Gate）

### T6.1 建离屏状态捕获工具

**Files：**

- `tools/render_batch_compact_ui.py`（新建）
- `tests/ui/test_batch_compact_render.py`（新建）
- `docs/superpowers/verify/batch-compact-ui/`（证据目录）

**工具要求：**

- [ ] 创建临时 `XDG_CONFIG_HOME`/QSettings namespace，不读取或污染用户真实预设。
- [ ] 固定 `QT_QPA_PLATFORM=offscreen`、DPR、字体与窗口尺寸；记录 platformName/Qt/PyQt/
  OS/commit SHA。
- [ ] 用真实 BatchSheet API 注入文件事实、信号、方法、预设、参数、output 和 runner state，
  不通过直接改 label 文本伪造状态。
- [ ] 以精确像素尺寸保存 PNG，并输出 widgets geometry JSON。
- [ ] 生成与 HTML 同尺寸截图的 side-by-side/contact sheet。

### T6.2 截图矩阵

按 Spec §9.3 生成全部状态；最少包含：

- [ ] 1080×760：time/task、time/source、time/signal、file modal、fft applied、fft dirty、
  fft source range、fft_time、order_time、running、blocked。
- [ ] 1440×900：time 总览、fft 总览、running 总览。
- [ ] 输出复选框组合：data-only、image-only、both；both-off 作为 blocked。
- [ ] time 截图无 dB；fft_time/order 截图无源数据区间。

### T6.3 机器几何断言与人工目视

- [ ] 固定行高相对 HTML ≤4 px；三栏分割 ≤6 px，或在 evidence 中明确记录 Qt scrollbar
  的单项差异。
- [ ] 控件/文字不相交、不被裁切；1080×760 所有必需操作可通过各栏滚动到达。
- [ ] active/dirty/disabled/error/progress 视觉状态可区分。
- [ ] 波形卡不读说明也能分辨固定 F/固定 S/F×S。
- [ ] 执行主 agent **实际打开**每张 contact sheet，逐 case 写 PASS/FAIL 与偏差说明。
- [ ] 任一 case FAIL：回到对应 Batch 修复并重新生成完整矩阵；不得只重截失败局部。

**建议执行命令（实施完成后才运行）：**

```bash
ui_state_dir="$(mktemp -d /tmp/tracelab-batch-ui.XXXXXX)"
TMPDIR=/tmp XDG_CONFIG_HOME="$ui_state_dir/config" \
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1 PYTHONPATH=. \
  .venv/bin/python tools/render_batch_compact_ui.py \
  --html docs/analyzer/ui-prototypes/2026-08-01-batch-compact-ui-redesign.html \
  --output docs/superpowers/verify/batch-compact-ui
```

**Gate 6：** 机器几何断言全绿，全部 Qt contact sheet 由执行主 agent 目视 PASS，evidence
绑定待验收 commit。离屏结果与 macOS 前台验收分开记录，禁止把前者表述为后者。

## Batch 7：收尾与交付

- [ ] 跑项目 lessons completion gate；如本次形成可复用风险，按项目流程新增/推广 lesson。
- [ ] 复核 Spec D1–D9 每条有测试与截图证据。
- [ ] 复核 HTML 与最终 Qt 的所有有意微调均有清单，不存在未解释偏差。
- [ ] 复核旧高级 output/recovery/TaskList 不在默认 UI，后端兼容能力仍有测试。
- [ ] 复核没有把用户真实 QSettings、输出文件、离屏临时配置或截图中绝对路径误提交。
- [ ] 最终报告分别列：代码/测试事实、Qt 离屏目视事实、macOS 前台事实、仍未验证项。

## 完成定义

只有同时满足以下条件才可宣称完成：

1. Spec D1–D9 全部实现且目标/批处理回归测试绿色；
2. 单次分析和批处理预设读取同一仓库，名称/参数/dirty 行为有集成测试；
3. 四方法区间与 dB 的 recipe 和真实数值输入行为均正确；
4. 交互式输出固定 XLSX/PNG/1920×1080/auto-number，且 XLSX 无静默截断；
5. 默认 UI 无大文件区、advanced output、恢复 section、TaskList；
6. 1080×760、1440×900 的完整 Qt 离屏矩阵已由执行主 agent 实际打开并逐项 PASS；
7. 未把离屏证据误写成 macOS 前台真机验证。

本文件完成不等于上述实现完成；当前仍处于“计划已写、尚未执行”。

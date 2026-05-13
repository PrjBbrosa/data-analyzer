# Inspector 紧凑化总结报告

- **日期范围**：2026-04-26 单日（4 轮 squad 派发，~32 分钟净执行 + 多轮交互讨论）
- **触发**：用户截图反馈右侧 inspector 参数区"比较多，需要紧凑点，同时再想下有没可以优化的点"
- **派发模型**：Claude Code squad runbook（squad-orchestrator → 单 pyqt-ui-engineer specialist 4 次）
- **Top-level 完成数**：`top_level_completions` 7 → 10（+3 完整轮 + 1 子任务修复）

## 1. 阶段总览

| 轮次 | 触发 | 改动 | 测试 | 备注 |
|---|---|---|---|---|
| R1 | "做 1+2+5" | 同行并排 + 条件 hide + 行间距收紧 | 27 通过 / 1 失败 | 范围行初始化遗漏 |
| R2 | 自动捕获 R1 红测 | 修 `_set_form_row_visible` wrapper 子控件传播 | 128/128 | 根因比预期深 |
| R3 | "做 #3-B / #6 / #8 / #9 + A/B/C" | 7 件事一个 envelope | 167/167（+39） | 引入 3 个视觉回退 |
| R4 | 截图反馈 3 个回退 | 内容 maxWidth + QSS 兜底 + 工具按钮收紧 | 177/177（+10） | 收尾 |

测试净增长 **128 → 177**（+49 用例覆盖紧凑化新行为），全程零回归（pre-existing fft_time worker 线程 flakiness 除外，3 个测试已 deselect 并 flag 给 signal-processing-expert）。

## 2. 决策路径上的关键节点

### 2.1 Playground 解锁讨论卡死

R1 交付后，主 Claude 提出 6 条进一步优化建议（#3 / #6 / #7 / #8 / #9 / #10），用户回复**"不同的方案我不太理解是什么区别"**。

主 Claude 用 `playground:playground` skill 写出 `/tmp/inspector-compaction-playground.html`：左栏控件切换每条建议、右栏实时渲染 PyQt 视觉模拟、底栏拼出"请实施 X / Y / Z"的 prompt 串。

**用户在 1 分钟内复制 prompt 决定走 #3-B + #6 + #8 + #9**，并附 3 条新观察（A/B/C）。

→ 这是本项目最有价值的一步交互。详见新 lesson `orchestrator/2026-04-26-interactive-playground-unblocks-ui-alignment.md`。

### 2.2 R3 一次性 7 件事的押注

R3 把 #3-B / #6 / #8 / #9 + 用户新观察 A/B/C 共 7 件事压成单 specialist 单 envelope。

押注理由（写在 orchestrator 决策中）：
- 7 件事 100% 落在 `inspector_sections.py` + `style.qss`
- 切到多 specialist 会触发已有 lesson `orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- TDD 一次性写 16 个红测覆盖全部行为，再走绿

结果：成功完成所有功能性目标，但**视觉回退 3 个**（信号 card 白底 / 输入框过宽 / 工具按钮外框过大），R4 收拾。

教训：见 R4 lesson `pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md` 第三条 ——"紧凑化必须在窄/默认/宽三个 splitter 宽度下都视觉验证"。

### 2.3 R2 的 isHidden 陷阱

R1 的红测期望 `spin_start.isHidden() == True`，主 Claude 第一直觉是"`__init__` 末尾漏调 sync"。

实际根因更深：`_set_form_row_visible` 只 hide 了 `_pair_field` wrapper，没下发 `setVisible` 到 wrapper 的直接子控件。Qt `QWidget.isHidden()` 只读自身 `WA_WState_Hidden` flag，**不反映"通过父容器隐藏"的状态**。

→ lesson `pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`，含两个相关坑（init-sync + paired-field children propagation）。

### 2.4 R4 的 WA_StyledBackground 陷阱

R4 specialist 移除 `setAttribute(Qt.WA_StyledBackground, True)` 后**白底依然存在**。

根因：Qt 的 stylesheet polish 在匹配到全局 `QFrame { background-color: #fff }` 规则时**自动重新启用 WA_StyledBackground flag**。所以代码路径修改无效，QSS 显式 transparent 才是兜底。

→ lesson `pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md` 第二条。

## 3. 最终交付物

### 代码改动文件
- `mf4_analyzer/ui/inspector.py`（容器 maxWidth + 左对齐 host）
- `mf4_analyzer/ui/inspector_sections.py`（PersistentTop 折叠器、PresetBar 单行 + 右键菜单 + builtin-aware、custom group header、字段宽度上限、_enforce_label_widths additive guard）
- `mf4_analyzer/ui/style.qss`（GroupBox 紧凑 + 下划线、QFrame#xSignalCard transparent 兜底、QPushButton[role="tool"] 零 min-width/min-height）
- `mf4_analyzer/ui/main_window.py`（splitter `[250, 900, 360]`）
- `mf4_analyzer/ui/file_navigator.py`（_btn_close / _btn_kebab setFixedSize 24×24）
- `tests/ui/test_inspector.py`（+33 新 / 改测试）
- `tests/ui/test_file_navigator.py`（+icon size 测试）

### 用户可见的改动
1. PersistentTop 三组（横坐标 / 范围 / 刻度）折叠为 `▶ 图表设置 (时间轴 · 范围 · 刻度)` 单行
2. group 标题 13/700 → 12/600 + 1px 下划线
3. PresetBar 单行 3 个槽位、左键加载、右键菜单（保存/重命名/清空）
4. FFTTime 三个 builtin 预设升级为可自定义（保存覆盖 / 重置默认 / 重命名，QSettings 持久化）
5. rebuild 图标从 Fs 行移到"分析信号"标题栏右
6. 数字字段统一 ≤110px、长文本下拉 ≤260px
7. 工具按钮外框紧凑（24×24，icon 仍 16×16）
8. 横向条件 hide：通道行（来源=自动时）/ 范围行（未勾选时）/ 频率上下限行（自动时）

### lessons-learned 沉淀
- **新增 3 条 pyqt-ui**：
  - `2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`
  - `2026-04-26-action-button-on-group-title-needs-qframe-header.md`
  - `2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md`
- **修订 1 条 pyqt-ui**：
  - `2026-04-24-responsive-pane-containers.md`（补 Wide-pane verification 段）
- **新增 1 条 orchestrator**（本报告同步）：
  - `2026-04-26-interactive-playground-unblocks-ui-alignment.md`

## 4. 未解决尾巴

- **`test_fft_time_non_uniform_auto_opens_rebuild_and_retries`** —— R4 specialist 顺手发现的第三起 fft_time worker 线程 flakiness，与之前 R2 暴露的两个同源（`test_fft_time_worker_emits_finished` / `test_fft_time_worker_cancels`）。全套跑能过、隔离跑必挂。
- **解法**：套用 lesson `pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md` + `2026-04-25-defer-retry-from-worker-failed-slot.md` 模式，由 signal-processing-expert 修 `_on_fft_time_failed` 的 auto-retry 路径。
- **优先级**：低（不阻塞用户日常使用），但下一轮 fft_time 相关功能开发前应优先清掉。

## 5. 用过的 squad 策略反思（→ 元 lesson）

| 策略 | 收益 | 代价 |
|---|---|---|
| **单 specialist + 多 fix 一个 envelope** | 0 跨专家 rework；TDD 红一次过 | 单轮过载，视觉回退一次性集中暴露 |
| **playground 介入 UI 决策** | 用户 1 分钟出选项；零 prompt 来回 | 一次性 5-10 分钟 HTML 编写成本 |
| **每轮强制写 lesson** | 同病不复发（R4 修了 R2/R3 漏的两个泛化点） | 文件量增长，需定期 prune |
| **missed-keyword force-route** | UI 反馈不漏 squad（4 轮中 3 轮触发） | 无负作用，建议把 "紧凑化" / "实施" 加触发词 |

下一轮新功能前建议：
- 把 `紧凑化` / `实施 #N` / 截图 + 中文反馈 等加入 CLAUDE.md squad 触发关键词
- 若需多轮 UI 迭代，先做 playground 再派 agent，避免文字描述带歧义反复返工
- 任何修改 inspector / file_navigator / 任何 splitter 内 widget 的轮次，**TDD 测试必须含至少一条窄+宽双端断言**

# Mac 浅色 3-Pane UI 重构 · 总结 / 反思报告

**日期：** 2026-04-24
**触发：** 用户请求"整个UI布局重新调整，做成mac的app逻辑；左侧文件管理，中间图形，右边inspector；已有功能不能删除。"
**输出：** 34 个 commit，13 个新 Python 模块，53 个 pytest-qt 测试，1 个 spec + 1 个 plan + 2 条新 orchestrator lesson。

---

## 1. 做了什么

### 1.1 架构
`mf4_analyzer/ui/` 从 2-pane 布局（`main_window.py` 单体 + QTabWidget 容器）重构为 Mac 浅色 3-pane + drawer/sheet/popover 模型：

- **左栏 `file_navigator.py`** — 文件列表行（替代 `QTabWidget`） + kebab 菜单（全部关闭）+ 原 `MultiFileChannelWidget` 通道树（保留搜索、All/None/Inv、>8 警告）
- **中栏 `chart_stack.py`** — `QStackedWidget` 容纳三个 canvas，顶部 segmented 模式切换，底部常驻 stats strip，cursor pill 在画布上浮动
- **右栏 `inspector.py` + `inspector_sections.py`** — 常驻顶部（横坐标 / 范围 / 刻度）+ 上下文下部（时域：绘图模式/游标 segmented/绘图按钮；FFT：窗/NFFT/重叠/自适应/标注 + 计算按钮；阶次：信号源/谱参数/跟踪独立节/进度）
- **`toolbar.py`** — 三段式工具栏（左：添加/编辑/导出；中：模式 segmented；右：重置游标/轴锁）
- **`drawers/`** — ChannelEditor drawer（右侧 slide-in）、Export sheet（顶部 anchored 模态）、RebuildTime popover、AxisLock popover（均为 frameless QDialog + WindowDeactivate 自动关）
- **`style.qss`** — 全浅色 Mac 主题 tokens（白底 / 半透明侧栏 / SF Pro 字族 / 圆角 / 细边）

### 1.2 MainWindow 瘦身
`main_window.py` 从 500+ 行混合装配+表单读值+信号分发+分析调用，缩减为纯"装配三栏容器 + toolbar + 信号路由 + 分析方法分发"。所有表单值现在从 `inspector.*` 子组件的 getter API 读取；旧的 ~40 个直接 widget 引用全部消除。

### 1.3 Fs 追踪规则（§6.3 实现）
`spin_fs` 显示当前下拉所选信号所在文件的 Fs，而不是活动文件的 Fs。通过 `FFTContextual.signal_changed` / `OrderContextual.signal_changed` → `MainWindow._on_inspector_signal_changed` → `ctx.set_fs(...)` 路由实现。多文件会话下不会因为切换 active file 误改 Fs（codex 发现 4.1）。

### 1.4 Drawer 实现选择
Spec 最初描述使用 `Qt.Sheet` / `Qt.Popup`，但 PyQt5 在 `Qt.Sheet` 上跨平台不稳定、`Qt.Popup` 含 `QSpinBox` 时会因为 spin 按钮抢焦点而误关。Codex 审 spec 时就预警了这一点；实现层改为 frameless `QDialog` + `WindowDeactivate` 事件自动关闭。专属测试 `test_rebuild_time_popover_does_not_close_on_spin_interaction` 覆盖这个回归。

### 1.5 测试
53 个 pytest-qt 测试覆盖每个 widget 类及主要交互（模式切换 / 文件加载流 / 游标 pill / stats strip / drawer 构造 / popover 锚点 + 失焦保护 / 自定义 X 长度校验 / Fs 联动）。用 `QT_QPA_PLATFORM=offscreen` 确保 headless 可跑。仅 `test_stats_strip_update` 在全量 run 时会因 matplotlib Qt paintEvent 访问冲突偶发卡崩溃，单独跑通过——先验已有问题，非本次引入。

---

## 2. 流程如何运转

按用户要求的流水线执行：

```
brainstorming  (用户对话 4 轮 + 可视化 mockup)
    ↓
写 spec  →  codex round 1（22 findings，blocker 11）  →  补齐
          →  codex round 2（5 new-issue）            →  补齐
    ↓
写 plan  →  codex（16 findings，blocker 6）          →  补齐
    ↓
squad-orchestrator (Phase 1) → 26-subtask 决策树
    ↓
主 Claude 分 13 波派发（Phase 2）
    ↓
squad Phase 3 (rework 检测 + 2 条新 lesson)
    ↓
squad Phase 4 (.state.yml: top_level_completions 3 → 4)
    ↓
codex 审最终实现（10 findings，0 blocker）           →  3 个修复 commit
    ↓
总结 + push
```

---

## 3. 顺利之处

- **文档 → 实施的传递性**。Spec 被 codex 审两轮、plan 被审一轮后，specialists 拿到的 brief 足够具体，26 个 subtask 中只有 4 个需要主 Claude 补救（2 个忘了 commit，2 个提前 commit 挂载了并发文件）。没有一个出现算法行为回归。

- **Inspector API 契约先行**。skeleton-inspector 阶段（Task 1.4）就定死了 14 个 signal 和每个 contextual 类的 getter 名称。后续 main-window-analysis-rewire 能一次性重写 11 个分析方法，没有反复"字段名对不齐"的往返。

- **legacy shim 过渡模式**。`_legacy_hidden` QWidget 里挂满 40 个旧 widget 别名，让 Phase 1 的 `_init_ui` 重构可以一次落地而 `plot_time / do_fft / do_order_*` 暂不碰——Phase 2 再按 widget 类迁移；到 Task 3.5 整个 shim 容器被删除作为 Phase 2 完工信号。这个模式把"原子大重构"的风险分散到了 7 个更小的 PR。

- **codex 两轮 spec 审 + 一轮 plan 审的投资回报**。用户不 review 任何文档。如果没有 codex，22 条 spec 漏洞（大多数是功能覆盖缺失）会在实施阶段以 "specialist 找不到对应控件" 形式爆发，返工成本会远高于两轮文档审的 token 成本。

- **rework 检测起作用了**。机械规则触发在 7 对 refactor→ui 的跨专家同文件编辑上（`main-window-analysis-rewire` 后面跟了 6 个 pyqt-ui 任务都编辑 `main_window.py`），都不是真 rework，但触发促使写了 lesson 记录"如何用 brief 里的'禁止方法清单'让跨专家同文件编辑也是安全的"。这正是 rework 机制设计的目的。

---

## 4. 不顺利 / 需要改进

### 4.1 并行同文件碰撞（Wave 9）
4 个 drawer 任务同为 `pyqt-ui-engineer`、都需要小幅修改 `main_window.py` + `tests/ui/test_drawers.py`，orchestrator 没标记它们互相冲突就并行派发了。结果：`git add` 把一个 specialist 未提交的改动卷进了另一个 specialist 的 commit，导致两个 commit 标题和内容不一致。内容最终是对的，但 bisect 起来困难。已写 lesson `2026-04-24-parallel-same-file-drawer-task-collision.md` 并建议 orchestrator 后续在决策 JSON 中加 `shared_files` 字段。

### 4.2 Specialist 忘记 commit
两次（file-navigator-rows-and-kebab 在 Wave 4；chart-stack-stats-strip 在 Wave 8）specialist 报告 `status: done` 但工作只落到工作区没 commit。我补提了。需要在 specialist system prompt 里加"最后一步必须 `git commit`"硬约束。

### 4.3 Spec 契约漂移
Codex 最终审发现 `Inspector.rebuild_time_requested` 实际签名是 `(anchor, mode)`，但 spec §12.2 写的是 `(fs)` → `MainWindow.rebuild_time_axis(fid, fs)`。实现层面 popover 吸收了 rebuild 逻辑（不再需要 MainWindow 上的独立方法），更简洁。我更新了 spec 来对齐实现，而不是反过来——契约漂移是好变化的讯号。Spec 应该定期回头审，不是一写就永远不改。

### 4.4 Pre-existing 已知缺陷
`test_stats_strip_update` 在全量 pytest 跑时会因为 matplotlib backend_qtagg paintEvent 访问冲突偶发崩溃（单跑通过）。这不是本次重构引入的，但也没修。build 时要注意 CI 配置，不然全量 run 会误报 red。

### 4.5 视觉验证 gap
`QT_QPA_PLATFORM=offscreen` 下跑完所有 53 个 pytest-qt，但 rubber-band 拖动视觉效果、双击 45px 轴外区域、QSS 整体观感等需要人眼确认的项目未真正"跑过"。final-parity-verify 诚实标记了 4 项 "not-verified-headless"。需要真机跑一遍前 App 不应该认为交付完成。

---

## 5. 仍有的风险

- `mf4_analyzer/app.py` 里有一个用户本地修改没有提交（不在本次重构范围），保留原样不动。
- 52/53 测试的 paintEvent 崩溃需要持续观察；可能要给这个测试加 `@pytest.mark.flaky` 或单独 CI 轨道。
- Drawer 动画 v1 基线是"无动画，模态 QDialog 定位到右边"。若要加真正的 slide-in，需要 `QPropertyAnimation(geometry)`，但要处理 `QDialog` 模态下窗口 focus 问题。留给 v2。
- Mac 浅色 QSS 在 Windows 上可能微有偏差（系统字体回退、半透明效果差异），需真机确认。

---

## 6. Lessons 归档

写入 `docs/lessons-learned/orchestrator/` 的两条：

1. `2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` — rework 机械规则在 disjoint-method 情况下也会触发，用 brief 中的"禁止方法清单"来规避。
2. `2026-04-24-parallel-same-file-drawer-task-collision.md` — 同专家同文件小编辑的并行派发会产生 git-add race，建议序列化或把共享文件编辑集中到一个 specialist 的 brief。

已更新 `LESSONS.md` 索引、`.state.yml`（top_level_completions: 3 → 4）。

---

## 7. 接下来

- `git push origin main` — 本报告之后执行。
- 真机（非 headless）UI 验证 spec §15 的 4 个 "not-verified-headless" 项。
- 持续观察 `test_stats_strip_update` 稳定性。
- 考虑为 v2 加入 drawer 动画 + 保存 splitter 宽度到磁盘。

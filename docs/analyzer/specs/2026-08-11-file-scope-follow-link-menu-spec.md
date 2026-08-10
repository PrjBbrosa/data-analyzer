# 文件范围跟随 · 链接菜单 Spec（Stage 1.1）

- 日期：2026-08-11
- 状态：按产品报告复审结论定版，待用户确认文案与项 1 作用域后实施
- 基线分支：`codex/analysis-view-source-isolation-pilot`（Stage 1 已落地）
- 配套计划：
  [`2026-08-11-file-scope-follow-link-menu-implementation.md`](../plans/2026-08-11-file-scope-follow-link-menu-implementation.md)
- 产品报告：
  [`2026-08-11-file-scope-follow-link-menu-report.md`](../reviews/2026-08-11-file-scope-follow-link-menu-report.md)
- 前置 spec：
  [`2026-08-10-analysis-view-source-isolation-pilot-spec.md`](2026-08-10-analysis-view-source-isolation-pilot-spec.md)

## 1. 一句话结论

> 文件区链接按钮从单一 boolean toggle 升级为**勾选菜单**，提供三项可组合的
> **文件范围跟随**：新文件加入当前焦点上下文、`+` 新建继承文件范围、进入分析模式
> 填充空 View。跟随只拷贝 `attached_file_ids`，只填空不覆盖，只响应用户手势；
> 全关时行为与 Stage 1 完全一致。

这是 Stage 1 spec §4 非目标里预留的「后续提效入口」：隔离仍是默认真相，跟随是
显式用户偏好。

## 2. 为什么现在做

Stage 1 之后「新建为空 / 切换恢复 / 复制才继承」语义正确，但高频操作路径变长：
用户每新建一个分析 View、每切进一个空分析 section，都要重新把文件拖入通道树。
链接按钮（`btn_auto_attach`）当前只覆盖「加载 → 时域焦点 View」一条路径，用户感知
「链接开着，切分析却是空的」，隐喻与行为脱节。

量化收益：一次典型「6 文件 × 新建 3 个分析 View」的会话，现状需要 18 次拖拽；
开启项 2/3 后为 0 次（继承）+ 必要的减法（从 View 移出个别文件）。减法天然比
加法少——文件范围通常是「桌上这几个」的子集微调。

## 3. 交互契约

### 3.1 入口

`FileNavigatorPane.btn_auto_attach` 由 checkable QToolButton 改为
**菜单按钮**（`InstantPopup`）：单击弹出勾选菜单，不再直接 toggle。

菜单三项（首期），全部 checkable、互不排斥：

| # | 文案（待用户确认） | QSettings key | 默认 |
| --- | --- | --- | --- |
| 1 | 新文件加入当前 View | `channel_selection/auto_attach_current_view`（复用现有 key，零迁移） | 开 |
| 2 | 新建 View 继承文件范围 | `channel_selection/follow_new_view_inherit_files` | 关 |
| 3 | 切换分析时填充空 View | `channel_selection/follow_fill_empty_on_mode_entry` | 关 |

二期候选（本期不实现，不进菜单）：频谱继承时域勾选、时域 `+` 顺带继承勾选、
空态一键「加入全部已打开」。

### 3.2 图标与文案

| 条件 | 呈现 |
| --- | --- |
| 三项全关 | `mdi.link-variant-off` 灰（沿用现关闭态配色 `#8b98aa`） |
| 至少一项开 | `mdi.link-variant` 亮（`#4b6078` + `active` property） |
| tooltip 全关 | `未启用文件范围跟随` |
| tooltip 有勾 | `已启用 N 项文件范围跟随 · 点击调整` |

空分析 View 的空态次级文案增加一行引导：
`从上方拖入；或在链接菜单启用「切换分析时填充空 View」`（经
`set_empty_state_context` 现有通道）。

## 4. 行为契约

### 4.1 项 1 — 新文件加入当前 View

- 触发：`_on_source_load_finished(new_fids)`（文件加载完成）。
- 行为：`_attach_files_to_active_context(new_fids)` —— 当前在时域则加时域焦点
  View；在分析 section 则加该 section 的 active View。逐 logical source 追加，
  身份为复合 `fid`，已存在的跳过。
- **作用域替换**：旧行为是「无论在哪个页面都写时域焦点 View」。新行为在分析页
  不再写时域 View——这是有意替换（消灭对不可见 View 的静默写，与 Stage 1 同一
  原则），必须写进帮助 changelog 与迁移说明。
- toast：`已加入 <section 标签> · <View 名> · N 个文件`（时域侧沿用现有主/副栏文案）。

### 4.2 项 2 — `+` 新建继承文件范围

- 触发：用户点时域或分析 tab 栏的 `+`（`_on_view_new` / `_on_analysis_new`），
  且 `new_view()` 成功（满员返回 `-1` 时整体 no-op）。
- 模板来源（固定优先级）：按下 `+` 时同 section 的活动 View →
  该 View attachment 为空则时域焦点 View → 再空则保持空。
- 行为：新 View 的 `attached_file_ids` = 模板的浅拷贝（保序去重，过滤已不在
  `self.files` 的 fid）。**只拷贝文件范围**：checked、hidden、颜色、来源角色、
  参数、范围一概不带（那是「复制 View」的职责）。
- toast：`已继承 N 个文件 · 来自 <View 名>`；继承数为 0 时不弹。

### 4.3 项 3 — 进入分析模式填充空 View

- 触发：用户切换**进入**某分析模式（`_on_mode_changed` 的分析分支，
  在 `_apply_active_analysis_context` 之前），且目标 section 的 active View
  `attached_file_ids` 为空。
- 来源：**固定取时域焦点 View**（时域是主桌面，来源固定才可预测；不取「刚离开的
  分析 section」，避免填充结果依赖浏览路径）。时域焦点 View 也为空则保持空。
- **不触发**的场景（显式列举）：
  - 同 section 内 tab 切到空 View（`_on_analysis_view_switched` 管线不挂钩子）；
  - 目标 active View 已有任何 attachment（只填空）；
  - 项目恢复 / 程序化切换（见 §4.4）。
- toast：`已填充 N 个文件 · 来自 <时域 View 名>`。

### 4.4 硬规则（全部菜单项共用）

1. **只填空，不覆盖**：已有 attachment 的目标不被替换或清空；项 1 的追加不算覆盖。
2. **不触发自动计算**：填充后画布仍走缓存命中或「点击计算」（Stage 1 spec §G4）。
3. **只响应用户手势**：`_opening_project` / `_restoring_project` /
   `_applying_analysis_view` 期间一律不跟随。项 1 现有 `_restoring_project` 守卫
   保持；项 2/3 的钩子只放在用户手势路径上，天然规避程序化管线。
4. **单一写路径**：所有 attachment 变更走 `_channel_scope_mixin` 既有 helper
   （`_attach_files_to_focused_view` / `_attach_files_to_active_analysis_view` /
   `_attach_files_to_active_context`），不新增第二条 mutation 路径（状态所有权
   棘轮与 navigator-as-projection 合同都依赖这一点）。
5. **全关 = Stage 1**：三项全关时，任何路径的行为与当前分支逐字节一致。

### 4.5 决策逻辑无 GUI 化

「该不该继承 / 该从谁继承」的决策收进纯函数（建议
`ui/main_window/file_scope_follow.py`）：输入为（菜单状态、触发类型、模板候选的
attachment 列表、`files` 键集合），输出为「要写入的 fid 列表或 None」。
MainWindow 侧只做取状态和写状态。这让契约测试不必起 MainWindow 全量装配。

## 5. 与既有护栏的关系

| 护栏 | 本变更的姿态 |
| --- | --- |
| 状态所有权棘轮（`test_main_window_state_ownership.py`） | 不新增多文件写属性；菜单状态由 navigator 持有，MainWindow 只读 |
| navigator 投影合同（Stage 1） | navigator 仍不拥有 attachment；菜单只是偏好开关的宿主 |
| `test_qsettings_isolation.py` | 新增 2 个 key 走同一 `_preset_settings()` 通道，自动被隔离覆盖 |
| G3（来源 ⊆ attachment） | 本期只动 attachment 不动来源，合同不可能被破坏 |
| View 上限（时域 12 / 分析 6） | `new_view()` 返回 `-1` 时继承整体 no-op |

## 6. 验收标准

1. 三项全关：加载 / `+` / 模式切换行为与基线逐项一致（含 toast 不多不少）。
2. 只开 1：时域页加载 → 进时域焦点 View；FFT 页加载 → 进 FFT active View 且时域
   View 不变。
3. 只开 2：分析 `+` → 新 View 继承同 section 活动 View 的文件范围；活动 View 为空
   时回退时域焦点 View；时域 `+` 同理退化；满员 `+` 无副作用。
4. 只开 3：时域 → 空 FFT View 被时域范围填充；已配置 FFT View 不动；FFT 内
   tab 切到空 View 不填充；fft → order 填充来源仍是时域焦点 View。
5. 项目恢复全程（含恢复中触发的模式/View 切换）零跟随；恢复后故意留空的 View 仍空。
6. 图标/tooltip 随「任一勾选」正确切换；重启后勾选状态从 QSettings 恢复；
   旧用户已有的 `auto_attach_current_view=False` 被尊重。
7. hints / quickref 增加对应条目（`/update-hints`）。

## 7. 回退

纯 UI 层增量：菜单退回 checkable 按钮 + 移除两个新 QSettings key 即回到 Stage 1。
不动项目 schema（`attached_file_ids` 的持久化格式无任何变化），无数据迁移，
NO-GO 时旧程序读新项目文件无差异。

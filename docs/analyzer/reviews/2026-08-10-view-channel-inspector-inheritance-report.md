# View · 通道 · Inspector 继承关系报告

- **日期：** 2026-08-10
- **基线：** TraceLab v7.9.7（以当前检出为准）
- **性质：** 代码事实梳理 + 顺手性判断（非实现计划）
- **相关规格：** `docs/superpowers/specs/2026-07-20-view-file-attachment-and-channel-config-design.md`（历史附件设计）；产品速查 `mf4_analyzer/ui/quickref.py`

---

## 1. 一句话心智模型

| 界面区域 | 角色 |
| --- | --- |
| 上方「文件」列表 | **仓库**：全局已打开来源 |
| 底部时域 View 标签 | **工作台**：决定「本桌用了哪些文件 / 勾了哪些通道」 |
| 顶栏分析模式 | **镜头**：对当前工作台做时域 / 频谱 / 时频 / 阶次 / 频响 |
| 左侧通道树 | **当前时域 View 的投影**（不是全局文件清单） |
| 右侧 Inspector | **当前镜头的旋钮**；分析 View 切换时再灌回该 View 的参数/源 |

产品文案（quickref）已写明：**打开只是载入；要画图/分析得先加入 View**（拖到通道树，或开链接图标「自动加入」）。

---

## 2. 代码归属表

### 2.1 两套「View」

同名「View」在代码里是两套并行系统：

| 种类 | 状态类型 | 所有者 | 上限 | 管什么 |
| --- | --- | --- | --- | --- |
| 时域 View | `ViewState` | `MainWindow.view_manager` | **12** | 加入文件、勾选、布局、轴、缩放、游标 |
| 分析 View | `AnalysisViewState` | `ChartStack.analysis_managers[section]` | **6**（每段独立） | 该段参数、pane 源信号、时间范围、游标 |

关键模块：

- `mf4_analyzer/ui/view_state.py` — `ViewState` / `ViewManager`
- `mf4_analyzer/ui/analysis_view_state.py` — `AnalysisViewState` / `PaneState`
- `mf4_analyzer/ui/main_window/_view_mixin.py` — 时域 View 切换 / 新建 / 投影
- `mf4_analyzer/ui/main_window/_analysis_mixin.py` — 分析 View 切换 / 新建
- `mf4_analyzer/ui/main_window/_channel_scope_mixin.py` — 加入 / 卸下 / 自动加入
- `mf4_analyzer/ui/main_window/window.py` — `_on_mode_changed`、`_analysis_scope_fids`

### 2.2 谁拥有什么

| 状态 | 归属 |
| --- | --- |
| `MainWindow.files` | 全局已打开来源 |
| 文件列表（`FileNavigator` 上半） | 全局投影 |
| `ViewState.attached_file_ids` | **每时域 View**：本桌成员 |
| 通道树勾选 / 显隐 | **当前聚焦时域 View** 的活投影 |
| `ViewState.checked` 等 | **每时域 View** 快照 |
| `AnalysisViewState.params` / `panes` | **每分析 View**（按 section 独立） |
| Inspector contextual 控件 | 主要按**模式**存活；切分析 View 时用 state 回灌 |
| 时间范围勾选意图 | **按模式分开记**（`checkout_range_for_mode`） |
| 自动加入开关 | 全局用户偏好（QSettings） |
| `chart_stack.current_mode` | 全局当前分析页 |

不变量：`checked` 里的 `fid` 必须 ⊆ `attached_file_ids`。

---

## 3. 四个操作问题（现在怎样 / 理论上怎样）

### 3.1 左侧有文件，顶栏选好分析，底部 `+` 新 View

**现在：**

- 时域 `+` → `ViewManager.new_view()` → **空桌**：`attached_file_ids` / `checked` 皆空。
- 上方文件列表**不变**；通道区出现「当前 View 尚未加入文件…」。
- **不继承**上一 View；要整桌拷贝用「复制 View」。
- 若在频谱等分析页点 `+`：新建的是**该分析段**的空 View（参数/源清空），时域加入关系不动。

**理论产品语义：**

- `+` = 新开一桌对照实验 → **空桌是正确的隔离语义**。
- 空态容易被误读成「坏了」，属于反馈问题，不是规则自相矛盾。

### 3.2 左侧有通道/文件，切换分析后左侧该怎样

**现在：**

| 面 | 切模式后 |
| --- | --- |
| 文件列表 | 不变（全局） |
| 已加入 / 勾选 | 基本保留（仍投影当前时域 View） |
| 眼睛（时域显隐） | 非时域关闭；detach `×` 仍可用 |
| 分析候选通道 | 只列 **attached**，不是全部已打开文件 |

分析信号范围由 `_analysis_scope_fids()` 决定：等于**当前聚焦时域 View 的 `attached_file_ids`**。十个文件打开、只拖入一个，分析里只能搜到那一个。

频谱与时域还**共用同一套勾选导航**：进入频谱时可能把导航勾选写进当前 FFT View；回来时域时不一定立刻用时域 `ViewState` 回写，存在已知粘连。

### 3.3 实际操作应遵从的顺序

与代码 / quickref 一致的推荐顺序：

1. **打开**文件（进全局文件区）
2. **加入当前 View**（拖到通道树，或开自动加入）
3. **勾选**要画 / 要分析的通道
4. （建议）时域先确认波形
5. **再切**频谱 / 时频 / 阶次 / 频响 → 右侧设参 → 绘图
6. 要第二套对照：底部 `+` → **再加入**（或「复制 View」）→ 另选通道

反序踩坑：先切分析，却指望左侧等于「全部已打开文件」——不会；空 View 上分析 picker 也会空。

### 3.4 右侧 Inspector 是否应继承、何时继承

| 动作 | Inspector 行为 | 应否继承 |
| --- | --- | --- |
| 切分析模式 | 换 contextual；多数控件值留在该模式草稿里 | 模式级草稿保留，合理 |
| 切**同一模式**下的分析 View | 回灌该 View 的 params / 源 / 时间范围 | **应继承该 View** |
| 切时域 View | 恢复该桌轴、范围、勾选投影等 | **应继承该时域 View** |
| 新建时域 / 分析 View | 空 / 默认 | **不应继承**上一桌 |
| 时间范围勾选 | 按模式分记 | 防模式间泄漏 |

原则：**继承的是「同一 View 身份」上的参数与源**；不是「全局文件」或「上一桌偷偷变成下一桌」。

---

## 4. 继承矩阵（速查）

| 动作 | 全局文件列表 | 时域 attached | 通道勾选 | 分析源/参数 | Inspector UI |
| --- | --- | --- | --- | --- | --- |
| 新建时域 View（`+`） | 不变 | **空** | **空** | n/a | 投影为空树 |
| 复制时域 View | 不变 | 拷贝 | 拷贝 | n/a | 整桌应用 |
| 切换时域 View | 不变 | 恢复 | 恢复 | combos 按新 scope 刷新 | 轴/范围/布局恢复 |
| 新建分析 View | 不变 | 时域不变 | FFT 等可能被置空 | 空 pane + 默认 params | 该 View 默认 |
| 切换分析 View | 不变 | 不变 | FFT：按 pane.sources 投影 | 恢复 | 回灌 contextual |
| 切换分析模式 | 不变 | 保留 | 保留（FFT 进出可能改写） | 离开时 capture；目标页控件多半仍持旧值 | 换 contextual + 范围 checkout |

---

## 5. 顺手性判断

### 5.1 模型本身

对工程对比场景是合理的：

- **View = 通道桌面（实验条件）**
- **分析模式 = 对这桌换算法镜头**
- 新 View 空、分析只看 attached → **刻意隔离**，避免「十个文件混在一个分析里却对不上屏」

### 5.2 错乱感从哪来（表达问题 > 规则错误）

1. 同一个词「View」管两套东西（时域桌 vs 频谱桌）
2. 文件全局可见 + 通道按 View 过滤 → 空态像故障
3. 切分析后左侧几乎不动，但候选其实已收窄 → 规则太隐性
4. 时域勾选 ↔ 频谱源共用导航 → 进出模式会「抢」勾选

### 5.3 更合理的体验方向（不推翻模型）

短期 / 中期（反馈与入口）：

- 空 View 文案强调：「文件已打开，尚未加入**本** View」+ 一键「加入全部已打开 / 从上一 View 带入」
- 加重「复制 View」入口，与空白 `+` 并列说明
- 分析模式空态 / 顶栏旁提示：「信号范围 = 当前时域 View（N 个文件）」

中长期（结构）：

- 频谱源与时域勾选拆开存储，避免模式来回改写
- 文案上区分「时域工作台」与「分析页签」（若产品愿意改名）

---

## 6. 已知不一致 / 双归属（实现层）

1. **共享时域/FFT 导航**：FFT `pane.sources` 与时域 `checked` 共用勾选 UI；`_enter_fft_mode` 会把导航再捕获进当前 FFT View。
2. **两套 View 宇宙**：时域 12 ≠ 各分析段各 6；Alt+1..6 跟当前 section 走。
3. **加入关系以时域为中心**：分析 View 不拥有 `attached_file_ids`；空时域 View → 分析候选空。
4. **Inspector 双存储**：活控件 + `AnalysisViewState.params`；切模式多半靠控件残留，切 View 才显式 apply。
5. **帮助 vs quickref**：部分帮助仍偏「勾选即出图」，对「先加入 View」强调不如 quickref / 附件规格。

---

## 7. 关键符号索引

| 符号 | 位置 |
| --- | --- |
| `ViewManager.new_view` / `duplicate` / `set_active` | `ui/view_state.py` |
| `_on_view_new` / `_switch_view` / `_project_view_controls` | `ui/main_window/_view_mixin.py` |
| `_attach_files_to_focused_view` / 自动加入 | `ui/main_window/_channel_scope_mixin.py` |
| `_on_mode_changed` / `_analysis_scope_fids` / `_update_combos` | `ui/main_window/window.py` |
| `_on_analysis_new` / `_on_analysis_switch` / capture·apply sources | `ui/main_window/_analysis_mixin.py` |
| `Inspector.set_mode` / `checkout_range_for_mode` | `ui/inspector*.py` / `persistent_top.py` |
| 空态文案 | `ui/widgets/channel_tree.py` |
| 自动加入 tooltip | `ui/file_navigator.py` |

---

## 8. 结论

当前继承规则在代码里是自洽的：**全局开文件 → 按时域 View 加入 → 勾选 → 再切分析；Inspector 跟「模式草稿 + 分析 View 身份」走，不跟全局文件走。**

用户感到错乱，主要是因为 UI 没有把「仓库 / 工作台 / 镜头」三层说清楚，再加上「View」一词双义与时域/FFT 勾选粘连。产品上更合理的方向是**保留隔离模型，补齐空态与范围提示，并逐步拆开时域勾选与分析源**——而不是让新 View 默认吞下全部已打开文件。

# 文件范围跟随 · 链接菜单产品报告

- 日期：2026-08-11（同日复审后修订：触发面收敛、来源优先级统一、补程序化切换守卫）
- 性质：产品设计报告（未实施）
- 基线分支：`codex/analysis-view-source-isolation-pilot`
- 相关：
  - Spec：`docs/analyzer/specs/2026-08-10-analysis-view-source-isolation-pilot-spec.md`
  - 继承关系审查：`docs/analyzer/reviews/2026-08-10-view-channel-inspector-inheritance-report.md`
  - 实施审查：`docs/analyzer/reviews/2026-08-10-grok-analysis-view-source-isolation-implementation-review.md`
  - 本报告的实施 spec：`docs/analyzer/specs/2026-08-11-file-scope-follow-link-menu-spec.md`
  - 本报告的实施 plan：`docs/analyzer/plans/2026-08-11-file-scope-follow-link-menu-implementation.md`

---

## 1. 背景与问题

Stage 1「分析 View 来源隔离」落地后，行为变为：

- 全局文件仓库（上方「文件」）与 View 文件范围（下方通道树）分离；
- 时域 / 频谱 / 时频 / 频响 / 阶次的每个 View 各自拥有 `attached_file_ids`；
- 新建 View（`+`）默认为空；切换到空分析 View 时通道树清空。

这是隔离模型的正确结果，但也带来操作成本：用户每次新建 View 或切换分析，都要重新把文件拖入通道树。

文件区标题旁的链接按钮（`btn_auto_attach`）**当前只做一件事**：

> 新加载的文件自动加入**当前时域** View。

它**不会**在「新建 View」或「切换分析」时继承上一上下文的通道树。用户感知为「链接开了，切分析却还是空的」，与按钮外观上的「连接」隐喻不完全一致。

---

## 2. 目标

在不破坏 Stage 1 隔离合同的前提下，增加可选的**文件范围跟随**能力：

1. 减少重复拖拽；
2. 选项可组合、可关闭；
3. 全关时视觉回到灰「断开链」，与现网一致；
4. **只填空，不覆盖**已配置 View；
5. 默认不自动继承 Inspector 参数、时间范围、计算结果等实验条件。

一句话：

> **跟随 ≈ 继承「桌上有哪些文件」；不是继承「整份分析配置」。**

---

## 3. 交互方案：链接按钮 → 勾选菜单

### 3.1 为什么用菜单而不是单开关

| 方案 | 问题 |
| --- | --- |
| 单按钮 toggle | 「加载跟随」与「切换/新建继承」语义不同，挤在一个开关会互相误解 |
| 两个独立按钮 | 占位多，和现有文件区标题密度不匹配 |
| **链接按钮弹出勾选菜单** | 一个入口、多项可组合；灰链 = 全关，亮链 = 至少一项生效 |

### 3.2 图标状态

| 条件 | 图标 |
| --- | --- |
| 菜单内一项都未勾选 | 灰色断开链（与当前关闭态一致） |
| 至少勾选一项 | 亮色闭合链（可带轻微 active 底） |
| 点击按钮 | 弹出勾选菜单（InstantPopup / 菜单按钮），**不再**把单击当成单一 boolean toggle |

建议 tooltip：

- 全关：`未启用文件范围跟随`
- 有勾：`已启用 N 项跟随 · 点击调整`

### 3.3 菜单项（推荐文案）

菜单项为 **checkable**；勾选即生效，取消即关闭。互不排斥，可组合。

| # | 菜单文案 | 生效时机 | 行为 |
| --- | --- | --- | --- |
| 1 | **新文件加入当前 View** | 文件加载完成 | 将新 logical source 追加到**当前焦点上下文**的 `attached_file_ids`（当前在时域则加时域焦点 View；在分析页则加该分析 active View）。注意这是**行为替换**而非纯增强：在分析页加载时不再写入不可见的时域 View（见 §7 迁移说明） |
| 2 | **新建 View 继承文件范围** | 用户点 `+`（时域与分析节均适用），且新 View attachment 为空 | 拷贝「按下 `+` 时同 section 活动 View」的 `attached_file_ids`（保序去重）；该 View 也为空则回退时域焦点 View；再为空则保持空 |
| 3 | **切换分析时填充空 View** | 用户切换**进入**某分析模式（mode entry），且目标 section 的 active View attachment 为空 | 用时域焦点 View 的 `attached_file_ids` 填入目标；目标已有内容则**不改动**。同 section 内 tab 切到空 View **不**填充——那是用户显式选择的空 View |
| 4 | **（可选）频谱继承时域勾选** | 进入频谱，且目标 Pane `sources` 为空 | 将时域 `checked` 映射为当前 FFT Pane 的 overlay 来源；时频 / FRF / 阶次默认不做。注意 G3 合同：来源 fid 必须 ⊆ `attached_file_ids`，映射前需先保证文件已加入 |

**触发面互斥**（复审收敛）：项 2 只挂在 `+` 手势上，项 3 只挂在模式进入路径上。
`+` 会连带触发 manager 的 `active_changed`（内部 view-switch 管线），但项 3 不挂在
view-switch 管线里，所以两项永远不会对同一个新 View 重复触发；「只开 3 不开 2」时
点 `+` 得到的仍是空 View，语义清晰。

实施时可先做 **1–3**；第 4 项进菜单但默认关闭，或二期再加。

### 3.4 与「复制 View」的关系

| 动作 | 范围 |
| --- | --- |
| 跟随菜单 | 主要拷贝**文件范围**（可选：时域勾选 → 频谱来源） |
| 复制 View | 全量拷贝 attachment、来源、参数、范围、分屏、比较等，并生成新 `view_id` |

两者正交：跟随是「少拖几次」；复制是「整桌实验条件再来一份」。

---

## 4. 触发矩阵

| 用户动作 | 全关（现 Stage 1） | 仅勾选「新文件…」 | 勾选「新建继承」 | 勾选「切换填充空 View」 |
| --- | --- | --- | --- | --- |
| 打开新文件 | 不加入任何 View（若 1 关） | 加入当前焦点上下文 | — | — |
| `+` 新 View | 空 | 空（除非另有 2） | 继承来源 attachment | — |
| 切到已配置的分析 View | 恢复该 View | 恢复该 View | 恢复该 View | **仍恢复该 View**（不覆盖） |
| 进入分析模式，active View 为空 | 空 | 空 | — | 用时域焦点 View 的 attachment 填充 |
| 同 section 内 tab 切到空 View | 空 | 空 | — | **保持空**（显式留空的 View 不动） |
| 复制 View | 全量拷贝 | 不变 | 不变 | 不变 |
| 从当前 View 移出文件 | 只影响当前 View | 不变 | 不变 | 不变 |

硬规则：

1. **已有 attachment / 来源的目标不得被跟随覆盖。**「覆盖」指整体替换或清空既有
   attachment；项 1 对已配置 View 的**追加**（只增不减、不动来源/参数）是预期行为，
   不算覆盖。
2. 跟随不触发自动计算；画布仍走缓存命中或「点击计算」。
3. 一个物理文件展开多个 logical source 时，按 logical source 逐条加入，身份仍是复合 `fid`。
4. **跟随只响应用户手势**（点 `+`、点模式按钮、加载文件）。项目恢复与内部 apply 管线
   期间（`_opening_project` / `_restoring_project` / `_applying_analysis_view`）一律
   不触发——否则打开工程时，用户故意留空的分析 View 会被静默填上，违背「保存什么恢复
   什么」。项 1 现有实现已经带 `_restoring_project` 守卫，项 2/3 必须同样对齐。

---

## 5. 跟随时建议带什么 / 不带什么

### 5.1 默认跟随（勾选对应项后）

- `attached_file_ids`（文件范围）——必做
- 加入顺序（左栏父节点稳定顺序）

### 5.2 二期再议（首期一律不跟）

- 时域 `checked`：进频谱映射为 overlay（菜单项 4）与「时域 `+` 顺带继承勾选」都归二期。
  首期新时域 View 只继承文件范围、不继承勾选——「桌上有文件但画布空白」正好提示用户
  这是新 View；想连勾选一起要，用「复制 View」。
- `hidden_channels` / 通道颜色：随 checked 一起归二期。
- 搜索框关键字 / 树展开状态：纯交互便利，非身份，不进菜单。

### 5.3 默认不要跟随

- Inspector 参数（nfft、窗函数、滤波等）
- 时间范围、游标、分屏、比较锁定
- FRF 输入/输出对、阶次 RPM（角色敏感，误跟代价高）
- 计算结果或把旧缓存当「新 View 已算完」展示

---

## 6. 来源优先级（按菜单项分列）

复审修订：原版此节与 §4 触发矩阵互相矛盾（§4 说切换填充用时域 attachment，本节又说
同 section 优先）。现按菜单项分列，一项一个确定来源，避免「跟上了但不知道跟的谁」：

- **项 2（`+` 继承）**：按下 `+` 时同 section 的活动 View → 该 View 为空则时域焦点
  View → 再空则保持空。时域节里前两级本来就是同一个 View，天然退化。
- **项 3（模式进入填充）**：**固定取时域焦点 View**，不看上一个离开的分析 section。
  理由：时域是「主桌面」，来源固定才可预测；若取「刚离开的上下文」，fft → order 之类
  的分析间切换会让填充结果依赖浏览路径，用户无法预判。时域焦点 View 也为空则保持空。

**可观测性**：项 2 / 项 3 每次实际发生填充时，toast 报「已继承 N 个文件 · 来自
<View 名>」（项 3 带上 section 标签）。没有这条，固定优先级也挡不住「树里怎么有东西」
的困惑；填充为 0（来源为空）时不弹。

空态次级文案可与菜单呼应，例如：

> 当前「频谱 · View 2」尚未加入文件  
> 从上方拖入；或在链接菜单启用「切换分析时填充空 View」

---

## 7. 默认值建议

| 菜单项 | 默认 |
| --- | --- |
| 新文件加入当前 View | **开**（延续现网「链接默认开」习惯） |
| 新建 View 继承文件范围 | **关** |
| 切换分析时填充空 View | **关** |
| 频谱继承时域勾选 | **关**（若首期就做） |

**QSettings 落法（复审具体化，零迁移）**：项 1 直接复用现有 key
`channel_selection/auto_attach_current_view`（默认 True 保持不变，用户已关掉的继续是
关），不写任何迁移代码；项 2 / 3 各新增一个 key（如
`channel_selection/follow_new_view_inherit_files` /
`channel_selection/follow_fill_empty_on_mode_entry`），默认 False。项目文件不保存该
全局偏好。

**项 1 迁移说明（必须写进帮助/changelog）**：作用域从「仅时域焦点 View」变为「当前
焦点上下文」是**替换**——在分析页加载文件后，时域焦点 View 将**不再**自动收到该文件。
这是有意为之：Stage 1 的核心就是消灭「对不可见 View 的静默写」，旧行为恰是一例。
代价由 toast（报 section · View 名）与文件区全局可见性兜底：回时域后文件仍在上方
文件仓库，拖一次即可。

---

## 8. 与 Stage 1 Spec 的关系

原 Spec 非目标曾写明：

- Stage 1 不改变「新文件自动加入」偏好（当时仅时域）；
- 不让新分析 View 自动继承时域文件；需要时用复制 View，后续可另立提效入口。

本报告描述的正是该「后续提效入口」的产品形态：

- **隔离仍是默认真相**（全关或目标已有内容时行为与 Stage 1 一致）；
- **跟随是显式用户偏好**，不是静默改写；
- 不撤回「新建为空 / 切换恢复自己 / 复制才全量继承」的基础语义。

实施前应另立 dated spec（或 Stage 1.1 补丁），并更新 `hints.py` / `quickref.py`。

---

## 9. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 用户以为跟随会带上参数 | 菜单文案强调「文件范围」；帮助/quickref 写明不跟参数 |
| 切分析时覆盖已配好的 View | 合同：仅填充空 attachment |
| 「当前 View」在分析页被理解成时域 | 菜单项 1 写清「当前焦点」；toast 带 section · View 名 |
| 默认全开导致试运行再次「感觉没隔离」 | 新建/切换两项默认关 |
| 与加载自动加入旧设置迁移 | 旧 boolean 映射到菜单项 1；项 2/3 默认 false |

---

## 10. 实施边界（本报告不实施）

本文件仅为产品报告，**不包含代码改动**。后续若立项，建议最小切片：

1. 将 `btn_auto_attach` 改为菜单按钮 + 勾选项 1–3；
2. 图标随「是否任一勾选」切换；
3. 接线：加载完成 / `_on_view_new`·分析 `+` / `_on_mode_changed` 空目标填充；
4. 聚焦测试：全关不变；只开 2 时 `+` 继承；只开 3 时切空分析填充；已有目标不覆盖；
   项目恢复期间不触发任何跟随；
5. 同步 hints / quickref / 空态文案。

实施注意（对齐既有护栏，复审补充）：

- 所有 attachment 变更**必须走 `_channel_scope_mixin` 既有 helper**
  （`_attach_files_to_focused_view` / `_attach_files_to_active_analysis_view` /
  `_attach_files_to_active_context`），别新开第二条写路径——该 mixin 的 docstring 就是
  「Own attachment mutations while the navigator remains a projection」，且状态所有权
  棘轮测试盯着多文件写属性。
- `+` 在 View 满员时 `new_view()` 返回 `-1` 不建不切，继承逻辑要跟着 no-op。
- 项 3 的填充钩子放 `_on_mode_changed` 的分析分支（用户手势路径），放在
  `_apply_active_analysis_context` **之前**，这样投影/候选刷新天然拿到填充后的范围；
  **不要**放进 `_on_analysis_view_switched`（那是程序化管线，项目恢复也会走）。

第 4 项（频谱勾选映射）、空态「加入全部已打开」可作为紧随其后的小项。

细化后的实施契约见同日 spec：
`docs/analyzer/specs/2026-08-11-file-scope-follow-link-menu-spec.md`，任务拆分见
`docs/analyzer/plans/2026-08-11-file-scope-follow-link-menu-implementation.md`。

---

## 11. 结论

1. Stage 1 清空通道树是隔离正确性的表现，不是链接按钮坏了。  
2. 用户需要的是可选的**文件范围跟随**，不是取消隔离。  
3. **链接按钮 → 勾选菜单**是合适的入口：灰链 = 全关，亮链 = 有跟随生效。  
4. 首期菜单三项足够：新文件加入当前 View、新建继承文件范围、切换分析填充空 View；参数与角色来源默认不跟。  
5. 硬规则：**只填空、不覆盖、只响应用户手势**；与「复制 View」分工明确。

复审已完成触发面与来源优先级的收敛，dated spec + plan 已立
（见文首「相关」链接）；实施前待用户确认的只剩菜单文案与项 1 作用域替换是否接受。

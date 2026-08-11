# 分析 View 参数隔离：正确语义与最优解

- **日期：** 2026-08-12
- **性质：** 根因分析 + 产品语义 + 架构选型（**不包含实现**）
- **触发：** FFT View1 已有结果 → 新建 View2 → 在 View2 改 Linear/dB 或点 Preset（未点计算）→ 切回 View1 清屏，需重算
- **相关既有文档：**
  - `docs/analyzer/reviews/2026-08-10-view-channel-inspector-inheritance-report.md`（View / Inspector 心智模型）
  - `docs/analyzer/reviews/2026-08-10-grok-analysis-view-source-isolation-implementation-review.md`（源隔离）
  - `docs/analyzer/reviews/2026-08-11-analysis-view-source-isolation-final-acceptance.md`

---

## 0. 一句话结论

**正常逻辑：** 每个分析 View 是独立实验台——参数、源、缓存结果都属于该 View；切走再切回应原样恢复，sibling 未点「计算」的改动不得毁掉本 View 的结果。

**当前病灶：** 分区共用一份 Inspector，切 View 时只捕获 `get_params()`，而 FFT/Order 的 Linear/dB、平均模式等关键字段只在 `current_params()` 里 → sibling 污染 live 控件 → 切回用错参数做 cache lookup → miss 清屏。

**最优解：** 统一「View 可持久化参数面 = `current_params`」+ 显式区分 **compute 参数** vs **display 参数**；切 View 永远按目标 View 的记账回灌后再查缓存；display 变更只重绘当前页，绝不 invalidate sibling。FRF 已接近该模型，应作为模板横展。

---

## 1. 复现与现象

| 步骤 | 期望 | 现状 |
| --- | --- | --- |
| View1 计算完成 → 新建 View2 → 切回 View1 | View1 结果仍在 | ✅ 正常 |
| 在 View2 **只改**「幅值单位」Linear ↔ dB，**不点计算** → 切回 View1 | View1 仍显示原结果与原单位 | ❌ 清屏 / 需重算（或单位串味） |
| 在 View2 点上方 Preset（会改 dB/Linear，常连带 `avg_mode`）→ 切回 View1 | 同上 | ❌ 清屏需重算 |

用户体感：「改 dB/Linear 或点 preset 就会把另一个 View 弄坏」。

---

## 2. 正常软件逻辑（产品语义）

与时域 View「一桌一实验」同构；分析段内每个 View 是一张独立谱图实验台。

### 2.1 所有权

| 对象 | 归属 | 切 View 时 |
| --- | --- | --- |
| 通道源 / pane 布局 | **本 View** | 捕获 / 回灌 |
| 计算参数（窗、NFFT、平均模式…） | **本 View** | 捕获 / 回灌；决定 cache key |
| 显示参数（Linear/dB、色标、相位模式…） | **本 View** | 捕获 / 回灌；**不**进 cache key |
| 计算结果缓存条目 | **本 View 的 pin**（按 key） | 命中则重绘，miss 才空态 |
| Inspector 控件 | **当前活动 View 的投影** | 只是投影，不是全局真相 |

心智模型（接续 2026-08-10 报告）：

> 右侧 Inspector = **当前镜头对着当前分析 View 的旋钮投影**；旋钮改的是「当前 View 的账本」，不是「整个 FFT 分区的全局设置」。

### 2.2 用户操作契约

1. **在 View A 点「计算」**  
   - 用 A 的 compute 参数算出结果，按 key pin 到 A。  
   - 画布按 A 的 display 参数渲染。

2. **切到 View B（空或未算）**  
   - 先把 A 的完整参数账本写回 `AnalysisViewState.params`。  
   - 再把 B 的账本灌进 Inspector。  
   - B 无缓存 → 空画布 +「点击计算」是正确的。

3. **在 View B 改 Linear/dB / 轴范围 / 其它显示项，不点计算**  
   - 只改 B 的 display 账本（及 live 投影）。  
   - **不得**改写 A 的账本，**不得**动 A 的缓存 pin。  
   - 切回 A：Inspector 恢复 A 的 Linear/dB；画布用 A 的缓存 + A 的 display 重绘。

4. **在 View B 点 Preset**  
   - Preset 写入 **当前 View（B）** 的参数账本（可能同时含 compute + display）。  
   - 未点计算 → B 仍无结果。  
   - 切回 A：**A 的账本与缓存不变**；A 仍显示原结果。

5. **在 View B 改了 compute 参数并点了计算**  
   - 只影响 B 的 pin。  
   - A 仍按 A 的 key 命中。

6. **在已有结果的 View 上改 Linear/dB**  
   - 应 **即时重绘当前页**（display-only），无需重算。  
   - 这是「本 View 内」的体验；与跨 View 隔离正交。

### 2.3 明确禁止的行为

- Sibling 未点计算的改动，导致本 View 清屏 / 丢缓存命中。  
- 用「当前 live Inspector」去查 **非活动 View** 的缓存。  
- 把 display 旋钮放进 cache key（改单位就 miss）。  
- 把 compute 旋钮漏出 View 账本（切回无法复位 → 隐性 miss）。

---

## 3. 现状机制（代码事实）

### 3.1 管线已对，捕获面不对

切换管线本身正确：

```
离开 View：capture_params_to_state(ctx.get_params()) → state.params
进入 View：apply_params_from_state → _render_analysis_view_from_cache（只查缓存，不算）
```

实现：`analysis_view_bridge.py` + `_analysis_mixin._on_analysis_view_switched`。

问题在 **捕获读的是不完整的 `get_params()`**。

### 3.2 FFT：两套接口分家留下的洞

```text
get_params()      → window/nfft/轴/weighting/db_ref …   ← bridge 用这个
current_params()  → get_params + avg_mode + avg_overlap + amp_y
apply_params()    → 已能回灌 amp_y / avg_mode（但 state 里没有就灌不回去）
```

历史注释写明：`current_params` 是后来为 Welch / Linear-dB 加的扩展，旧调用方继续用 `get_params`——**View bridge 被留在了旧面上**。

同时 `_analysis_compute_params('fft')` 的 cache key **从 `current_params()` 读 `avg_mode`**，却 **不**把 `amp_y` 放进 key（display-only，设计正确）。

于是：

| View2 动作 | 污染 live 字段 | 切回 View1 |
| --- | --- | --- |
| 只改 Linear/dB | `amp_y` | 账本无 `amp_y` → 无法复位；display 串味；若同时有其它 key 泄漏则 miss 清屏 |
| 点 Preset | `amp_y` + **`avg_mode`**（内置 preset 常一起改） | `avg_mode` 在 key 里 → **确定 miss → 清屏** |

缓存条目往往还在，是 **lookup 被 sibling 污染**，不是 pin 被删。

### 3.3 横展四模块

| 模块 | Linear/dB 类 | `get_params` 是否完整 | 风险 |
| --- | --- | --- | --- |
| **FFT** | `amp_y` | ❌ 缺 amp/avg | **主病灶**；preset → 清屏 |
| **Order** | `amplitude_mode` + 轴/z | ❌ 多数字段只在 `current_params` | 单位/轴串味；`samples_per_rev` 等泄漏可 miss |
| **FFT-vs-Time** | `amplitude_mode` | ✅ 较完整 | 纯改单位一般不应清屏 |
| **FRF** | `magnitude_scale` 等 | ✅ `get_params == current_params`；compute/display 分家 | **应作模板**；display 变更写当前 `state.params` 且只重绘本页 |

---

## 4. 方案比较

### 方案 A — 最小补丁：bridge 改读 `current_params()`

- **做法：** `capture_params_to_state` → `ctx.current_params()`；保证各 contextual 的 `apply_params` 能 round-trip 全字段；必要时让 `get_params = current_params`（FFT/Order 对齐 FRF）。
- **优点：** 改动面小，直接堵住「账本缺字段」。
- **缺点：** 不强制 compute/display 边界文档化；后续新人仍可能只往 `current_params` 加字段却忘了 apply。
- **评价：** **必修的正确性底线**，但是「止血」，还不是完整最优。

### 方案 B — FRF 模板横展：compute / display 显式分家

- **做法：**
  1. 每个 contextual 提供：
     - `compute_params()` → 进入 cache key 的字段
     - `display_params()` → 仅影响渲染
     - `current_params()` = 二者并集
     - `get_params()` ≡ `current_params()`（View/项目持久化只认这一面）
  2. View 账本存完整 `current_params`。
  3. `_analysis_compute_params` **只**吃 `compute_params`（或从已 apply 的目标 View 账本取），禁止「一半 get、一半 current」的拼盘。
  4. Display 控件变更：
     - 立刻写入 **当前** `AnalysisViewState.params`；
     - 有结果则 **只重绘当前页**；
     - 绝不 `invalidate` sibling / 绝不清屏。
  5. Compute 控件变更：可标脏当前 View；不自动算；切走再切回仍用旧 pin，直到用户重算（或产品选择「参数脏则提示」）。
- **优点：** 与已验收的 FRF 模型一致；产品语义清晰；防回归。
- **缺点：** FFT/Order 需整理字段表与测试；工作量大于 A。
- **评价：** **最优解**。

### 方案 C — 每 View 独立 Inspector 实例

- **做法：** 每个分析 View 挂自己的控件树。
- **优点：** 物理隔离，无泄漏。
- **缺点：** 内存/信号连接/布局成本高；与现有 ChartStack + 单 contextual 架构冲突；过度设计。
- **评价：** 拒绝。投影模型正确，缺的是账本完整性。

### 方案 D — 把 `amp_y` 塞进 cache key

- **做法：** Linear/dB 也参与 key，切单位就 miss。
- **优点：** 无。
- **缺点：** 违背「display-only 不重算」；浪费缓存；不修复 avg_mode 泄漏。
- **评价：** 明确错误方向。

---

## 5. 最优解（推荐：A 为第一刀，落地为 B）

### 5.1 目标架构

```text
┌─ AnalysisViewState (每 View 一本账) ─────────────────────┐
│  params = current_params()   # compute ∪ display        │
│  panes / sources / time_range / cursors …               │
│  cache pins keyed by compute_params + source + range    │
└─────────────────────────────────────────────────────────┘
              ▲ capture / apply
              │
┌─ Inspector（分区共享，仅投影活动 View）───────────────────┐
│  compute 旋钮 ──► 写入当前 View.params；标脏可选         │
│  display 旋钮 ──► 写入当前 View.params；即时重绘本页     │
│  Preset        ──► 只写当前 View.params（同左）          │
└─────────────────────────────────────────────────────────┘
```

切 View 不变量（验收用）：

1. 离开前：完整 `current_params` → 源 View.params  
2. 进入后：目标 View.params → Inspector（含 amp / avg / 轴）  
3. 再用 **已回灌后的** compute 参数查 **该 View** 的 pin  
4. 命中 → 用该 View 的 display 重绘；miss → 空态提示计算  

### 5.2 字段分类（FFT 示例；其它模块同构）

| 类别 | 字段例 | View 账本 | Cache key | 改了不点计算 |
| --- | --- | --- | --- | --- |
| Compute | window, nfft, avg_mode, avg_overlap, weighting | ✅ | ✅ | 本 View 可变脏；sibling 不受影响 |
| Display | amp_y, 轴 auto/min/max*, db_reference* | ✅ | ❌ | 本页即时重绘 |
| 源/范围 | panes.sources, time_range | ✅（别处） | ✅（另腿） | — |

\*轴范围：产品上更接近 display；若历史上曾影响「自动重算」边界，实现时按现有行为钉死并写进测试，避免借机改语义。

### 5.3 推荐落地顺序

1. **P0 正确性：** bridge 捕获 `current_params`；FFT/Order `get_params` 与 `current_params` 对齐或弃用分叉；切回回归测试（见 §6）。  
2. **P0 体验：** 当前 View 改 Linear/dB → 有结果则即时重绘（接上已有 `_fft_entry_from_cache` 路径）。  
3. **P1 结构：** 显式 `compute_params` / `display_params`；`_analysis_compute_params` 不再拼盘。  
4. **P1 记账：** display/preset 变更同步写 **当前** `state.params`（学 FRF），避免「只改 live、切走才 capture」的时间窗。  
5. **文档：** 更新 quickref / 本报告验收清单；必要时升一版短 spec。

### 5.4 明确不做什么

- 不为修隔离去改 ink / 渲染栈。  
- 不把 display 放进 cache key。  
- 不每 View 复制一份 Inspector。  
- 不扩大「切 View 自动重算」——空态点计算仍是产品契约。

---

## 6. 验收标准（实现后必须绿）

### 6.1 行为

1. View1 有 FFT 结果 → View2 只切 Linear/dB → 回 View1：**曲线仍在，单位仍是 View1 的**。  
2. View1 有结果 → View2 点会改 `avg_mode` 的 preset、不计算 → 回 View1：**仍命中缓存，无需重算**。  
3. View1 有结果 → 在 View1 切 Linear/dB：**即时换轴，不重算、不清屏**。  
4. Order：同构用例（`amplitude_mode` / preset）。  
5. FFT-vs-Time / FRF：确认无回归；FRF 保持现有 display 即时写账本行为。

### 6.2 测试建议（失败先行）

- `tests/ui/` 下跨 View 切换用例：mock/真实算一条 → sibling 改 amp/preset → assert 目标 View canvas `has_result` 且 inspector `amp_y`/`avg_mode` 恢复。  
- 契约测试：`get_params()` 字段 ⊇ cache key 所需字段 ∪ display 字段（或直接断言 `get_params == current_params`）。  
- 禁止回归：`_analysis_compute_params('fft')` 不得在 apply 目标 View 之前读「未回灌的」泄漏控件——可用切换序断言。

### 6.3 非目标验收

- Offscreen 断言不能替代「真机看一眼单位与曲线」；但本 bug 是状态机问题，离屏单测即可钉死。

---

## 7. 风险与注意

| 风险 | 说明 |
| --- | --- |
| 项目文件旧 params | 缺 `amp_y`/`avg_mode` 的旧会话：apply 时用默认，不得崩溃；打开后第一次切 View 即写全字段。 |
| Preset 语义 | Preset 必须只打当前 View；若有「全局默认」入口，需与 View 账本分开命名。 |
| `overlap` vs `avg_overlap` | FFT 注释已说明二者用途不同；对齐捕获时勿把 fraction/percent 再次写歪 key。 |
| Order `get_params` 被 compute 直读 | 扩大 `get_params` 时确认 `_order_mixin` / COT 不会误吃纯 display 字段。 |

---

## 8. 总结表

| 问题 | 答案 |
| --- | --- |
| 正常逻辑？ | 每分析 View 独立账本；Inspector 是投影；sibling 改旋钮不影响已算 View |
| 根因？ | 共享 Inspector + 捕获面漏字段 + cache lookup 读泄漏的 live compute 字段 |
| 最优解？ | FRF 式 compute/display 分家 + View 账本 = 完整 current_params + 切 View 先回灌再查缓存 |
| 第一刀？ | bridge/`get_params` 对齐 `current_params`，加跨 View 回归测试 |
| 错误方向？ | 每 View 复制 Inspector；把 Linear/dB 塞进 cache key |

---

## 9. 建议下一步

若认可本报告的产品语义与方案 B：

1. 出一页短 **spec**（字段表 + 切 View 不变量 + 验收用例）。  
2. 按 §5.3 做 P0 实现与失败先行测试。  
3. 不把无关 dirty worktree（进度条 / QSS lesson 等）混进同一提交。

**本文件到此为止：分析与选型，不含代码改动。**

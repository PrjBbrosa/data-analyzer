# 分析结果缓存 View 绑定常驻（Pinning）Spec

- 日期：2026-08-11
- 状态：已实施
- 对应计划：
  [`2026-08-11-analysis-cache-view-pinning-implementation.md`](../plans/2026-08-11-analysis-cache-view-pinning-implementation.md)
- 真实基线：merge `5477add1`（分析区 View 上限 6 → 12）后的树；
  `mf4_analyzer/ui/analysis_cache.py` · `ui/main_window/window.py:382-387` ·
  `ui/main_window/_analysis_mixin.py`（`_render_analysis_view_from_cache` /
  `_analysis_cache_key`）· 两个 coordinator（`fft_time_coordinator.py` /
  `frf_coordinator.py`）· `_fft_mixin.py` / `_order_mixin.py` 的直接 `cache.put`

## 1. 一句话结论

> 分析结果缓存的淘汰语义从「总条数 LRU」改为「**被任一 View 当前绑定的结果常驻
> （pinned），无主历史条目按原容量走 LRU**」。容量常量 32/12/12 一个都不改，
> 改的是它的含义：从「总条数上限」变成「无主历史条数上限」。

这不是加大缓存，是让「切 View 绝不自动重算、渲染只读缓存」（`_analysis_mixin.py`
spec §4 的既有产品承诺）在 12 View 上限下**机械成立**——缓存是该承诺的唯一载体，
淘汰规则罩不住 View 上限时，承诺就静默失效。

## 2. 为什么现在做：6 → 12 之后的容量错配

merge `5477add1` 把四个分析分区的 View 上限从 6 提到 12（时域本来就是 12），但
`window.py:382` 的缓存容量仍是 6 View 时代标定的：

| 分区 | 容量 | 旧上限最坏绑定数 | 新上限最坏绑定数 |
| --- | --- | --- | --- |
| `fft_time` / `order` / `frf` | 12 | 6 View × 2 pane = **12**（恰好罩住） | 12 View × 2 pane = **24**（罩不住一半） |
| `fft`（按曲线计数） | 32 | 12 pane，人均 ~2.6 条曲线 | 24 pane，人均 ~1.3 条曲线 |

两个具体破产场景（均为纯 LRU 的结构性问题）：

- **轮巡**：把 12 个 View 都算出来后按顺序切一圈，后 12 个 pane 结果把前 12 个挤
  出缓存；切回第一个 View 得到空画布 +「点击计算」。用户视角：「我算过的结果丢了」。
- **参数迭代**：在一个 View 上反复调参重算（比如对一张时频图试 10 组 `nfft`），
  每次重算都是新 key 入缓存，把**其他 View** 的绑定结果逐个挤掉。这个场景说明
  **单纯加大容量只能推迟、不能消除**——任何固定容量都会被足够多的参数历史耗尽，
  所以本 spec 选 pinning 而不是调数字。

定性澄清：这不是卡顿问题。计算在 `AnalysisJobService` 的 QThread 上跑，切换本身
只读缓存渲染；破的是**结果留存**，表现为静默丢结果 + 被迫手动重算。

## 3. 唯一语义变化：`AnalysisResultCache.put` 的淘汰规则

```python
# 现状
while len(self._store) > self._capacity:
    self._store.popitem(last=False)

# 目标
pinned = self._pinned_provider() if self._pinned_provider else frozenset()
unpinned = [k for k in self._store if k not in pinned]
while len(unpinned) > self._capacity:
    del self._store[unpinned.pop(0)]        # 仍按插入序=LRU 序淘汰最老无主项
```

- `pinned_provider` 是构造时注入的可选回调（`AnalysisResultCache(capacity,
  pinned_provider=None)`），返回该分区当前被 pin 的键集合。cache 本身保持
  UI-free、可脱离窗口单测；provider 由 window 侧闭包提供。
- `get` / `invalidate_fid` / `clear` 行为不变。`invalidate_fid` **可以删除
  pinned 条目**——文件都没了，结果必然失效，pin 不是正确性屏障而是留存策略。
- 被 pin 的条目数可以超过 capacity（12 View × 2 pane 全算满时 heatmap 分区
  最多 24 个 pinned + 12 个无主历史）。这是设计意图，不是溢出 bug。
- `FrfAnalysisResultCache` 继承同一规则；`FrfCacheKey` 是 frozen dataclass，
  可直接进集合。

## 4. pin 记账：只记「实际用过的键」，禁止从 state 重推导

**这是本设计最重要的约束。** 缓存键经过「state → inspector 控件 → 过滤
compute params → json.dumps」这一条路产生（`_analysis_cache_key`，
`_analysis_mixin.py:601`）；写入键与查询键都出自这条路，所以天然逐字节一致。
若 pin 集合改从 `state.params` 直接重推导，Qt 控件 apply/get round-trip 的数值
归一化（spinbox 取整、float 精度）可能让 pin 键与真实键失配——失配的后果恰好
落在最需要保护的地方（pin 不住真实条目）。因此 pin 记账**必须**挂在两个已经
持有真实键的漏斗点上：

1. **渲染查键点**（切 View 时）：`_render_analysis_view_from_cache`
   （`_analysis_mixin.py:687`）与 `_render_frf_view_from_cache`
   （`_frf_mixin.py:629`）在为目标 View 逐 pane 枚举键时，把该
   `(section, view_id, pane_idx)` 的 pin 集合**整体替换**为本次枚举的全部键
   （无论命中与否——记的是当前绑定意图，未命中的键在之后计算落盘时已被 pin）。
2. **计算落盘点**（`cache.put` 时）：按 `(section, view_id, pane_idx)`
   **追加**本次写入的键。

记账簿归 window 所有：`_analysis_pins: dict[(section, view_id, pane_idx),
set[key]]`；每个分区 cache 的 `pinned_provider` = 对该 section 取并集。

替换/追加的组合有一个自清洁性质，作为设计依据明确记录：用户停在一个 View 上
连续调参重算会让该 pane 的 pin 集合暂时累积多组结果键（全部常驻，无法淘汰），
但**下一次切回该 View** 的渲染查键会把集合整体替换为当前键，旧参数的结果随即
变为无主、回到 LRU 尾巴。瞬时超额有界（单会话单 pane 的调参次数），且自动回收。
曾考虑「put 时按 (fid, ch) 同源替换」以消除瞬时超额，被否决：四种键形状
（fft/fft_time/order 元组 + FrfCacheKey）各需一套源身份提取，为一个有界且
自清洁的瞬态加常驻复杂度不值。

### 4.1 put 单点化（仿 batch `_RunReporter` 范式）

pin 追加若靠「每个 put 站点旁边手写一行记账」维持，必然腐化。所以把全部
`analysis_caches[...].put` 收拢到 window 的单一 helper：

```python
def _store_analysis_result(self, section, view_id, pane_idx, key, result):
    self.analysis_caches[section].put(key, result)
    self._analysis_pins.setdefault((section, view_id, pane_idx), set()).add(key)
```

现有 5 个直接 put 站点全部改道：

| 站点 | 身份来源 |
| --- | --- |
| `_fft_mixin.py:281`（同步循环） | 循环外的 active view state 就在作用域内 |
| `_order_mixin.py:351`（缓存命中回写） | 同上（此站点同时是一次“查键事件”，经 helper 顺带记 pin 正确） |
| `_order_mixin.py:688`（job 回调） | **dispatch 时**写入 ctx 的 `view_id`/`pane_idx`（见 §4.2） |
| `fft_time_coordinator.py:221` | coordinator 构造改为注入 window 的 store 回调；候选 dict 在 dispatch 时带 `view_id` |
| `frf_coordinator.py:285` | 同上 |

配 AST 守卫测试：`mf4_analyzer/` 内除该 helper 外不得出现对 analysis 缓存的
直接 `.put(`（含 coordinator——它们只持有 store 回调，不再持有裸 cache 的写权）。

view_id 缺失（None）时只入库不 pin，并经 logger 留痕——防未来某条 dispatch 路径
漏带身份造成永久 pin 泄漏。

### 4.2 异步身份规则

coordinator / order job 的完成回调可能在用户已切走 View 之后触发（generation
只在 `request_batch(replace=True)` 时递增，`fft_time_coordinator.py:82`，切
View 不作废在途任务——结果仍会落盘，只是不渲染）。因此 **view_id 必须在
dispatch 时刻捕获进 ctx/候选 dict**（此刻 active view 即计算目标），回调里
禁止读「当时的 active」。`fft_time` 候选 dict 经 `_build_context` 的
`dict(candidate)` 原样携带新字段，无 schema 阻力。

## 5. pin 生命周期

| 事件 | 动作 |
| --- | --- |
| 切到 View（渲染查键） | 该 View 各 pane 的集合整体替换（§4 第 1 点） |
| 计算落盘 | 追加（§4 第 2 点） |
| 删除 View | 剪掉 `(section, 该 view_id, *)` 全部条目（挂在删除 intent 处理器上，view_id 在删除前可得） |
| 复制 View | 不动。副本首次渲染时用相同键建自己的 pin 集合；同一条目被两个 view_id 引用，取并集天然正确 |
| `analysis_caches[s].clear()`（现仅 `window.py:2452` 一处） | 同步清空该 section 的 pin 条目 |
| `invalidate_fid` | 缓存条目照删（含 pinned，见 §3）；pin 簿里的死键**允许残留**——键不在 store 里就约束不了任何淘汰，无害，且下次渲染替换时自然消失。不做主动剪枝（那需要按 4 种键形状提取 fid，得不偿失） |
| 项目重开 | pin 簿从空开始；`_analysis_restore_pending` 的惰性重算经落盘点自然重建 |

pin 簿本身的内存上界：4 分区 × 12 View × 2 pane × pane 内键数（heatmap 为 1，
fft 为曲线数）个小元组——KB 量级，不需要治理。

## 6. 内存量刻画（接受的代价，明确写出）

`SpectrogramResult.amplitude` 是 float32 `(nfft//2+1, frames)`
（`signal/spectrogram.py:81`），典型 EPS 记录单张 1–15 MB；阶次图同量级；
fft 曲线为 KB–MB 级一维数组。

- 现状最坏驻留：12 条 × 单张上限 ≈ 每 heatmap 分区 ~180 MB。
- 本设计最坏驻留：24 pinned + 12 无主 = 36 条 ≈ 每分区 ~540 MB——但 pinned
  部分只在用户**显式**算满 12 View × 2 pane 时才存在，内存归用户的操作决定，
  这与「显式加载 10 个大文件就占 10 个文件的内存」同一伦理。无主部分维持现状
  容量不变。
- 按字节预算淘汰（`nbytes` 易求）作为后续增强记入 §9 非目标，不进本次。

## 7. 行为矩阵（验收）

| 场景 | 必须结果 |
| --- | --- |
| 4 个分区各建 12 View、全部算满（heatmap 单 pane） | 任意顺序轮巡切换，全部命中缓存渲染，零「点击计算」空态 |
| 12 View × 2 pane 算满（24 绑定 > 容量 12） | 同上，轮巡零 miss |
| 停在一个 View 连续调参重算 20 次 | 其他 11 个 View 的绑定结果一个不丢；该 View 的 20 组历史里最老的按 LRU 淘汰 |
| 调参后**未**重算就切走再切回 | 维持现状：键失配 → 空态 +「点击计算」（这是「参数变了结果就是旧的」的既有设计，本次不改动、不劣化） |
| 删除已算满的 View | 其结果变为无主，随后续写入按 LRU 正常淘汰（不立即清除） |
| 移除文件（`invalidate_fid`） | 涉该文件的条目照删，含 pinned；其余 View 不受扰动 |
| 项目重开 + 惰性重算 | 每个 View 首次访问重算后即被 pin，之后轮巡零 miss |
| `test_nonuniform_fft_full_flow` 等现有断言 `_store` 长度/键形状的测试 | 缓存对象身份、键形状、`_store` 语义不变，全部原样通过 |

## 8. 验收标准

1. `AnalysisResultCache` 单元测试：pinned 条目在任意 put 风暴下不被淘汰；无主
   条目严格按 LRU、容量语义为「无主条数」；`pinned_provider=None` 时行为与现状
   逐字节一致（这是所有不关心 pin 的既有用例的兼容面）。
2. 集成守卫测试（offscreen）：§7 前三行场景各一条用例，作为常驻护栏放
   `tests/ui/`，红了修代码不是放宽。
3. AST 守卫：直接 `.put(` 只允许出现在单点 helper 内（§4.1）。
4. 异步身份：构造「dispatch 后立刻切 View 再等回调」的用例，断言结果 pin 到
   dispatch 时的 View 而不是回调时的 active View。
5. 全量套件按两条命令跑法维持基线（主体 + `tests/acquisition_ui` 分开），改动
   前后失败数不增。

## 9. 非目标

- 不做字节预算淘汰（记为后续增强；见 §6）。
- 不改「切换绝不自动重算」的产品语义，不为 cache miss 加自动重算。
- 不改容量常量 32/12/12 的数值，不新增可调旋钮。
- 不做分析结果的磁盘持久化 / 跨会话留存（项目文件仍是 recompute-on-open）。
- 不处理「调参未重算切回显示空态」——那是键语义的既有设计，另议。
- 时域侧零改动（时域切换是全量重画，无结果缓存概念）。
- 附带小修（独立于缓存，见 plan Task 7）：`_view_mixin.py:182` 的 View 快捷键
  仍是 `range(6)`，与 12 View 口径不一致；扩到 Alt+1..9（Alt+10 以上不是单一
  按键弦，10–12 号 View 走标签栏/溢出菜单）。

## 10. 回退

`AnalysisResultCache` 的 `pinned_provider` 参数可选、默认 None 即现状行为；
回退 = 摘掉 window 侧记账簿与 provider 注入、把 5 个 put 站点改回直写。无
schema、无项目文件、无 QSettings 迁移。

# FFT/Order「计算 vs 显示」参数边界根治 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **项目规矩(CLAUDE.md):** 所有代码改动经专家子 agent。数值算法/缓存键/dB → `signal-processing-expert`；UI 控件/tooltip/测试夹具 → `pyqt-ui-engineer`。

**Goal:** 根治「拖动色阶后与重算结果不一致」这一 bug 类，并从结构上消除 FFT/Order 各 section「计算参数 vs 显示参数」边界靠人手维护、散落多处而导致的同形态隐患，使同类问题结构上不可复发。

**Architecture:** 四条不变量 ——(A) 计算参数全集由 frozen dataclass(`SpectrogramParams`/`COTParams`)单一定义，缓存键从 dataclass **机械派生**而非手抄；(B) 显示参数(色阶/动态范围)**绝不**写回存储数据矩阵，只改显示 levels；(C) amplitude→dB 转换收敛到**单一** helper；(D) 凡改动某文件计算输入的操作走**单一**缓存失效入口。7 个节点**严格串行**(同文件深耦合,不可并行),全程 TDD。

**Tech Stack:** Python · NumPy · scipy.signal · PyQt5 · pyqtgraph · pytest / pytest-qt。

## Global Constraints

- **严格 TDD**:每个节点先写 RED 失败测试再实现;缓存键变更、dB 数值变更**必须**展示红→绿两相。
- **基线**:非 slow 测试 `pytest`(pytest.ini 默认 `-m "not slow"`)当前 **2349 passed**,全程任一节点结束都不得回归。
- **git add 用显式 pathspec**(`git add <精确文件>`),**绝不** `git add -A`/`git add .`(用户可能同时在同一工作树跑 codex;见 lesson workflow-parallel-codex-same-worktree)。提交用 `git commit -- <路径>` 锁定。
- **契约爆炸半径**:动 `SpectrogramParams`/`COTParams` 字段必须在**同一节点**内更新其全部消费者(result.params 序列化、`batch.py` `_run_one`、preset IO、project IO、canvas `_result_db_token` memo)。不得拆给别的专家造成 flag 往返。
- **验真机渲染**:任何 UI/视觉断言(色阶拖动、db_reference 改变、tooltip)必须验真实渲染(截图 / objc 读原生属性),不得凭「属性设上了 + 单测过」判定(CLAUDE.md gotcha + memory verify-ui-visually)。
- **面向用户文案**不夹 `pyqtgraph`/类名/文件路径等开发术语(memory user-facing-manual-not-technical)。
- **7 节点全串行**,不并行——文件簇重叠(`heatmap_canvas.py`: P1/P2/P3/P6;`_*_mixin.py`+`window.py`: P3/P4;`order_cot.py`: P3/P5;三个 `contextual_*.py`: 仅 P6)。

---

## File Structure

| 文件 | 职责 | 触及节点 |
|---|---|---|
| `mf4_analyzer/signal/spectrogram.py` | `amplitude_to_db` 唯一 helper(权威 dB 语义);`SpectrogramParams` 计算契约(去 db_reference) | P1, P3 |
| `mf4_analyzer/signal/order_cot.py` | `COTParams` 计算契约;COT compute 真正消费 `time_res` 推 hop | P3, P5 |
| `mf4_analyzer/signal/fft.py` | (P7 仅特征测试,不改 math) Welch 口径 | P7(测试) |
| `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` | 删 manual dB 分支 clip+peak ref;dB 经 helper;render 时读 inspector db_reference;`_result_db_token` memo | P1, P2, P3, P6 |
| `mf4_analyzer/ui/main_window/_fft_mixin.py` | `_amplitude_to_db`→helper;FFT 缓存键加 fs | P1, P3 |
| `mf4_analyzer/ui/main_window/_order_mixin.py` | Order dB→helper;order 缓存键加 window | P1, P3 |
| `mf4_analyzer/ui/main_window/_fft_time_mixin.py` | fft_time 缓存键去 db_reference、机械派生 | P3 |
| `mf4_analyzer/ui/main_window/_analysis_mixin.py` | 统一 key 分发;fallback 复用主键 | P3, P4 |
| `mf4_analyzer/ui/main_window/window.py` | 重建时间轴/改 Fs 走单一失效入口 | P4 |
| `mf4_analyzer/ui/main_window/_project_io_mixin.py` | 单一失效入口的参考实现(:236 已是全清) | P4 |
| `mf4_analyzer/batch.py` | dB→helper;SpectrogramParams 构造去 db_reference | P1, P3 |
| `mf4_analyzer/ui/inspector_sections/contextual_fft.py` `_fft_time.py` `_order.py` | `_apply_preset_values` 加 weighting 守卫;time_res tooltip | P6, P7 |
| `tests/ui/test_pg_heatmap_canvas.py` 等 | 改正锁死坏契约的测试;不变量/守卫/特征测试 | P2, P3, P4, P6, P7 |

---

## Task 1 (P1/C/⑦): amplitude→dB 收敛到单一 helper

**Files:**
- Modify: `mf4_analyzer/signal/spectrogram.py:128-156`(`amplitude_to_db` 已存在,定为权威)
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py:410`、`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:1134-1139`、`mf4_analyzer/ui/main_window/_fft_mixin.py:27`、`mf4_analyzer/batch.py:781`
- Test: `tests/signal/test_spectrogram.py`(或就近)、各调用方就近测试

**Interfaces:**
- Produces: `SpectrogramAnalyzer.amplitude_to_db(amplitude, reference=1.0) -> np.ndarray`,语义=`20*log10(maximum(amp, np.finfo(float).tiny)/ref)`,`ref<=0` raise;**调用方一律传 `max(ref, 1e-12)`**。
- Consumes: 无(最先落地)。

- [ ] **Step 1 (RED):** 写特征测试钉死 helper 输出:(a) 正常幅值;(b) 幅值<floor → 钳到 `tiny` 而非 `1e-12`;(c) 调用方 `max(ref,1e-12)` 守卫使 `ref<=0` 仍得有限值。再写 parity 测试:每个旧调用点改造后输出==helper 值(in-range data 差 `<1e-6` dB)。`heatmap_canvas.py:1134` 的 **peak ref→绝对 ref** 是语义修复,显式 characterize 新旧差异。
- [ ] **Step 2:** 跑测试确认失败(parity 测试当前红,因调用点还是内联)。
- [ ] **Step 3 (GREEN):** 把 4 处内联 `20*log10(...)` 改为 `from ...signal.spectrogram import SpectrogramAnalyzer` 调 `amplitude_to_db`,调用方传 `max(ref,1e-12)`。`heatmap_canvas.py` 的 peak-ref 改绝对 ref(若该 dB 分支保留;P2 可能整段删,届时此处随之消解——P1 先统一语义,P2 决定去留)。
- [ ] **Step 4:** 跑就近测试 + 全量非 slow,确认绿、无回归。
- [ ] **Step 5 (commit):** `git add mf4_analyzer/signal/spectrogram.py mf4_analyzer/ui/main_window/_order_mixin.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/main_window/_fft_mixin.py mf4_analyzer/batch.py tests/...` → `git commit -- <同上路径> -m "refactor(signal): converge dB conversion onto single amplitude_to_db helper"`

**Lessons:** signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface(grep 每个**消费端**,非只改产出端)。
**Verify:** `pytest -q` 全绿;parity 测试证明 in-range 数值不变。

---

## Task 2 (P2/B/⑥): 删 manual dB 分支 clip+peak ref;改正锁死的测试;扩展不变量

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:1133-1142`(`plot_or_update_heatmap` dB 分支)
- Modify: `tests/ui/test_pg_heatmap_canvas.py:237-248`(`test_db_mode_manual_levels_clip`)、:439、:454
- Test: 同文件新增/扩展 display-only 不变量

**Interfaces:**
- Consumes: Task 1 的 `amplitude_to_db`(不得在 canvas 内重建 dB 副本)。
- Produces: 「manual(z_auto=False)色阶纯 display-only」不变量——存储矩阵不被裁,仅 levels 变。

- [ ] **Step 1 (RED):** 改 `test_db_mode_manual_levels_clip`:把 `img.min()==-30`(:248)改为未裁的 `≈-40`,`getLevels()` 仍断言 `(-30,0)`;核对并修 :439/:454 相关断言。新增不变量测试:对所有 heatmap canvas 的 z_auto=False 分支,断言「改 z_floor/z_ceiling/dynamic 后 `_matrix_disp` 逐字节不变,只有显示 levels 变」。跑,确认红(当前 clip 行为使矩阵 min=-30)。
- [ ] **Step 2:** 确认红来自现存 clip。
- [ ] **Step 3 (GREEN):** 删 `heatmap_canvas.py:1140-1141` 的 `if not z_auto: m_disp = np.clip(m_disp, z_floor, z_ceiling)`;peak ref(:1134)在 Task 1 已转绝对/或整 dB 分支删除(确认无生产调用方:`plot_result`、`_render_order_on` 均传 `amplitude_mode='amplitude'` 绕开)。manual 仅 `vmin,vmax=z_floor,z_ceiling` 当显示 levels。
- [ ] **Step 4:** 跑该模块 + 全量非 slow,确认绿。
- [ ] **Step 5 (verify render):** 真机渲染验证:加载数据→FFT-vs-Time→manual 设极端色阶[27,67]→拖回→确认细节可恢复(非烘死)、hover/切片读真 dB 值。截图留证。
- [ ] **Step 6 (commit):** `git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py` → `git commit -- <同上> -m "fix(ui): manual dB color-scale is display-only; drop matrix clip + peak ref; correct locked test"`

**Lessons:** pyqt-ui/2026-06-11-slice-must-read-same-display-matrix-as-heatmap;pyqt-ui/2026-06-21-heatmap-auto-level-absolute-vs-relative;CLAUDE.md 验真机渲染。
**Verify:** 不变量测试绿;真机拖色阶可逆;`pytest -q` 无回归。

---

## Task 3 (P3/A/①③④⑨): frozen dataclass 成计算契约唯一定义,缓存键机械派生

**Files:**
- Modify: `mf4_analyzer/signal/spectrogram.py:56-74`(`SpectrogramParams` 去 `db_reference`)、`mf4_analyzer/signal/order_cot.py:24-45`(`COTParams`)
- Modify: `_fft_mixin.py:79`(加 fs)、`_fft_time_mixin.py:54/86/106`(去 db_reference,派生)、`_order_mixin.py:141`(加 window)、`_analysis_mixin.py`(`_analysis_compute_params`/`_analysis_cache_key` fft_time 分支去 db_reference)
- Modify(契约消费者): `batch.py` `_run_one` 的 `SpectrogramParams` 构造、preset IO、project IO、`heatmap_canvas.py:1514` `plot_result` + `_result_db_token`
- Test: `tests/ui/`、`tests/signal/` 缓存键 + 守卫测试

**Interfaces:**
- Consumes: Task 1/2(heatmap dB 已统一、clip 已删——`_result_db_token` 在本节点同一专家手中改,无跨专家重叠)。
- Produces: 缓存键由 dataclass 字段机械派生的主键函数(供 P4 fallback 复用);`db_reference` 不在任何 compute 键、仅留在 `get_params`+render 签名。

- [ ] **Step 1 (RED):** 写失败的缓存键测试:
  - ① 「重建 Fs → fft/order 主键改变 → 不命中旧缓存」(单帧模式 nfft=None 也须变键,因 key 含 fs)。
  - ③ 「改 db_reference → fft_time 主键**不变** → 不触发重算」(用 compute 调用计数器断言)。
  - ⑨ 「order 主键含 window」。
  - 守卫测试(措施 A 核心):断言 `SpectrogramParams`/`COTParams` **每个字段都被对应 `compute()` 读取**(introspect/call-trace),且**无显示字段**(db_reference)残留在 dataclass/派生键。
- [ ] **Step 2:** 跑,确认红。
- [ ] **Step 3 (GREEN):** ① `_fft_compute_cache_params` 纳入 fs 并确定性解析 nfft;③ 从 `SpectrogramParams` 与 5 处键(`_fft_time_analysis_cache_key`/`_fft_time_cache_key`/`_analysis_compute_params`/`_analysis_cache_key` fft_time 分支)移除 db_reference;⑨ order 键加 `'window': p.get('window','hanning')`。让缓存键由 dataclass 字段派生(替代手抄 dict)。**同节点**更新全部契约消费者(batch/preset IO/project IO/`_result_db_token`+`plot_result:1514`);`db_reference` 保留在 `get_params`+render 签名(P6 接 render 时读)。
- [ ] **Step 4:** 跑全量非 slow + batch/preset/project 往返测试,确认绿、序列化无破。
- [ ] **Step 5 (commit):** 显式 pathspec `git add` 上列文件 → `git commit -- <...> -m "refactor(cache): derive analysis cache keys from compute dataclass; drop display-only db_reference; add fs/window; guard test"`

**Lessons:** pyqt-ui/2026-06-11-cache-key-stability-id-reuse-and-param-roundtrip;pyqt-ui/2026-06-21-display-param-guard-vs-preset-load;orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update。`_project_io_mixin.py:236` 作为「全失效」参考。
**Verify:** 守卫测试绿(字段↔compute 一一对应);①③⑨ 测试绿;全量无回归。

---

## Task 4 (P4/D/① part/④): 缓存失效单一入口;fallback 复用主键

**Files:**
- Create/Modify: `mf4_analyzer/ui/main_window/` 新增 `_invalidate_all_analysis_caches_for_fid(fid)`(参考 `_project_io_mixin.py:236`)
- Modify: `window.py:1233`(重建路)、Fs 变更路、文件关闭路 → 全走新入口
- Modify: `_analysis_mixin.py:424-437`(fallback 改调 Task 3 主键函数)
- Test: `tests/ui/`

**Interfaces:**
- Consumes: Task 3 的主键函数(`_fft_time_analysis_cache_key`)。
- Produces: 单一失效入口;fallback 键 == 主键(键形不分叉)。

- [ ] **Step 1 (RED):** 测试:① 「重建 Fs 后 fft 与 order 缓存对该 fid 均失效」(断旧键不再命中);④ 「fallback 键 == 主键(含 weighting,逐字节相等)」→ A 计权结果命中而非空白。跑确认红。
- [ ] **Step 2:** 确认红(当前重建路只清 fft_time;fallback 漏 weighting)。
- [ ] **Step 3 (GREEN):** 实现 `_invalidate_all_analysis_caches_for_fid`,把重建/改 Fs/关闭三路接入;`_analysis_mixin.py:424-437` 自建 dict 改调主键函数。
- [ ] **Step 4:** 跑全量非 slow,确认绿。
- [ ] **Step 5 (commit):** `git add window.py _analysis_mixin.py _project_io_mixin.py tests/...` → `git commit -- <...> -m "fix(cache): single invalidation entry for fid compute-input changes; fallback reuses main key"`

**Lessons:** signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface;pyqt-ui/2026-06-11-cache-key-stability-id-reuse-and-param-roundtrip。
**Verify:** ①④ 测试绿;重建 Fs 后单帧 FFT 频率轴正确(可加端到端断言)。

---

## Task 5 (P5/②): COT 真正消费 time_res 推 hop

**Files:**
- Modify: `mf4_analyzer/signal/order_cot.py:120-125`(hop 由 time_res 派生)
- Test: `tests/signal/test_order_cot.py`

**Interfaces:**
- Consumes: Task 3(COTParams + 键定型,time_res 仍为 keyed 字段)。
- Produces: hop = f(time_res) 的角度域映射(time_res↓ ⇒ hop↓ ⇒ 时间切片更细),`1 ≤ hop ≤ nfft`。

- [ ] **Step 1 (RED):** 特征测试:(a) 两个不同 time_res → **不同** hop 且 COT 结果时间切片**数量不同**;(b) 单调(time_res 越小切片越多);(c) 极端值下 hop 边界成立。跑确认红(当前 hop 写死 `nfft*0.25`,time_res 无效)。
- [ ] **Step 2:** 确认红。
- [ ] **Step 3 (GREEN):** 在 `order_cot.py` 由 `params.time_res` 推角度域 hop(替换 `hop_angle = max(int(nfft*0.25),1)`),映射有界(≥1,≤nfft)。不动 UI/tooltip(P7 负责文案)。
- [ ] **Step 4:** 跑 signal 测试 + 全量非 slow,确认绿。
- [ ] **Step 5 (commit):** `git add mf4_analyzer/signal/order_cot.py tests/signal/test_order_cot.py` → `git commit -- <...> -m "fix(order): COT consumes time_res to derive hop (honor time-resolution control)"`

**Lessons:** signal-processing/2026-05-19-branch-reached-is-not-behavior-correct(证明两输入→严格不同输出,非一次性分支覆盖)。
**Verify:** 两 time_res→不同切片数;单调成立。

---

## Task 6 (P6/③ canvas/⑤): canvas dB 读 inspector 实时 db_reference;三面板 preset 守卫

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`(FFT-vs-Time dB 转换读 inspector 当前 db_reference;`plot_result:1514`+`_result_db_token` memo 锚在显示 db_reference)——**仅限 db_reference 显示读取路径与 memo,禁碰 dB-math/clip 行**
- Modify: `contextual_fft.py:498`、`contextual_fft_time.py:845`、`contextual_order.py:470`(`_apply_preset_values` 加 `if 'weighting' in d:` 守卫)
- Test: `tests/ui/`

**Interfaces:**
- Consumes: Task 3(db_reference 已是纯显示,仅在 get_params+render 签名)、Task 5。
- Produces: 改 db_reference → 仅重渲染、不重算;旧预设无 weighting 键时不重置计权。

- [ ] **Step 1 (RED):** (A) 测试:改 db_reference → 图按新 dB 窗重绘但 `_matrix_disp` 不变且**无重算**(compute 计数器断言),切片/readout 与图一致(读同一 `_matrix_disp`);(B) 测试:加载无 `'weighting'` 键的预设 dict → 三面板现有 weighting 保留、不被重置为 None。跑确认红。
- [ ] **Step 2:** 确认红。
- [ ] **Step 3 (GREEN):** (A) FFT-vs-Time canvas dB 转换改读 inspector 当前 db_reference(镜像 Order 的 `order_params.get('db_reference')`);确认 `_result_db_token` memo 锚显示 db_reference;核对 batch/preset/project IO 仍把 db_reference 作显示字段往返。**边界栅栏**:若发现必须改 dB-math 行 → 停并 flag 回主 Claude(那属 P1/P2 范围)。(B) 三面板 `_apply_preset_values` 加守卫。
- [ ] **Step 4:** 跑全量非 slow,确认绿。
- [ ] **Step 5 (verify render):** 真机:改 dB 参考即时重绘无「正在计算」、无色阶跳变;加载老预设 A 计权不丢。截图留证。
- [ ] **Step 6 (commit):** `git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/inspector_sections/contextual_fft.py mf4_analyzer/ui/inspector_sections/contextual_fft_time.py mf4_analyzer/ui/inspector_sections/contextual_order.py tests/...` → `git commit -- <...> -m "fix(ui): FFT-vs-Time reads db_reference at render time (no recompute); guard preset weighting in 3 panels"`

**Lessons:** pyqt-ui/2026-06-21-display-param-guard-vs-preset-load(直接先例);pyqt-ui/2026-06-11-slice-must-read-same-display-matrix-as-heatmap;CLAUDE.md 验真机渲染。
**Verify:** A/B 测试绿;真机 db_reference 改变无重算、计权保留。

---

## Task 7 (P7/⑧/②-tooltip): Welch 口径标注;time_res tooltip 校正;特征测试钉数

**Files:**
- Modify: FFT 平均模式选择处的 UI 提示(tooltip/inline note);`contextual_order.py:123-128`(time_res tooltip 校正)
- Test: `tests/`(Welch vs 单帧 dB 差特征测试 + tooltip 文案断言)
- **不改** `fft.py` math。

**Interfaces:**
- Consumes: Task 5(time_res 已是真控件)。
- Produces: Welch −3dB 口径的用户可见标注 + 锁数特征测试;time_res tooltip 与真实行为一致。

- [ ] **Step 1 (RED):** 特征测试:同一正弦,Welch 平均与单帧的 dB 偏移 ≈ −3.01dB(√2)在容差内;跑确认红(尚无该测试/无标注)。
- [ ] **Step 2:** 确认红。
- [ ] **Step 3 (GREEN):** (A) 在用户选 Welch/单帧处加口径差异标注(面向用户、无术语);加锁数特征测试。(B) 改 `contextual_order.py` time_res tooltip 为与 P5 真实行为相符(越小越细)且承诺为真。
- [ ] **Step 4:** 跑全量非 slow,确认绿。
- [ ] **Step 5 (verify render):** 真机确认 tooltip/标注显示正确。
- [ ] **Step 6 (commit):** `git add mf4_analyzer/ui/inspector_sections/contextual_order.py <welch 标注文件> tests/...` → `git commit -- <...> -m "docs(ui): annotate Welch caliber (-3dB) and fix time_res tooltip; characterization test"`

**Lessons:** memory user-facing-manual-not-technical;CLAUDE.md 验真机渲染。
**Verify:** 特征测试钉住 3dB;tooltip 文案断言绿。

---

## Self-Review

- **Spec 覆盖:** ①→Task3/4;②→Task5(+Task7 tooltip);③→Task3(键)+Task6(render);④→Task3/4;⑤→Task6;⑥→Task2;⑦→Task1;⑧→Task7;⑨→Task3。措施 A→Task3;B→Task2;C→Task1;D→Task4。**无遗漏。**
- **占位符扫描:** 关键代码(helper 签名、缓存键派生、不变量/守卫/特征测试断言、失效函数、preset 守卫)均有明确契约;唯 time_res→hop 映射公式由专家在 TDD 中按「两输入→不同切片数 + 单调 + 有界」特征推导(非占位符,是 TDD 边界)。
- **类型一致:** `amplitude_to_db(amplitude, reference)` 全节点一致;主键函数 `_fft_time_analysis_cache_key` 在 Task3 产出、Task4 复用,命名一致。
- **串行依赖:** P1→P2→P3→{P4,P5}→P6→P7;P4/P5 都依赖 P3 但因 P5 改 `order_cot.py`、P4 改 `window.py`/`_analysis_mixin.py`,文件不冲突可顺序执行(本计划仍按 P4→P5 串行以稳妥)。

## Execution Handoff

按 CLAUDE.md squad runbook + superpowers:subagent-driven-development:每个 Task 派**新的**专家子 agent(P1–P5 `signal-processing-expert`,P6–P7 `pyqt-ui-engineer`),串行执行,节点间做 rework 检测(同文件跨专家改 = 写 cause:rework lesson),保留各专家 `tests_before/tests_after/ui_verified/files_changed`,最后聚合汇报。

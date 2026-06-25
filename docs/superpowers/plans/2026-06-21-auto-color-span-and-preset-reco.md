# 自动算法优化（色阶跨度 + 预设推荐）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让分析面板的「自动」算法不再用写死的常量无视数据——色阶自动跨度默认 30 dB、特殊情况自适应到 40 dB；预设推荐从「仅看单位」升级到「看信号性质」。

**Architecture:** 分两条线。线 A（色阶跨度）把目前散落在两处的自动窗口公式 `[ceiling − _AUTO_SPAN_DB, ceiling]` 收成单一 helper `_auto_db_window(matrix)`，先把默认跨度 40→30（用户噪声分析常态），再在同一个 helper 内加「按数据稳健动态范围自适应到 40」的特殊情况判别。线 B（预设推荐）在 `recommend_preset_for_unit` 之上叠加基于信号统计（crest/kurtosis、转速扫描率）的内容分类器。

**Tech Stack:** Python 3.12 · NumPy · PyQt5 · pytest（`.venv/bin/python -m pytest`，`-p no:cacheprovider`）。

## Global Constraints

- 运行测试一律用 `.venv/bin/python -m pytest`（系统无 `python`/裸 `pytest`）。
- TDD：先写失败测试→看它失败→最小实现→看通过→提交（小步）。
- **执行时机**：本计划**等 codex 当前 annotation/heatmap 批次收口后**再开工——线 A 触及 `heatmap_canvas.py`（codex 正在改），同树并行会冲突。开工前先 `git status` 确认 `heatmap_canvas.py` 不再是 codex 的活动文件。
- **并行同树提交纪律**：若开工时仍与 codex 共享工作树，按 [[workflow-parallel-codex-same-worktree]] 只提交本任务的 hunk（`git apply --cached` 拆 hunk），`heatmap_canvas.py` 这类共享文件不整文件 `git add`。
- 「自动色阶」语义是**显示-only**：绝不 clip 存储矩阵（见 `heatmap_canvas.py:1520` 注释与 [[project-analysis-db-reference-weighting-guard]] 的第四轮真因）。本计划只动「显示窗口 vmin/vmax 怎么算」，不动矩阵。
- 自动窗口的 ceiling 继续用稳健高百分位 `_robust_db_ceiling`（99%），**不要回退到 `np.nanmax`**（会被瞬态尖峰拉爆、整图发黑——已是历史教训）。

---

## 现状（执行前必读，行号会因 codex 改动漂移，按符号名重新定位）

自动色阶窗口公式当前**复制在两处**，这是要消除的重复：

1. `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` `plot_result` 内（约 1545-1546，`z_auto` 分支）：
   ```python
   data_hi = _robust_db_ceiling(m, _AUTO_CEILING_PCT)
   vmin, vmax = data_hi - _AUTO_SPAN_DB, data_hi
   ```
2. `mf4_analyzer/ui/main_window/_order_mixin.py`（约 478-480，阶次渲染 override）：
   ```python
   from ...ui.pg_canvas.heatmap_canvas import (_AUTO_CEILING_PCT, _AUTO_SPAN_DB, _robust_db_ceiling)
   data_hi = _robust_db_ceiling(matrix, _AUTO_CEILING_PCT)
   vmin_override = data_hi - _AUTO_SPAN_DB
   ```

常量定义：`heatmap_canvas.py:259 _AUTO_SPAN_DB = 40.0`、`:270 _AUTO_CEILING_PCT = 99.0`、`:273 def _robust_db_ceiling`。

预设推荐：`mf4_analyzer/ui/inspector_sections/_helpers.py:108 recommend_preset_for_unit`，单位表 `:82 _TORQUE_UNITS`、`:87 _VIBRATION_UNITS`（无 transient 分支 → 「时间优先」永不被单位推荐）。signal 包**目前无** crest/kurtosis/平稳性 helper。

---

# 线 A：色阶自动跨度

## Phase A1（执行就绪，无需用户数据）：默认 30 + 单一来源

把两处公式收成一个 helper，并把默认跨度从 40 改成 30。这一步**严格改善**——直接兑现「噪声分析常态 30 dB」，且为 Phase A2 留下唯一改动点。

### Task A1.1: 新增 `_auto_db_window` helper（默认跨度 30）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（`_AUTO_SPAN_DB` 常量 + `_robust_db_ceiling` 下方新增 helper）
- Test: `tests/ui/test_pg_heatmap_canvas.py`

**Interfaces:**
- Produces: `_auto_db_window(matrix) -> (vmin: float, vmax: float)`，其中 `vmax = _robust_db_ceiling(matrix, _AUTO_CEILING_PCT)`、`vmin = vmax - _AUTO_SPAN_DB`。
- Consumes: 已有 `_robust_db_ceiling`、`_AUTO_CEILING_PCT`。

- [ ] **Step 1: 写失败测试**

```python
def test_auto_db_window_default_span_is_30(qapp):
    import numpy as np
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc
    # p99 ≈ 10：构造一片 [-50, 10] 的矩阵，99 百分位落在 ~10
    m = np.linspace(-50.0, 10.0, 6001).reshape(1, -1)
    vmin, vmax = hc._auto_db_window(m)
    ceiling = hc._robust_db_ceiling(m, hc._AUTO_CEILING_PCT)
    assert vmax == ceiling
    assert abs((vmax - vmin) - 30.0) < 1e-9        # 默认跨度 30，不再是 40
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_auto_db_window_default_span_is_30 -v -p no:cacheprovider`
Expected: FAIL（`_auto_db_window` 不存在 / 跨度仍 40）

- [ ] **Step 3: 最小实现**

把常量改为 30 并新增 helper（紧邻 `_robust_db_ceiling`）：

```python
_AUTO_SPAN_DB: float = 30.0   # was 40.0 — 噪声分析常态窗口；特殊情况由 Phase A2 自适应放宽


def _auto_db_window(matrix):
    """绝对-dB 自动色阶窗口的单一来源，返回 (vmin, vmax)。

    顶 = 稳健高百分位 ceiling（抗瞬态尖峰）；跨度 = ``_AUTO_SPAN_DB``。
    plot_result 的 z_auto 分支与 _order_mixin 的阶次 override 都走这里，
    保证两条路径的自动窗口字节一致（消除历史上的复制公式漂移）。
    """
    ceiling = _robust_db_ceiling(matrix, _AUTO_CEILING_PCT)
    return ceiling - _AUTO_SPAN_DB, ceiling
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_auto_db_window_default_span_is_30 -v -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tests/ui/test_pg_heatmap_canvas.py
git apply --cached <(git diff -- mf4_analyzer/ui/pg_canvas/heatmap_canvas.py)   # 若共享则只拆本 hunk
git commit -m "feat(ui): 色阶自动窗口单一 helper + 默认跨度 40→30"
```

### Task A1.2: 两处调用点改用 helper

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（`plot_result` z_auto 分支）
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`（阶次 override 分支）
- Test: `tests/ui/test_pg_heatmap_canvas.py`、`tests/ui/test_main_window_smoke.py`（更新任何断言 40 dB 自动窗口的既有用例为 30）

**Interfaces:**
- Consumes: `_auto_db_window`（Task A1.1）。

- [ ] **Step 1: 写失败测试**（断言 plot_result 的 z_auto 窗口跨度=30；用既有 heatmap 渲染测试夹具，读 `_last_auto_levels`）

```python
def test_plot_result_z_auto_window_uses_30db(qapp, qtbot):
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import HeatmapCanvas  # 按实际类名/构造调整
    # ……用既有夹具构造一个 result（dB 矩阵 p99≈0），plot_result(z_auto=True)……
    # 断言 canvas._last_auto_levels 跨度为 30：
    vmin, vmax = canvas._last_auto_levels
    assert abs((vmax - vmin) - 30.0) < 1e-9
```
> 注：按 `tests/ui/test_pg_heatmap_canvas.py` 既有渲染夹具补全构造；若已有「自动窗口」用例，直接改其期望 40→30 并复用。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -k z_auto -v -p no:cacheprovider`
Expected: FAIL（仍 40）

- [ ] **Step 3: 最小实现**

heatmap_canvas `plot_result` z_auto 分支：
```python
            if z_auto:
                vmin, vmax = _auto_db_window(m)
                self._last_auto_levels = (vmin, vmax)
```
_order_mixin override：
```python
            from ...ui.pg_canvas.heatmap_canvas import _auto_db_window
            vmin_override, vmax_override = _auto_db_window(matrix)
```
（删掉两处对 `_AUTO_SPAN_DB`/`_robust_db_ceiling` 的直接复制；`_order_mixin` 若只用 vmin，则取 `vmin_override` 即可。）

- [ ] **Step 4: 运行确认通过 + 跑相关回归**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py tests/ui/test_main_window_smoke.py -p no:cacheprovider`
Expected: PASS（更新任何旧的 40 dB 断言为 30）

- [ ] **Step 5: 提交**

```bash
git commit -m "refactor(ui): 阶次/谱图自动色阶统一走 _auto_db_window（消除复制公式）"
```

## Phase A2（数据闸门：需要用户代表性数据后再细化）：自适应放宽到 40

**目标**：默认 30；当数据**确有**有意义的内容落在 ceiling 下 30–40 dB 区间时，自动放宽到 40；高信噪比稀疏图（噪声地板很深但内容都在顶部 30 dB 内）**仍保持 30**。

**候选算法（待数据验证，勿凭空定阈值）**：在 `_auto_db_window` 内
```
ceiling = _robust_db_ceiling(m, 99)
# 「特殊情况」探针：ceiling 下 [30,40] 这一带里，高于噪声地板估计的单元占比
band = cells in [ceiling-40, ceiling-30]
floor_est = robust 噪声地板估计（如低百分位 / 直方图主峰）
frac = fraction(band 中 > floor_est + margin)
span = 40 if frac >= FRAC_THRESH else 30
```
**为什么不能简单用 `clamp(p99 - p_low, 30, 40)`**：稀疏高信噪比阶次图里低百分位掉进噪声地板 → 恒判 40，违背「默认 30」。必须区分「带内是真信号还是地板」。

**需要用户提供（提供后我把本 Phase 细化成可执行 TDD 任务）**：
- 5–10 份代表性谱图/阶次数据（覆盖：典型噪声、强单频、富谐波、瞬态/冲击各若干）；
- 每份你期望的色阶跨度（30 还是 40），即标注；
- 由此标定 `FRAC_THRESH`、`floor_est` 方法与 `margin`，并验证「典型噪声→30、富内容→40、稀疏高 SNR→30」。

---

# 线 B：智能预设推荐（数据闸门）

**现状问题**：`recommend_preset_for_unit` 只按单位分 torque/vibration，「时间优先(transient)」永不被推荐；且预设本质是**时频分辨率取舍**，单位不足以决定。

**目标设计**：单位给先验，信号统计做精修——
- **频率优先**：平稳、强单频/窄带（需分辨相邻阶次/谱线）。指标：转速方差小、谱平稳。
- **时间优先**：瞬态/非平稳。指标：crest factor / kurtosis 高（冲击性）、转速扫描快（`|dRPM/dt|` 大）、短促事件。
- **均衡**：默认 / 中间态。

**新增 helper（signal 包，目前没有）**：`crest_factor(sig)`、`kurtosis(sig)`、（阶次相关）转速扫描率；这些是数值算法，按 [[CLAUDE.md]] 走 `signal-processing-expert` + TDD。

**需要用户提供（提供后细化为可执行任务）**：
- 你们常用的**通道单位清单**（扩 `_TORQUE_UNITS`/`_VIBRATION_UNITS`，并决定声学/压力等映射到哪个预设）；
- 一批信号样本 + 「这条你会选哪个预设」的标注，用来标定 crest/kurtosis/扫描率阈值；
- 是否希望推荐随**载入数据**实时变化（需把分类器接到 `_on_inspector_signal_changed`，类似本次 nfft 的 provider 模式）。

---

## 执行顺序与依赖

1. **等 codex heatmap/annotation 批次收口**（硬前置，见 Global Constraints）。
2. **Phase A1**（A1.1 → A1.2）：默认 30 + 单一 helper。立即可做、收益最大、风险最低。
3. **Phase A2 / 线 B**：待用户给数据后，分别把对应「需要用户提供」清单落成可执行 TDD 任务，再实现。

## Self-Review 记录

- 覆盖：用户两诉求（色阶默认 30/特殊 40 自识别、推荐更智能）均有对应 Part；可立即执行的部分（默认 30 + 去重）已写成完整 TDD 任务。
- 占位扫描：A2/线 B 的阈值**有意不写死**——明确标注「数据闸门」并列出所需数据，而非伪造数字（符合「阈值须用真实数据标定」的判断）。
- 一致性：helper 名 `_auto_db_window`、返回 `(vmin, vmax)` 在 A1.1/A1.2 一致；ceiling 仍走 `_robust_db_ceiling(99%)` 全程不变。

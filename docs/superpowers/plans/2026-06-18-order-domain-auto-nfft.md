# Order 段「自动 nfft」（角度域）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现。复选框（`- [ ]`）跟踪。每任务先写失败测试，再实现，再跑测试。

**Goal:** 给 Order 段补一个**角度域**的「自动 nfft」，与时频图的 fs 自动并列。Order 的 nfft 不是时间域（`fs×秒`），而是角度域：阶次分辨率 `Δorder = samples_per_rev / nfft`。所以自动规则按**目标阶次分辨率**解析：`nfft = ceil_pow2(samples_per_rev / order_res)`，再按角度域数据长度（总转数×每转样本数）加帧数/窗占比护栏。

**Architecture:** 复用既有 `signal/adaptive.py` 的 `resolve_nfft` —— 把「fs」换成 `samples_per_rev`、「t_win_s」换成 `1/order_res`、「N」换成角度域采样数 `n_angle`，护栏量纲自洽。新增薄封装 `resolve_order_nfft` 表达角度域语义。OrderContextual 的 `combo_nfft` 加「自动」并默认；预设不需新字段（自动由各预设已有的 `order_res`+`samples_per_rev` 推导）；真正计算时在 main_window 用真实 `n_angle` 解析后再喂给 `COTParams`。

**Tech Stack:** Python, numpy, PyQt5, pytest。

参考 spec：`docs/superpowers/specs/2026-06-17-fs-adaptive-analysis-defaults.md`（A/B/C 的同源设计）。
关键代码：`signal/order_cot.py`（`COTParams.nfft`、bin→`k*samples_per_rev/nfft`、`len(theta)<nfft` 会抛）；`ui/inspector_sections.py` 的 `OrderContextual`；`ui/main_window.py` 的 `do_order_time` / 阶次参数组装。

> **测试环境：** `tmp_path` 报 `WinError 5` 时加 `--basetemp=.pytmp/run`。解释器 `.venv/Scripts/python.exe`。真实数据：`D:\1. work\P779_S92_260616`（注意：这批数据转速反向，阶次本不适用、会触发提示——验证 auto **解析正确**即可，不强求结果有意义）。

---

### Task 1：纯函数 `resolve_order_nfft` + 单测

**Files:**
- Modify: `mf4_analyzer/signal/adaptive.py`、`mf4_analyzer/signal/__init__.py`（导出）
- Test: `tests/test_signal_adaptive.py`

- [ ] **Step 1：写失败测试**
  - `resolve_order_nfft(samples_per_rev=256, order_res=0.05, n_angle=10**6)` → 8192（256/0.05=5120→ceil_pow2=8192）。
  - `samples_per_rev=512, order_res=0.10` → 8192（512/0.1=5120→8192）。
  - `samples_per_rev=256, order_res=0.25` → 1024（256/0.25=1024）。
  - 角度域数据短（`n_angle` 小）→ 帧数/窗占比护栏把 nfft 降下来。
  - 下限/上限封顶（floor=256 / ceil=16384）。
- [ ] **Step 2：实现**（委托 `resolve_nfft`）
  ```python
  def resolve_order_nfft(samples_per_rev, order_res, n_angle_samples, *,
                         overlap=0.75, floor=256, ceil=16384,
                         min_frames=8, max_window_frac=0.5):
      # 角度域：fs<-samples_per_rev, t_win<-1/order_res, N<-n_angle
      return resolve_nfft(float(samples_per_rev), int(n_angle_samples),
                          1.0/float(order_res), overlap,
                          floor=floor, ceil=ceil,
                          min_frames=min_frames, max_window_frac=max_window_frac)
  ```
  （min_frames/max_window_frac 比时间域宽松：阶次窗几转即可，可调。）
- [ ] **Step 3：跑测试** `… -m pytest tests/test_signal_adaptive.py -q`

---

### Task 2：OrderContextual 接入「自动」+ 预设 + 摘要

**Files:** `mf4_analyzer/ui/inspector_sections.py`（`OrderContextual`），`tests/ui/test_inspector.py`

- [ ] `combo_nfft`（items `['512'..'8192']` 默认 `'2048'`）→ 加 `self._AUTO_NFFT_LABEL`（"自动"）并设默认。
- [ ] `_SIGNAL_BUILTIN_PRESETS`（torque/vibration/transient）：`nfft` → `'自动'`（**保留各自的 `order_res`/`samples_per_rev` 不动**——自动据此推导：扭矩 256/0.05→8192、振动 512/0.10→8192、启停 256/0.25→1024）。
- [ ] `_order_nfft_preview()`：`ceil_pow2(samples_per_rev / order_res)` 再 `clamp(256, 16384)`（构造期/无 rpm 时的摘要预览，量纲与计算一致，缺角度域 N 故不带帧护栏——与时频图同款"预览按比例、计算带护栏"约定）。
- [ ] `_order_summary_text()`：nfft==自动 时显示 `自动({preview})`，例 `≤20阶 · 0.05 · 自动(8192)`。
- [ ] `get_params` / `current_params` / `_collect_preset` / `_apply_preset`：加 `nfft_mode`（'auto'/'fixed'）；auto 时 `nfft=None`；读到旧固定 nfft（无 nfft_mode）仍照旧（与 FFT/FFT-time 同模式）。
- [ ] 联动：`spin_order_res`、`spin_samples_per_rev` 变化时刷新摘要预览（现有 `_on_preset_param_changed` 已连这些控件 → 确认 `_refresh_order_summary` 走新的预览逻辑）。
- [ ] 测试：combo 含「自动」且默认；应用扭矩预设 → `combo_nfft=='自动'`、摘要含 `自动(8192)`；改 `order_res`/`samples_per_rev` → 预览 nfft 跟着变；旧固定 nfft 存档仍能加载。

---

### Task 3：main_window 计算时用真实 n_angle 解析

**Files:** `mf4_analyzer/ui/main_window.py`，`tests/ui/test_main_window_smoke.py`

- [ ] **Step 0（探查）：** 定位阶次计算里**构造 `COTParams`/取 `nfft`** 的位置（`do_order_time` → worker job → `COTAnalyzer.compute` 调用点；搜 `COTParams(`、`order_ctx.get_params()`、`samples_per_rev`）。
- [ ] **Step 1：写失败测试** —— 喂单向恒速 rpm + 信号，auto 模式下传给 COT 的 `nfft` 等于 `resolve_order_nfft(spr, order_res, n_angle)`；固定模式原样透传。
- [ ] **Step 2：实现** `_resolve_order_effective_params(p, rpm, t)`（仿 `_resolve_fft_time_effective_params`）：
  - auto 时估角度域长度 `n_angle ≈ int(round(samples_per_rev * ∫|rpm|/60 dt))`（总转数×每转样本；用 |rpm| 防反向负积分）；
  - `nfft = resolve_order_nfft(samples_per_rev, order_res, n_angle, overlap=0.75)`；
  - 写回 `nfft`/`nfft_effective`/`nfft_mode`，再构造 `COTParams`。
  - 兜底：`n_angle < nfft`（转数不足，COT 本会抛）时，让护栏已降档；若仍不足则保留现有报错路径（不要静默）。
- [ ] **Step 3：跑测试**（`--basetemp=.pytmp/run`）

---

### Task 4：回归 + 真实数据复验

- [ ] `… -m pytest tests/test_signal_adaptive.py tests/ui/test_inspector.py tests/ui/test_main_window_smoke.py -q --basetemp=.pytmp/run`
- [ ] 真实数据脱 GUI 复验：对 P779 某文件，`resolve_order_nfft` 在三类预设的 `order_res`/`samples_per_rev` 下解析出 8192/8192/1024;（该数据转速反向→阶次提示照常触发,只验证 nfft 解析正确）。
- [ ] 更新本 plan 勾选。

---

### 风险 / 注意

- **量纲**:order 自动**绝不**用 `fs×秒`;只用 `samples_per_rev/order_res`(角度域)。
- **预览 vs 计算一致**:摘要预览仅 `ceil_pow2(spr/order_res)`(无 N 护栏),计算用带 `n_angle` 护栏的 `resolve_order_nfft`;极短转数下两者可能差一档(同时频图,已知可接受)。
- **角度域 Nyquist**:可分辨最大阶次 = `samples_per_rev/2`。若 `max_order > samples_per_rev/2`,自动 nfft 再大也够不着——**可选**加一句提示(本计划不强制)。
- **反向/近零转速**:`n_angle` 用 `∫|rpm|` 估;但这类数据阶次本不适用(已有 C 提示),auto 只保证"解析不崩"。
- **旧存档**:固定 nfft 的 order 预设/项目仍要能加载(`nfft_mode` 缺省走 fixed)。
- **不动** order 的 `order_res`/`samples_per_rev`/`max_order`/`time_res` 语义与算法。

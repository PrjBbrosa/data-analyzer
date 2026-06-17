# 分析默认值「随采样率/数据自适应」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现。步骤用复选框（`- [ ]`）。每个任务先写失败测试，再实现，再跑测试。

**Goal:** 让分析默认值随 fs / 数据长度 / 能量分布自适应：A 频率显示范围按能量收窄；B 时频图 nfft 按 fs 自动（目标窗时长）；预设携带 T_win 并把扭矩幅值改 dB；C 阶次对反向/近零转速给不适用提示。手动挡一律保留。

**Architecture:** 三个纯函数放 `signal/` 层（`energy_band_fmax` / `resolve_nfft` / `assess_speed_for_order`），UI 只表达「自动」和 `t_win_s`，真实计算层在拿到 `sig` 后解析 `effective_nfft`。`main_window.py` 负责把 effective nfft 写入 FFT/FFT-vs-Time cache key、worker params、status/render params；Order 适用性提示也放在能拿到 rpm 数组的 main_window 调度层。时频图 `combo_nfft` 增「自动」项并默认；FFT/FFT-vs-Time builtin presets 用 `t_win_s` 替换写死 nfft；合并段摘要显示解析后的 nfft（无 N 时用 fs×T_win 的预览值，计算时以真实 N 为准）。

**Tech Stack:** Python, numpy/scipy, PyQt5, pytest + pytest-qt。

Spec: `docs/superpowers/specs/2026-06-17-fs-adaptive-analysis-defaults.md`

> **测试环境：** `tmp_path` 在本机报 `WinError 5`（环境问题），跑测试加
> `--basetemp=.pytmp/run`。解释器 `.venv/Scripts/python.exe`。
> **真实数据复验：** `D:\1. work\P779_S92_260616`（脱 GUI 调 signal 层即可）。

---

### Task 1：纯函数 + 单测（signal 层）

**Files:**
- Create: `mf4_analyzer/signal/adaptive.py`（收纳 `ceil_pow2`、`resolve_nfft`、`energy_band_fmax`；避免继续膨胀 `spectrogram.py`）
- Modify: `mf4_analyzer/signal/__init__.py`（导出新纯函数，便于 UI/main_window 复用）
- Modify: `mf4_analyzer/signal/order.py` 或 `order_cot.py`（仅当需要复用已有 order 逻辑时；默认把 `assess_speed_for_order` 放在 `adaptive.py` 并从 `signal/__init__.py` 导出）
- Test: `tests/test_signal_adaptive.py`（新建，纯函数无需 Qt）

- [x] **Step 1：写失败测试**
  - `ceil_pow2`：191→256、1500→2048、2000→2048、8193→16384；非正输入抛 `ValueError`。
  - `resolve_nfft(fs=96,n_samples=5002,t_win_s=1.5,overlap=0.75)` → 256；`fs=1000,n_samples=60000,t_win_s=1.5` → 2048；短记录触发 `max_window_frac` 护栏（例如 `fs=1000,n_samples=5002,t_win_s=1.5,overlap=0.75` 应降到 512 而不是 2048）；`fs=96,t_win_s=0.6` 允许到 64（下限）；`overlap` 非 finite、<0 或 ≥1 抛 `ValueError`。
  - `energy_band_fmax`：窄带（能量集中 1Hz）→ 远小于 Nyquist 且 ≥2Hz；宽带（均匀）→ 接近 Nyquist；纯 DC（仅 bin0 有值）→ 返回 floor；nice 取整到 1/2/5；`p` 非 `(0,1]`、`headroom` 非 finite/≤0、`floor_hz` 非 finite/<0 均抛 `ValueError`。
  - `assess_speed_for_order`：单向恒速 → (True,'')；含符号反转 → (False, 含「转速」字样)；大量近零 → (False,…)；finite RPM 样本数 <2 → (False, 含「转速」字样)。
- [x] **Step 2：实现**
  - `ceil_pow2(x)` 用 `int(2 ** math.ceil(math.log2(float(x))))`，再由 `resolve_nfft` clamp 到 `[floor, ceil]`。
  - `resolve_nfft(fs, n_samples, t_win_s, overlap, *, floor=64, ceil=8192, min_frames=24, max_window_frac=0.15)`：`nfft = ceil_pow2(fs * t_win_s)`；`hop=max(int(nfft*(1-overlap)),1)`；`frames=max(0,(N-nfft)//hop+1)`；先降到满足 `min_frames`，再降到不超过 `max_window_frac*N`，最后 clamp。
  - `energy_band_fmax(freq, amp, *, p=0.98, headroom=4.0, floor_hz=2.0)`：只用 `freq>0` 且 finite 的 bin；能量为 `amp**2`；全 DC/全零/非法输入返回 `min(nyquist, floor_hz)`；`nice_ceil` 取 1/2/5×10^n，且最终不超过 Nyquist。
  - `assess_speed_for_order(rpm)`：忽略非 finite；`peak=max(abs(rpm))`；`near0=mean(abs(rpm)<max(50.0,0.05*peak))`；sign flips 只统计非零符号变化；`flips>3 or near0>0.2` 返回非阻塞提示。
- [x] **Step 3：跑测试** `… -m pytest tests/test_signal_adaptive.py -q`

---

### Task 2：时频图 nfft「自动」+ effective nfft 计算路径（FFTTimeContextual + main_window）

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`
  - FFTTimeContextual `combo_nfft`（~3057，items `['512'..'8192']` 默认 `'1024'`）→ 加 `'自动'` 并设默认。
  - 该类的 builtin 预设来源（`_BUILTIN_PRESETS` / `_builtin_preset_full_params` ~3512）→ 改为携带 `t_win_s`（扭矩 2.5 / 振动 1.5 / 启停 0.6），扭矩 `amplitude_mode`→`'Amplitude dB'`。
  - 新增 `self._t_win_s = 1.5`；`get_params()` 中 `combo_nfft=='自动'` 时返回 `nfft=None`，同时返回 `nfft_mode='auto'`、`t_win_s=self._t_win_s`、`nfft_preview=<ceil_pow2(fs*t_win_s) clamp 后的预览值>`；固定 nfft 时保持 `nfft=int(...)`、`nfft_mode='fixed'`。
  - `_tf_summary_text()`（~已存在）：nfft==自动 时显示 `自动({nfft_preview})`；不要把 preview 当最终计算值。
  - `_collect_preset`/`_apply_preset`（~3827）：支持 `t_win_s`；builtin preset 应用时设 `combo_nfft='自动'`+更新 `_t_win_s`；读到旧用户 preset 的固定 `nfft` 且无 `t_win_s` 时照旧选固定 nfft。
- Modify: `mf4_analyzer/ui/main_window.py`
  - 新增 `_resolve_fft_time_effective_params(p, n_samples)`：若 `p['nfft'] is None` 或 `p.get('nfft_mode')=='auto'`，调用 `resolve_nfft(p['fs'], n_samples, p.get('t_win_s',1.5), p['overlap'])`，返回 `dict(p, nfft=<effective>, nfft_effective=<effective>, nfft_mode='auto')`；固定 nfft 返回原值并补 `nfft_effective=int(p['nfft'])`。
  - 在 `do_fft_time()` 和 `_dispatch_fft_time_job()` 中，必须先完成时间范围裁剪，拿到真实 `len(sig)` 后再调用该 helper；之后用 effective params 建 `_fft_time_cache_key`、`SpectrogramParams`、`_fft_time_pending['render_params']` 和 status 文案。
  - `_fft_time_cache_key()` 继续只收 compute-relevant 字段，但其 `nfft` 必须是 effective int，不能是 `None`/`'自动'`。
- Test: `tests/ui/test_inspector.py`、`tests/ui/test_main_window_smoke.py`

- [x] **Step 1：写失败测试**
  - `combo_nfft` 含「自动」且默认选中；`is_tf_expanded()` 行为不变。
  - 应用扭矩预设 → `_t_win_s≈2.5`、`combo_nfft=='自动'`、amplitude_mode 含 `dB`、摘要含 `自动(`。
  - `FFTTimeContextual.get_params()` 在自动时不抛 `ValueError`，并返回 `nfft is None`、`t_win_s==1.5`、`nfft_preview`。
  - `MainWindow._resolve_fft_time_effective_params({'fs':96,'nfft':None,'t_win_s':1.5,'overlap':0.75}, 5002)['nfft']` → 256；`fs=1000,n_samples=60000,t_win_s=1.5` → 2048；同一 helper 的返回值进入 `_fft_time_cache_key()` 后 key 的 nfft 槽是 int。
- [x] **Step 2：实现** Step 3：跑测试：`… -m pytest tests/ui/test_inspector.py::test_fft_time_* tests/ui/test_main_window_smoke.py::*fft_time* -q --basetemp=.pytmp/run`

---

### Task 3：FFT 谱 + Order 预设跟进（FFT effective nfft / 扭矩 dB）

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`
  - FFTContextual `_SIGNAL_BUILTIN_PRESETS`（~2390）：builtin presets 增 `t_win_s`（扭矩 2.5 / 振动 1.5 / 启停 0.6），`nfft='自动'`；**扭矩 `amp_y='Linear'`→`'dB'`**；保留三类窗函数/平均模式/重叠差异。
  - FFTContextual `_collect_preset`/`_apply_preset_values`/`current_params` 支持 `t_win_s`；旧用户 preset 没有 `t_win_s` 且带固定 `nfft` 时照旧应用固定 nfft。
  - OrderContextual `_SIGNAL_BUILTIN_PRESETS`（~2866）：仅把扭矩 `amplitude_mode='Amplitude'`→`'Amplitude dB'`；**nfft 不动**（角度域）。
- Modify: `mf4_analyzer/ui/main_window.py`
  - 新增 `_resolve_fft_effective_params(fft_params, n_samples, fs)`：`combo_nfft` 自动（`nfft is None`）且 `avg_mode` 为 `线性平均` 或 `峰值保持` 时，用 `resolve_nfft(fs,n_samples,t_win_s,avg_overlap/100)` 得到 effective nfft；`单帧` 自动仍保持整段 FFT（现有 `nfft=None` 语义）。
  - `_fft_compute_arrays()` 的 `compute_averaged_fft` / `compute_peak_hold_fft` 不再用 `nfft or 1024`；用 effective nfft。`do_fft()` 多源 cache key 也必须包含 effective compute params，避免同一 UI 自动值在不同 fs/N 下误命中缓存。
- Test: `tests/ui/test_inspector.py`、`tests/ui/test_main_window_smoke.py`

- [x] 写失败测试：
  - FFT builtin presets：扭矩 `amp_y=='dB'`；三类 `t_win_s` 为 2.5/1.5/0.6 且 `combo_nfft=='自动'`；旧固定-nfft preset 仍能 apply。
  - `_resolve_fft_effective_params`：Welch/峰值保持 + auto + 96 Hz/5002 samples → 256；1000 Hz/60000 samples → 2048；单帧 + auto 仍返回 `nfft=None`（整段）。
  - Order 扭矩 preset：`amplitude_mode` 含 dB，`nfft` 仍是原固定角度域值。
- [x] 实现 + 跑测试：`… -m pytest tests/ui/test_inspector.py::test_*preset* tests/ui/test_main_window_smoke.py::*fft* -q --basetemp=.pytmp/run`

---

### Task 4：A — 频率显示范围按能量自适应

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`（FFT / 时频图渲染里把「auto 频率上界=Nyquist」改为 `energy_band_fmax(freq, amp)`）
- Test: `tests/ui/test_main_window_smoke.py` 或 `tests/ui/test_inspector.py`

- [x] **Step 0（探查）：** 定位现在「auto 频率 → Nyquist」的具体位置：搜
      `spin_freq_max`、`chk_freq_auto`/`chk_y_auto`、`chk_x_auto`、Nyquist/`fs/2`
      在 main_window 渲染路径里的解析点。
- [x] **Step 1：写失败测试**
  - FFT 谱：构造低频窄带信号，走 `_fft_compute_arrays` + `_plot_fft_entries` 或 `do_fft()` 后，`x_auto=True` 时 X 上界应远小于 Nyquist 且 ≥2Hz；`x_auto=False,x_max=80` 时保持 80。
  - FFT-vs-Time：构造 `SpectrogramResult` 或跑 `_render_fft_time_on()`，`freq_auto/y_auto=True` 时传给 canvas 的 `freq_range` 或 Y 轴上界来自 `energy_band_fmax(result.freq, representative_amp)`，本数据形态约 0–5Hz；手填 `freq_max` 时不覆盖。
  - 宽带信号：`energy_band_fmax` 接近 Nyquist，确保 auto 不误收窄。
- [x] **Step 2：实现**
  - FFT 谱：在 `_plot_fft_entries` / FFT 渲染前，如果 `x_auto` 为 True，用每条曲线或合并幅值的 `energy_band_fmax(freq, amp)` 计算 X 上界；多曲线取最大上界；仅影响显示范围，不重算 FFT。
  - FFT-vs-Time：在 `_render_fft_time_on()` 里，当 `freq_auto/y_auto` 为 True 时，根据 `SpectrogramResult.freq` 和结果 amplitude（建议对 time axis 聚合 `max` 或 `mean` 后作为代表谱）算 `freq_range=(0, fmax)`，传入 `canvas.plot_result`；manual `freq_range` 仍按 `_normalize_freq_range(p)`。
  - 不要把 display-only 频率范围放进 FFT-vs-Time compute cache key。
- [x] **Step 3：跑测试** `… -m pytest tests/ui/test_main_window_smoke.py::*fft* -q --basetemp=.pytmp/run`

---

### Task 5：C — 阶次不适用提示（main_window Order 调度层）

**Files:** `mf4_analyzer/ui/main_window.py`，`tests/ui/test_main_window_smoke.py`

- [x] **Step 1：写失败测试**
  - 在 `MainWindow._do_order_time_single()` 或 `_dispatch_order_job()` 可覆盖的路径里，给反向/近零 rpm 数据，断言非阻塞提示触发且文本含「转速」；`btn_ot` 仍 enabled，计算不被禁用。
  - 给单向稳定 rpm 数据，断言不触发提示。
  - 多 pane 队列路径也要至少覆盖 `_dispatch_order_job()`，避免只修 single path。
- [x] **Step 2：实现**
  - 在 `main_window.py` 新增小 helper `_warn_if_order_speed_unsuitable(rpm)`：调用 `assess_speed_for_order(rpm)`；不 ok 时用 `self.toast(message, "warning")` 或 `statusBar.showMessage(message)`，返回 bool 但**调用方不因 False 阻塞计算**。
  - 在 `_do_order_time_single()` 获取 rpm 数组后、构造 `OrderAnalysisParams` 前调用；在 `_dispatch_order_job()` 的 `rpm = self._order_rpm_for(...)` 后调用。
  - 不把提示状态写入 project/cache；不要改变 `btn_ot` enabled 状态。
- [x] **Step 3：跑测试** `… -m pytest tests/ui/test_main_window_smoke.py::*order* -q --basetemp=.pytmp/run`

---

### Task 6：回归 + 真实数据复验

- [x] `… -m pytest tests/test_signal_adaptive.py tests/ui/test_inspector.py tests/ui/test_side_panel_widgets.py tests/ui/test_main_window_smoke.py -q --basetemp=.pytmp/run`
- [x] 复跑验证脚本（`D:\1. work\P779_S92_260616`）：确认时频图默认窗变成 1–3 s、
      FFT/时频图频率默认收到 ~0–5 Hz、Order 触发提示。可再出一组对比图。
- [x] 复验前后检查真实 `QSettings("MF4Analyzer","DataAnalyzer")`：不要让截图/验证脚本写入 `inspector/*/params_expanded` 或其它 UI 默认状态（见 lesson `codex-qt-render-probes-isolate-qsettings`）。
- [x] 更新本 plan 勾选。

---

### 风险 / 注意

- **N 未知时的摘要**：构造期或未选信号时没有 N，`resolve_nfft` 的帧数护栏无法
  生效——摘要可先仅按 `fs×T_win` 解析（标注「自动」），**真正计算时**再用真实
  N 解析并护栏。两处解析口径要一致地走同一个函数。
- **旧预设存档兼容**：读到带固定 `nfft`（无 `t_win_s`）的存档要照旧应用，不能崩。
- **A 的 DC 处理**：能量/峰值搜索必须排除 DC（freq>0），否则去均值残留/直流会
  把上界拉到 ~0。
- **Order nfft 不要套 T_win**（角度域）；只改扭矩幅值为 dB。
- **summary 与计算口径一致**：有真实 N 的路径里，合并段摘要/状态文案显示的 nfft 必须等于真正喂给 `SpectrogramAnalyzer` 的 effective nfft；无真实 N 时只能显示 preview，不要把 preview 写入 compute cache。
- **QSettings 隔离**：任何 Qt render/screenshot probe 必须用临时 settings 或保存恢复真实 key，不能污染本机默认折叠/预设状态。

# 预设改名（取舍导向）+ 谱参数 tooltip + 悬浮卡说明 — Implementation Plan

> **For agentic workers:** 本计划由 main Claude 派发 `pyqt-ui-engineer` 实现（纯 UI 文案 + tooltip + 测试，**无数值/算法改动，不需 signal-processing-expert**）。步骤用 checkbox（`- [ ]`）跟踪，TDD：先写失败测试 → 跑红 → 实现 → 跑绿。

**Goal:** 把三视图（FFT-1D / FFT 时频 / 阶次）共用的三个内置预设显示名由"信号种类"改为"取舍导向"——**频率优先 / 均衡 / 时间优先**；给每条谱参数加一句话玻璃态 tooltip；预设悬浮卡副标题改为"特性 + 适合工况"。

**为什么：** 旧名 `扭矩类/振动类/启停类` 混用了两套逻辑（前两个按物理量、第三个按工况），且预设本质调的是"时频-幅值取舍"，与信号种类无关 → 误导。详见设计 mockup。

**Design artifact（已签收）：** `docs/mockups/2026-06-19-preset-rename-tooltips.html`

**Tech Stack:** PyQt5、pytest-qt、既有 `tests/ui/` 套件（offscreen）。

---

## 硬约束（必读，违反会静默失效或破坏契约）

- **只改显示文字与提示文案。** 不动 `_BUILTIN_PRESETS` 任何数值、不动内部 key（`torque`/`vibration`/`transient`）、不动 `recommend_preset_for_unit` 的单位别名集与槽位映射、不动 legacy 别名。改名不影响"按单位自动推荐"高亮与历史已保存预设（两者均按 key/slot，不按显示名）。
- **显示名是单一来源：** `inspector_sections/_helpers.py` 的 `BUILTIN_PRESET_DISPLAY`。三视图都从它取（`contextual_fft_time.py` 还 `dict(...)` 拷一份）。改这一处即三视图同时生效——**不要**在各 contextual 里另写一份名字。
- **悬浮卡副标题文案视图无关。** blurb 描述共性取舍 + 适合工况，**不写** view-specific 的窗/平均（flattop、峰值保持等）——那些 raw 值已在卡片 chips 里显示，写进 blurb 在另两个视图会失真。
- **玻璃 tooltip 不换行。** `ui_kit/glass_tooltip.py` 的弹层 QLabel 未开 word-wrap，**不要改它**（全局共享）。较长文案在字符串里用 `\n` 手动断行。
- 行号为 2026-06-19 快照，**以函数/符号名定位**。

## File Structure

| 文件 | 改动 |
|---|---|
| `mf4_analyzer/ui/inspector_sections/_helpers.py` | `BUILTIN_PRESET_DISPLAY` 改三名；新增 `BUILTIN_PRESET_BLURB`（key→"特性·适合"）；更新顶部注释 |
| `mf4_analyzer/ui/inspector_sections/presets.py` | `set_summary`：`builtin=True` 时副标题用 blurb 取代"已保存参数快照 · 来源…" |
| `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py` | 时频参数/幅值/色阶各控件 `setToolTip`；更新注释 |
| `mf4_analyzer/ui/inspector_sections/contextual_fft.py` | 谱参数各控件 `setToolTip`；更新注释 |
| `mf4_analyzer/ui/inspector_sections/contextual_order.py` | 谱参数各控件 `setToolTip`；更新注释 |
| `mf4_analyzer/ui/main_window/window.py` | 仅 docstring/注释里 `振动类`→`均衡`（1225 行附近），非功能 |
| `docs/superpowers/specs/2026-06-17-signal-type-presets-design.md` | 顶部加一行"显示名已于 2026-06-19 改为取舍导向，见本 plan" |
| `tests/ui/test_inspector.py` | 改断言旧名的用例（详见 Task 1）+ 新增 tooltip 契约测试 |

---

## 文案定稿

### 显示名（`BUILTIN_PRESET_DISPLAY`）
| key | 旧 | 新 |
|---|---|---|
| `torque` | 扭矩类 | **频率优先** |
| `vibration` | 振动类 | **均衡** |
| `transient` | 启停类 | **时间优先** |

### 悬浮卡副标题（`BUILTIN_PRESET_BLURB`，视图无关）
| key | 文案 |
|---|---|
| `torque` | 频率 / 幅值最准，时间偏粗 · 适合扭矩、压力等稳态量 |
| `vibration` | 时间-频率折中，宽动态 · 适合振动等通用诊断 |
| `transient` | 时间最细，频率偏粗 · 适合启停、冲击等瞬态 |

### 谱参数 tooltip（`\n` 为手动断行）
| 视图 | 控件 | 文案 |
|---|---|---|
| 通用 | 窗函数 `combo_win` | `抑制频谱泄漏：flattop 幅值最准、\nhanning 最均衡、blackman 旁瓣最低。` |
| 通用 | FFT点数/NFFT `combo_nfft` | `越大频率越细、计算量越高；\n「自动」＝按窗长取 2 的幂。` |
| 时频/FFT-1D | 幅值单位 `combo_amp_unit`/`combo_amp_y` | `dB 看宽动态，Linear 看绝对幅值。` |
| 时频 | 重叠 `spin_overlap` | `相邻时间帧的重叠：越高时频图越平滑、\n计算量越大。` |
| 时频 | 去均值 `chk_remove_mean` | `减去直流，避免 0 Hz 大值压低低频成分。` |
| 时频 | dB 参考 `spin_db_ref` | `0 dB 对应的线性幅值，仅平移 dB 刻度、不改波形。` |
| 时频 | 色阶 `spin_z_floor`/`spin_z_ceiling` | `颜色映射区间(dB)：缩小区间增强弱信号对比。` |
| FFT-1D | 重叠 `spin_overlap` | `相邻分析帧的重叠：越高频谱越平滑、计算量越大。` |
| 阶次 | 最大阶次 `spin_mo` | `分析的最高阶次；越大覆盖越宽、计算量越大。` |
| 阶次 | 阶次分辨率 `spin_order_res` | `阶次轴细度：越小越细，\n但需更多转数 / 更长数据。` |
| 阶次 | 时间分辨率 `spin_time_res` | `阶次谱图时间轴细度：\n越小时间越细、阶次相应变粗。` |
| 阶次 | FFT点数 `combo_nfft` | `越大阶次越细、计算量越高；\n「自动」＝按需取 2 的幂。` |

> 已有 tooltip 的 `combo_avg_mode`/`spin_avg_overlap`（FFT-1D）、`spin_samples_per_rev`（阶次）**不重写**，仅语气对齐即可。

---

## Task 1: 改三个显示名（+ 同步测试断言）

**Files:** `_helpers.py`；`tests/ui/test_inspector.py`

- [ ] **Step 1: 改红现有测试**——把断言旧名的用例改成新名：
  - `test_inspector.py` 约 1362–1364：`"扭矩类"/"振动类"/"启停类" in texts` → `"频率优先"/"均衡"/"时间优先"`。
  - 约 1955–1957 与 1978：`bar._load_btns[1].text() == '扭矩类'` 等 → 新名。
  - 跑这些用例确认**现在红**（实现还没改）。
- [ ] **Step 2: 实现**——`BUILTIN_PRESET_DISPLAY` 三个值改为 `频率优先/均衡/时间优先`；更新 `_helpers.py:37` 注释与各 contextual 里"扭矩类 / 振动类 / 启停类"注释（fft_time:235/656、order:196、fft:227、presets:324、window.py:1225 docstring）。
- [ ] **Step 3: 跑绿**——上述用例 + `bar._default_name`/`_load_btns[n].text()` 相关全绿。
- [ ] **Step 4:** 复核：`recommend_preset_for_unit('Nm')=='torque'` 等单位推荐测试**仍绿**（key 没动），历史预设 round-trip 测试仍绿。

## Task 2: 悬浮卡副标题 → blurb

**Files:** `_helpers.py`（加 `BUILTIN_PRESET_BLURB`）、`presets.py`（`set_summary`/`_show_hover`）；`tests/ui/test_inspector.py`

- [ ] **Step 1: 失败测试**——构造 PresetBar，触发内置槽的 hover（或直接调 `_hover_card.set_summary(name=..., builtin=True, ...)`），断言副标题 QLabel 文本包含"适合"且**不含**"已保存参数快照"；非内置（用户保存）槽仍显示旧副标题。
- [ ] **Step 2: 跑红。**
- [ ] **Step 3: 实现**——
  - `_helpers.py` 加 `BUILTIN_PRESET_BLURB = {'torque': …, 'vibration': …, 'transient': …}`（文案见上）。
  - `_show_hover`（presets.py:514）已知槽位/`builtin`：把对应内置 **key** 解析出来（slot→key 反查 `_PRESET_KEY_TO_SLOT`，或经 `BUILTIN_PRESET_DISPLAY` 反查）传入 `set_summary`。
  - `set_summary`（:116/:131）：当 `builtin=True` 且能取到 blurb 时，`sub` 文本用 blurb；否则保持原"已保存参数快照 · 来源：…"。
- [ ] **Step 4: 跑绿**，并人工/截图复核三张卡（可复用 `tools/_screenshot_preset_hover_card.py`，把 `name="振动类"`→新名）。

## Task 3: 时频图谱参数 tooltip

**Files:** `contextual_fft_time.py`；`tests/ui/test_inspector.py`

- [ ] **Step 1: 失败测试**——构造 `FFTTimeContextual`，断言 `combo_win/combo_nfft/spin_overlap/chk_remove_mean/spin_db_ref/combo_amp_unit/spin_z_floor` 的 `.toolTip()` 非空且含关键词（如窗函数含"泄漏"、重叠含"重叠"）。
- [ ] **Step 2: 跑红。**
- [ ] **Step 3: 实现**——按上表对各控件 `setToolTip(...)`。`combo_amp_unit`/`spin_z_floor`/`spin_z_ceiling` 在 `_make_axis_settings_group` 返回后于本类内 `self.combo_amp_unit.setToolTip(...)` 设置（**不**改 `_helpers` 那个共享 helper 的签名）。
- [ ] **Step 4: 跑绿。**

## Task 4: FFT-1D 谱参数 tooltip

**Files:** `contextual_fft.py`；`tests/ui/test_inspector.py`

- [ ] Step 1 失败测试：断言 `combo_win/combo_nfft/spin_overlap/combo_amp_y` `.toolTip()` 非空含关键词；`combo_avg_mode/spin_avg_overlap` 仍有原 tooltip。
- [ ] Step 2 跑红 → Step 3 实现（按上表；FFT-1D 的"重叠"用其专属文案）→ Step 4 跑绿。

## Task 5: 阶次谱参数 tooltip

**Files:** `contextual_order.py`；`tests/ui/test_inspector.py`

- [ ] Step 1 失败测试：断言 `spin_mo/spin_order_res/spin_time_res/combo_nfft` `.toolTip()` 非空含关键词；`spin_samples_per_rev` 仍有原 tooltip；若阶次 axis 有 `combo_amp_unit` 亦加。
- [ ] Step 2 跑红 → Step 3 实现 → Step 4 跑绿。

## Task 6: 文档同步

- [ ] spec `2026-06-17-signal-type-presets-design.md` 顶部加一行：显示名于 2026-06-19 改为取舍导向（频率优先/均衡/时间优先），key/单位推荐不变，见本 plan。
- [ ] 旧 mockup（`tf-params-merged-section.html`、`preset-hover-placement.html`）不动（历史快照），不必回改。

## Task 7: 全套件 + 冒烟

- [ ] Run：`pytest tests/ui/test_inspector.py -q`（offscreen），记录 before/after 通过数；确认无新红。
- [ ] Run：`pytest tests/ui/test_main_window_smoke.py -q` 确认未回归。
- [ ] 手动起一次应用：三视图预设条显示新名；悬停预设看副标题；悬停谱参数看玻璃 tooltip（浅色磨砂、行下方、长文案两行不溢出）；按单位切换通道仍正确高亮推荐槽。

---

## Self-Review（写完自查）

1. **范围零外溢**：grep 确认无任何 `setValue`/数值常量/`_BUILTIN_PRESETS`/key/别名集被触碰；diff 应只含字符串、`setToolTip`、`set_summary` 分支、测试与注释。
2. **三视图一致**：显示名只改 `_helpers` 一处；blurb 视图无关；tooltip 同名参数共用同句。
3. **契约不破**：`recommend_preset_for_unit`、`_PRESET_KEY_TO_SLOT`、历史预设 round-trip、legacy 别名相关测试全绿。
4. **tooltip 渲染**：复用全局玻璃弹层（不改 `glass_tooltip.py`）；长文案 `\n` 断行，已在 Task 7 人工复核宽度。
5. **风险**：低。唯一外部可见变化是文字；若有未 grep 到的第三方/截图脚本仍引用旧名，Task 7 冒烟会暴露。

# 按信号类型的三套分析预设 + 单位自动推荐 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给三个分析视图（FFT-1D / FFT 时频 / 阶次）填同一套三个按信号类型设计的内置预设（扭矩类/振动类/启停类），并按通道单位自动高亮推荐。参数已由 `signal-processing-expert` 校核定稿。

**Architecture:** 预设值为常量，按 §3 表照搬；三视图各自的 contextual 类持有 `_BUILTIN_PRESETS` + display 名 + `_builtin_preset_full_params`（映射到该视图 `_collect_preset` 真实形状），FFT-1D / 阶次的 PresetBar 从 legacy 切到 builtin-aware（传 `builtin_defaults`），时频图沿用已有 builtin-aware 仅改值/名。单位推荐 = 一个模块级 `recommend_preset_for_unit` + `PresetBar.set_recommended` 高亮 + 在 `main_window` 既有 signal-changed handler 里接线。

**Tech Stack:** PyQt5、pytest-qt、既有 `tests/ui/` 套件（offscreen）。

**配套 spec：** `docs/superpowers/specs/2026-06-17-signal-type-presets-design.md`

---

## 硬约束（必读，违反会静默失效）

- 字段名/文案见 spec §1 F2：FFT-1D **无 remove_mean**、幅值轴 `amp_y ∈ {'Linear','dB'}`、平均模式文案 `单帧/线性平均/峰值保持`、阶次**无 window**。
- 写入预设前对每个视图 Read `_collect_preset` 复核字段集合，只放真实存在的键。
- 单位**精确**匹配（F9），不要子串匹配。
- `PresetBar.SLOTS` 是 1-based（1/2/3），推荐槽位映射必须是 扭矩=1 / 振动=2 / 启停=3；不要在 `PresetBar` API 或测试里使用 0/1/2。
- `set_recommended_for_unit(None)` 只表示“选择清空”，应清空高亮；空字符串 `''` 或未知单位不是清空，应按 `recommend_preset_for_unit` 兜底到振动类。
- 不改 `signal/`（算法）。`time_res` 本批仅存值不接 COT（F6）。
- 行号为 2026-06-17 快照，**以函数/符号名定位**。

## File Structure

- `mf4_analyzer/ui/inspector_sections.py` — 模块级 `recommend_preset_for_unit`；`PresetBar.set_recommended`；FFT-1D / 阶次的 `_BUILTIN_PRESETS`+display+`_builtin_preset_full_params`+builtin-aware PresetBar；各 ctx 的 `set_recommended_for_unit`；时频图 `_BUILTIN_PRESETS` 改值/名 + z_floor 泛化。
- `mf4_analyzer/ui/main_window.py` — 在 `_on_inspector_signal_changed` / `_on_fft_time_signal_changed` 里读单位 → 调 `set_recommended_for_unit`。
- `tests/ui/test_inspector.py` — 全部回归测试。

---

## Task 1: 模块级 `recommend_preset_for_unit`（单位→预设 key）

**Files:** Modify `inspector_sections.py`；Test `tests/ui/test_inspector.py`

- [ ] **Step 1: 写失败测试**

```python
def test_recommend_preset_for_unit():
    from mf4_analyzer.ui.inspector_sections import recommend_preset_for_unit
    assert recommend_preset_for_unit('Nm') == 'torque'
    assert recommend_preset_for_unit('kPa') == 'torque'
    assert recommend_preset_for_unit('°') == 'torque'
    assert recommend_preset_for_unit('g') == 'vibration'
    assert recommend_preset_for_unit('m/s²') == 'vibration'
    assert recommend_preset_for_unit('m/s^2') == 'vibration'
    # 精确匹配：子串不应误命中
    assert recommend_preset_for_unit('kg') == 'vibration'      # 兜底，不因含 'g' 判振动? -> 见下
    assert recommend_preset_for_unit('rpm') == 'vibration'     # 兜底
    assert recommend_preset_for_unit('') == 'vibration'        # 兜底
```

> 注：`kg` 不在任何别名集 → 兜底 vibration；关键是它**不因子串 `g`** 被"主动判定"为 vibration（两者结果都是 vibration，但需另测 `Pa`/`kPa` 区分能力，见下）。补一条 `assert recommend_preset_for_unit('Pa') == 'torque'`（在集内）与确保 `kPa`/`hPa` 也都命中 torque 而非靠子串。

- [ ] **Step 2: 跑测试确认失败**（`ImportError`）。

- [ ] **Step 3: 实现**

在 `inspector_sections.py` 顶部（类定义之前）加归一化 + 别名集 + 精确匹配函数：归一化 `unit.strip().lower()`，把 `²→2`、`^2` 统一；三个 `frozenset` 别名集（见 spec §4）；命中返回对应 key，否则 `'vibration'`。

- [ ] **Step 4: 跑测试确认通过**。

---

## Task 2: `PresetBar.set_recommended` 推荐高亮

**Files:** Modify `inspector_sections.py`（`PresetBar`）；Test `tests/ui/test_inspector.py`

- [ ] **Step 1: 写失败测试**

```python
def test_preset_bar_set_recommended_highlights_one_slot():
    from mf4_analyzer.ui.inspector_sections import PresetBar
    bar = PresetBar('t_reco', lambda: {}, lambda d: None)
    bar.set_recommended(2)
    btns = bar._load_btns  # PresetBar.SLOTS: 1/2/3
    assert btns[2].property('recommended') in (True, 'true')
    assert btns[1].property('recommended') in (False, 'false', None)
    assert btns[3].property('recommended') in (False, 'false', None)
    bar.set_recommended(None)
    assert not any(btns[n].property('recommended') in (True, 'true') for n in (1, 2, 3))
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现 `set_recommended(slot)`**

遍历槽按钮，set `recommended` QSS property（命中槽 True、其它 None/False），逐个 `style().unpolish()/polish()`。在 `style.qss` 或 PresetBar 内联样式补 `[recommended="true"]` 规则（绿框/绿底，复用 `#047857`/`#e9f9f1`）。先记住当前 `_recommended_slot`，重建槽（`_refresh`）后重应用。

- [ ] **Step 4: 跑测试确认通过**。

---

## Task 3: FFT-1D 三套内置预设（legacy → builtin-aware）

**Files:** Modify `inspector_sections.py`（FFT contextual 类）；Test `tests/ui/test_inspector.py`

- [ ] **Step 1: 写失败测试**（字符串不失配 + builtin 名）

```python
def test_fft_builtins_findtext_hit(qapp):
    ctx = <构造 FFT contextual>
    bar = ctx.preset_bar
    names = [bar._default_name(s) for s in (1, 2, 3)]
    assert names == ['扭矩类', '振动类', '启停类']
    expected = {
        'torque': dict(window='flattop', nfft='4096', overlap=75,
                       amp_y='Linear', avg_mode='线性平均', avg_overlap=75),
        'vibration': dict(window='hanning', nfft='2048', overlap=50,
                          amp_y='dB', avg_mode='线性平均', avg_overlap=50),
        'transient': dict(window='hanning', nfft='1024', overlap=75,
                          amp_y='dB', avg_mode='峰值保持', avg_overlap=75),
    }
    for key, p in expected.items():
        assert ctx._SIGNAL_BUILTIN_PRESETS[key] == p
        assert ctx.combo_win.findText(p['window']) >= 0
        assert ctx.combo_nfft.findText(str(p['nfft'])) >= 0
        assert ctx.combo_amp_y.findText(p['amp_y']) >= 0          # 真实属性名为准
        assert ctx.combo_avg_mode.findText(p['avg_mode']) >= 0
        assert 'remove_mean' not in p                              # F2
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现**

给 FFT contextual 类加 `_BUILTIN_PRESETS`（spec §3 FFT-1D 表）、`_BUILTIN_PRESET_DISPLAY = {'torque':'扭矩类','vibration':'振动类','transient':'启停类'}`、`_builtin_preset_full_params(name)`（映射到 FFT-1D `_collect_preset` 形状，**不含 remove_mean**）；构造 `builtin_defaults` 并把 PresetBar 改为传 `builtin_defaults=`。

- [ ] **Step 4: 跑测试确认通过**。

---

## Task 4: 阶次 三套内置预设（legacy → builtin-aware）

**Files / 步骤同 Task 3**，针对阶次 contextual 类，用 spec §3 阶次表；`_builtin_preset_full_params` 映射到阶次 `_collect_preset` 形状（`max_order/order_res/time_res/nfft/samples_per_rev/amplitude_mode` + axis），**不含 window**。

- [ ] Step 1 失败测试：用 spec §3 阶次表写独立 `expected` 字典，断言实现常量逐项相等；再断言三个 display 名 + `combo_nfft.findText(str(nfft))>=0` + `spin_mo` 范围容得下 max_order + `samples_per_rev >= 2*max_order`（F7）+ `'window' not in p`。不要新增会推翻 spec 参数表的 `order_res` 自动修正规则；振动类 `order_res=0.10` / 原生 0.125、扭矩类 `order_res=0.05` / 原生 0.0625 都是信号专家已接受的近似。
- [ ] Step 2 失败 → Step 3 实现 → Step 4 通过。

---

## Task 5: FFT 时频 改值/名 + z_floor 泛化

**Files:** Modify `inspector_sections.py`（时频 contextual `_BUILTIN_PRESETS` ~3263、`_BUILTIN_PRESET_DISPLAY` ~3295、`_builtin_preset_full_params` ~3332）；Test `tests/ui/test_inspector.py`

- [ ] **Step 1: 写失败测试**：用 spec §3 时频表写独立 `expected` 字典，断言 `_BUILTIN_PRESETS` 逐项相等；display 名→`扭矩类/振动类/启停类`；三套 `cmap` ∈ {turbo,viridis,gray} 且 `combo_cmap.findText>=0`；扭矩 window=flattop；`_builtin_preset_full_params` 对 `'80 dB'`→z_floor=-80、`'60 dB'`→-60、`'Auto'`→z_auto=True。
- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**：把 `_BUILTIN_PRESETS` 三键改为 `torque/vibration/transient`（或保留键名只改值——以 display 名为准），值用 spec §3 时频表；display 名改三类名；把 z_floor 构造（~3332-3334）泛化为解析任意 `'NN dB'→-NN`，`'Auto'→z_auto`。保留 `apply_builtin_preset` 向后兼容（若有旧测试引用旧键名，加别名或更新测试）。
- [ ] **Step 4: 跑测试确认通过**；并跑既有时频预设相关用例确认未回归。

---

## Task 6: `set_recommended_for_unit` + main_window 接线

**Files:** Modify `inspector_sections.py`（三个 ctx）+ `main_window.py`；Test `tests/ui/test_inspector.py`（+ 必要时 `test_main_window_smoke.py`）

- [ ] **Step 1: 写失败测试**（ctx 级，不依赖 main_window）

```python
def test_ctx_set_recommended_for_unit_highlights(qapp):
    ctx = <构造 FFT contextual>
    ctx.set_recommended_for_unit('Nm')
    assert ctx.preset_bar._load_btns[1].property('recommended') in (True, 'true')   # 扭矩=1
    ctx.set_recommended_for_unit('g')
    assert ctx.preset_bar._load_btns[2].property('recommended') in (True, 'true')   # 振动=2
    ctx.set_recommended_for_unit('')  # 空单位/未知单位：兜底振动，不清空
    assert ctx.preset_bar._load_btns[2].property('recommended') in (True, 'true')
    ctx.set_recommended_for_unit(None)
    assert not any(ctx.preset_bar._load_btns[n].property('recommended') in (True, 'true') for n in (1, 2, 3))
```

- [ ] **Step 2: 跑测试确认失败**。

- [ ] **Step 3: 实现 `set_recommended_for_unit(unit)`** 于三个 ctx：`unit is None` → `set_recommended(None)`；否则（包括 `''` 空字符串）`recommend_preset_for_unit` → 1-based slot map → `preset_bar.set_recommended(slot)`。

- [ ] **Step 4: main_window 接线**

Read `_on_inspector_signal_changed`（~2063）与 `_on_fft_time_signal_changed`（~2080）及 `signal_changed` payload（~1854 注释 `(fid,ch)` or None）。在两 handler 里解析 `(fid, ch)` → `fd.channel_units.get(ch,'')` → 对应 ctx 调 `set_recommended_for_unit`；payload None → `set_recommended_for_unit(None)`。**沿用既有 handler，不加新信号**。

- [ ] **Step 5: 跑测试确认通过**。

---

## Task 7: 全套件 + 构造冒烟

- [ ] Run: `pytest tests/ui/test_inspector.py tests/ui/test_main_window_smoke.py -q`，记录 before/after 通过数。
- [ ] 构造三个 contextual 控件不崩；手动起一次应用：选不同单位通道，确认对应槽高亮、手动点击其它槽仍可用、改名/重置交互未坏。

---

## Self-Review（写完自查）

1. **Spec 覆盖**：G1→Task 3/4/5；G2→各任务字段复核 + Task 1 文案；G3→Task 1/2/6；G4→各任务失败测试 + Task 7。无缺口。
2. **F2 字段坑**：每个 builtin task 的失败测试都断言了 `findText>=0` 与"无 remove_mean / 无 window"，钉死静默失配。
3. **命名一致**：`recommend_preset_for_unit` / `set_recommended` / `set_recommended_for_unit` / `_BUILTIN_PRESET_DISPLAY` / property `recommended` 跨任务一致；slot map 扭矩=1/振动=2/启停=3（`PresetBar.SLOTS` 1-based）统一。
4. **风险**：振动阶次数据量（spec §6 R-振动阶次数据量，回退 nfft=2048+order_res=0.25）；`time_res` 不生效需对用户说明（spec §6 R-time_res）；`_load_btns` 等私有属性名以实际代码为准。

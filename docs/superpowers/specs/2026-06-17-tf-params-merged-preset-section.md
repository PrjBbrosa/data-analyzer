# 时频参数「预设 + 折叠」合并段设计（方案 B）

状态：草案（已与用户对齐方案 B + 简单摘要）
日期：2026-06-17
对应 mockup：`docs/mockups/tf-params-merged-section.html`
对应 plan：`docs/superpowers/plans/2026-06-17-tf-params-merged-preset-section.md`

## 背景 / 问题

FFT、FFT-vs-Time、Order 三个分析 section 的右侧参数面板里，
「预设」(`PresetBar`：扭矩类 / 振动类 / 启停类) 目前作为一个**独立的
QGroupBox 排在下方面板的底部**（在 谱参数/时频参数、坐标轴设置、色标
之后），而详细的频谱/时频参数（FFT点数、窗函数、重叠……）则以一个
常驻展开的 QGroupBox 排在最上面。

实际使用中，多数用户只需「选一个预设」就能跑；详细参数是少数人才微调
的高级项。当前布局把高级项常驻、把快捷入口埋在底部，主次颠倒、且占用
垂直空间。

## 目标

把每个 section 的「主参数组 + 预设」合并成**一个段**，采用渐进式呈现：

1. **预设按钮常驻**（扭矩 / 振动 / 启停）——快捷入口最显眼。
2. 段标题行右侧常显**当前参数摘要**（如 `1024 · hanning · 80%`），
   折叠也能一眼看到当前配置。
3. 详细参数（FFT点数 / 窗函数 / 重叠 / …）**默认折叠**，点箭头展开才
   能自定义。
4. 折叠/展开状态**记住**（QSettings 持久化），下次进入保持。
5. 用户**手动改了任一参数**后，预设按钮**取消高亮**（表示"已脱离配方、
   自定义中"）。

UI 必须匹配 `tf-params-merged-section.html` 的视觉与结构。

## 适用范围

三个 contextual 类（均在 `mf4_analyzer/ui/inspector_sections.py`）：

| section | 类（约行号） | 主参数组标题 | kind | 摘要字段（主参数组里取） |
|---|---|---|---|---|
| FFT | `FFTContextual`（~1984） | `谱参数` | `fft` | NFFT · 窗函数 · 重叠% |
| FFT-vs-Time | `FFTTimeContextual`（~3008） | `时频参数` | `fft_time` | FFT点数 · 窗函数 · 重叠% |
| Order | `OrderContextual`（~2439） | `谱参数` | `order` | 最大阶次 · 阶次分辨率 · FFT点数 |

每个类的下方面板由 `_make_params_card` 生成（`params_lay`），现状各组
顺序示例（FFT-vs-Time）：`时频参数` → `幅值` → `坐标轴设置` → `色标`
→ `预设` → `计算时频图`。

摘要 token 用 ` · ` 连接，示例：
- FFT：`combo_nfft.currentText()` · `combo_win.currentText()` ·
  `f"{spin_overlap.value()}%"` → `"1024 · hanning · 50%"`
  （NFFT 可能是 `自动`，按原样显示）。
- FFT-vs-Time：同上 → `"1024 · hanning · 80%"`。
- Order：`f"≤{spin_mo.value()}阶"` · `f"{spin_order_res.value():g}"` ·
  `combo_nfft.currentText()` → `"≤20阶 · 0.1 · 2048"`。

摘要具体取哪几项可在实现时微调，原则是**简单、能一眼判断当前配方**。

## UI 规格（必须匹配 mockup）

合并后，主参数组变成一个段，结构自上而下：

```
┌─ 段 ──────────────────────────────────────────┐
│ ▶ 时频参数                 1024 · hanning · 80% │  ← 标题行(toggle)：箭头 + 标题 + 右对齐摘要
│ [扭矩类] [振动类] [启停类]                       │  ← 预设按钮，常驻（折叠态也显示）
│ ┄┄┄┄┄┄┄┄ 展开后才出现 ┄┄┄┄┄┄┄┄                │
│ FFT 点数:  [1024 ▾]                             │
│ 窗函数:    [hanning ▾]                          │
│ 重叠:      [80 %]                               │
│ ☑ 去均值              (FFT-vs-Time 才有)         │
└────────────────────────────────────────────────┘
```

- 标题行复用现有折叠条观感（`objectName="inspectorCollapser"` 的扁平
  `QToolButton` + 箭头），右侧追加灰色小字摘要。
- 折叠态：仅显示 标题行 + 预设按钮。展开态：箭头转向下，额外显示详细
  参数表单。
- 其余组（`幅值` / `坐标轴设置` / `色标`）和底部的「计算」按钮**保持
  原样、原位置**，不受本次改动影响。
- 旧的独立「预设 / 预设配置」QGroupBox **移除**，其 `preset_bar` 迁移到
  本段的常驻区。

## 交互细节

1. **摘要联动**：主参数组里参与摘要的控件
   (`combo_nfft`/`combo_win`/`spin_overlap`，Order 用其对应控件)
   的 `currentTextChanged` / `valueChanged` 触发刷新摘要文本。
2. **预设高亮**：复用 `PresetBar.set_recommended(slot)` 的高亮机制。
   - 点击某预设 → 应用参数成功后把该槽设为高亮（表示"当前配方"）。
     该逻辑放在 `PresetBar` 的加载路径里，三类 section 共用，避免每个
     contextual 重复处理。
   - 用户手动改合并主参数段 body 里的任一可保存主参数 →
     `set_recommended(None)`（取消高亮，"已自定义"）。摘要只展示其中
     3 个关键字段，但清高亮覆盖该主参数段里会被 preset 保存/恢复的控件。
3. **apply guard**：`_apply_preset` 程序化写入控件值时会触发上面的
   `valueChanged`/`currentTextChanged`。必须用一个守卫标志
   （如 `self._applying_preset`）包住 `_apply_preset`，使「手动改→取消
   高亮」逻辑在程序化应用期间**不**误触发；但**摘要刷新仍要执行**
   （摘要只读当前值，无副作用）。
4. **折叠持久化**：QSettings key 形如 `inspector/{kind}/params_expanded`
   （`kind` ∈ fft / fft_time / order），默认 **False（折叠）**。复用
   `_preset_settings()`（与 PresetBar / PersistentTop 折叠条同一 store）。
5. **可达性不变**：折叠时详细参数控件只是 `setVisible(False)`，仍存在、
   仍可被程序读写（沿用 `PersistentTop` 折叠条的约定——getter/setter 在
   折叠态下照常工作），不破坏 `main_window` 读取参数、project 存取、
   `_collect_preset`/`_apply_preset` 的现有调用面。

## 复用的现成组件

`PersistentTop`（~1566）已有一套折叠条实现：`btn_collapser`
(`inspectorCollapser`) + `_collapser_body` (QFrame) + `_sync_collapser`
+ QSettings 持久化 + 现成 QSS。

本设计**抽出一个可复用的小部件** `_CollapsibleParamSection`，封装：
标题行（箭头 + 标题 + 右对齐摘要 label）、常驻区（放 preset_bar）、
可折叠 body（放详细参数表单）、`set_summary(text)`、持久化与默认折叠。
三个 contextual 共用，避免在 3 处复制折叠逻辑。

## 非目标 / Out of scope

- 不动 `幅值` / `坐标轴设置` / `色标` 三组，也不动各 section 底部的
  「计算」按钮。
- 不重构 `PersistentTop` 现有折叠条（可后续用同一新部件统一，但本次
  不做，以控制范围）。
- 不改预设的存储格式、`_collect_preset`/`_apply_preset`/builtin 配方
  内容、unit-推荐 的触发逻辑。
- 不改 FFT/Order/FFT-time 的数值算法。

## 验收标准

- 三个 section 的主参数段：预设按钮常驻、详细参数默认折叠、标题行显示
  正确摘要；展开/折叠可切换并跨会话记住。
- 手动改主参数 → 摘要实时更新且预设取消高亮；点预设 → 参数与摘要更新、
  该预设高亮，且不会被自身的程序化写入误清高亮。
- 旧的独立「预设/预设配置」组消失；其它组与计算按钮位置/行为不变。
- 标签列对齐契约（A1：`test_fft_contextual_fields_fill_column_under_qss`
  等）仍通过；`main_window`/project 对参数控件的读写不回归。
- 视觉与 `tf-params-merged-section.html` 一致。

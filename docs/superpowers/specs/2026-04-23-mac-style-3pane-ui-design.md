# Mac 浅色风格 · 三栏 + Drawer UI 重构

**日期：** 2026-04-23
**范围：** `mf4_analyzer/ui/` 整层，以 `main_window.py` 为核心
**约束：** 现有所有 feature 不得删除；纯 UI 重构，不改变分析算法

> **修订说明（2026-04-23, post-codex review）**：本版根据 codex 对初稿的 22 条发现完整补齐，重点补全功能覆盖（channel 筛选/批量/警告、光标双态、FFT remark 行为、axis 双击编辑、滚轮缩放、Esc 取消、通道编辑 drawer 内容、导出 sheet 内容），修正交互一致性（Fs 持久化、time-domain 重算模型、rebuild 目标、custom X 长度检查），调整 PyQt5 可行性（舍弃 Qt.Sheet / Qt.Popup、drawer 动画可选），并新增 §16 Phases 分相实施。

---

## 1. 目标

把当前的 2-pane 布局（窄左栏参数面板 + 右侧 TabWidget 容器）重构为 Mac 浅色风格的 **3-pane + Drawer** 布局：

- **左栏**：数据源导航 — 文件 + 通道
- **中栏**：可视化主区 — 单一图表画布，由顶部 segmented 切换时域 / FFT / 阶次三种模式
- **右栏**：Inspector — 上半常驻（跨模式共享的横坐标、范围、刻度），下半按中栏模式上下文切换
- **Drawer / Sheet / Popover**：较重或低频功能从主布局剥离

视觉语言参考 Finder / 邮件 / 备忘录：浅色 + 半透明侧栏 + SF Pro + 大圆角 + 细分隔线。

## 2. 不变量（功能覆盖映射）

**原则：** 现有 UI 文件中每个 user-facing 控件 / 交互 / 信号均需在新布局中有明确归宿。下表为完整映射（以现 `mf4_analyzer/ui/*.py` 的代码结构为基准）。

### 2.1 `main_window.py` 控件

| 现控件 | 作用 | 新位置 |
|---|---|---|
| `btn_load` 添加 | 加载文件 | Toolbar 左段 `＋ 添加文件` |
| `btn_close` 关闭 | 关闭 active 文件 | 移除（改成左栏每行 `✕`） |
| `btn_close_all` 全部 | 关闭全部 | 左栏文件头部 kebab 菜单 `全部关闭…`（保留 QMessageBox 二次确认） |
| `file_tabs` QTabWidget | 多文件切换 | 左栏文件列表竖排 row（`QListWidget` 或自绘 row），active 高亮 |
| `lbl_info` | 文件元信息 | 每个 file row 第二行 |
| `channel_list` MultiFileChannelWidget | 跨文件通道选择 | 左栏下半（见 §4.2） |
| `combo_mode` Subplot/Overlay | 绘图模式 | Inspector 时域下部 segmented |
| `btn_plot` 绘图 | 时域绘图 | Inspector 时域下部 `▶ 绘图` 按钮 |
| `chk_cursor` 游标 / `chk_dual` 双游标 | 游标开关 | Inspector 时域下部 `游标: Off / Single / Dual` segmented |
| `btn_reset` 重置 | 重置游标 | Toolbar 右段 `⌖`（仅时域模式启用） |
| `btn_edit` 🔧 编辑 | 打开通道编辑 | Toolbar 左段 `🔧 编辑通道`（触发右侧 drawer） |
| `btn_export` 📥 导出 | 打开导出对话框 | Toolbar 左段 `📥 导出`（触发顶部 sheet） |
| `combo_xaxis` 自动/指定通道 | 横坐标模式 | Inspector 上部常驻 `▾ 横坐标` 节 |
| `combo_xaxis_ch` | 横坐标通道 | 同上 |
| `edit_xlabel` | 标签 | 同上 |
| `btn_apply_xaxis` 应用 | 触发横坐标 re-plot | 同上（保留显式 `应用` 按钮；参数改动非 live） |
| `chk_range` / `spin_start` / `spin_end` | 区间选择 | Inspector 上部常驻 `▾ 范围` 节 |
| `spin_xt` / `spin_yt` | 刻度密度 | Inspector 上部常驻 `▸ 刻度` 节（默认折叠） |
| `combo_sig` 信号 | FFT / 阶次信号源 | Inspector 上下文（FFT 下半 & 阶次下半） |
| `combo_rpm` 转速 | 阶次转速源 | Inspector 阶次下半 |
| `spin_fs` Fs | 采样率 | Inspector 上下文（FFT / 阶次下半） |
| `btn_rebuild_time` 重建时间轴 | 按 Fs 重建时间轴 | Fs 旁 `⏱` 按钮 → popover（见 §6.3 目标文件规则） |
| `spin_rf` RPM系数 | RPM scale | Inspector 阶次下半 |
| `combo_win` / `combo_nfft` / `spin_overlap` | FFT 参数 | Inspector FFT 下半 |
| `btn_fft` | 执行 FFT | Inspector FFT 下半 `▶ 计算 FFT` 按钮 |
| `chk_fft_remark` 标注 | FFT 标注模式 | Inspector FFT 下半 checkbox |
| `chk_fft_autoscale` 自适应 | FFT 频率范围自适应 | Inspector FFT 下半 checkbox |
| `spin_mo` 最大阶次 / `spin_order_res` 阶次分辨率 / `combo_order_nfft` FFT 点数 / `spin_time_res` 时间分辨率 / `spin_rpm_res` RPM 分辨率 | 阶次参数 | Inspector 阶次下半"谱参数"节 |
| `spin_to` 目标阶次 | 阶次跟踪专用 | Inspector 阶次下半"阶次跟踪"独立节 |
| `btn_ot` / `btn_or` / `btn_ok` | 三个阶次分析按钮 | Inspector 阶次下半（前两个并排，跟踪独立节内） |
| `lbl_order_progress` | 阶次进度 | 阶次按钮下方 progress Label |
| `toolbar_time/fft/order` NavigationToolbar | matplotlib 工具栏 | 每个 canvas 所在卡片顶部，slim 工具栏行（见 §5.1） |
| `lbl_cursor` / `lbl_dual` | 游标读数 | 浮于画布内部左下角 pill（见 §5.2） |
| `stats` StatisticsPanel | 统计 | 画布下方 stats strip + 点击展开 full matrix |
| `axis_lock` AxisLockBar | 轴锁 | Toolbar 右段 `🔒` → popover（见 §8） |
| `statusBar` | 状态栏 | 保留底部 QStatusBar |

### 2.2 `widgets.py / MultiFileChannelWidget`

必须保留的全部能力：

- `search` QLineEdit：placeholder `🔍 Filter...`，实时过滤
- All / None / Inv 批量按钮（最大宽 40px）
- 文件级 checkbox（父节点），勾选/取消级联到子通道
- 子级通道 checkbox + 颜色前景
- `MAX_CHANNELS_WARNING = 8`：全选或文件级全选超过 8 时弹 `QMessageBox.question` 确认
- `check_first_channel(fid)`：新加载文件时自动勾选首通道
- `channels_changed` pyqtSignal 向外通知（用于 auto re-plot）

### 2.3 `widgets.py / StatisticsPanel`

6 个指标必须保留：`min / max / mean / rms / std / p2p`，每通道一行，格式 `:.3g`。

### 2.4 `dialogs.py / ChannelEditorDialog`（改造为 Drawer）

**单通道运算：** `d/dt` · `∫dt` · `× 系数` · `+ 偏移` · `滑动平均` · `|x| 绝对值` — 下拉选择，参数 DoubleSpinBox（range `[-1e12, 1e12]`）

**双通道运算：** `A + B` · `A - B` · `A × B` · `A ÷ B` · `max(A,B)` · `min(A,B)` — 通道 A/B 下拉 + 新名称 LineEdit（空则自动生成 `{op}_{A}_{B}`）；单位合并规则：同单位保留，除法 `a/b`，其他空

**删除：** QListWidget 多选，`🗑 删除` 触发二次确认（`QMessageBox.question` 显示计数）

**新增计数 label：** `新增: N (name)`

**OK / Cancel：** QDialogButtonBox

这些在新 drawer 中一项不缺。

### 2.5 `dialogs.py / ExportDialog`（改造为 Sheet）

- 通道勾选列表（QListWidget，默认全选）
- `包含时间列` checkbox（默认勾选）
- `仅导出选定范围` checkbox
- OK 触发 `QFileDialog.getSaveFileName`（xlsx）
- 仅导出 active 文件的数据

### 2.6 `dialogs.py / AxisEditDialog`（保留 — 双击画布轴触发）

- 最小值 / 最大值 DoubleSpinBox (decimals=4, range `±1e15`)
- 标签 LineEdit
- `自动范围` checkbox
- OK / Cancel

### 2.7 `canvases.py / TimeDomainCanvas` 必须保留的交互

- `MAX_PTS=8000` 的下采样（`_ds`）
- 单游标：hover 即 `axvline` + `cursor_info` 信号
- 双游标：click 放置 A / B，再 click 重放 A → hover 显示 A/B/ΔT/1-over-ΔT + 各通道区间 min/max/avg/rms
- 滚轮：无修饰 = Y 轴 pan；`Ctrl+滚轮` = X 轴 zoom；`Shift+滚轮` = Y 轴 zoom
- `SpanSelector` 区间拖选 → 回调 `_on_span` → 写入 `spin_start/end` + `chk_range=True` + 更新 stats
- 轴锁模式下 SpanSelector 失效，click+drag 画 rubber-band（蓝色 `#007AFF` alpha 0.18）→ release 设置对应轴 limit
- `Esc` 取消进行中的 rubber-band
- 颜色：双游标 A = `#00BFFF`，B = `#FF6347`，区分度高

### 2.8 `canvases.py / PlotCanvas` 必须保留的交互

- 双击轴 → `AxisEditDialog`（`_find_axis_for_dblclick` 包含轴外 45px margin，覆盖刻度标签区）
- 滚轮缩放：同 TimeDomain（无修饰 Y pan / Ctrl X zoom / Shift Y zoom）；快速滚动节流 `_scroll_timer` 60ms
- FFT remark 模式（`_remark_enabled=True`）：
  - 左键 → `_snap_to_curve` 吸附到最近曲线数据点 → `_add_remark` 画黄底 tooltip + 红圆点
  - 右键 → `_remove_remark_at` 找 50px 内最近 remark 删除
- `store_line_data(ax_index, x, y)`：FFT 计算后调用，为 remark 提供吸附源

### 2.9 其他顶层行为

- `_reset_plot_state(scope='file'|'all')`：关闭文件时清图 + 清游标/双游标/轴锁状态 + rebuild combos + 无效化 custom X 指针（保留现有语义，扩展到三种 canvas）
- Overlay 模式 > 5 通道二次确认（`QMessageBox.question`）
- 状态栏消息：加载成功 / 计算完成 / 峰值频率 / 错误 等，全部保留

## 3. 整体框架

```
┌────────────────────────────────────────────────────────────────┐
│  TitleBar: MF4 Data Analyzer │ <active file metadata>          │
├────────────────────────────────────────────────────────────────┤
│  Toolbar:  ＋ 添加  🔧 编辑通道  📥 导出  │  [时域|FFT|阶次]  │  ⌖ 🔒  │
├────────────┬─────────────────────────────────────┬─────────────┤
│            │                                     │             │
│  LEFT      │           CENTER                    │   RIGHT     │
│  文件列表   │           Chart canvas              │   Inspector │
│  通道区域   │           (单画布, 模式切换)         │   (持久+上下文)│
│            │                                     │             │
│            ├─────────────────────────────────────┤             │
│            │     Stats strip (常驻)              │             │
├────────────┴─────────────────────────────────────┴─────────────┤
│  StatusBar: Ready · 2 channels · Fs 1000 Hz · 12.0 s           │
└────────────────────────────────────────────────────────────────┘
```

三栏之间用 `QSplitter(Qt.Horizontal)` 拼接，splitter handle 可拖动调整各栏宽度。栏比例默认依据实际内容设置（见 §9），拖动后持久化到本会话内存（v1 不落盘）。

## 4. 左栏 — 数据源

### 4.1 文件列表（替代 QTabWidget）

- 竖排 row。每行：`📄 filename` + 关闭 `✕` + metadata 副行（`{rows} 行 · {fs:.1f} Hz · {duration:.1f} s`）
- Active 文件：背景 `#007aff`，白字；其他：无背景，hover 微底色 `rgba(0,122,255,0.06)`，点击切换
- 每行 `✕` 点击 = 等价现 `_tab_close`（该文件 `_close`）
- 头部：`文件` 小标题 + 右侧加载数量 + kebab `⋯` 菜单，菜单项 `全部关闭…`（保留 QMessageBox 二次确认 `f"关闭全部 {N} 文件?"`）
- 实现：`QListWidget` 自定义 ItemDelegate 或 `QScrollArea` 内自绘 row widget；`file_id ↔ row` 映射持久化

### 4.2 通道区域

**完整保留 `MultiFileChannelWidget` 能力，仅外观重绘。**

- `🔍 Filter...` 搜索框（顶部）
- 批量按钮行：`All / None / Inv`，最大宽 40px
- 树形结构：文件级 row（粗体、黑色；带 checkbox）→ 子通道 rows（颜色前缀色块 + checkbox + 通道名 + 单位右对齐 `#86868b`）
- 文件级 checkbox：勾选级联到所有子通道；若子通道数 > 8 → 弹确认 `f"该文件有 {n} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？"`
- `All` 按钮同样触发 > 8 确认（按已过滤可见项）
- Active 文件的子通道行微底色 `rgba(0,122,255,0.08)`
- `channels_changed` 信号：在时域模式下 auto re-plot；在 FFT/阶次模式下仅更新 Inspector 下部"信号"下拉的候选（不自动计算）

### 4.3 头部

- `文件` 小标题 + 右侧 `N` 加载数 + kebab `⋯`
- `通道` 小标题 + 右侧搜索框 + All/None/Inv（紧凑）

## 5. 中栏 — 图表主区

### 5.1 画布容器

- `QStackedWidget` 容纳三个 canvas（`TimeDomainCanvas` / FFT `PlotCanvas` / 阶次 `PlotCanvas`），顶部 segmented 切换。**不再使用 `QTabWidget`。**
- 每个 canvas 包在一个"图表卡片"里，卡片顶部一行是 slim 工具栏（高度 ~28px，浅色底 `#fafafa`），内含 `NavigationToolbar2QT`（home/back/forward/zoom/pan/save）+ 右侧状态文字（如 "FFT · data1.mf4"）。**不使用浮动 overlay**（codex 指出 reparent 到 canvas 之上在 resize/HiDPI 下不稳定）。
- 卡片下方是 canvas 本身。

### 5.2 游标读数（重新设计 — 保留双态，替换视觉）

**当前：** 深色 + 绿色 monospace QLabel 独立一行。
**新：** 浅色 pill 标签，浮于 canvas 内部左下角（不占布局高度）。

- 背景 `rgba(255,255,255,0.92)` + 1px `#e5e5e7` + 圆角 6px + padding 5×8px
- 文字：系统字体（非 monospace），`#1d1d1f`，12px
- 实现：独立 `QLabel` 作为 canvas 的 child widget，手动定位 `(8, canvas.height-label.height-8)`；canvas resize 时同步

**单游标：** `t=5.3200s  │  Speed=1820.5 rpm  │  Torque=84.2 Nm`（与 `_update_single` 输出格式一致，换用竖分隔 `│`）

**双游标：** 两行
- 第 1 行（上）：`A=3.200s  │  B=5.350s  │  ΔT=2.150s  │  1/ΔT=0.47 Hz`
- 第 2 行（下）：每通道 `{name}: Min=… Max=… Avg=… RMS=…`（多通道时竖排，label 自动适应高度或截断）

**状态**：无通道绘制时隐藏；切到 FFT / 阶次 tab 时隐藏；游标模式 `Off` 时隐藏。

### 5.3 统计条（常驻，可展开）

- 默认形态（折叠）：画布下方一行 `QWidget`，浅灰底 `#f7f7f9`，边框 `#e5e5e7`，圆角 7px
- 内容简写 `● {ch}: min=… max=… rms=… p2p=…  │  …  │  区间 3.2s–8.5s`（每通道 1 行简写，超宽时横向滚动）
- **点击展开** → 弹出（向下展开 + 动画，高度 120px）完整 `StatisticsPanel` 的 6 指标 tree（Channel / Min / Max / Mean / RMS / Std / P-P），与现 widget 结构一致
- 无选中通道时内容替换为占位 `— 无通道 —`，不塌陷（保持高度）

### 5.4 画布交互（完整保留）

**所有模式共用：**
- 双击轴（含轴外 45px 刻度标签区域）→ `AxisEditDialog`（最小/最大/标签/自动范围）
- 滚轮：无修饰 = Y 轴 pan；`Ctrl+滚轮` = X 轴 zoom（中心=鼠标 x）；`Shift+滚轮` = Y 轴 zoom
- 快速滚动节流：PlotCanvas 60ms（`_scroll_timer`）

**时域专有：**
- 单游标（默认 `Single`）：鼠标 hover → `axvline` + pill 更新
- 双游标 `Dual`：click 放置 A → click 放置 B → 第三次 click 回放 A；pill 显示 A/B/ΔT + 各通道区间统计
- SpanSelector：区间拖选 → 写入 Inspector 上部"范围"节（`spin_start/end` + `chk_range=True`）
- Axis lock 开启时 SpanSelector 禁用；click+drag = rubber-band 选区 → release 设置 `set_xlim/set_ylim`；`Esc` 取消

**FFT 专有：**
- `标注` checkbox → `PlotCanvas._remark_enabled=True`
- 启用后：**左键单击** 画布 → 吸附到最近曲线数据点 → 黄底 tooltip + 红点
- 启用后：**右键单击** → 删除 50px 像素内最近的 remark
- 未启用时左右键无特殊行为（不影响 matplotlib 工具栏的 zoom/pan）

**阶次专有：**
- 无特殊交互（仅 pcolormesh 显示 + NavigationToolbar）

## 6. 右栏 — Inspector

**结构：两个垂直堆叠的卡片，卡片内按节折叠。**

### 6.1 常驻顶部卡片

三种模式下都显示：

| 节 | 内容 | 对应现控件 |
|---|---|---|
| ▾ 横坐标 | `时间/通道` segmented · 通道下拉 · 标签 LineEdit · `应用` 按钮 | `combo_xaxis` / `combo_xaxis_ch` / `edit_xlabel` / `btn_apply_xaxis` |
| ▾ 范围 | 启用 checkbox · 开始/结束 双 DoubleSpinBox（`.3f s` 后缀） · `↻ 从图中拖选` 说明 | `chk_range` / `spin_start` / `spin_end` |
| ▸ 刻度密度 | X/Y SpinBox（range 3–30 / 3–20，默认折叠） | `spin_xt` / `spin_yt` |

**横坐标应用规则：** 参数改动**不 live**；用户必须点 `应用` 触发 re-plot（与当前 `_apply_xaxis` 一致）。

**Custom X 校验：** 若 mode 为"指定通道"且所选通道来自不同文件或长度 `!= len(fd.data)`，`应用` 不触发 re-plot，改弹 `QMessageBox.warning` `"横坐标通道长度与数据不匹配"` — 替代现 `plot_time` 中的静默 fallback。

**`从图中拖选` 说明：** 只是 hint 文字，不是按钮；实际行为是"拖选画布时 SpanSelector 会自动写入开始/结束"（与现有行为一致）。

### 6.2 上下文下部卡片

**时域：**
- 绘图模式 — `Subplot / Overlay` segmented
- 游标 — `Off / Single / Dual` segmented（默认 `Single`，替代现 `chk_cursor/chk_dual` 两 checkbox）
- `▶ 绘图` 按钮（宽度满 card，`#007aff` 强调色）

**时域重算模型（明确）：** 自动 + 显式按钮**共存**（与当前代码一致）：
- 通道勾选变化（`channels_changed`） → auto re-plot
- `绘图` 按钮 → 强制 re-plot（改完范围 / 横坐标 / 刻度后手动刷新）
- 模式切换到时域 → 自动用当前勾选通道 re-plot

**FFT：**
- 信号 — 下拉（所有已加载文件 × 所有通道；与现 `combo_sig` 一致）
- Fs — DoubleSpinBox（range `[1, 1e6]` Hz）+ 右侧 `⏱` 小按钮 → popover（见下）
- 谱参数 — 窗函数下拉（hanning/hamming/blackman/bartlett/kaiser/flattop）· NFFT 下拉（自动/512/…/16384）· 重叠 SpinBox（0–90%）
- 选项 — `自适应频率范围` checkbox（默认勾选）+ `点击标注` checkbox
- `▶ 计算 FFT` 按钮（宽度满 card）

**Rebuild Fs popover：** 锚定在 `⏱` 按钮下方，frameless `QDialog`（见 §8 popover 实现）。内容：
- 提示文字：`"重建哪个文件的时间轴？"` + 当前显示 `"目标：[data1.mf4]（来自所选信号）"`
- Fs 输入 DoubleSpinBox + `确定` 按钮
- **目标文件规则：** 目标 = 当前 FFT 信号下拉所选通道所在的文件（非 active 文件）。若信号下拉为空 → 回退到 active 文件并在提示中显示该文件名
- 行为与现 `rebuild_time_axis` 一致（更新 `fd.rebuild_time_axis(fs)` + 刷新 range 控件 + re-plot）

**阶次：**
- 信号源节 — 信号下拉 + 转速下拉 + Fs + RPM 系数
- 谱参数节（时间-阶次 / 转速-阶次 共用） — 最大阶次（1–100）· 阶次分辨率（0.01–1.0）· 时间分辨率（0.01–1.0s）· RPM 分辨率（1–100 rpm）· FFT 点数（512–8192）
- 两按钮行：`▶ 时间-阶次` · `▶ 转速-阶次`（宽度均分）
- 阶次跟踪节（独立 subcard） — 目标阶次 DoubleSpinBox（0.5–100）+ `▶ 阶次跟踪` 按钮
- 进度 Label 显示在按钮行下方（替代 `lbl_order_progress`）

**分组说明：** `目标阶次` 只被"阶次跟踪"使用，独立节避免视觉误导。

### 6.3 切换逻辑

**模式切换：** 上部卡片原样保留；下部卡片 swap。上一模式用户已输入的下部值记在 MainWindow 的 inspector state dict，回切时恢复。

**文件切换（active 文件改变）：**
- 上部 `横坐标 / 范围 / 刻度 / 通道勾选` 全部保留
- 下部"信号 / 转速"下拉刷新：`_update_combos()` 重建（等价现行为）
- Fs 规则：
  - 每个 `FileData` 对象在内存中有自己的 Fs（来自 `fd.fs` 或用户通过 rebuild-time popover 设定）
  - `spin_fs`（UI 控件）始终显示**当前下拉所选信号的所在文件的 Fs**
  - 用户在 `spin_fs` 中编辑的值**只影响本次计算（FFT/阶次）**，不回写 FileData（与现行为一致）
  - 下拉切换到不同文件的通道时，`spin_fs` 刷新为该文件的 Fs（覆盖用户编辑）
  - Popover `⏱ 重建时间轴` 是显式将 Fs 写回目标 FileData 并重建 `time_array` 的唯一入口

**所有"计算类"按钮（`绘图` / `计算 FFT` / `时间-阶次` / `转速-阶次` / `阶次跟踪`）都在 Inspector 内**，不在顶部 toolbar。改完参数就地触发。

## 7. 顶部工具栏

三段式：

| 左 | 中 | 右 |
|---|---|---|
| ＋ 添加文件 · 🔧 编辑通道 · 📥 导出 | [时域 \| FFT \| 阶次] segmented | ⌖ 重置游标 · 🔒 轴锁 |

- 所有按钮均为浅色 pill：白底 + `#d2d2d7` 边 + 6px 圆角 + 5×11 padding
- segmented control：`#e8e8ed` 底 + 选中 segment 白底 + 轻阴影
- `关闭活动文件` 按钮去掉（改到左栏每行 `✕`）
- `全部关闭` 移到左栏文件头部 kebab `⋯`（保留 QMessageBox 二次确认）
- **`截图` 按钮不在 v1 范围**（当前代码无实现；保留到未来增强）— 注：这仅指 "screenshot" 按钮；绘图按钮 `btn_plot`（re-plot 时域）**保留**，位置见 §6.2 时域下部 `▶ 绘图` 按钮

### 7.1 启用状态矩阵

| Toolbar 项 | 时域 | FFT | 阶次 | 无文件加载 |
|---|---|---|---|---|
| ＋ 添加 | 启用 | 启用 | 启用 | 启用 |
| 🔧 编辑通道 | 启用 | 启用 | 启用 | 禁用 |
| 📥 导出 | 启用 | 启用 | 启用 | 禁用 |
| 模式 segmented | 启用 | 启用 | 启用 | 启用（但切到非时域时画布显示"加载文件以开始"占位） |
| ⌖ 重置游标 | 启用 | 禁用 | 禁用 | 禁用 |
| 🔒 轴锁 | 启用 | 禁用 | 禁用 | 禁用 |

禁用态用 `QAction.setEnabled(False)` + QSS `:disabled` 样式（降低对比度）。

## 8. Drawer / Sheet / Popover

### 8.1 形态分配

| 功能 | 形态 | 触发 | 实现 |
|---|---|---|---|
| 通道编辑 | Slide-in Drawer（右侧） | Toolbar 🔧 | 自写 `QWidget` + 可选 `QPropertyAnimation`（v1 基线：固定侧板无动画；若时间允许再加动画） |
| 导出 Excel | 顶部 anchored 模态 | Toolbar 📥 | 普通 `QDialog`（`Qt.Dialog` flag）+ 手动定位到窗口顶部中央；**不使用 `Qt.Sheet`**（PyQt5 跨平台不稳定） |
| 重建时间轴 | 锚定浮窗 | Inspector FFT/阶次 Fs 旁 `⏱` | 无边框 `QDialog`（`Qt.Dialog \| Qt.FramelessWindowHint`）+ 手动定位到按钮下方 + 失焦自动关闭（`focusOutEvent`）；**不使用 `Qt.Popup`**（含 SpinBox 时焦点切换会误关） |
| 轴锁 | 同上 | Toolbar 🔒 | 同上，面板内容为 `None / X / Y` 三选一 + 提示文字 |

### 8.2 通道编辑 Drawer 内容（等价现 ChannelEditorDialog）

**宽度：** 420 px；从右侧 slide-in（或 v1 基线：固定宽度侧板）

**Header：** 标题 `"通道编辑 — {filename}"` + 关闭按钮 `✕`

**Body 三组：**

1. **单通道运算** QGroupBox
   - `源:` 通道下拉（填充 `fd.get_signal_channels()`）
   - `运算:` 下拉（6 项：`d/dt`, `∫dt`, `× 系数`, `+ 偏移`, `滑动平均`, `|x| 绝对值`）
   - `参数:` DoubleSpinBox（range `[-1e12, 1e12]`, default `1`）
   - `✚ 创建` 按钮

2. **双通道运算（A ⊕ B）** QGroupBox
   - 通道A / 通道B 下拉
   - `运算:` 下拉（6 项：`A + B`, `A - B`, `A × B`, `A ÷ B`, `max(A,B)`, `min(A,B)`）
   - `新名称:` LineEdit（placeholder `"留空自动生成"`）
   - `✚ 创建` 按钮

3. **删除** QGroupBox
   - QListWidget 多选
   - `🗑 删除` 按钮（保留现 `QMessageBox.question` 二次确认 `f"删除 {N} 通道?"`）

**Footer：** `新增: N` 计数 Label + `OK / Cancel` 按钮行

**作用范围：** 仅 active 文件（保留现语义）。

### 8.3 导出 Sheet 内容（等价现 ExportDialog）

**宽度：** 320 px；顶部 anchored 模态

**Body：**
- 通道勾选 QListWidget（默认全选；从 `fd.get_signal_channels()` 填充）
- `包含时间列` checkbox（默认勾选）
- `仅导出选定范围` checkbox

**Footer：** `OK / Cancel`；OK 点击 → `QFileDialog.getSaveFileName` → 调用 `pd.DataFrame.to_excel`。

**作用范围：** 仅 active 文件（保留现语义）。

## 9. 尺寸与窗口

- **默认尺寸：** 1400 × 860（基于：左 220 + 中 ≥ 600 + 右 260 + 间距 + title/toolbar/status ≈ 880 px 高）
- **最小尺寸：** 1100 × 640
- **栏初始比例：** `QSplitter.setSizes([220, total-220-260, 260])`
- **栏最小宽度：** 左 180 / 中 400 / 右 220（splitter handle 不能拖过此阈）
- Splitter handle：1 px 细线、悬停时显示拖动游标

## 10. 视觉 tokens（QSS 层）

```
颜色
  背景主       #ffffff
  背景侧栏     rgba(248,248,250,0.85)
  背景次卡     #f7f7f9
  边框         #e5e5e7
  边框深       #d2d2d7
  文字主       #1d1d1f
  文字次       #6e6e73
  文字弱       #86868b
  强调         #007aff
  警示         #ff9500
  危险         #ff3b30

字体
  系统         -apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif
  尺寸         12/11/10/9 px (body/label/subtitle/hint)

圆角
  卡片         10 px
  按钮         6 px
  pill         5 px

阴影
  浅           0 1px 2px rgba(0,0,0,0.04)
  卡片悬浮     0 4px 12px rgba(0,0,0,0.06)
```

状态栏、title 栏、游标读数的深色残留（当前 `background:#1e1e1e;color:#0f0` 及 `background:#0d1117;color:#58a6ff`）全部替换为上述浅色 tokens。

## 11. 快捷键

v1 不加。保留 matplotlib NavigationToolbar 自带的键盘交互（P/S/H 等），保留 `Esc` 取消 axis-lock rubber-band。

## 12. 代码组织影响

```
mf4_analyzer/ui/
  main_window.py              # 瘦身：装配三栏 + toolbar + 信号路由
  toolbar.py                  # 新增：顶部三段工具栏 + segmented
  file_navigator.py           # 新增：左栏（文件列表 + 通道区域）
  chart_stack.py              # 新增：中栏 QStackedWidget + 模式切换 + stats strip
  inspector.py                # 新增：右栏框架
  inspector_sections.py       # 新增：各节子 widget（横坐标/范围/刻度/绘图模式/FFT/阶次）
  drawers/
    channel_editor_drawer.py  # 原 ChannelEditorDialog 改造
    export_sheet.py           # 原 ExportDialog 改造
    axis_lock_popover.py      # 原 AxisLockBar 改造
    rebuild_time_popover.py   # 原 btn_rebuild_time 对话框
  canvases.py                 # 保留；cursor pill 不在此处
  widgets.py                  # StatisticsPanel 改为 stats strip + 展开 tree; MultiFileChannelWidget 迁入 file_navigator
  axis_lock_toolbar.py        # **DELETE**（内容全部搬入 drawers/axis_lock_popover.py，不保留过渡文件）
  icons.py                    # 保留，新增 segmented / kebab / close 图标
  style.qss                   # 全面重写为浅色 tokens
```

**`main_window.py` 职责**：仅装配三栏容器 + toolbar + 路由信号。现分析方法（`plot_time / do_fft / do_order_*`）保留，但表单读值改为从 Inspector 子组件读（Inspector 暴露 getter）。

### 12.1 状态 / 单例归属（消除跨模块歧义）

下表明确每个跨模块的状态片段由哪个模块独占拥有；其他模块只能通过 API 访问：

| 状态片段 | 拥有模块 | 说明 |
|---|---|---|
| `files: OrderedDict[str, FileData]` | `main_window.py` | 保留现行，所有模块通过 MainWindow 的 getter/signal 访问 |
| `_active: Optional[str]`（活动文件 id） | `main_window.py` | 同上；切换通过 `set_active_file(fid)` 方法 |
| `_custom_xlabel / _custom_xaxis_fid / _custom_xaxis_ch` | `main_window.py` | 保留现行（xaxis state） |
| `inspector_state_dict`（各模式下部输入的缓存） | `inspector.py` 的 `Inspector` 类 | 切模式时由 Inspector 自己读写，MainWindow 不触碰 |
| Cursor pill widget（单例） | `chart_stack.py` 的 `ChartStack` 类 | 浮于当前 active canvas 上，**不依附于 canvas 类**；监听当前 canvas 的 `cursor_info` / `dual_cursor_info` 信号；切换模式时 re-wire 信号 |
| `_reset_plot_state(scope)` 实现 | `main_window.py` | 保留现位置；内部调用 `chart_stack.full_reset_all()` + `inspector.reset_to_defaults()` + 左栏 `file_navigator.refresh_combos()` |
| Axis lock state（`None/X/Y`） | `drawers/axis_lock_popover.py` + `TimeDomainCanvas` | popover 是 UI 载体；状态值由 TimeDomainCanvas 持有（`_axis_lock`），popover 通过 signal 设置 |
| FFT `_remark_enabled` | `PlotCanvas` | 保留现位置；Inspector FFT 下部 checkbox 通过 signal 写入 |

### 12.2 信号路由表（emitter → handler）

| Signal | Emitter | Handler | 作用 |
|---|---|---|---|
| `MultiFileChannelWidget.channels_changed` | `file_navigator.py` | `MainWindow._ch_changed` | 时域模式下 auto re-plot；FFT/阶次模式下刷新 Inspector 信号下拉候选 |
| `Toolbar.file_add_requested` | `toolbar.py` | `MainWindow.load_files` | 弹 QFileDialog |
| `Toolbar.channel_editor_requested` | `toolbar.py` | `MainWindow.open_editor` | 显示通道编辑 drawer |
| `Toolbar.export_requested` | `toolbar.py` | `MainWindow.export_excel` | 显示导出 sheet |
| `Toolbar.mode_changed(str)` | `toolbar.py` | `MainWindow._on_mode_changed` | 切换 `ChartStack.currentIndex` + 切换 `Inspector` 下部上下文 |
| `Toolbar.cursor_reset_requested` | `toolbar.py` | `TimeDomainCanvas.reset_cursors` | 重置游标（保留现 `_reset_cursors` 行为） |
| `Toolbar.axis_lock_requested` | `toolbar.py` | 显示 `axis_lock_popover` | popover 内 radio → `TimeDomainCanvas.set_axis_lock(mode)` |
| `FileNavigator.file_activated(fid)` | `file_navigator.py` | `MainWindow.set_active_file` | 切换 active + 刷新 `spin_fs` + 刷新 combos |
| `FileNavigator.file_close_requested(fid)` | `file_navigator.py` | `MainWindow._close` | 保留现 `_close` 行为 |
| `FileNavigator.close_all_requested` | `file_navigator.py` | `MainWindow.close_all` | 保留二次确认 |
| `Inspector.plot_time_requested` | `inspector.py` | `MainWindow.plot_time` | `▶ 绘图` 按钮触发 |
| `Inspector.fft_requested` | `inspector.py` | `MainWindow.do_fft` | `▶ 计算 FFT` 触发 |
| `Inspector.order_time_requested` | `inspector.py` | `MainWindow.do_order_time` | `▶ 时间-阶次` 触发 |
| `Inspector.order_rpm_requested` | `inspector.py` | `MainWindow.do_order_rpm` | `▶ 转速-阶次` 触发 |
| `Inspector.order_track_requested` | `inspector.py` | `MainWindow.do_order_track` | `▶ 阶次跟踪` 触发 |
| `Inspector.xaxis_apply_requested` | `inspector.py` | `MainWindow._apply_xaxis` | `应用` 按钮 |
| `Inspector.rebuild_time_requested(fs)` | `inspector.py`（popover 内） | `MainWindow.rebuild_time_axis(fid, fs)` | 目标 fid 由 Inspector 依据当前信号下拉解析 |
| `Inspector.tick_density_changed(xt, yt)` | `inspector.py` | `MainWindow._update_all_tick_density` | 保留现行为 |
| `Inspector.remark_toggled(bool)` | `inspector.py` | `PlotCanvas.set_remark_enabled` | FFT `标注` checkbox |
| `TimeDomainCanvas.cursor_info(str)` | `canvases.py` | `ChartStack` cursor pill | 单游标读数 |
| `TimeDomainCanvas.dual_cursor_info(str)` | `canvases.py` | `ChartStack` cursor pill | 双游标读数（第二行） |
| `TimeDomainCanvas.span_selected(xmin, xmax)` | `canvases.py`（新增；封装 `_on_span`） | `Inspector` 的 range 节 | 拖选 → 写入 `spin_start/end`，更新 stats |

**布线原则：**
- 子组件通过 Qt signal emit；MainWindow 作为中心节点订阅并调度分析方法
- 子组件不直接互相 import；保持解耦，便于未来测试
- Inspector 暴露只读 getter（如 `get_range() -> (bool, float, float)`, `get_fft_params() -> dict`, `get_order_params() -> dict`）供 MainWindow 的分析方法调用

## 13. 交互一致性规则

1. **模式切换保留上下文输入** — 顶部常驻节不动；下部节切换，上一模式的输入值记在 inspector state dict
2. **文件切换不重置计算** — 三个 canvas 各保留上一次绘制结果；切 active 文件只刷新 Fs 和信号/转速下拉
3. **关闭文件即清图** — 等价现 `_reset_plot_state('file')`，扩展到三种 canvas 的 `full_reset()`
4. **Overlay > 5 通道二次确认** — 保留
5. **Channel list > 8 通道批量确认** — 保留（All 按钮、文件级全选）
6. **无通道选中** — 画布 clear + stats strip 占位，不塌陷
7. **时域 auto re-plot** — `channels_changed` 触发（仅时域模式）
8. **FFT / 阶次** — 不 auto 触发，必须点计算按钮

## 14. 非目标（v1 不做）

- 深色模式
- 拖文件到窗口打开
- 键盘快捷键
- 保存栏宽 / 窗口状态到磁盘
- Inspector 多面板分离成独立窗口
- Drawer 动画（基线无动画；若时间允许再加）
- 截图按钮

## 15. 验证标准

- [ ] 现有所有文件/通道/绘图/FFT/阶次功能行为一致（与重构前对比测试）
- [ ] 三栏 splitter 可拖动，最小宽度阈生效，极限拖动不崩溃
- [ ] 模式切换：上部常驻区保留，下部切换，回切恢复输入
- [ ] 文件切换：上部保留，下部信号/转速下拉刷新，Fs 刷新
- [ ] 关闭文件：三种 canvas 全部 clear，游标/轴锁状态清除
- [ ] 关闭全部：QMessageBox 二次确认
- [ ] Channel list：搜索、All/None/Inv、文件级全选、>8 警告正常
- [ ] 单/双游标模式切换正常；双游标 pill 显示 A/B/ΔT/每通道统计
- [ ] 时域 SpanSelector 写入 range；轴锁 rubber-band + Esc 取消
- [ ] FFT remark：左键添加（吸附曲线）、右键删除（50px 内）
- [ ] 双击轴弹 AxisEditDialog（含轴外刻度区域）
- [ ] 滚轮：Y pan / Ctrl+X zoom / Shift+Y zoom
- [ ] Drawer / Sheet / Popover 打开关闭无残留
- [ ] Rebuild-time popover 正确目标文件
- [ ] 自定义 X 长度不匹配时弹 warning（替代静默 fallback）
- [ ] 窗口最小尺寸 1100×640，所有控件可见
- [ ] QSS 全浅色，无深色残留
- [ ] 中文字体显示正常

## 16. 分相实施（Phases for plan）

应用层分为 4 相串行实施，便于 writing-plans 拆解、便于中途验证：

**Phase 1 — 骨架 & 功能映射**
- 三栏 QSplitter + toolbar + status
- 新建 `toolbar.py / file_navigator.py / chart_stack.py / inspector.py / inspector_sections.py` 空壳
- 把现 `main_window.py` 中的装配逻辑按映射表拆到新模块
- 保留现 ChannelEditor / Export / AxisLock / Rebuild 对话框不动（用旧 Dialog 触发）
- 目标：结构对，功能完整，视觉不变

**Phase 2 — 左栏 + Inspector 内容**
- MultiFileChannelWidget 迁入 file_navigator，外观重绘
- 文件列表替代 tabs（含 kebab 菜单 + 关闭 ✕）
- Inspector 上部常驻 + 下部上下文的信号连接完整
- 游标 Off/Single/Dual segmented 替换双 checkbox
- 目标：核心交互完整，外观仍偏老

**Phase 3 — Drawer / Sheet / Popover 迁移**
- ChannelEditor → 右侧 drawer（v1 基线：固定面板无动画）
- Export → 顶部 anchored 模态
- Rebuild-time / AxisLock → frameless popover
- 目标：所有 modal 对话框改造完成

**Phase 4 — 视觉统一**
- `style.qss` 全重写：浅色 tokens + 圆角 + 细边
- Cursor pill 浅色化
- Stats strip 浅色化 + 点击展开完整 tree
- Chart 卡片 + 顶部 slim toolbar 布局
- 目标：Mac 浅色视觉完整
